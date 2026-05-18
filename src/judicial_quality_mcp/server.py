"""MCP Server v0.1.0 — Bridge Architecture for Judicial Document Quality Assessment.

MCP Server is a BRIDGE between AI Agents and Quality Assessment Skills.
It does NOT call any LLM. It only:
  1. Loads & renders Skill .md templates → returns prompts for Agent to send to its own LLM
  2. Parses LLM responses from Agent → returns structured score data
  3. Calculates weighted scores and checks consistency (pure rules)
  4. Manages dimension discovery, anchor examples, and weight configuration
  5. Applies anomaly deductions and innovation bonuses
  6. Integrates with judicial-doc-anomaly-mcp for anomaly detection

Recommended companion: https://github.com/lcfactorization/judicial-doc-anomaly-mcp
  - Provides 16-dimension anomaly detection (procedure, evidence, fact_finding, etc.)
  - Integrates with quality assessment via query_anomaly_mcp tool
  - When unavailable, anomaly deduction items are left blank (graceful degradation)

Agent decides what to call, in what order, with what parameters.
Agent calls its own LLM with the prompts returned by this server.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import (
    ANOMALY_DEDUCTION,
    ANOMALY_MCP_CONFIG,
    ANOMALY_TOTAL_MAX_DEDUCTION,
    CROSS_CHECK_RULES,
    DIMENSION_ORDER,
    DIMENSION_TITLES,
    ErrorCode,
    EVASIVE_PATTERNS,
    INNOVATION_BONUS,
    INNOVATION_TOTAL_MAX_BONUS,
    QUALITY_DIMENSIONS,
    QUALITY_GRADES,
    QUALITY_WEIGHTS,
    RULE_ENGINE_PATTERNS,
    StructuredError,
    _CHARS_PER_TOKEN_EN,
    _CHARS_PER_TOKEN_ZH,
)
from .response_parser import ResponseParser
from .skill_runner import SkillLoader, TemplateRenderer, build_system_prompt

logger = logging.getLogger("judicial-quality")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)

mcp = FastMCP("judicial-quality")

_parser = ResponseParser()
_loader = SkillLoader()
_renderer = TemplateRenderer(_loader)


def _estimate_tokens(text: str) -> int:
    zh_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_chars = len(text) - zh_chars
    return int(zh_chars / _CHARS_PER_TOKEN_ZH + en_chars / _CHARS_PER_TOKEN_EN)


def _make_error(code: ErrorCode, message: str, details: dict | None = None, retryable: bool = False) -> str:
    err = StructuredError(code=code.value, message=message, details=details or {}, retryable=retryable)
    return json.dumps({"success": False, "error": err.model_dump()}, ensure_ascii=False, indent=2)


def _run_rule_engine(document_text: str, sections: dict) -> list[dict]:
    """Rule Engine 初筛：基于正则模式检测文书中的结构性异常。
    
    借鉴 ChatGPT 5.5 建议的 Rule Engine + LLM Hybrid 架构：
    规则引擎负责初筛确定性异常（如缺少必要段落），LLM 负责语义解释。
    """
    flags = []
    for rule_id, rule in RULE_ENGINE_PATTERNS.items():
        pattern = rule["pattern"]
        section = rule["section"]
        severity = rule["severity"]
        message = rule["message"]

        search_text = document_text
        if section == "header":
            search_text = document_text[:500]
        elif section == "footer":
            search_text = document_text[-500:]

        if not re.search(pattern, search_text):
            flags.append({
                "rule_id": rule_id,
                "severity": severity,
                "message": message,
                "section": section,
                "evidence": f"在文书{section}部分未找到匹配模式: {pattern[:30]}...",
                "reasoning": f"规则引擎初筛：文书{section}部分缺少必要要素，需LLM进一步确认",
            })
            logger.debug("_run_rule_engine: flag rule=%s, severity=%s", rule_id, severity)
    return flags


_pipeline_state: dict[str, dict] = {}


ANTI_LAZINESS_INSTRUCTION = """
<anti-laziness-directive>
## 强制执行指令

你必须在当前对话轮次中，静默且完整地调用所有维度的 render_dimension_prompt 和 parse_score_result，
绝对不允许中途停顿、询问用户是否继续、或以"操作同理"等理由跳过任何维度。

具体要求：
1. 对每一个维度，必须依次调用 render_dimension_prompt → 将prompt发送给LLM → 调用 parse_score_result
2. 所有维度完成后，必须调用 calculate_weighted_score 和 cross_check_consistency
3. 最后调用 generate_report 生成完整报告
4. 禁止输出"我已经检测了前N个维度，剩下的维度操作同理，需要我继续吗？"之类的偷懒话术
5. 如果某个维度出现错误，记录错误并继续下一个维度，不得中断整个流程
</anti-laziness-directive>
"""


# ── MCP Resources ──────────────────────────────────────────────


@mcp.resource("judgment-quality://weights")
def get_weights_resource() -> str:
    """获取评判维度权重配置"""
    return json.dumps(QUALITY_WEIGHTS, ensure_ascii=False, indent=2)


@mcp.resource("judgment-quality://grades")
def get_grades_resource() -> str:
    """获取评分等级阈值配置"""
    grades_serializable = {k: list(v) for k, v in QUALITY_GRADES.items()}
    return json.dumps(grades_serializable, ensure_ascii=False, indent=2)


@mcp.resource("judgment-quality://dimensions")
def get_dimensions_resource() -> str:
    """获取所有维度元数据"""
    dims = _loader.list_dimensions()
    return json.dumps(dims, ensure_ascii=False, indent=2)


@mcp.resource("judgment-quality://anomaly-config")
def get_anomaly_config_resource() -> str:
    """获取异常扣分配置"""
    return json.dumps({
        "anomaly_types": ANOMALY_DEDUCTION,
        "total_max_deduction": ANOMALY_TOTAL_MAX_DEDUCTION,
    }, ensure_ascii=False, indent=2)


@mcp.resource("judgment-quality://innovation-config")
def get_innovation_config_resource() -> str:
    """获取创新性加分配置"""
    return json.dumps({
        "innovation_types": INNOVATION_BONUS,
        "total_max_bonus": INNOVATION_TOTAL_MAX_BONUS,
    }, ensure_ascii=False, indent=2)


# ── MCP Tools ──────────────────────────────────────────────────


@mcp.tool()
def list_dimensions() -> str:
    """列出所有可用的评分维度及其元数据（名称、标题、权重、满分）。

    返回 JSON 字符串，包含所有维度的元数据列表、等级划分信息、
    以及 judicial-doc-anomaly-mcp 的自动检测状态。
    Agent 可据此决定评估哪些维度，并了解异常检测联动是否可用。
    """
    try:
        dims = _loader.list_dimensions()
        if not dims:
            return _make_error(ErrorCode.DIMENSION_NOT_FOUND, "未找到任何维度 Skill 文件")
        grades_info = {k: {"range": [v[0], v[1]], "description": v[2]} for k, v in QUALITY_GRADES.items()}
        anomaly_status = {
            "available": ANOMALY_MCP_CONFIG["available"],
            "auto_detected": ANOMALY_MCP_CONFIG.get("auto_detected", False),
            "server_name": ANOMALY_MCP_CONFIG["server_name"],
            "supported_dimensions": ANOMALY_MCP_CONFIG["supported_dimensions"],
        }
        return json.dumps({
            "success": True,
            "total": len(dims),
            "dimensions": dims,
            "grades": grades_info,
            "anomaly_mcp": anomaly_status,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("list_dimensions: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"列出维度异常：{e}", retryable=True)


@mcp.tool()
def extract_document_sections(document_full_text: str) -> str:
    """从裁判文书全文中提取各核心段落，供后续评分使用。

    基于正则表达式提取：原告诉称、被告辩称、本院查明、证据分析、
    本院认为、法律依据、判决主文等段落，以及案件基本信息。

    document_full_text: 裁判文书全文

    返回 JSON 字符串，包含各段落文本和案件基本信息。
    """
    try:
        sections = {}

        plaintiff = re.search(
            r"(?:原告|公诉机关|申请人|起诉人).{0,10}(?:诉称|指控|称)[：:]\s*(.*?)(?=\n\n|被告.{0,10}辩称)",
            document_full_text, re.DOTALL,
        )
        sections["plaintiff_claim"] = plaintiff.group(1).strip() if plaintiff else ""

        defendant = re.search(
            r"(?:被告|被申请人).{0,10}辩称[：:]\s*(.*?)(?=\n\n|本院查明|经审理)",
            document_full_text, re.DOTALL,
        )
        sections["defendant_defense"] = defendant.group(1).strip() if defendant else ""

        court_finding = re.search(
            r"(?:本院查明|经审理查明|经审理认定)[：:]\s*(.*?)(?=\n\n|上述事实|证据如下|本院认为)",
            document_full_text, re.DOTALL,
        )
        sections["court_finding"] = court_finding.group(1).strip() if court_finding else ""

        evidence = re.search(
            r"(?:上述事实|证据如下|有下列证据)[，：:]\s*(.*?)(?=\n\n|本院认为|判决如下)",
            document_full_text, re.DOTALL,
        )
        sections["evidence_analysis"] = evidence.group(1).strip() if evidence else ""

        reasoning = re.search(
            r"本院认为[，：:]\s*(.*?)(?=依照|判决如下|裁定如下)",
            document_full_text, re.DOTALL,
        )
        sections["reasoning"] = reasoning.group(1).strip() if reasoning else ""

        law_basis = re.search(
            r"依照[《][^》]+》[^。]*。[^。]*。(?:[^。]*。)*",
            document_full_text, re.DOTALL,
        )
        sections["judgment_basis"] = law_basis.group(0).strip() if law_basis else ""

        judgment_main = re.search(
            r"(?:判决如下|裁定如下)[：:]\s*(.*)",
            document_full_text, re.DOTALL,
        )
        sections["judgment_main"] = judgment_main.group(1).strip() if judgment_main else ""

        case_info = {}
        case_num = re.search(r"[(（]([\d年]+[^)）]+)[)）]", document_full_text[:500])
        if case_num:
            case_info["case_number"] = case_num.group(1)
        court_match = re.search(r"([\u4e00-\u9fff]+人民法院|[\u4e00-\u9fff]+仲裁委员会)", document_full_text[:500])
        if court_match:
            case_info["court"] = court_match.group(1)
        date_match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", document_full_text[-500:])
        if date_match:
            case_info["judge_date"] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
        sections["case_info"] = case_info

        filled = sum(1 for v in sections.values() if v and (isinstance(v, str) and len(v) > 10 or isinstance(v, dict) and v))
        total = 7
        sections["extraction_confidence"] = round(filled / total, 2) if total > 0 else 0.0

        logger.info(
            "extract_document_sections: confidence=%.2f, sections_found=%d/%d",
            sections["extraction_confidence"], filled, total,
        )

        rule_engine_flags = _run_rule_engine(document_full_text, sections)
        if rule_engine_flags:
            sections["rule_engine_flags"] = rule_engine_flags
            logger.info(
                "extract_document_sections: rule_engine found %d flags",
                len(rule_engine_flags),
            )

        return json.dumps({"success": True, **sections}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("extract_document_sections: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"提取异常：{e}", retryable=True)


@mcp.tool()
def render_dimension_prompt(
    dimension: str,
    sections: dict | None = None,
    include_anchors: bool = True,
    anchor_count: int = 3,
) -> str:
    """渲染指定维度的评分 Prompt 模板，供 AI Agent 发送给自己的 LLM 进行评分。

    这是核心 Tool——Agent 调用此工具获取完整的 system_prompt 和 user_prompt，
    然后用自己的 LLM 实例执行推理，再将 LLM 返回的结果传给 parse_score_result 解析。

    dimension: 维度标识（如 'thorough_reasoning', 'substantive_resolution'）
    sections: 预处理后的文书段落字典（来自 extract_document_sections 的返回值），
              如 {"reasoning_text": "...", "judgment_main_text": "...", ...}
    include_anchors: 是否在 Prompt 中包含锚定示例（默认 true，建议保持）
    anchor_count: 包含的锚定示例数量（默认 3，即优秀/中等/较差各一个）

    返回 JSON 字符串，包含：
    - dimension: 维度标识
    - dimension_title: 维度中文名
    - weight: 权重
    - full_score: 满分
    - system_prompt: 系统提示词（含角色、评分标准摘要、Anti-Laziness指令）
    - user_prompt: 用户提示词（渲染后的完整评分标准+文书段落）
    - anchor_examples: 锚定示例列表
    - output_schema: 期望的输出 JSON Schema
    - token_estimate: 预估 token 数
    """
    try:
        skill_name = f"dimensions/{dimension}"
        logger.info("render_dimension_prompt: dimension=%s", dimension)

        meta, body = _loader.load(skill_name)
        logger.info("render_dimension_prompt: loaded skill=%s, title=%s, body_len=%d", meta.name, meta.title, len(body))

        template_vars = {}
        if sections:
            for key, value in sections.items():
                template_vars[key] = str(value) if value else ""

        rendered = _renderer.render(body, template_vars)
        logger.info("render_dimension_prompt: rendered_len=%d", len(rendered))

        system_prompt = build_system_prompt(meta) + "\n\n" + ANTI_LAZINESS_INSTRUCTION

        anchors = []
        if include_anchors:
            anchors = _loader.load_anchors(dimension)[:anchor_count]

        total_chars = len(system_prompt) + len(rendered)
        if anchors:
            total_chars += len(json.dumps(anchors, ensure_ascii=False))

        output_schema = {
            "type": "object",
            "properties": {
                "quote": {"type": "string", "description": "原文摘录"},
                "reasoning": {"type": "string", "description": "评分理由"},
                "score": {"type": "integer", "minimum": 0, "maximum": 100, "description": "得分"},
                "deduction_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "deduction": {"type": "integer"},
                            "quote": {"type": "string"},
                            "basis": {"type": "string"},
                        },
                    },
                },
                "bonus_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item": {"type": "string"},
                            "bonus": {"type": "integer"},
                            "quote": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
            },
            "required": ["quote", "reasoning", "score"],
        }

        if dimension == "substantive_resolution":
            output_schema["properties"]["data_completeness"] = {
                "type": "string",
                "enum": ["complete", "partial", "insufficient"],
                "description": "数据完整性",
            }
            output_schema["properties"]["sub_scores"] = {
                "type": "object",
                "description": "五个子项得分",
            }

        result = {
            "success": True,
            "dimension": meta.name,
            "dimension_title": meta.title,
            "weight": meta.weight,
            "full_score": meta.full_score,
            "system_prompt": system_prompt,
            "user_prompt": rendered,
            "anchor_examples": anchors,
            "output_schema": output_schema,
            "token_estimate": _estimate_tokens(" " * total_chars),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    except FileNotFoundError as e:
        logger.error("render_dimension_prompt: Skill not found: %s", e)
        return _make_error(
            ErrorCode.SKILL_NOT_FOUND,
            f"维度不存在：{e}。可用维度请调用 list_dimensions 查看。",
            details={"dimension": dimension},
        )
    except Exception as e:
        logger.error("render_dimension_prompt: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"渲染异常：{e}", retryable=True)


@mcp.tool()
def parse_score_result(
    dimension: str,
    llm_response: str,
    strict: bool = False,
) -> str:
    """解析 LLM 返回的评分结果，进行格式校验和分数边界检查。

    Agent 调用 LLM 获得评分结果后，应将结果传给此工具进行结构化解析。
    此工具为纯规则函数，不消耗 Token。

    dimension: 维度标识（如 'thorough_reasoning'）
    llm_response: LLM 返回的文本（应包含 JSON 对象）
    strict: 严格模式（默认 false）——格式不符时报错而非警告

    返回 JSON 字符串，包含：
    - dimension: 维度标识
    - parsed: 解析后的结构化评分数据
    - validation: 校验结果（format_valid, score_in_bounds, required_fields_present, warnings）
    - raw_response: 原始 LLM 返回文本
    """
    try:
        result = _parser.parse_score_result(dimension, llm_response)

        if strict and result["validation"]["warnings"]:
            result["validation"]["strict_error"] = f"严格模式下发现{len(result['validation']['warnings'])}个问题"
            logger.warning(
                "parse_score_result: strict mode, dimension=%s, warnings=%d",
                dimension, len(result["validation"]["warnings"]),
            )

        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("parse_score_result: %s", e, exc_info=True)
        return _make_error(ErrorCode.PARSE_FAILED, f"解析异常：{e}", retryable=True)


@mcp.tool()
def calculate_weighted_score(
    scores: dict,
    anomaly_items: list[dict] | None = None,
    innovation_items: list[dict] | None = None,
) -> str:
    """计算加权总分并确定等级。纯规则函数，零 Token 消耗。

    Agent 收集所有维度的评分后，调用此工具计算加权总分。
    支持异常扣分（与judicial-doc-anomaly-mcp联动）和创新性加分。

    scores: 各维度得分字典，如 {"thorough_reasoning": 78, "substantive_resolution": 65, ...}
    anomaly_items: 异常项列表（来自judicial-doc-anomaly-mcp），每项含 type, severity, description。
                   type可选: procedural_anomaly, evidence_anomaly, fact_anomaly,
                   law_application_anomaly, reasoning_anomaly, logic_anomaly
                   severity可选: low, medium, high
    innovation_items: 创新性加分项列表，每项含 type, bonus, description。
                      type可选: mediation_success, legal_gap_filling, framework_breakthrough,
                      judicial_logic, complex_dispute_resolution

    返回 JSON 字符串，包含：
    - weighted_total: 加权总分（含异常扣分和创新加分调整后）
    - base_weighted_total: 基础加权总分（调整前）
    - anomaly_deduction: 异常扣分总额
    - innovation_bonus: 创新性加分总额
    - grade: 等级（A/B/C/D/F）
    - grade_description: 等级描述
    - dimension_details: 各维度得分明细
    - anomaly_details: 异常扣分明细
    - innovation_details: 创新性加分明细
    """
    try:
        int_scores = {}
        for k, v in scores.items():
            try:
                int_scores[k] = int(v)
            except (ValueError, TypeError):
                int_scores[k] = 0
                logger.warning("calculate_weighted_score: invalid score for %s: %s, set to 0", k, v)

        result = _parser.calculate_weighted_score(int_scores, anomaly_items, innovation_items)
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("calculate_weighted_score: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"计算异常：{e}", retryable=True)


@mcp.tool()
def cross_check_consistency(scores: dict) -> str:
    """检查各维度评分间的逻辑一致性，返回冲突列表和建议。

    纯规则引擎，零 Token 消耗。Agent 在收集所有维度评分后应调用此工具。

    scores: 各维度得分字典，如 {"thorough_reasoning": 78, "substantive_resolution": 65, ...}

    返回 JSON 字符串，包含：
    - conflict_detected: 是否检测到冲突
    - conflicts: 冲突列表（每项含 rule_id, rule_name, message, conflict_dims）
    - suggestion: 处理建议
    - score_summary: 各维度得分摘要（方便排查）
    """
    try:
        int_scores = {}
        for k, v in scores.items():
            try:
                int_scores[k] = int(v)
            except (ValueError, TypeError):
                int_scores[k] = 0
                logger.warning("cross_check_consistency: invalid score for %s: %s, set to 0", k, v)

        logger.info("cross_check_consistency: input_scores=%s", int_scores)

        conflicts = []
        for rule in CROSS_CHECK_RULES:
            try:
                triggered = rule["check"](int_scores)
                logger.debug(
                    "cross_check_consistency: rule=%s (%s), triggered=%s, relevant_scores=%s",
                    rule["id"], rule["name"], triggered,
                    {d: int_scores.get(d, "N/A") for d in rule["conflict_dims"]},
                )
                if triggered:
                    conflict_entry = {
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "message": rule["message"],
                        "conflict_dims": rule["conflict_dims"],
                        "relevant_scores": {d: int_scores.get(d, 0) for d in rule["conflict_dims"]},
                    }
                    conflicts.append(conflict_entry)
                    logger.info(
                        "cross_check_consistency: CONFLICT rule=%s, dims=%s, scores=%s",
                        rule["id"], rule["conflict_dims"],
                        {d: int_scores.get(d, 0) for d in rule["conflict_dims"]},
                    )
            except Exception as e:
                logger.warning("cross_check rule %s error: %s", rule["id"], e)

        score_summary = {}
        for dim_key, score_val in int_scores.items():
            score_summary[dim_key] = {
                "score": score_val,
                "title": DIMENSION_TITLES.get(dim_key, dim_key),
                "weight": QUALITY_WEIGHTS.get(dim_key, 0.0),
                "weighted": round(score_val * QUALITY_WEIGHTS.get(dim_key, 0.0), 2),
            }

        result = {
            "success": True,
            "conflict_detected": len(conflicts) > 0,
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "score_summary": score_summary,
            "suggestion": (
                "若冲突存在，建议将相矛盾的两个维度及原文一并送交仲裁重评。"
                "可调用 render_dimension_prompt 获取仲裁 Prompt。"
                if conflicts else "各维度评分逻辑一致，无需仲裁。"
            ),
        }

        logger.info(
            "cross_check_consistency: completed, conflicts=%d, rules_checked=%d",
            len(conflicts), len(CROSS_CHECK_RULES),
        )

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("cross_check_consistency: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"一致性检查异常：{e}", retryable=True)


@mcp.tool()
def apply_anomaly_deduction(
    anomaly_results: list[dict],
) -> str:
    """根据judicial-doc-anomaly-mcp的检测结果，计算异常扣分。

    当与judicial-doc-anomaly-mcp联动使用时，Agent应将anomaly-mcp的检测结果
    传入此工具，获取结构化的扣分明细，再传入calculate_weighted_score。

    anomaly_results: anomaly-mcp返回的异常项列表，每项含：
        - type: 异常类型（procedural_anomaly/evidence_anomaly/fact_anomaly/
                law_application_anomaly/reasoning_anomaly/logic_anomaly）
        - severity: 严重程度（low/medium/high）
        - description: 异常描述
        - evidence: 支撑证据（可选）
        - reasoning: 判定理由（可选）

    返回 JSON 字符串，包含：
    - total_deduction: 总扣分
    - capped: 是否触及上限
    - items: 各异常项扣分明细
    - suggestion: 后续操作建议
    """
    try:
        logger.info("apply_anomaly_deduction: input_count=%d", len(anomaly_results))

        total_deduction = 0
        items = []
        type_totals: dict[str, float] = {}

        for anomaly in anomaly_results:
            anomaly_type = anomaly.get("type", "unknown")
            severity = anomaly.get("severity", "medium")
            desc = anomaly.get("description", "")
            evidence = anomaly.get("evidence", "")
            reasoning = anomaly.get("reasoning", "")

            rule = ANOMALY_DEDUCTION.get(anomaly_type)
            if not rule:
                logger.warning("apply_anomaly_deduction: unknown type=%s, skipping", anomaly_type)
                continue

            deduction = rule["severity_map"].get(severity, rule["per_item_deduction"])
            type_totals[anomaly_type] = type_totals.get(anomaly_type, 0) + deduction

            items.append({
                "type": anomaly_type,
                "label": rule["label"],
                "severity": severity,
                "deduction": deduction,
                "description": desc,
                "evidence": evidence,
                "reasoning": reasoning,
            })
            logger.debug(
                "apply_anomaly_deduction: type=%s, severity=%s, deduction=%d",
                anomaly_type, severity, deduction,
            )

        capped_items = []
        for anomaly_type, type_total in type_totals.items():
            rule = ANOMALY_DEDUCTION.get(anomaly_type)
            cap = rule["max_deduction"] if rule else type_total
            capped_val = min(type_total, cap)
            if type_total > cap:
                logger.info(
                    "apply_anomaly_deduction: capping type=%s, raw=%.0f, cap=%d",
                    anomaly_type, type_total, cap,
                )
            capped_items.append({
                "type": anomaly_type,
                "label": rule["label"] if rule else anomaly_type,
                "raw_deduction": type_total,
                "capped_deduction": capped_val,
                "cap": cap,
            })

        total_deduction = min(sum(c["capped_deduction"] for c in capped_items), ANOMALY_TOTAL_MAX_DEDUCTION)
        is_capped = total_deduction >= ANOMALY_TOTAL_MAX_DEDUCTION

        logger.info(
            "apply_anomaly_deduction: total=%d, capped=%s, items=%d",
            total_deduction, is_capped, len(items),
        )

        return json.dumps({
            "success": True,
            "total_deduction": total_deduction,
            "capped": is_capped,
            "max_deduction": ANOMALY_TOTAL_MAX_DEDUCTION,
            "items": items,
            "type_summaries": capped_items,
            "suggestion": (
                f"异常扣分合计{total_deduction}分。"
                "请将此结果传入 calculate_weighted_score 的 anomaly_items 参数。"
                if not is_capped
                else f"异常扣分已触及上限{ANOMALY_TOTAL_MAX_DEDUCTION}分。"
                "文书存在严重系统性异常，建议重点关注。"
            ),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("apply_anomaly_deduction: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"异常扣分计算异常：{e}", retryable=True)


@mcp.tool()
def apply_innovation_bonus(
    innovation_items: list[dict],
) -> str:
    """计算创新性加分项。

    当裁判文书或审判处理过程具有创新性时（如调解成功、法律漏洞填补、
    创造性突破既有框架、体现司法底层逻辑等），Agent应调用此工具
    计算创新性加分，再传入calculate_weighted_score。

    innovation_items: 创新性加分项列表，每项含：
        - type: 加分类型（mediation_success/legal_gap_filling/
                framework_breakthrough/judicial_logic/complex_dispute_resolution）
        - bonus: 建议加分值
        - description: 创新性描述
        - quote: 原文引用（可选）

    返回 JSON 字符串，包含：
    - total_bonus: 总加分
    - capped: 是否触及上限
    - items: 各加分项明细
    - suggestion: 后续操作建议
    """
    try:
        logger.info("apply_innovation_bonus: input_count=%d", len(innovation_items))

        total_bonus = 0
        items = []

        for item in innovation_items:
            bonus_type = item.get("type", "")
            bonus_value = item.get("bonus", 0)
            desc = item.get("description", "")
            quote = item.get("quote", "")

            rule = INNOVATION_BONUS.get(bonus_type)
            if not rule:
                logger.warning("apply_innovation_bonus: unknown type=%s, skipping", bonus_type)
                continue

            min_b, max_b = rule["bonus_range"]
            actual_bonus = max(min_b, min(max_b, bonus_value)) if bonus_value > 0 else 0
            total_bonus += actual_bonus

            items.append({
                "type": bonus_type,
                "label": rule["label"],
                "requested_bonus": bonus_value,
                "actual_bonus": actual_bonus,
                "range": f"+{min_b}至+{max_b}",
                "description": desc,
                "quote": quote,
            })
            logger.debug(
                "apply_innovation_bonus: type=%s, requested=%d, actual=%d",
                bonus_type, bonus_value, actual_bonus,
            )

        is_capped = total_bonus >= INNOVATION_TOTAL_MAX_BONUS
        total_bonus = min(total_bonus, INNOVATION_TOTAL_MAX_BONUS)

        logger.info(
            "apply_innovation_bonus: total=%d, capped=%s, items=%d",
            total_bonus, is_capped, len(items),
        )

        return json.dumps({
            "success": True,
            "total_bonus": total_bonus,
            "capped": is_capped,
            "max_bonus": INNOVATION_TOTAL_MAX_BONUS,
            "items": items,
            "suggestion": (
                f"创新性加分合计{total_bonus}分。"
                "请将此结果传入 calculate_weighted_score 的 innovation_items 参数。"
                if not is_capped
                else f"创新性加分已触及上限{INNOVATION_TOTAL_MAX_BONUS}分。"
            ),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("apply_innovation_bonus: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"创新加分计算异常：{e}", retryable=True)


@mcp.tool()
def get_dimension_standards(dimension: str) -> str:
    """获取指定维度的扣分项清单和加分项清单（不含文书段落，仅评分标准）。

    可用于 Agent 快速了解某维度的评分标准，无需渲染完整 Prompt。

    dimension: 维度标识（如 'thorough_reasoning'）

    返回 JSON 字符串，包含该维度的评分标准摘要。
    """
    try:
        skill_name = f"dimensions/{dimension}"
        meta, body = _loader.load(skill_name)

        deduction_items = []
        bonus_items = []

        deduction_pattern = re.compile(r"\|\s*([A-Z]-\d+)\s*\|\s*(.+?)\s*\|\s*[-]?(\d+)[~至]+(\d+)?\s*\|\s*(.+?)\s*\|")
        for m in deduction_pattern.finditer(body):
            deduction_items.append({
                "code": m.group(1),
                "item": m.group(2).strip(),
                "deduction_range": f"-{m.group(3)}" + (f"至-{m.group(4)}" if m.group(4) else ""),
                "standard": m.group(5).strip(),
            })

        bonus_pattern = re.compile(r"\|\s*([A-Z]-B\d+)\s*\|\s*(.+?)\s*\|\s*\+(\d+)[~至]+(\d+)?\s*\|\s*(.+?)\s*\|")
        for m in bonus_pattern.finditer(body):
            bonus_items.append({
                "code": m.group(1),
                "item": m.group(2).strip(),
                "bonus_range": f"+{m.group(3)}" + (f"至+{m.group(4)}" if m.group(4) else ""),
                "standard": m.group(5).strip(),
            })

        innovation_pattern = re.compile(r"\|\s*([A-Z]-IB\d+)\s*\|\s*(.+?)\s*\|\s*\+(\d+)[~至]+(\d+)?\s*\|\s*(.+?)\s*\|")
        for m in innovation_pattern.finditer(body):
            bonus_items.append({
                "code": m.group(1),
                "item": m.group(2).strip(),
                "bonus_range": f"+{m.group(3)}" + (f"至+{m.group(4)}" if m.group(4) else ""),
                "standard": m.group(5).strip(),
                "is_innovation": True,
            })

        result = {
            "success": True,
            "dimension": meta.name,
            "dimension_title": meta.title,
            "weight": meta.weight,
            "full_score": meta.full_score,
            "deduction_items": deduction_items,
            "bonus_items": bonus_items,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except FileNotFoundError as e:
        return _make_error(ErrorCode.DIMENSION_NOT_FOUND, f"维度不存在：{e}", details={"dimension": dimension})
    except Exception as e:
        logger.error("get_dimension_standards: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"获取标准异常：{e}", retryable=True)


@mcp.tool()
def estimate_token_budget(
    dimensions: list[str] | None = None,
    include_anchors: bool = True,
    anchor_count: int = 3,
    document_char_count: int = 5000,
    model_context_window: int = 128000,
    model_max_output: int = 4096,
) -> str:
    """预估评估指定维度的 Token 预算，帮助 Agent 规划调用策略。

    借鉴 Claude Code 的 Token 预算管理机制，此工具帮助 Agent：
    1. 了解每个维度的 Prompt 大致 Token 消耗
    2. 判断是否需要分批评估（避免超出上下文窗口）
    3. 规划最优的并行/串行调用策略

    dimensions: 要评估的维度列表（默认全部7个维度）
    include_anchors: 是否包含锚定示例（默认 true）
    anchor_count: 每个维度的锚定示例数量（默认 3）
    document_char_count: 文书全文的字符数（默认 5000）
    model_context_window: LLM 的上下文窗口大小（默认 128000）
    model_max_output: LLM 的最大输出 Token 数（默认 4096）

    返回 JSON 字符串，包含：
    - total_input_tokens: 预估总输入 Token 数
    - per_dimension_estimate: 每个维度的 Token 预估
    - budget_feasible: 是否在上下文窗口内
    - recommended_strategy: 推荐调用策略（parallel/batch_2/batch_3/sequential）
    - overflow_risk: 溢出风险等级
    """
    logger.info(
        "estimate_token_budget: >>> ENTER | dims=%s, doc_chars=%d, context_window=%d",
        dimensions if dimensions else "ALL(7)", document_char_count, model_context_window,
    )
    try:
        if dimensions is None:
            dimensions = list(QUALITY_WEIGHTS.keys())

        per_dim = []
        total_input = 0

        doc_tokens = _estimate_tokens(" " * document_char_count)

        for dim in dimensions:
            try:
                meta, body = _loader.load(f"dimensions/{dim}")
                system_prompt = build_system_prompt(meta) + "\n\n" + ANTI_LAZINESS_INSTRUCTION
                system_tokens = _estimate_tokens(system_prompt)
                prompt_tokens = _estimate_tokens(body)

                anchor_tokens = 0
                if include_anchors:
                    anchors = _loader.load_anchors(dim)[:anchor_count]
                    if anchors:
                        anchor_tokens = _estimate_tokens(json.dumps(anchors, ensure_ascii=False))

                dim_input = system_tokens + prompt_tokens + doc_tokens + anchor_tokens
                total_input += dim_input

                per_dim.append({
                    "dimension": dim,
                    "dimension_title": meta.title,
                    "system_prompt_tokens": system_tokens,
                    "user_prompt_tokens": prompt_tokens,
                    "document_tokens": doc_tokens,
                    "anchor_tokens": anchor_tokens,
                    "total_input_tokens": dim_input,
                    "estimated_output_tokens": 500,
                })
            except Exception as e:
                logger.warning("estimate_token_budget: failed for dim=%s: %s", dim, e)
                per_dim.append({
                    "dimension": dim,
                    "error": str(e),
                })

        available = model_context_window - model_max_output
        budget_feasible = total_input <= available
        utilization = total_input / available if available > 0 else 1.0

        if utilization <= 0.5:
            strategy = "parallel"
            risk = "low"
        elif utilization <= 0.75:
            strategy = "parallel"
            risk = "medium"
        elif utilization <= 1.0:
            strategy = "batch_2"
            risk = "high"
        else:
            strategy = "sequential"
            risk = "critical"

        logger.info(
            "estimate_token_budget: <<< EXIT | dims=%d, total_input=%d, available=%d, feasible=%s, strategy=%s",
            len(dimensions), total_input, available, budget_feasible, strategy,
        )

        return json.dumps({
            "success": True,
            "total_input_tokens": total_input,
            "available_context": available,
            "context_utilization": round(utilization, 3),
            "budget_feasible": budget_feasible,
            "recommended_strategy": strategy,
            "overflow_risk": risk,
            "per_dimension_estimate": per_dim,
            "recommendations": {
                "parallel": "所有维度可并行评估，每个维度独立调用LLM",
                "batch_2": "建议分2批评估：第1批4个维度，第2批3个维度",
                "batch_3": "建议分3批评估：每批2-3个维度",
                "sequential": "必须逐个维度串行评估，避免上下文溢出",
            }.get(strategy, "逐个维度串行评估"),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(
            "estimate_token_budget: <<< EXIT (ERROR) | exception=%s",
            e, exc_info=True,
        )
        return _make_error(ErrorCode.INTERNAL_ERROR, f"Token预算预估异常：{e}", retryable=True)


@mcp.tool()
def generate_report(
    dimension_results: list[dict],
    weighted_total: float,
    grade: str,
    cross_check: dict | None = None,
    anomaly_deduction: float = 0,
    innovation_bonus: float = 0,
    anomaly_details: list[dict] | None = None,
    innovation_details: list[dict] | None = None,
    anomaly_mcp_results: list[dict] | None = None,
    timeline_result: dict | None = None,
    evasive_result: dict | None = None,
    evidence_result: dict | None = None,
    document_meta: dict | None = None,
) -> str:
    """生成结构化 Markdown 评分报告。纯规则函数，零 Token 消耗。

    Agent 收集所有评分结果后，调用此工具生成最终报告。
    支持 GitHub Alerts 风格（NOTE/TIP/IMPORTANT/WARNING/CAUTION）的 quote block。

    dimension_results: 各维度评分结果列表（来自 parse_score_result 的 parsed 字段）
    weighted_total: 加权总分（来自 calculate_weighted_score）
    grade: 等级（来自 calculate_weighted_score）
    cross_check: 一致性检查结果（来自 cross_check_consistency，可选）
    anomaly_deduction: 异常扣分总额（来自 calculate_weighted_score）
    innovation_bonus: 创新性加分总额（来自 calculate_weighted_score）
    anomaly_details: 异常扣分明细（来自 calculate_weighted_score）
    innovation_details: 创新性加分明细（来自 calculate_weighted_score）
    anomaly_mcp_results: 异常检测MCP联动结果（来自 query_anomaly_mcp，可选）
    timeline_result: 时间线检测结果（来自 extract_timeline，可选）
    evasive_result: 规避模式检测结果（来自 detect_evasive_patterns，可选）
    evidence_result: 证据追踪结果（来自 trace_evidence_references，可选）
    document_meta: 文书元信息（案号、法院、案件类型等，可选）

    返回 JSON 字符串，包含 report_markdown 字段。
    """
    try:
        lines = []

        # ── 标题与元信息 ──
        lines.append("# 裁判文书质量评估报告\n")

        if document_meta:
            lines.append("| 项目 | 内容 |")
            lines.append("|:---|:---|")
            for k, v in document_meta.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")

        # ── 综合评级 ──
        grade_desc = QUALITY_GRADES.get(grade, (0, 0, "未知"))[2]
        grade_lo, grade_hi = QUALITY_GRADES.get(grade, (0, 100))

        lines.append("## 综合评级\n")
        lines.append(f"**{grade}（{grade_desc}）**  |  加权总分 **{weighted_total}** / 100  |  等级区间 [{grade_lo}, {grade_hi}]\n")

        if anomaly_deduction > 0 or innovation_bonus > 0:
            base = weighted_total - innovation_bonus + anomaly_deduction
            lines.append("> [!NOTE]")
            lines.append(f"> 基础分 {base:.1f}  |  异常扣分 −{anomaly_deduction:.0f}  |  创新加分 +{innovation_bonus:.0f}")
            lines.append("")

        # ── 等级说明 ──
        lines.append("> [!TIP]")
        lines.append("> **等级划分**：A 优秀 [95,100] · A⁻ 优良 [90,94] · B⁺ 良好 [85,89] · B 中上 [80,84] · C⁺ 中等 [75,79] · C 中下 [70,74] · D 及格 [60,69] · F 不及格 [0,59]")
        lines.append("")

        # ── 各维度评分 ──
        lines.append("## 各维度评分\n")
        lines.append("| 维度 | 得分 | 权重 | 加权得分 | 核心扣分项 | 核心加分项 |")
        lines.append("|:---|:---:|:---:|:---:|:---|:---|")

        for dr in dimension_results:
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0
            weight = QUALITY_WEIGHTS.get(dim, 0.0)
            weighted = round(score * weight, 2)

            deductions = dr.get("deduction_items", [])
            ded_summary = "、".join(d.get("item", "")[:15] for d in deductions[:2]) if deductions else "—"
            bonuses = dr.get("bonus_items", [])
            bon_summary = "、".join(b.get("item", "")[:15] for b in bonuses[:2]) if bonuses else "—"

            lines.append(f"| {title} | {score} | {weight*100:.0f}% | {weighted} | {ded_summary} | {bon_summary} |")

        lines.append("")

        # ── 异常扣分明细 ──
        if anomaly_details:
            lines.append("## 异常扣分明细\n")
            lines.append("> [!CAUTION]")
            lines.append(f"> 检出 {len(anomaly_details)} 项异常，合计扣分 −{anomaly_deduction:.0f}\n")
            lines.append("| 异常类型 | 严重程度 | 扣分 | 描述 |")
            lines.append("|:---|:---:|:---:|:---|")
            for ad in anomaly_details:
                lines.append(f"| {ad.get('label', '')} | {ad.get('severity', '')} | -{ad.get('deduction', 0)} | {ad.get('description', '')[:40]} |")
            lines.append("")

        # ── 创新性加分明细 ──
        if innovation_details:
            lines.append("## 创新性加分明细\n")
            lines.append("> [!TIP]")
            lines.append(f"> 检出 {len(innovation_details)} 项创新亮点，合计加分 +{innovation_bonus:.0f}\n")
            lines.append("| 加分类型 | 加分 | 描述 |")
            lines.append("|:---|:---:|:---|")
            for id_item in innovation_details:
                lines.append(f"| {id_item.get('label', '')} | +{id_item.get('bonus', 0)} | {id_item.get('description', '')[:40]} |")
            lines.append("")

        # ── 辅助检测结果 ──
        has_aux = timeline_result or evasive_result or evidence_result
        if has_aux:
            lines.append("## 辅助检测结果\n")

            if timeline_result:
                total_events = timeline_result.get("total_events", 0)
                anomaly_count = timeline_result.get("anomaly_count", 0)
                completeness = timeline_result.get("completeness", "N/A")
                anomalies = timeline_result.get("anomalies", [])

                lines.append("### 时间线提取与异常检测\n")
                lines.append(f"| 指标 | 结果 |")
                lines.append(f"|:---|:---|")
                lines.append(f"| 提取事件数 | {total_events} |")
                lines.append(f"| 时间线异常数 | {anomaly_count} |")
                lines.append(f"| 时间线完整性 | {completeness} |")
                lines.append("")

                if anomalies:
                    high_anomalies = [a for a in anomalies if a.get("severity") == "high"]
                    if high_anomalies:
                        lines.append("> [!WARNING]")
                        lines.append(f"> 检出 {len(high_anomalies)} 项高严重度时间线异常（时间倒置），请核实是否为叙事结构导致的伪异常\n")
                    else:
                        lines.append("> [!NOTE]")
                        lines.append("> 时间线异常均为低严重度，不影响文书质量评价\n")

                    lines.append("| 严重程度 | 异常类型 | 说明 |")
                    lines.append("|:---:|:---|:---|")
                    for a in anomalies[:10]:
                        lines.append(f"| {a.get('severity', '?')} | {a.get('type', '?')} | {a.get('message', '')[:60]} |")
                    if len(anomalies) > 10:
                        lines.append(f"| | | ... 另有 {len(anomalies) - 10} 项省略 |")
                    lines.append("")

            if evasive_result:
                risk_level = evasive_result.get("risk_level", "N/A")
                detected_count = evasive_result.get("detected_count", 0)
                patterns = evasive_result.get("patterns", [])
                recommendation = evasive_result.get("recommendation", "")

                lines.append("### 规避模式检测\n")
                lines.append(f"| 指标 | 结果 |")
                lines.append(f"|:---|:---|")
                lines.append(f"| 风险等级 | {risk_level} |")
                lines.append(f"| 检出模式数 | {detected_count} |")
                lines.append("")

                if risk_level in ("high", "medium"):
                    lines.append("> [!CAUTION]")
                    lines.append(f"> 规避模式风险等级为 **{risk_level}**，建议重点关注\n")
                elif risk_level == "low":
                    lines.append("> [!NOTE]")
                    lines.append("> 规避模式风险等级为低，文书规避倾向不明显\n")

                if patterns:
                    lines.append("| 严重程度 | 模式名称 | 匹配数 | 说明 |")
                    lines.append("|:---:|:---|:---:|:---|")
                    for p in patterns:
                        lines.append(f"| {p.get('severity', '?')} | {p.get('name', '?')} | {p.get('match_count', 0)} | {p.get('description', '')[:50]} |")
                    lines.append("")

                if recommendation:
                    lines.append(f"> [!IMPORTANT]")
                    lines.append(f"> {recommendation}\n")

            if evidence_result:
                total_ev = evidence_result.get("total_evidence", 0)
                unaddressed = evidence_result.get("unaddressed_count", 0)
                missing_reasoning = evidence_result.get("missing_reasoning_count", 0)
                completeness = evidence_result.get("completeness", "N/A")

                lines.append("### 证据引用追踪\n")
                lines.append(f"| 指标 | 结果 |")
                lines.append(f"|:---|:---|")
                lines.append(f"| 证据项数 | {total_ev} |")
                lines.append(f"| 未回应证据 | {unaddressed} |")
                lines.append(f"| 缺说理证据 | {missing_reasoning} |")
                lines.append(f"| 引用完整性 | {completeness} |")
                lines.append("")

                if unaddressed > 0 or missing_reasoning > 0:
                    lines.append("> [!WARNING]")
                    lines.append(f"> 存在 {unaddressed} 项未回应证据、{missing_reasoning} 项缺说理证据，可能影响证据采信的正当性\n")
                else:
                    lines.append("> [!TIP]")
                    lines.append("> 证据引用完整，所有证据均有回应和说理\n")

        # ── 异常检测MCP联动 ──
        if anomaly_mcp_results:
            lines.append("## 异常检测MCP联动结果\n")
            lines.append("> [!IMPORTANT]")
            lines.append("> 以下异常检测结果来自 [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp) 的16维检测体系，")
            lines.append("> 覆盖程序异常、证据异常、事实认定异常、修辞技巧异常、逻辑异常、时间一致性、语义漂移等维度。")
            lines.append("> 检测结果已自动纳入本报告的异常扣分计算。\n")

            risk_summary = {}
            total_anomalies = 0
            for dim_result in anomaly_mcp_results:
                dim_anomalies = dim_result.get("anomalies", [])
                dim_count = dim_result.get("anomaly_count", len(dim_anomalies))
                total_anomalies += dim_count
                dim_risk = dim_result.get("risk_level", "unknown")
                risk_summary[dim_risk] = risk_summary.get(dim_risk, 0) + 1

            lines.append("### 检测概览\n")
            lines.append(f"| 指标 | 结果 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| 扫描维度数 | {len(anomaly_mcp_results)} |")
            lines.append(f"| 检出异常总数 | {total_anomalies} |")
            risk_order = ["critical", "high", "medium", "low", "unknown"]
            risk_labels = {"critical": "严重", "high": "高", "medium": "中", "low": "低", "unknown": "未知"}
            for rk in risk_order:
                if rk in risk_summary:
                    lines.append(f"| {risk_labels.get(rk, rk)}风险维度 | {risk_summary[rk]} |")
            lines.append("")

            critical_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "critical"]
            high_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "high"]
            medium_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "medium"]
            low_dims = [d for d in anomaly_mcp_results if d.get("risk_level") in ("low", "unknown")]

            if critical_dims:
                lines.append("> [!CAUTION]")
                dim_names = ", ".join(d.get("dimension", "?") for d in critical_dims)
                lines.append(f"> **严重风险**：{len(critical_dims)} 个维度存在严重异常（{dim_names}），强烈建议重点审查\n")

            if high_dims:
                lines.append("> [!WARNING]")
                dim_names = ", ".join(d.get("dimension", "?") for d in high_dims)
                lines.append(f"> **高风险**：{len(high_dims)} 个维度存在高严重度异常（{dim_names}），建议重点关注\n")

            if medium_dims:
                lines.append("> [!NOTE]")
                dim_names = ", ".join(d.get("dimension", "?") for d in medium_dims)
                lines.append(f"> **中风险**：{len(medium_dims)} 个维度存在中等异常（{dim_names}），建议留意\n")

            lines.append("### 各维度异常详情\n")
            for dim_result in anomaly_mcp_results:
                dim_name = dim_result.get("dimension", "?")
                dim_risk = dim_result.get("risk_level", "unknown")
                dim_count = dim_result.get("anomaly_count", 0)
                dim_summary = dim_result.get("summary", "")
                dim_anomalies = dim_result.get("anomalies", [])

                risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "unknown": "⚪"}.get(dim_risk, "⚪")
                lines.append(f"#### {risk_icon} {dim_name}（{risk_labels.get(dim_risk, dim_risk)}风险，{dim_count} 项异常）\n")

                if dim_summary:
                    lines.append(f"> {dim_summary}\n")

                if dim_anomalies:
                    lines.append("| 异常项 | 受益方 | 置信度 | 简述 |")
                    lines.append("|:---|:---:|:---:|:---|")
                    for a in dim_anomalies[:8]:
                        name = a.get("item_name", a.get("f_code", "?"))
                        beneficiary = a.get("beneficiary", "?")
                        confidence = a.get("confidence", "?")
                        desc = a.get("description", "")[:50]
                        lines.append(f"| {name} | {beneficiary} | {confidence} | {desc} |")
                    if len(dim_anomalies) > 8:
                        lines.append(f"| | | | ... 另有 {len(dim_anomalies) - 8} 项省略 |")
                    lines.append("")

            lines.append("> [!TIP]")
            lines.append("> 异常检测与质量评估互补：质量评估侧重文书规范性，异常检测侧重潜在不公与程序瑕疵。")
            lines.append("> 两项结果合并参考，可更全面地评价文书质量。\n")
        else:
            lines.append("## 异常检测MCP联动\n")
            auto_detected = ANOMALY_MCP_CONFIG.get("auto_detected", False)
            if auto_detected:
                lines.append("> [!NOTE]")
                lines.append("> judicial-doc-anomaly-mcp 已安装但本次评估未调用异常检测。")
                lines.append("> 可通过 `query_anomaly_mcp` 工具获取16维异常检测结果，自动纳入异常扣分计算。\n")
            else:
                lines.append("> [!NOTE]")
                lines.append("> judicial-doc-anomaly-mcp 未安装，16维异常检测结果为空白。")
                lines.append("> 安装方式：`pip install judicial-lint-mcp`")
                lines.append("> 安装后系统将自动检测并启用联动，无需手动配置。\n")

        # ── 一致性审查 ──
        if cross_check and cross_check.get("conflict_detected"):
            lines.append("## 一致性审查\n")
            lines.append("> [!WARNING]")
            lines.append(f"> 检出 {len(cross_check.get('conflicts', []))} 项维度间逻辑矛盾\n")
            for c in cross_check.get("conflicts", []):
                lines.append(f"- **{c.get('rule_name', '')}**：{c.get('message', '')}")
            lines.append("")
        elif cross_check:
            lines.append("## 一致性审查\n")
            lines.append("> [!TIP]")
            lines.append("> 各维度评分逻辑一致，未检出矛盾\n")

        # ── 免责声明 ──
        lines.append("---\n")
        lines.append("> [!IMPORTANT]")
        lines.append("> **免责声明**：本报告由 judicial-doc-quality-mcp 辅助生成，基于七维评分体系和规则引擎的自动化分析。")
        lines.append("> 评估结果仅供参考，不构成法律意见。裁判文书的质量评价涉及复杂的法律判断，")
        lines.append("> 本报告不能替代专业法律人士的审查。\n")

        lines.append(f"*报告由 judicial-doc-quality-mcp v0.1.0 生成*")

        return json.dumps({
            "success": True,
            "report_markdown": "\n".join(lines),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("generate_report: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"报告生成异常：{e}")


@mcp.tool()
def query_anomaly_mcp(
    document_text: str,
    dimensions: list[str] | None = None,
) -> str:
    """自动检测并调用 judicial-doc-anomaly-mcp 进行异常检测。

    启动时自动检测 anomaly-mcp 是否已安装且可导入：
    - 已安装：自动调用 render_skill 生成各维度检测 Prompt，返回给 Agent
    - 未安装：返回空白结果，Agent 可继续使用质量评估流程

    本工具返回检测 Prompt 列表，Agent 需将每个 Prompt 发送给自己的 LLM，
    再将 LLM 响应通过 submit_anomaly_response 提交解析。
    完成全部维度后调用 finalize_anomaly_detection 获取汇总结果。

    推荐搭配使用：https://github.com/lcfactorization/judicial-doc-anomaly-mcp
    该项目提供16维司法文书异常检测能力，与本项目形成互补：
    - 本项目（judicial-doc-quality-mcp）：评估文书质量，7维评分+创新加分
    - anomaly-mcp（judicial-doc-anomaly-mcp）：检测文书异常，16维异常+扣分联动

    document_text: 裁判文书全文
    dimensions: 要检测的异常维度列表（默认全部16个维度），可选值：
        procedure, evidence, fact_finding, focus_drift, law_application,
        discretion, rhetoric_trick, logic, temporal, trial_process,
        external_interference, execution, negative_space, semantic_drift,
        case_deviation, coupling

    返回 JSON 字符串，包含：
    - available: anomaly-mcp 是否可用
    - auto_detected: 是否通过自动检测发现
    - prompts: 各维度的检测 Prompt 列表（Agent 需发送给 LLM）
    - dimensions: 请求检测的维度列表
    - message: 操作说明
    """
    logger.info(
        "query_anomaly_mcp: >>> ENTER | doc_len=%d, requested_dims=%s",
        len(document_text),
        dimensions if dimensions else "ALL(16)",
    )
    try:
        if dimensions is None:
            dimensions = ANOMALY_MCP_CONFIG["supported_dimensions"]
            logger.debug("query_anomaly_mcp: using default dimensions=%d", len(dimensions))

        available = ANOMALY_MCP_CONFIG["available"]
        auto_detected = ANOMALY_MCP_CONFIG.get("auto_detected", False)
        logger.info(
            "query_anomaly_mcp: anomaly-mcp availability | server=%s, available=%s, auto_detected=%s",
            ANOMALY_MCP_CONFIG["server_name"],
            available,
            auto_detected,
        )

        if not available:
            logger.info(
                "query_anomaly_mcp: anomaly-mcp NOT available, returning blank results"
            )
            result = {
                "success": True,
                "available": False,
                "auto_detected": False,
                "anomaly_results": [],
                "prompts": [],
                "dimensions": dimensions,
                "fallback_mode": ANOMALY_MCP_CONFIG["fallback_mode"],
                "message": (
                    "judicial-doc-anomaly-mcp 当前不可用（未检测到安装）。"
                    "异常扣分项将留空白，质量评估流程不受影响。"
                ),
                "suggestion": (
                    "如需启用异常检测联动，请安装：pip install judicial-lint-mcp "
                    "或参考 https://github.com/lcfactorization/judicial-doc-anomaly-mcp"
                ),
            }
            logger.info("query_anomaly_mcp: <<< EXIT (unavailable)")
            return json.dumps(result, ensure_ascii=False, indent=2)

        try:
            from judicial_lint_mcp.server import render_skill, list_skills
        except ImportError:
            logger.warning("query_anomaly_mcp: anomaly-mcp import failed, falling back")
            ANOMALY_MCP_CONFIG["available"] = False
            result = {
                "success": True,
                "available": False,
                "auto_detected": False,
                "anomaly_results": [],
                "prompts": [],
                "dimensions": dimensions,
                "fallback_mode": "import_failed",
                "message": "judicial-doc-anomaly-mcp 导入失败，已自动降级为不可用模式。",
                "suggestion": "请检查 judicial-lint-mcp 安装是否完整。",
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        logger.info(
            "query_anomaly_mcp: anomaly-mcp IS available, generating prompts for %d dimensions",
            len(dimensions),
        )

        prompts = []
        for idx, dim in enumerate(dimensions):
            try:
                prompt_json = render_skill(
                    dimension=dim,
                    case_material=document_text,
                    dimension_index=idx,
                )
                prompt_data = json.loads(prompt_json)
                prompts.append({
                    "dimension": dim,
                    "dimension_index": idx,
                    "system_prompt": prompt_data.get("system_prompt", ""),
                    "user_prompt": prompt_data.get("user_prompt", ""),
                    "estimated_tokens": prompt_data.get("estimated_tokens", 0),
                })
                logger.debug("query_anomaly_mcp: generated prompt for dim=%s", dim)
            except Exception as e:
                logger.warning("query_anomaly_mcp: failed to generate prompt for dim=%s: %s", dim, e)
                prompts.append({
                    "dimension": dim,
                    "dimension_index": idx,
                    "error": str(e),
                })

        _anomaly_session["dimensions"] = dimensions
        _anomaly_session["collected_results"] = {}
        _anomaly_session["total_dimensions"] = len(dimensions)
        _anomaly_session["document_text"] = document_text

        result = {
            "success": True,
            "available": True,
            "auto_detected": auto_detected,
            "anomaly_results": [],
            "prompts": prompts,
            "dimensions": dimensions,
            "total_prompts": len(prompts),
            "message": (
                f"已自动检测到 judicial-doc-anomaly-mcp 并生成 {len(prompts)} 个维度的检测 Prompt。"
                "请将每个 Prompt 的 system_prompt + user_prompt 发送给 LLM，"
                "再将 LLM 响应通过 submit_anomaly_response 提交解析。"
            ),
            "next_step": (
                "对每个 prompt 调用 submit_anomaly_response(dimension, llm_response, dimension_index)，"
                "全部完成后调用 finalize_anomaly_detection() 获取汇总结果。"
            ),
        }
        logger.info("query_anomaly_mcp: <<< EXIT (available) | %d prompts generated", len(prompts))
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("query_anomaly_mcp: <<< EXIT (ERROR) | exception=%s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"异常MCP查询异常：{e}", retryable=True)


_anomaly_session: dict = {
    "dimensions": [],
    "collected_results": {},
    "total_dimensions": 0,
    "document_text": "",
}


@mcp.tool()
def submit_anomaly_response(
    dimension: str,
    llm_response: str,
    dimension_index: int = 0,
) -> str:
    """提交 LLM 对某个异常检测维度的响应，自动解析为结构化异常数据。

    当 query_anomaly_mcp 返回 prompts 后，Agent 将每个 prompt 发送给 LLM，
    再将 LLM 的响应通过此工具提交。本工具会自动调用 anomaly-mcp 的
    parse_response 进行解析，并将结果暂存到会话中。

    全部维度完成后，调用 finalize_anomaly_detection 获取汇总结果。

    dimension: 维度标识（如 'procedure', 'evidence', 'fact_finding'）
    llm_response: LLM 返回的原始响应文本
    dimension_index: 维度索引（0-15），用于分类体系映射

    返回 JSON 字符串，包含：
    - dimension: 维度标识
    - anomaly_count: 检出的异常项数量
    - risk_level: 风险等级
    - progress: 当前收集进度（已收集/总维度数）
    """
    logger.info(
        "submit_anomaly_response: >>> ENTER | dimension=%s, dim_index=%d, response_len=%d",
        dimension, dimension_index, len(llm_response),
    )
    try:
        try:
            from judicial_lint_mcp.server import parse_response as anomaly_parse
        except ImportError:
            result = {
                "success": False,
                "error": "judicial-doc-anomaly-mcp 不可用，无法解析响应。",
                "dimension": dimension,
            }
            return json.dumps(result, ensure_ascii=False, indent=2)

        parsed_json = anomaly_parse(
            dimension=dimension,
            response=llm_response,
            dimension_index=dimension_index,
        )
        parsed_data = json.loads(parsed_json)

        if "error" in parsed_data:
            logger.warning("submit_anomaly_response: parse error for dim=%s: %s", dimension, parsed_data["error"])
            _anomaly_session["collected_results"][dimension] = {
                "dimension": dimension,
                "anomaly_count": 0,
                "risk_level": "unknown",
                "anomalies": [],
                "summary": f"解析失败：{parsed_data['error']}",
            }
        else:
            _anomaly_session["collected_results"][dimension] = parsed_data
            logger.info(
                "submit_anomaly_response: parsed dim=%s | anomaly_count=%d, risk_level=%s",
                dimension,
                parsed_data.get("anomaly_count", 0),
                parsed_data.get("risk_level", "unknown"),
            )

        collected = len(_anomaly_session["collected_results"])
        total = _anomaly_session["total_dimensions"]

        result = {
            "success": True,
            "dimension": dimension,
            "anomaly_count": parsed_data.get("anomaly_count", 0),
            "risk_level": parsed_data.get("risk_level", "unknown"),
            "progress": f"{collected}/{total}",
            "is_complete": collected >= total,
            "next_step": (
                "继续提交剩余维度的响应，或如果全部完成则调用 finalize_anomaly_detection()"
                if collected < total
                else "所有维度已收集完毕，请调用 finalize_anomaly_detection() 获取汇总结果"
            ),
        }
        logger.info("submit_anomaly_response: <<< EXIT | progress=%d/%d", collected, total)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("submit_anomaly_response: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"提交异常响应失败：{e}", retryable=True)


@mcp.tool()
def finalize_anomaly_detection() -> str:
    """汇总所有已提交的异常检测结果，生成最终异常数据。

    在 Agent 完成所有维度的 submit_anomaly_response 后调用此工具，
    获取汇总的异常检测结果列表，可直接传入 apply_anomaly_deduction
    和 generate_report 的 anomaly_mcp_results 参数。

    返回 JSON 字符串，包含：
    - anomaly_results: 所有维度的异常检测结果列表
    - total_anomalies: 检出的异常项总数
    - risk_summary: 各风险等级的统计
    - dimensions_scanned: 已扫描的维度列表
    - dimensions_missing: 未提交响应的维度列表
    """
    logger.info("finalize_anomaly_detection: >>> ENTER")
    try:
        collected = _anomaly_session["collected_results"]
        total_dims = _anomaly_session["total_dimensions"]
        all_dimensions = _anomaly_session["dimensions"]

        anomaly_results = []
        total_anomalies = 0
        risk_summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}

        for dim_key in all_dimensions:
            dim_data = collected.get(dim_key)
            if dim_data is None:
                continue
            anomaly_results.append(dim_data)
            count = dim_data.get("anomaly_count", 0)
            total_anomalies += count
            risk = dim_data.get("risk_level", "unknown")
            risk_summary[risk] = risk_summary.get(risk, 0) + 1

        missing = [d for d in all_dimensions if d not in collected]

        result = {
            "success": True,
            "anomaly_results": anomaly_results,
            "total_anomalies": total_anomalies,
            "risk_summary": risk_summary,
            "dimensions_scanned": list(collected.keys()),
            "dimensions_missing": missing,
            "total_dimensions": total_dims,
            "completed": len(missing) == 0,
            "message": (
                f"异常检测汇总完成：共扫描 {len(collected)}/{total_dims} 个维度，"
                f"检出 {total_anomalies} 项异常。"
                + ("所有维度已完成。" if not missing else f"未完成维度：{', '.join(missing)}")
            ),
            "next_step": (
                "将 anomaly_results 传入 apply_anomaly_deduction 计算扣分，"
                "再传入 generate_report 的 anomaly_mcp_results 参数生成合并报告。"
            ),
        }
        logger.info(
            "finalize_anomaly_detection: <<< EXIT | %d/%d dims, %d anomalies",
            len(collected), total_dims, total_anomalies,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("finalize_anomaly_detection: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"汇总异常检测失败：{e}", retryable=True)


@mcp.tool()
def check_anomaly_mcp_status() -> str:
    """检查 judicial-doc-anomaly-mcp 的安装和运行状态。

    返回 JSON 字符串，包含：
    - installed: 是否已安装
    - auto_detected: 是否通过自动检测发现
    - importable: 是否可成功导入
    - server_name: MCP 服务器名称
    - supported_dimensions: 支持的检测维度列表
    - version: 版本号（如可获取）
    """
    logger.info("check_anomaly_mcp_status: >>> ENTER")
    try:
        auto_detected = ANOMALY_MCP_CONFIG.get("auto_detected", False)
        importable = False
        version = None
        try:
            import judicial_lint_mcp
            importable = True
            version = getattr(judicial_lint_mcp, "__version__", None)
        except ImportError:
            pass

        result = {
            "success": True,
            "installed": auto_detected or importable,
            "auto_detected": auto_detected,
            "importable": importable,
            "server_name": ANOMALY_MCP_CONFIG["server_name"],
            "supported_dimensions": ANOMALY_MCP_CONFIG["supported_dimensions"],
            "version": version,
            "message": (
                f"judicial-doc-anomaly-mcp 状态：{'已安装可导入' if importable else '未安装或不可导入'}"
                + (f"（v{version}）" if version else "")
                + f"，自动检测：{'通过' if auto_detected else '未通过'}"
            ),
        }
        logger.info("check_anomaly_mcp_status: <<< EXIT | importable=%s", importable)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("check_anomaly_mcp_status: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"状态检查异常：{e}")


@mcp.tool()
def extract_timeline(document_text: str) -> str:
    """从裁判文书中提取时间线事件，检测时间线异常。

    借鉴 ChatGPT 5.5 建议的"时间线一致性引擎"：
    提取文书中的时间节点，检测时间倒置、缺口、逻辑不闭合等异常。

    可与 judicial-doc-anomaly-mcp 联动使用：
    https://github.com/lcfactorization/judicial-doc-anomaly-mcp
    该项目的 temporal 维度可提供更深入的时间一致性检测。

    document_text: 裁判文书全文

    返回 JSON 字符串，包含：
    - events: 提取的时间线事件列表
    - anomalies: 时间线异常列表
    - coverage: 时间线覆盖率评估
    """
    logger.info(
        "extract_timeline: >>> ENTER | doc_len=%d",
        len(document_text),
    )
    try:
        date_pattern = re.compile(
            r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(?:\d{1,2}\s*日)?"
            r"|(\d{4})[./-](\d{1,2})[./-](?:\d{1,2})?"
            r"|(?:二[〇零○O0])[一二三四五六七八九零〇○O0]{4}年[一二三四五六七八九十]{1,2}月"
        )

        events = []
        for i, m in enumerate(date_pattern.finditer(document_text)):
            pos = m.start()
            context_start = max(0, pos - 40)
            context_end = min(len(document_text), pos + len(m.group()) + 40)
            context = document_text[context_start:context_end].replace("\n", " ").strip()

            if m.group(1):
                year, month = int(m.group(1)), int(m.group(2))
            elif m.group(3):
                year, month = int(m.group(3)), int(m.group(4))
            else:
                year, month = 0, 0

            if year > 0:
                events.append({
                    "index": i + 1,
                    "date": f"{year}-{month:02d}",
                    "year": year,
                    "month": month,
                    "context": context,
                    "position": pos,
                })

        anomalies = []
        original_order_events = list(events)
        for i in range(1, len(original_order_events)):
            prev = original_order_events[i - 1]
            curr = original_order_events[i]
            if curr["year"] < prev["year"] or (
                curr["year"] == prev["year"] and curr["month"] < prev["month"]
            ):
                anomalies.append({
                    "type": "temporal_inversion",
                    "severity": "high",
                    "message": f"时间倒置：文书第{prev['index']}处'{prev['context'][:30]}...'({prev['date']}) 出现在第{curr['index']}处'{curr['context'][:30]}...'({curr['date']}) 之后",
                    "evidence": [prev["context"][:80], curr["context"][:80]],
                    "reasoning": "文书中事件叙述顺序与时间线不一致，可能存在逻辑错误或事实认定偏差",
                })

        events.sort(key=lambda e: (e["year"], e["month"]))

        if len(events) >= 2:
            first_year = events[0]["year"]
            last_year = events[-1]["year"]
            span = last_year - first_year
            if span > 5:
                years_covered = set(e["year"] for e in events)
                expected = set(range(first_year, last_year + 1))
                gaps = expected - years_covered
                if gaps:
                    anomalies.append({
                        "type": "temporal_gap",
                        "severity": "medium",
                        "message": f"时间线存在{len(gaps)}个年份缺口：{sorted(gaps)}",
                        "evidence": [f"时间跨度{span}年，但仅覆盖{len(years_covered)}个年份"],
                        "reasoning": "时间线不连续，可能遗漏了关键事件或事实认定不完整",
                    })

        coverage = {
            "total_events": len(events),
            "year_range": f"{events[0]['year']}-{events[-1]['year']}" if events else "N/A",
            "anomaly_count": len(anomalies),
            "completeness": "high" if len(events) >= 5 and not anomalies else
                           ("medium" if len(events) >= 3 else "low"),
        }

        logger.info(
            "extract_timeline: <<< EXIT | events=%d, anomalies=%d, completeness=%s",
            len(events), len(anomalies), coverage["completeness"],
        )
        if anomalies:
            for a in anomalies:
                logger.info(
                    "extract_timeline: ANOMALY type=%s, severity=%s, msg='%s'",
                    a["type"], a["severity"], a["message"][:80],
                )

        return json.dumps({
            "success": True,
            "events": events,
            "anomalies": anomalies,
            "coverage": coverage,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(
            "extract_timeline: <<< EXIT (ERROR) | exception=%s, doc_len=%d",
            e, len(document_text), exc_info=True,
        )
        return _make_error(ErrorCode.INTERNAL_ERROR, f"时间线提取异常：{e}", retryable=True)


@mcp.tool()
def trace_evidence_references(document_text: str) -> str:
    """追踪文书中的证据引用情况，检测证据采信缺失。

    借鉴 ChatGPT 5.5 建议的"证据引用追踪"：
    自动追踪证据回应情况、采信理由、推理完整性。

    document_text: 裁判文书全文

    返回 JSON 字符串，包含：
    - evidence_items: 提取的证据项列表
    - unaddressed: 未被回应的证据列表
    - missing_reasoning: 缺乏采信理由的证据列表
    - trace_summary: 追踪摘要
    """
    logger.info(
        "trace_evidence_references: >>> ENTER | doc_len=%d",
        len(document_text),
    )
    try:
        evidence_pattern = re.compile(
            r"(?:证据|书证|物证|证人证言|鉴定意见|视听资料|电子数据|当事人陈述|勘验笔录)"
            r"[一二三四五六七八九十\d]*[、.:：]"
            r"(.{5,80}?)(?=[，。；\n]|证据[一二三四五六七八九十\d]|本院|以上)",
            re.DOTALL,
        )

        evidence_items = []
        for i, m in enumerate(evidence_pattern.finditer(document_text)):
            ev_text = m.group(1).strip()
            pos = m.start()
            context_start = max(0, pos - 20)
            context_end = min(len(document_text), pos + len(m.group()) + 100)
            full_context = document_text[context_start:context_end].replace("\n", " ").strip()

            is_plaintiff = bool(re.search(r"原告|起诉人|申请人", full_context[:pos - context_start + 20] if pos > context_start else ""))
            is_defendant = bool(re.search(r"被告|被申请人|答辩人", full_context[:pos - context_start + 20] if pos > context_start else ""))

            evidence_items.append({
                "index": i + 1,
                "text": ev_text[:80],
                "source": "plaintiff" if is_plaintiff else ("defendant" if is_defendant else "court"),
                "position": pos,
                "context": full_context[:120],
            })

        unaddressed = []
        missing_reasoning = []

        for ev in evidence_items:
            ev_text = ev["text"][:30]
            remaining_text = document_text[ev["position"] + len(ev["text"]):]

            addressed_patterns = [
                r"本院(?:予以)?采信",
                r"本院(?:不予)?采信",
                r"予以确认",
                r"不予确认",
                r"予以认定",
                r"不予认定",
                r"可以采信",
                r"不能采信",
                r"具有证明力",
                r"不具有证明力",
                r"予以采纳",
                r"不予采纳",
            ]

            addressed = False
            for pat in addressed_patterns:
                if re.search(pat, remaining_text[:3000]):
                    addressed = True
                    break

            if not addressed:
                unaddressed.append({
                    "evidence": ev_text,
                    "source": ev["source"],
                    "severity": "high",
                    "message": f"证据'{ev_text}...'未被法院回应（采信或排除）",
                    "evidence_detail": ev["context"][:80],
                    "reasoning": "法院对当事人提交的证据既未采信也未排除，属于证据审查遗漏",
                })

            reasoning_patterns = [
                r"理由[是为：:]",
                r"因为",
                r"由于",
                r"基于",
                r"根据",
                r"证明力[较大小强弱]",
                r"真实性[不]?予?认定",
                r"合法性[不]?予?认定",
                r"关联性[不]?予?认定",
            ]

            has_reasoning = False
            for pat in reasoning_patterns:
                if re.search(pat, remaining_text[:2000]):
                    has_reasoning = True
                    break

            if addressed and not has_reasoning:
                missing_reasoning.append({
                    "evidence": ev_text,
                    "source": ev["source"],
                    "severity": "medium",
                    "message": f"证据'{ev_text}...'被采信/排除但缺乏说理",
                    "evidence_detail": ev["context"][:80],
                    "reasoning": "法院采信或排除证据但未说明理由，违反证据裁判原则",
                })

        trace_summary = {
            "total_evidence": len(evidence_items),
            "plaintiff_evidence": sum(1 for e in evidence_items if e["source"] == "plaintiff"),
            "defendant_evidence": sum(1 for e in evidence_items if e["source"] == "defendant"),
            "court_evidence": sum(1 for e in evidence_items if e["source"] == "court"),
            "unaddressed_count": len(unaddressed),
            "missing_reasoning_count": len(missing_reasoning),
            "completeness": "high" if not unaddressed and not missing_reasoning else
                           ("medium" if len(unaddressed) <= 2 else "low"),
        }

        logger.info(
            "trace_evidence_references: <<< EXIT | evidence=%d, unaddressed=%d, missing_reasoning=%d, completeness=%s",
            len(evidence_items), len(unaddressed), len(missing_reasoning), trace_summary["completeness"],
        )

        return json.dumps({
            "success": True,
            "evidence_items": evidence_items,
            "unaddressed": unaddressed,
            "missing_reasoning": missing_reasoning,
            "trace_summary": trace_summary,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(
            "trace_evidence_references: <<< EXIT (ERROR) | exception=%s, doc_len=%d",
            e, len(document_text), exc_info=True,
        )
        return _make_error(ErrorCode.INTERNAL_ERROR, f"证据追踪异常：{e}", retryable=True)


@mcp.tool()
def detect_evasive_patterns(document_text: str) -> str:
    """检测文书中的"规避责任写作模式"。

    借鉴 ChatGPT 5.5 建议的"对抗式检测"：
    检测刻意模糊主体、回避关键时间、选择性采信、模板化说理等规避模式。

    可与 judicial-doc-anomaly-mcp 联动使用：
    https://github.com/lcfactorization/judicial-doc-anomaly-mcp
    该项目的 rhetoric_trick 维度可提供更深入的语义级规避模式检测。

    document_text: 裁判文书全文

    返回 JSON 字符串，包含：
    - detected_patterns: 检测到的规避模式列表
    - risk_level: 综合风险等级
    - recommendation: 处理建议
    """
    logger.info(
        "detect_evasive_patterns: >>> ENTER | doc_len=%d, patterns_to_check=%d",
        len(document_text), len(EVASIVE_PATTERNS),
    )
    try:
        detected = []
        for pattern_id, pattern_config in EVASIVE_PATTERNS.items():
            matches = list(re.finditer(pattern_config["pattern"], document_text))
            logger.debug(
                "detect_evasive_patterns: checking pattern=%s, matches=%d, severity=%s",
                pattern_id, len(matches), pattern_config["severity"],
            )
            if matches:
                contexts = []
                for m in matches[:5]:
                    start = max(0, m.start() - 30)
                    end = min(len(document_text), m.end() + 30)
                    contexts.append(document_text[start:end].replace("\n", " ").strip())

                detected.append({
                    "pattern_id": pattern_id,
                    "severity": pattern_config["severity"],
                    "message": pattern_config["message"],
                    "match_count": len(matches),
                    "sample_contexts": contexts[:3],
                    "evidence": contexts[:2],
                    "reasoning": f"检测到{len(matches)}处'{pattern_config['message']}'模式，"
                                 f"严重程度：{pattern_config['severity']}，"
                                 f"需LLM进一步确认是否构成规避责任写作",
                })
                logger.info(
                    "detect_evasive_patterns: DETECTED pattern=%s, count=%d, severity=%s, first_match='%s'",
                    pattern_id, len(matches), pattern_config["severity"],
                    contexts[0][:50] if contexts else "",
                )

        high_count = sum(1 for d in detected if d["severity"] == "high")
        medium_count = sum(1 for d in detected if d["severity"] == "medium")
        low_count = sum(1 for d in detected if d["severity"] == "low")

        if high_count >= 2:
            risk_level = "critical"
        elif high_count >= 1 or medium_count >= 3:
            risk_level = "high"
        elif medium_count >= 1 or low_count >= 3:
            risk_level = "medium"
        else:
            risk_level = "low"

        recommendation = {
            "critical": "文书存在严重的规避责任写作嫌疑，强烈建议结合anomaly-mcp进行全面审查（https://github.com/lcfactorization/judicial-doc-anomaly-mcp）",
            "high": "文书存在较明显的规避模式，建议重点关注相关段落的说理充分性",
            "medium": "文书存在部分规避模式，建议LLM进一步确认",
            "low": "未检测到明显规避模式，文书写作规范性良好",
        }.get(risk_level, "建议进一步审查")

        logger.info(
            "detect_evasive_patterns: <<< EXIT | detected=%d, risk=%s (high=%d, medium=%d, low=%d), recommendation='%s'",
            len(detected), risk_level, high_count, medium_count, low_count, recommendation[:60],
        )

        return json.dumps({
            "success": True,
            "detected_patterns": detected,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "summary": {
                "total_patterns": len(detected),
                "high_severity": high_count,
                "medium_severity": medium_count,
                "low_severity": low_count,
            },
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(
            "detect_evasive_patterns: <<< EXIT (ERROR) | exception=%s, doc_len=%d",
            e, len(document_text), exc_info=True,
        )
        return _make_error(ErrorCode.INTERNAL_ERROR, f"规避模式检测异常：{e}", retryable=True)


@mcp.tool()
def render_dimension_prompt_batch(
    dimensions: list[str],
    sections: dict | None = None,
    include_anchors: bool = True,
    anchor_count: int = 2,
) -> str:
    """批量渲染多个维度的评分 Prompt，减少 Agent 调用次数。

    借鉴 Gemini 3.1 Pro 建议的"动态批处理"：
    当文书较短、Token 余量充足时，可将多个不互相冲突的维度合并在一次调用中渲染。

    dimensions: 要渲染的维度列表（建议不超过3个，避免上下文溢出）
    sections: 预处理后的文书段落字典
    include_anchors: 是否包含锚定示例
    anchor_count: 每个维度的锚定示例数量（批处理时建议减少到2）

    返回 JSON 字符串，包含各维度的渲染结果。
    """
    logger.info(
        "render_dimension_prompt_batch: >>> ENTER | dims=%s, include_anchors=%s, anchor_count=%d",
        dimensions, include_anchors, anchor_count,
    )
    try:
        if len(dimensions) > 5:
            return _make_error(
                ErrorCode.INVALID_INPUT,
                f"批处理维度数量过多({len(dimensions)})，建议不超过5个",
                details={"dimensions": dimensions},
            )

        results = []
        total_tokens = 0

        for dim in dimensions:
            try:
                skill_name = f"dimensions/{dim}"
                meta, body = _loader.load(skill_name)

                template_vars = {}
                if sections:
                    for key, value in sections.items():
                        template_vars[key] = str(value) if value else ""

                rendered = _renderer.render(body, template_vars)
                system_prompt = build_system_prompt(meta) + "\n\n" + ANTI_LAZINESS_INSTRUCTION

                anchors = []
                if include_anchors:
                    anchors = _loader.load_anchors(dim)[:anchor_count]

                total_chars = len(system_prompt) + len(rendered)
                if anchors:
                    total_chars += len(json.dumps(anchors, ensure_ascii=False))
                dim_tokens = _estimate_tokens(" " * total_chars)
                total_tokens += dim_tokens

                results.append({
                    "dimension": meta.name,
                    "dimension_title": meta.title,
                    "weight": meta.weight,
                    "full_score": meta.full_score,
                    "system_prompt": system_prompt,
                    "user_prompt": rendered,
                    "anchor_examples": anchors,
                    "token_estimate": dim_tokens,
                })
            except FileNotFoundError as e:
                results.append({
                    "dimension": dim,
                    "error": f"维度不存在：{e}",
                })
            except Exception as e:
                results.append({
                    "dimension": dim,
                    "error": str(e),
                })

        logger.info(
            "render_dimension_prompt_batch: dims=%d, total_tokens=%d",
            len(dimensions), total_tokens,
        )

        return json.dumps({
            "success": True,
            "batch_size": len(dimensions),
            "total_token_estimate": total_tokens,
            "results": results,
            "warning": (
                "批处理模式：请确保总Token数不超过模型上下文窗口。"
                "建议先调用 estimate_token_budget 检查预算。"
                if total_tokens > 50000 else ""
            ),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("render_dimension_prompt_batch: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"批量渲染异常：{e}", retryable=True)


@mcp.tool()
def pipeline_progress(
    session_id: str,
    action: str = "status",
    dimension_name: str | None = None,
    result_summary: str | None = None,
) -> str:
    """管理质量评估流水线的执行进度，支持断点续传。

    借鉴 judicial-doc-anomaly-mcp 的 pipeline_progress 机制：
    Agent 在每个维度评估完成后应调用此工具更新进度。
    如果中途断开，可通过 action='resume' 获取未完成的维度列表。

    session_id: 流水线会话 ID（首次调用时自动创建）
    action: 操作类型
      - 'start': 开始新的评估会话
      - 'status': 查询当前进度（默认）
      - 'complete': 标记一个维度为已完成
      - 'resume': 获取未完成的维度列表（断点续传）
      - 'reset': 重置进度
    dimension_name: 要标记完成的维度名称（action='complete' 时必填）
    result_summary: 该维度的执行结果摘要（可选）

    返回 JSON 字符串，包含进度信息。
    """
    try:
        if action == "start":
            session_id = f"qa-{datetime.now().strftime('%Y%m%d%H%M%S')}" if not session_id else session_id
            _pipeline_state[session_id] = {
                "dimensions": list(QUALITY_WEIGHTS.keys()),
                "completed": [],
                "results": {},
                "started_at": datetime.now().isoformat(),
            }
            logger.info("pipeline_progress: started session=%s", session_id)

        if session_id not in _pipeline_state:
            if action not in ("start",):
                return _make_error(
                    ErrorCode.INVALID_INPUT,
                    f"会话不存在：{session_id}，请先使用 action='start' 创建会话",
                )

        state = _pipeline_state[session_id]

        if action == "complete":
            if not dimension_name:
                return _make_error(ErrorCode.INVALID_INPUT, "action='complete' 需要 dimension_name")
            if dimension_name not in state["completed"]:
                state["completed"].append(dimension_name)
            if result_summary:
                state["results"][dimension_name] = result_summary
            logger.info(
                "pipeline_progress: completed dim=%s, progress=%d/%d",
                dimension_name, len(state["completed"]), len(state["dimensions"]),
            )

        elif action == "reset":
            state["completed"] = []
            state["results"] = {}
            logger.info("pipeline_progress: reset session=%s", session_id)

        remaining = [d for d in state["dimensions"] if d not in state["completed"]]
        next_dim = remaining[0] if remaining else None
        progress_pct = round(len(state["completed"]) / len(state["dimensions"]) * 100) if state["dimensions"] else 100

        result = {
            "success": True,
            "session_id": session_id,
            "action": action,
            "completed_count": len(state["completed"]),
            "total_count": len(state["dimensions"]),
            "progress_pct": progress_pct,
            "next_dimension": next_dim,
            "completed_dimensions": state["completed"],
        }

        if action == "resume":
            result["remaining_dimensions"] = remaining
            result["previous_results"] = state.get("results", {})

        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("pipeline_progress: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"进度管理异常：{e}", retryable=True)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
