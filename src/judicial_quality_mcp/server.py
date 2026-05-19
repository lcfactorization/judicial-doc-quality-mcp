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

_SEVERITY_ZH = {"critical": "严重", "high": "高", "medium": "中", "low": "低", "unknown": "未知"}
_ANOMALY_TYPE_ZH = {
    "temporal_inversion": "时间倒置", "temporal_gap": "时间缺口",
    "procedural_sequence": "程序时序", "evidence_temporal": "证据时序",
    "law_retroactivity": "法律溯及力", "internal_contradiction": "内部时间矛盾",
}
_EVASIVE_PATTERN_ZH = {
    "vague_subject": "主体模糊",
    "evasive_timing": "时间模糊",
    "selective_citation": "选择性引用",
    "template_language": "模板化说理",
    "missing_response": "回避回应",
}
_DIMENSION_ZH = {
    "procedure": "程序规范",
    "evidence": "证据采信",
    "fact_finding": "事实认定",
    "focus_drift": "焦点漂移",
    "law_application": "法律适用",
    "discretion": "自由裁量",
    "rhetoric_trick": "修辞技巧",
    "logic": "逻辑闭环",
    "temporal": "时间一致性",
    "trial_process": "审理过程",
    "external_interference": "外部干预",
    "execution": "执行问题",
    "negative_space": "缺失信息",
    "semantic_drift": "语义漂移",
    "case_deviation": "类案偏离",
    "coupling": "惯性耦合",
}

_parser = ResponseParser()
_loader = SkillLoader()
_renderer = TemplateRenderer(_loader)


def _infer_trial_stage(case_name: str, document_text: str = "") -> str:
    if not case_name and not document_text:
        return "未知"
    search_text = case_name or document_text[:500]
    if re.search(r"民终|行终|刑终|终字|终\d+号", search_text):
        return "二审"
    if re.search(r"民再|行再|刑再|再字|再\d+号", search_text):
        return "再审"
    if re.search(r"民初|行初|刑初|初字|初\d+号", search_text):
        return "一审"
    if re.search(r"劳仲|仲字|仲\d+号", search_text):
        return "仲裁"
    if re.search(r"行罚|行决|罚字", search_text):
        return "行政"
    if document_text:
        if re.search(r"上诉人|被上诉人", document_text[:2000]):
            return "二审"
        if re.search(r"申诉人|被申诉人", document_text[:2000]):
            return "再审"
        if re.search(r"原告|被告", document_text[:2000]) and not re.search(r"上诉人|被上诉人", document_text[:2000]):
            return "一审"
    return "未知"


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
3. 从 parse_score_result 的解析结果中提取以下字段，传递给 generate_report：
   - thorough_reasoning 维度的 five_reasoning 字段 → generate_report 的 five_reasoning 参数
   - clear_facts 维度的 four_element 字段 → generate_report 的 four_element 参数
   - 如有异常详情，调用 ResponseParser.compute_beneficiary_distribution 和 compute_coupling_analysis，将结果传入对应参数
4. 最后调用 generate_report 生成完整报告
5. 禁止输出"我已经检测了前N个维度，剩下的维度操作同理，需要我继续吗？"之类的偷懒话术
6. 如果某个维度出现错误，记录错误并继续下一个维度，不得中断整个流程
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

        case_number = case_info.get("case_number", "")
        sections["trial_stage"] = _infer_trial_stage(case_number, document_full_text)

        logger.info(
            "extract_document_sections: confidence=%.2f, sections_found=%d/%d, trial_stage=%s",
            sections["extraction_confidence"], filled, total, sections["trial_stage"],
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

        if dimension == "thorough_reasoning":
            output_schema["properties"]["five_reasoning"] = {
                "type": "object",
                "description": "五理说理评估",
                "properties": {
                    "事理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "法理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "学理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "情理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "文理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                },
            }

        if dimension == "clear_facts":
            output_schema["properties"]["four_element"] = {
                "type": "object",
                "description": "四元结构分析",
                "properties": {
                    "界定民事主体": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "判断法律行为": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "保障民事权利": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                    "划分民事责任": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                },
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
    law_database_result: dict | None = None,
    case_precedent_result: dict | None = None,
    supplementary_docs_result: list[dict] | None = None,
    legal_difficulty_result: dict | None = None,
    five_reasoning: dict | None = None,
    four_element: dict | None = None,
    beneficiary_distribution: dict | None = None,
    coupling_analysis: list[dict] | None = None,
    report_id: str | None = None,
    minimum_score_applied: bool = False,
    trial_stage: str = "",
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
    law_database_result: 法律法规数据库查询结果（来自 query_law_database，可选）
    case_precedent_result: 类案判例查询结果（来自 query_case_precedent，可选）
    supplementary_docs_result: 补充文档列表（来自 submit_supplementary_doc，可选）
    legal_difficulty_result: 法律适用难点分析结果（来自 analyze_legal_difficulty，可选）
    five_reasoning: 五理说理评估结果（来自 parse_score_result 解析 thorough_reasoning 维度时的 five_reasoning 字段，可选）
    four_element: 四元结构分析结果（来自 parse_score_result 解析 clear_facts 维度时的 four_element 字段，可选）
    beneficiary_distribution: 获益方分布统计（来自 ResponseParser.compute_beneficiary_distribution，可选）
    coupling_analysis: 异常耦合分析结果（来自 ResponseParser.compute_coupling_analysis，可选）
    report_id: 报告编号（如不提供则自动生成，可选）
    minimum_score_applied: 是否适用了底线尊重原则（默认 False）

    返回 JSON 字符串，包含 report_markdown 字段。
    """
    try:
        lines = []

        if not report_id:
            report_id = f"QA-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        lines.append("# 司法/行政文书程序与实体异常深度检测与质量评估报告\n")
        lines.append(f"> 报告编号：{report_id}\n")

        if document_meta:
            lines.append("> [!NOTE]")
            lines.append("> **基础信息档案**")
            for k, v in document_meta.items():
                lines.append(f"> - **{k}**：{v}")
            if trial_stage:
                lines.append(f"> - **审级**：{trial_stage}")
                _STAGE_RESPONSIBILITY = {
                    "一审": "一审法院对事实认定和法律适用负全部责任",
                    "二审": "二审法院对一审判决的审查和自身裁判负责，不承担一审责任",
                    "再审": "再审法院对原审生效判决的审查和再审裁判负责",
                    "仲裁": "仲裁机构对仲裁裁决负责",
                    "行政": "行政机关对行政决定负责",
                }
                resp = _STAGE_RESPONSIBILITY.get(trial_stage, "")
                if resp:
                    lines.append(f"> - **责任界定**：{resp}")
            lines.append(f"> - **检测时间**：{datetime.now().strftime('%Y-%m-%d')}")
            lines.append(f"> - **报告编号**：{report_id}")
            lines.append("")

        if minimum_score_applied:
            lines.append("> [!CAUTION]")
            lines.append("> **底线尊重原则已适用**：原始计算分数低于40分，但因存在对弱势方有利的正确认定，")
            lines.append("> 根据底线尊重原则，总分已调整为40分（D级下限），以体现对法官在体制压力下坚持部分正义的尊重。\n")

        # ── 综合异常等级 ──
        grade_desc = QUALITY_GRADES.get(grade, (0, 0, "未知"))[2]
        grade_lo = QUALITY_GRADES.get(grade, (0, 100, ""))[0]
        grade_hi = QUALITY_GRADES.get(grade, (0, 100, ""))[1]

        _ANOMALY_LEVEL_MAP = {
            (0, 70): "极度异常",
            (70, 80): "高度异常",
            (80, 85): "中度异常",
            (85, 90): "低度异常",
            (90, 95): "极低度异常",
            (95, 101): "无明显异常",
        }
        anomaly_level = "低度异常"
        for (lo, hi), label in _ANOMALY_LEVEL_MAP.items():
            if lo <= weighted_total < hi:
                anomaly_level = label
                break

        high_anomaly_count = sum(1 for a in (anomaly_details or []) if a.get("severity") == "high")
        medium_anomaly_count = sum(1 for a in (anomaly_details or []) if a.get("severity") == "medium")
        total_anomaly_items = high_anomaly_count + medium_anomaly_count

        lines.append("> [!CAUTION]")
        lines.append(f"> **综合异常等级：{anomaly_level}**")
        lines.append(">")
        lines.append(f"> **评级理由**：本案文书在七维质量评分中加权总分 **{weighted_total}** 分（{grade}·{grade_desc}），"
                     f"等级区间 [{grade_lo}, {grade_hi}]。"
                     f"检出 {total_anomaly_items} 项需关注异常（🔴高 {high_anomaly_count} 项、🟡中 {medium_anomaly_count} 项），"
                     f"异常扣分 −{anomaly_deduction:.0f}，创新加分 +{innovation_bonus:.0f}。")

        if anomaly_mcp_results:
            mcp_anomaly_count = sum(d.get("anomaly_count", 0) for d in anomaly_mcp_results)
            mcp_high = sum(1 for d in anomaly_mcp_results if d.get("risk_level") in ("critical", "high"))
            mcp_medium = sum(1 for d in anomaly_mcp_results if d.get("risk_level") == "medium")
            lines.append(f"> 十六维度异常检测共扫描 {len(anomaly_mcp_results)} 个维度，"
                         f"检出 {mcp_anomaly_count} 项异常（高风险 {mcp_high} 维度、中风险 {mcp_medium} 维度）。")
            if mcp_high == 0 and mcp_medium <= 2:
                lines.append(f"> 未发现高置信的硬伤型异常，存疑点均属于可解释的裁量范畴，不存在多维异常耦合或指向一致性。")
        lines.append("")

        # ── 综合评级 ──
        lines.append("## 综合评级\n")
        lines.append(f"**{grade}（{grade_desc}）**  |  加权总分 **{weighted_total}** / 100  |  等级区间 [{grade_lo}, {grade_hi}]  |  异常等级 **{anomaly_level}**\n")

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
        lines.append("## 五、七维质量评分详情\n")
        lines.append("> [!NOTE]")
        lines.append("> 七维质量评分体系涵盖形式规范、事实清楚、证据充分、法律适用、说理透彻、实质解纷、语言精练七个维度，")
        lines.append("> 每个维度均包含扣分项、加分项和改进建议，为文书质量提供全面量化评价。\n")

        lines.append("### 各维度评分总览\n")
        lines.append("| 维度编号 | 维度 | 得分 | 权重 | 加权得分 | 核心扣分项 | 核心加分项 |")
        lines.append("|:---:|:---|:---:|:---:|:---:|:---|:---|")

        for dim_idx, dr in enumerate(dimension_results, 1):
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            dim_code = f"D{DIMENSION_ORDER.get(dim, dim_idx)}"
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0
            weight = QUALITY_WEIGHTS.get(dim, 0.0)
            weighted = round(score * weight, 2)

            deductions = dr.get("deduction_items", [])
            ded_summary = "、".join(d.get("item", "") for d in deductions) if deductions else "—"
            bonuses = dr.get("bonus_items", [])
            bon_summary = "、".join(b.get("item", "") for b in bonuses) if bonuses else "—"

            lines.append(f"| {dim_code} | {title} | {score} | {weight*100:.0f}% | {weighted} | {ded_summary} | {bon_summary} |")

        lines.append("")

        # ── 评分明细一览 ──
        lines.append("### 评分明细与改进建议\n")
        lines.append("| 维度编号 | 维度 | 得分 | 扣分项 | 扣分原因 | 加分项 | 加分原因 | 改进建议 |")
        lines.append("|:---:|:---|:---:|:---|:---|:---|:---|:---|")
        _DIM_IMPROVEMENT = {
            "formal_specification": "检查文书格式是否符合规范要求",
            "clear_facts": "加强关键事实的查明和论证",
            "sufficient_evidence": "确保证据采信标准统一",
            "correct_law_application": "核实法律适用的准确性",
            "thorough_reasoning": "增强说理的逻辑性和充分性",
            "substantive_resolution": "提升纠纷实质性化解效果",
            "concise_language": "精简文书语言，避免冗余",
        }
        _DIM_DETAIL_DESC = {
            "formal_specification": "文书格式规范、要素齐全、结构完整",
            "clear_facts": "案件事实查明清楚、关键情节认定准确",
            "sufficient_evidence": "证据采信充分、举证责任分配合理",
            "correct_law_application": "法律适用正确、条文引用准确",
            "thorough_reasoning": "裁判说理充分、逻辑严密、回应争议焦点",
            "substantive_resolution": "纠纷实质性化解、服判息诉效果好",
            "concise_language": "语言精练、表述准确、无冗余",
        }
        for dim_idx, dr in enumerate(dimension_results, 1):
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            dim_code = f"D{DIMENSION_ORDER.get(dim, dim_idx)}"
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0

            deductions = dr.get("deduction_items", [])
            ded_items = "、".join(d.get("item", d.get("code", "")) for d in deductions) if deductions else "—"
            ded_reasons = "；".join(d.get("reason", d.get("standard", "")) for d in deductions if d.get("reason") or d.get("standard")) if deductions else "—"

            bonuses = dr.get("bonus_items", [])
            bon_items = "、".join(b.get("item", b.get("code", "")) for b in bonuses) if bonuses else "—"
            bon_reasons = "；".join(b.get("reason", b.get("standard", "")) for b in bonuses if b.get("reason") or b.get("standard")) if bonuses else "—"

            improvement = _DIM_IMPROVEMENT.get(dim, "—")
            if deductions:
                improvement = "；".join(d.get("suggestion", improvement) for d in deductions if d.get("suggestion")) or improvement

            lines.append(f"| {dim_code} | {title} | {score} | {ded_items} | {ded_reasons} | {bon_items} | {bon_reasons} | {improvement} |")

        lines.append("")

        lines.append("### 各维度深度分析\n")
        for dim_idx, dr in enumerate(dimension_results, 1):
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            dim_code = f"D{DIMENSION_ORDER.get(dim, dim_idx)}"
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0
            weight = QUALITY_WEIGHTS.get(dim, 0.0)
            weighted = round(score * weight, 2)
            dim_desc = _DIM_DETAIL_DESC.get(dim, "")

            deductions = dr.get("deduction_items", [])
            bonuses = dr.get("bonus_items", [])

            lines.append(f"**{dim_code} {title}**（得分 {score}，权重 {weight*100:.0f}%，加权 {weighted}）\n")
            if dim_desc:
                lines.append(f"- 维度说明：{dim_desc}")

            if deductions:
                lines.append(f"- 扣分项：")
                for d in deductions:
                    lines.append(f"  - **{d.get('item', d.get('code', ''))}**：{d.get('reason', d.get('standard', '—'))}（扣 {d.get('deduction', '?')} 分）")
                    if d.get('suggestion'):
                        lines.append(f"    - 改进建议：{d.get('suggestion')}")

            if bonuses:
                lines.append(f"- 加分项：")
                for b in bonuses:
                    lines.append(f"  - **{b.get('item', b.get('code', ''))}**：{b.get('reason', b.get('standard', '—'))}（加 {b.get('bonus', '?')} 分）")

            lines.append("")

        # ── 异常扣分明细 ──
        if anomaly_details:
            lines.append("## 一、核心异常总览\n")
            lines.append("| # | 维度 | 异常检测项 | F编号 | A分类 | 简要表现 | 指向获益方 | 置信度 |")
            lines.append("|:---:|:---|:---|:---:|:---:|:---|:---|:---|")
            _ANOMALY_CODE_MAP = {
                "程序异常": "QA-01", "证据异常": "QA-02", "事实认定异常": "QA-03",
                "法律适用异常": "QA-04", "说理异常": "QA-05", "逻辑异常": "QA-06",
                "异常扣分": "QA-07",
            }
            sorted_anomalies = sorted(anomaly_details, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("severity", "low"), 3))
            for ad_idx, ad in enumerate(sorted_anomalies, 1):
                sev = ad.get('severity', 'low')
                sev_icon = {"high": "🔴", "medium": "⚠️", "low": "🟢"}.get(sev, "")
                beneficiary = ad.get('beneficiary', ad.get('target', '—'))
                confidence = ad.get('confidence', sev_icon)
                brief = ad.get('brief', ad.get('description', ''))
                f_code = ad.get('f_code', '—')
                a_code = ad.get('a_code', '—')
                lines.append(f"| {ad_idx} | {ad.get('label', '')} | {ad.get('item_name', ad.get('reason', ''))} | {f_code} | {a_code} | {brief} | {beneficiary} | {confidence} |")
            lines.append("")

            lines.append("## 二、异常项深度剖析\n")
            for ad_idx, ad in enumerate(sorted_anomalies, 1):
                sev = ad.get('severity', 'low')
                sev_zh = _SEVERITY_ZH.get(sev, sev)
                label = ad.get('label', '')
                item_name = ad.get('item_name', ad.get('reason', ''))
                ad_code = _ANOMALY_CODE_MAP.get(label, f"QA-{ad_idx:02d}")

                lines.append(f"### {ad_code} {label}：{item_name}\n")

                a_code_val = ad.get('a_code', '')
                f_code_val = ad.get('f_code', '')
                code_suffix = ""
                if a_code_val or f_code_val:
                    code_parts = []
                    if a_code_val:
                        code_parts.append(f"A分类：{a_code_val}")
                    if f_code_val:
                        code_parts.append(f"F编号：{f_code_val}")
                    code_suffix = f" | {'，'.join(code_parts)}"

                _MISSING = "⚠️ 未提供（违反说理充分性硬约束）"

                original_text_location = ad.get('original_text_location') or ad.get('location') or ad.get('original_text') or ''
                if not original_text_location or original_text_location in ('—', '全文', '多处'):
                    original_text_location = _MISSING

                evidence_reference = ad.get('evidence_reference') or ad.get('evidence') or ''
                if not evidence_reference or evidence_reference == '—':
                    evidence_reference = _MISSING

                beneficiary = ad.get('beneficiary') or ''
                if not beneficiary or beneficiary == '—':
                    beneficiary = _MISSING

                lines.append("> [!WARNING]")
                lines.append(f"> **触发项**：{item_name}")
                lines.append(f"> **原文定位**：{original_text_location}")
                lines.append(f"> **证据对照**：{evidence_reference}")
                lines.append(f"> **严重程度**：{sev_zh} | **扣分**：-{ad.get('deduction', 0)} | **指向获益方**：{beneficiary}{code_suffix}")
                lines.append("")

                description = ad.get('description', '')
                if description:
                    lines.append(f"**异常表现**：{description}\n")

                legal_analysis = ad.get('legal_analysis', '')
                if legal_analysis:
                    lines.append(f"**法理/背景点评**：\n")
                    lines.append(f"{legal_analysis}\n")
                else:
                    lines.append(f"**法理/背景点评**：{_MISSING}\n")

                alternative = ad.get('alternative_explanation', '')
                if alternative:
                    lines.append(f"**替代解释**：{alternative}\n")

                lines.append("> [!IMPORTANT]")
                lines.append("> **对抗校验结论**：")

                q1 = ad.get('q1_alternative') or alternative or ''
                if not q1 or q1 in ('存在', '不存在', '—'):
                    q1 = _MISSING

                q2 = ad.get('q2_subjective_intent') or ''
                if not q2 or q2 in ('无', '未见', '—'):
                    q2 = _MISSING

                q3 = ad.get('q3_contradictory_evidence') or ''
                if not q3 or q3 in ('无', '—'):
                    q3 = _MISSING

                lines.append(f"> - **Q1（替代解释）**：{q1}")
                lines.append(f"> - **Q2（排除主观故意）**：{q2}")
                lines.append(f"> - **Q3（相反证据）**：{q3}")

                conclusion = ad.get('conclusion') or ''
                if not conclusion or conclusion in ('成立', '存疑', '不成立', '—'):
                    conclusion = f"⚠️ 存疑——{item_name}需进一步核实"

                net_anomaly = ad.get('net_anomaly') or ''
                if not net_anomaly or net_anomaly in ('成立', '存疑', '不成立', '—'):
                    net_anomaly = _MISSING

                lines.append(f"> - **校验结论**：{conclusion}")
                lines.append(f"> - **净异常判定**：{net_anomaly}")
                lines.append("")

                reverse_anomaly = ad.get('reverse_anomaly') or ''
                if reverse_anomaly:
                    lines.append(f"**反向异常点**：{reverse_anomaly}\n")

                fix = ad.get('suggestion') or ad.get('fix') or ''
                if not fix or fix in ('—', '加强说理', '完善论证', '注意规范'):
                    fix = _MISSING
                lines.append(f"**修复建议**：{fix}\n")

            if beneficiary_distribution:
                lines.append("### 获益方分布统计\n")
                lines.append("> [!NOTE]")
                lines.append("> 以下统计展示各异常点指向的获益方分布，用于评估异常是否具有系统性偏向。\n")
                lines.append("| 获益方 | 异常项数 | 占比 |")
                lines.append("|:---|:---:|:---:|")
                total_ben = sum(beneficiary_distribution.values())
                for ben, count in sorted(beneficiary_distribution.items(), key=lambda x: -x[1]):
                    pct = f"{count/total_ben*100:.1f}%" if total_ben > 0 else "0%"
                    lines.append(f"| {ben} | {count} | {pct} |")
                lines.append("")

                single_ben = {k: v for k, v in beneficiary_distribution.items() if k not in ("双方", "无", "未标注")}
                if len(single_ben) == 1:
                    sole_ben = list(single_ben.keys())[0]
                    sole_count = list(single_ben.values())[0]
                    if sole_count >= 3:
                        lines.append("> [!WARNING]")
                        lines.append(f"> 所有异常均指向同一方（{sole_ben}），存在系统性偏向的可能性，建议结合对抗校验结论综合判断。\n")

            if coupling_analysis:
                lines.append("### 异常耦合分析\n")
                lines.append("> [!NOTE]")
                lines.append("> 耦合分析检测多个维度的异常是否指向同一获益方，以识别系统性偏差。\n")
                for ca in coupling_analysis:
                    dims = "、".join(ca.get("coupled_dimensions", []))
                    strength = ca.get("coupling_strength", "—")
                    desc = ca.get("coupling_description", "")
                    risk = ca.get("overall_risk", "—")
                    ben = "、".join(ca.get("beneficiary_analysis", []))
                    lines.append(f"**{dims}**（耦合强度：{strength}，综合风险：{risk}）")
                    lines.append(f"- {desc}")
                    if ben:
                        lines.append(f"- 耦合获益方：{ben}")
                    lines.append("")

        # ── 负面清单检测 ──
        _NEGATIVE_LIST = {
            "V1": "裁判主文与说理部分结论直接矛盾",
            "V2": "对关键证据只字不提且无任何解释",
            "V3": "引用的法条与案件类型完全不相关",
            "V4": "判决结果超出当事人诉讼请求范围",
            "V5": "剥夺当事人法定程序权利且无合法理由",
        }
        triggered_veto = []
        for dr in dimension_results:
            dim = dr.get("dimension", "")
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0
            if score == 0:
                for vcode, vdesc in _NEGATIVE_LIST.items():
                    triggered_veto.append({"code": vcode, "desc": vdesc, "dimension": dim})

        if triggered_veto:
            lines.append("### ⚠️ 负面清单（一票否决项）\n")
            lines.append("> [!CAUTION]")
            lines.append(f"> 检出 {len(triggered_veto)} 项一票否决情形，相关维度评分已降为0分\n")
            lines.append("| 编号 | 否决情形 | 涉及维度 |")
            lines.append("|:---:|:---|:---|")
            for tv in triggered_veto:
                dim_title = DIMENSION_TITLES.get(tv["dimension"], tv["dimension"])
                lines.append(f"| {tv['code']} | {tv['desc']} | {dim_title} |")
            lines.append("")

        # ── 五理说理评估 ──
        if five_reasoning:
            lines.append("### 五理说理评估\n")
            lines.append("> [!NOTE]")
            lines.append("> 五理说理理论从事理、法理、学理、情理、文理五个维度评估文书说理充分性，")
            lines.append("> 为说理充分透彻维度提供更精细的分析视角。\n")
            lines.append("| 说理维度 | 得分 | 分析 |")
            lines.append("|:---|:---:|:---|")
            for rkey, rval in five_reasoning.items():
                if isinstance(rval, dict):
                    lines.append(f"| {rkey} | {rval.get('score', '—')} | {rval.get('analysis', '—')} |")
                else:
                    lines.append(f"| {rkey} | {rval} | — |")
            lines.append("")

        # ── 四元结构分析 ──
        if four_element:
            lines.append("### 四元结构分析法\n")
            lines.append("> [!NOTE]")
            lines.append("> 四元结构分析法从界定民事主体、判断法律行为、保障民事权利、划分民事责任四个方面，")
            lines.append("> 评估事实认定维度的结构完整性。\n")
            lines.append("| 结构要素 | 得分 | 分析 |")
            lines.append("|:---|:---:|:---|")
            for ekey, eval_ in four_element.items():
                if isinstance(eval_, dict):
                    lines.append(f"| {ekey} | {eval_.get('score', '—')} | {eval_.get('analysis', '—')} |")
                else:
                    lines.append(f"| {ekey} | {eval_} | — |")
            lines.append("")

        # ── A系列异常分类总览 ──
        if anomaly_details:
            a_code_summary: dict[str, int] = {}
            for ad in anomaly_details:
                ac = ad.get("a_code", "")
                if ac:
                    a_code_summary[ac] = a_code_summary.get(ac, 0) + 1
            if a_code_summary:
                lines.append("### A系列异常分类总览\n")
                lines.append("> [!NOTE]")
                lines.append("> A系列异常分类体系将异常点映射到A1-A8共8种分类，便于快速识别异常类型和严重程度。\n")
                _A_CODE_DESC = {
                    "A1": "关键证据未回应", "A2": "事实认定跳跃", "A3": "法律适用未解释",
                    "A4": "同类证据双重标准", "A5": "程序时间线异常", "A6": "回避核心争点",
                    "A7": "机械复制模板化论证", "A8": "举证责任倒置异常",
                }
                lines.append("| A编号 | 分类名称 | 异常项数 | 严重度基数 | 双向适用 |")
                lines.append("|:---:|:---|:---:|:---:|:---:|")
                _A_SEVERITY_BASE = {"A1": 0.85, "A2": 0.80, "A3": 0.75, "A4": 0.90, "A5": 0.70, "A6": 0.85, "A7": 0.65, "A8": 0.90}
                _A_BIDIRECTIONAL = {"A1": "是", "A2": "是", "A3": "是", "A4": "是", "A5": "否", "A6": "是", "A7": "否", "A8": "是"}
                for acode in sorted(a_code_summary.keys()):
                    count = a_code_summary[acode]
                    desc = _A_CODE_DESC.get(acode, "—")
                    base = _A_SEVERITY_BASE.get(acode, "—")
                    bidi = _A_BIDIRECTIONAL.get(acode, "—")
                    lines.append(f"| {acode} | {desc} | {count} | {base} | {bidi} |")
                lines.append("")

        # ── 创新性加分明细 ──
        if innovation_details:
            lines.append("## 三、创新亮点与加分项\n")
            lines.append("> [!TIP]")
            lines.append(f"> 检出 {len(innovation_details)} 项创新亮点，合计加分 +{innovation_bonus:.0f}\n")
            lines.append("| 加分编号 | 加分类型 | 加分 | 鼓励原因 | 法理依据 |")
            lines.append("|:---:|:---|:---:|:---|:---|")
            _INNOVATION_CODE_MAP = {
                "证据妨碍规则适用": "QB-01", "一揽子解决多项争议": "QB-02",
                "类案检索报告提交": "QB-03", "判后答疑机制": "QB-04",
            }
            _INNOVATION_REASON = {
                "证据妨碍规则适用": "积极适用证据妨碍规则，有利于保护举证能力较弱一方",
                "一揽子解决多项争议": "一次性解决多项争议，减少当事人诉累",
                "类案检索报告提交": "提交类案检索报告，增强裁判一致性",
                "判后答疑机制": "判后答疑有助于当事人理解裁判，促进服判息诉",
            }
            _INNOVATION_LEGAL_BASIS = {
                "证据妨碍规则适用": "《劳动争议调解仲裁法》第6条、《劳动争议司法解释（一）》第43条",
                "一揽子解决多项争议": "《民事诉讼法》第153条、司法效率原则",
                "类案检索报告提交": "《最高人民法院关于统一法律适用加强类案检索的指导意见》",
                "判后答疑机制": "《最高人民法院关于判后答疑的若干规定》",
            }
            for id_idx, id_item in enumerate(innovation_details, 1):
                id_code = _INNOVATION_CODE_MAP.get(id_item.get('label', ''), f"QB-{id_idx:02d}")
                reason = id_item.get('reason', _INNOVATION_REASON.get(id_item.get('label', ''), id_item.get('description', '')))
                legal_basis = id_item.get('legal_basis', _INNOVATION_LEGAL_BASIS.get(id_item.get('label', ''), '—'))
                lines.append(f"| {id_code} | {id_item.get('label', '')} | +{id_item.get('bonus', 0)} | {reason} | {legal_basis} |")
            lines.append("")

            for id_idx, id_item in enumerate(innovation_details, 1):
                id_code = _INNOVATION_CODE_MAP.get(id_item.get('label', ''), f"QB-{id_idx:02d}")
                detail = id_item.get('detail', id_item.get('analysis', ''))
                if detail:
                    lines.append(f"**{id_code} {id_item.get('label', '')}详细说明**：{detail}\n")

        # ── 辅助检测结果 ──
        has_aux = timeline_result or evasive_result or evidence_result
        if has_aux:
            lines.append("## 六、辅助检测结果\n")
            lines.append("> [!NOTE]")
            aux_items = []
            if timeline_result:
                aux_items.append("时间线提取与异常检测")
            if evasive_result:
                aux_items.append("规避模式检测")
            if evidence_result:
                aux_items.append("证据引用追踪")
            lines.append(f"> 本节包含 {len(aux_items)} 项辅助检测结果：{'、'.join(aux_items)}，为质量评估提供补充参考。")
            lines.append("> 辅助检测通过时间线提取、规避模式识别和证据追踪等技术手段，发现文书中的潜在异常和逻辑问题。\n")

            if timeline_result:
                coverage = timeline_result.get("coverage", {})
                total_events = coverage.get("total_events", len(timeline_result.get("events", [])))
                anomaly_count = coverage.get("anomaly_count", len(timeline_result.get("anomalies", [])))
                completeness = coverage.get("completeness", "N/A")
                completeness_zh_tl = {"high": "高", "medium": "中", "low": "低"}.get(completeness, completeness)
                anomalies = timeline_result.get("anomalies", [])

                lines.append("### 时间线提取与异常检测\n")
                lines.append(f"| 指标 | 结果 |")
                lines.append(f"|:---|:---|")
                lines.append(f"| 提取事件数 | {total_events} |")
                lines.append(f"| 时间线异常数 | {anomaly_count} |")
                lines.append(f"| 时间线完整性 | {completeness_zh_tl} |")
                lines.append("")

                if anomalies:
                    high_anomalies = [a for a in anomalies if a.get("severity") == "high"]
                    medium_anomalies = [a for a in anomalies if a.get("severity") == "medium"]
                    low_anomalies = [a for a in anomalies if a.get("severity") == "low"]
                    if high_anomalies:
                        lines.append("> [!WARNING]")
                        lines.append(f"> 检出 {len(high_anomalies)} 项高严重度时序异常，可能影响裁判合法性，请重点核实\n")
                    elif medium_anomalies:
                        lines.append("> [!NOTE]")
                        lines.append(f"> 检出 {len(medium_anomalies)} 项中等时序异常，需关注法律溯及力及证据时序问题\n")
                    else:
                        lines.append("> [!TIP]")
                        lines.append("> 时序异常均为低严重度，不影响文书质量评价\n")

                    lines.append("| 异常编号 | 严重程度 | 异常类型 | 说明 |")
                    lines.append("|:---:|:---:|:---|:---|")
                    _TL_ANOMALY_CODE = {
                        "procedural_sequence": "TL-01", "evidence_temporal": "TL-02",
                        "law_retroactivity": "TL-03", "internal_contradiction": "TL-04",
                        "temporal_inversion": "TL-05", "temporal_gap": "TL-06",
                    }
                    for a_idx, a in enumerate(anomalies, 1):
                        sev_zh = _SEVERITY_ZH.get(a.get("severity", "?"), a.get("severity", "?"))
                        type_zh = _ANOMALY_TYPE_ZH.get(a.get("type", "?"), a.get("type", "?"))
                        a_code = _TL_ANOMALY_CODE.get(a.get("type", ""), f"TL-{a_idx:02d}")
                        lines.append(f"| {a_code} | {sev_zh} | {type_zh} | {a.get('message', '')} |")
                    lines.append("")

                    evidence_temporal_anomalies = [a for a in anomalies if a.get("type") == "evidence_temporal"]
                    if evidence_temporal_anomalies:
                        lines.append("#### 证据时序异常详情（TL-02）\n")
                        lines.append("| 项目 | 内容 |")
                        lines.append("|:---|:---|")
                        for ea in evidence_temporal_anomalies:
                            ev_list = ea.get("evidence", [])
                            lines.append(f"| 异常说明 | {ea.get('message', '')} |")
                            lines.append(f"| 证据线索 | {'；'.join(ev_list) if ev_list else '—'} |")
                            lines.append(f"| 推理依据 | {ea.get('reasoning', '—')} |")
                            lines.append(f"| 修复建议 | 核实证据形成时间是否准确，确认是否为补强证据或事后补充鉴定 |")
                        lines.append("")

                    law_retro_anomalies = [a for a in anomalies if a.get("type") == "law_retroactivity"]
                    if law_retro_anomalies:
                        lines.append("#### 法律溯及力异常详情（TL-03）\n")
                        lines.append("| 项目 | 内容 |")
                        lines.append("|:---|:---|")
                        for la in law_retro_anomalies:
                            ev_list = la.get("evidence", [])
                            law_names_short = []
                            for ev in ev_list[:3]:
                                m = re.search(r"《([^》]+)》", ev)
                                if m:
                                    law_names_short.append(m.group(1))
                            lines.append(f"| 异常说明 | {la.get('message', '')} |")
                            lines.append(f"| 涉及法律 | {'；'.join(law_names_short) if law_names_short else '—'} |")
                            lines.append(f"| 涉及法律详情 | {'；'.join(ev_list[:3]) if ev_list else '—'} |")
                            lines.append(f"| 推理依据 | {la.get('reasoning', '—')} |")
                            lines.append(f"| 修复建议 | 核实是否适用溯及力条款（如《民法典时间效力规定》），确认法律适用时间节点是否正确 |")
                        lines.append("")

                narrative_inv = coverage.get("narrative_inversions", 0)
                if narrative_inv > 0:
                    lines.append("> [!TIP]")
                    lines.append(f"> 文书存在{narrative_inv}处叙事结构倒置（先述裁判结果后回溯事实），属正常叙事结构，不作为异常\n")

            if evasive_result:
                risk_level = evasive_result.get("risk_level", "N/A")
                risk_level_zh = _SEVERITY_ZH.get(risk_level, risk_level)
                detected_patterns = evasive_result.get("detected_patterns", [])
                detected_count = len(detected_patterns)
                recommendation = evasive_result.get("recommendation", "")

                lines.append("### 规避模式检测\n")
                lines.append(f"| 指标 | 结果 |")
                lines.append(f"|:---|:---|")
                lines.append(f"| 风险等级 | {risk_level_zh} |")
                lines.append(f"| 检出模式数 | {detected_count} |")
                lines.append("")

                if risk_level in ("high", "medium"):
                    lines.append("> [!CAUTION]")
                    lines.append(f"> 规避模式风险等级为 **{risk_level_zh}**，建议重点关注\n")
                elif risk_level == "low":
                    lines.append("> [!NOTE]")
                    lines.append("> 规避模式风险等级为低，文书规避倾向不明显\n")

                if detected_patterns:
                    lines.append("| 模式编号 | 严重程度 | 模式名称 | 匹配数 | 说明 |")
                    lines.append("|:---:|:---:|:---|:---:|:---|")
                    _EVASIVE_CODE_MAP = {
                        "vague_subject": "EP-01", "evasive_timing": "EP-02",
                        "selective_detail": "EP-03", "passive_voice_abuse": "EP-04",
                        "hedging_language": "EP-05",
                    }
                    for p_idx, p in enumerate(detected_patterns, 1):
                        p_name = _EVASIVE_PATTERN_ZH.get(p.get("pattern_id", ""), p.get("pattern_id", p.get("name", "?")))
                        p_sev = _SEVERITY_ZH.get(p.get("severity", "?"), p.get("severity", "?"))
                        p_desc = p.get("message", p.get("description", ""))
                        p_code = _EVASIVE_CODE_MAP.get(p.get("pattern_id", ""), f"EP-{p_idx:02d}")
                        lines.append(f"| {p_code} | {p_sev} | {p_name} | {p.get('match_count', 0)} | {p_desc} |")
                    lines.append("")

                if recommendation:
                    lines.append(f"> [!IMPORTANT]")
                    lines.append(f"> {recommendation}\n")

            if evidence_result:
                total_ev = len(evidence_result.get("evidence_items", []))
                unaddressed = len(evidence_result.get("unaddressed", []))
                missing_reasoning = len(evidence_result.get("missing_reasoning", []))
                trace_summary = evidence_result.get("trace_summary", {})
                completeness = trace_summary.get("completeness", "N/A")
                completeness_zh = {"high": "高", "medium": "中", "low": "低"}.get(completeness, completeness)

                lines.append("### 证据引用追踪\n")
                lines.append(f"| 指标 | 结果 |")
                lines.append(f"|:---|:---|")
                lines.append(f"| 证据项数 | {total_ev} |")
                lines.append(f"| 未回应证据 | {unaddressed} |")
                lines.append(f"| 缺说理证据 | {missing_reasoning} |")
                lines.append(f"| 引用完整性 | {completeness_zh} |")
                lines.append("")

                if unaddressed > 0 or missing_reasoning > 0:
                    lines.append("> [!WARNING]")
                    lines.append(f"> 存在 {unaddressed} 项未回应证据、{missing_reasoning} 项缺说理证据，可能影响证据采信的正当性\n")
                else:
                    lines.append("> [!TIP]")
                    lines.append("> 证据引用完整，所有证据均有回应和说理\n")

        # ── 异常检测MCP联动 ──
        if anomaly_mcp_results:
            lines.append("## 四、十六维度深度异常剖析\n")
            lines.append("> [!IMPORTANT]")
            lines.append("> 以下异常检测结果来自 [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp) 的16维检测体系（20260516版），")
            lines.append("> 覆盖程序操作、证据采信、事实认定、焦点偏移、法律适用、自由裁量、修辞技巧、逻辑闭环、")
            lines.append("> 时间一致性、审理过程、外部干预、执行问题、缺失信息、语义漂移、类案偏离、惯性耦合等16个维度。")
            lines.append("> 检测结果已自动纳入本报告的异常扣分计算，与七维质量评分体系形成互补。\n")

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
            for rk in risk_order:
                if rk in risk_summary:
                    lines.append(f"| {_SEVERITY_ZH.get(rk, rk)}风险维度数 | {risk_summary[rk]} |")
            lines.append("")

            lines.append("> [!NOTE]")
            lines.append(f"> 本次检测共扫描 {len(anomaly_mcp_results)} 个维度，检出 {total_anomalies} 项异常。")
            if risk_summary.get("critical", 0) > 0 or risk_summary.get("high", 0) > 0:
                lines.append(f"> 其中严重风险 {risk_summary.get('critical', 0)} 个维度、高风险 {risk_summary.get('high', 0)} 个维度，需重点关注。")
            elif risk_summary.get("medium", 0) > 0:
                lines.append(f"> 未发现严重或高风险维度，中风险 {risk_summary.get('medium', 0)} 个维度建议留意。")
            else:
                lines.append("> 各维度均未检出明显异常，文书整体表现正常。")
            lines.append("")

            critical_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "critical"]
            high_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "high"]
            medium_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "medium"]
            low_dims = [d for d in anomaly_mcp_results if d.get("risk_level") in ("low", "unknown")]

            if critical_dims:
                lines.append("> [!CAUTION]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in critical_dims)
                lines.append(f"> **严重风险**：{len(critical_dims)} 个维度存在严重异常（{dim_names}），强烈建议重点审查\n")

            if high_dims:
                lines.append("> [!WARNING]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in high_dims)
                lines.append(f"> **高风险**：{len(high_dims)} 个维度存在高严重度异常（{dim_names}），建议重点关注\n")

            if medium_dims:
                lines.append("> [!NOTE]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in medium_dims)
                lines.append(f"> **中风险**：{len(medium_dims)} 个维度存在中等异常（{dim_names}），建议留意\n")

            if low_dims:
                lines.append("> [!TIP]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in low_dims)
                lines.append(f"> **低风险**：{len(low_dims)} 个维度未检出明显异常（{dim_names}），文书在这些方面表现正常\n")

            lines.append("### 各维度异常详情\n")

            _DIMENSION_ORDER_MAP = {d: i + 1 for i, d in enumerate([
                "procedure", "evidence", "fact_finding", "focus_drift",
                "law_application", "discretion", "rhetoric_trick", "logic",
                "temporal", "trial_process", "external_interference", "execution",
                "negative_space", "semantic_drift", "case_deviation", "coupling",
            ])}

            _DIMENSION_DETAIL_DESC = {
                "procedure": "检测案件拆分/合并、管辖权、回避、送达、审限、庭审程序、诉讼权利告知等程序性事项是否合法合规",
                "evidence": "检测证据采信是否存在双重标准、举证责任分配是否合理、证据链条是否完整、证据排除是否正当",
                "fact_finding": "检测事实认定是否有证据支撑、是否存在逻辑说理错误、举证责任分配是否合理、关键情节是否遗漏",
                "focus_drift": "检测争议焦点是否偏移、是否回避核心争议、是否引入无关议题",
                "law_application": "检测法律适用是否正确、是否存在法律冲突、溯及力问题、法律解释是否合理",
                "discretion": "检测自由裁量权行使是否合理、裁量幅度是否在合理范围内、是否说明裁量理由",
                "rhetoric_trick": "检测是否存在修辞技巧掩盖问题、模糊表述、选择性叙述、情绪化语言",
                "logic": "检测逻辑闭环是否完整、是否存在循环论证、自相矛盾、跳跃推理",
                "temporal": "检测时间线是否一致、是否存在时间倒置、时间间隔异常、溯及力问题",
                "trial_process": "检测审理过程是否规范、是否存在程序空转、审理顺序异常",
                "external_interference": "检测是否存在外部干预迹象、舆论影响、行政干预",
                "execution": "检测执行问题是否妥善处理、执行异议是否回应",
                "negative_space": "检测缺失信息、未回应的辩解意见、遗漏的诉讼请求、沉默的证据",
                "semantic_drift": "检测概念使用是否前后一致、是否存在偷换概念、语义漂移",
                "case_deviation": "检测与类案的偏离程度、偏离是否有合理说明",
                "coupling": "检测是否存在多维度异常耦合、异常指向是否一致、是否存在系统性偏差",
            }

            for dim_result in anomaly_mcp_results:
                dim_key = dim_result.get("dimension", "?")
                dim_num = _DIMENSION_ORDER_MAP.get(dim_key, "?")
                dim_name = _DIMENSION_ZH.get(dim_key, dim_key)
                dim_risk = dim_result.get("risk_level", "unknown")
                dim_count = dim_result.get("anomaly_count", 0)
                dim_summary = dim_result.get("summary", "")
                dim_anomalies = dim_result.get("anomalies", [])

                risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "unknown": "⚪"}.get(dim_risk, "⚪")
                lines.append(f"#### {risk_icon} 维度{dim_num}·{dim_name}（{_SEVERITY_ZH.get(dim_risk, dim_risk)}风险，{dim_count} 项异常）\n")

                dim_desc = _DIMENSION_DETAIL_DESC.get(dim_key, "")
                if dim_desc:
                    lines.append(f"**维度说明**：{dim_desc}\n")

                if dim_summary:
                    lines.append(f"> **检测摘要**：{dim_summary}\n")

                if dim_anomalies:
                    lines.append("| 检测项 | 检测结果 | 说明 |")
                    lines.append("|:---|:---:|:---|")
                    for a_idx, a in enumerate(dim_anomalies, 1):
                        name = a.get("item_name", a.get("f_code", "?"))
                        f_code = a.get("f_code", f"{dim_key[:2].upper()}-{a_idx:02d}")
                        status = "⚠️ 存疑" if a.get("confidence") in ("high", "⚠️") else ("✅ 正常" if a.get("confidence") in ("low", "🟢") else "🔍 关注")
                        desc = a.get("description", "")
                        beneficiary = a.get("beneficiary", "—")
                        if beneficiary and beneficiary != "—":
                            desc += f"（指向获益方：{beneficiary}）"
                        lines.append(f"| {f_code} {name} | {status} | {desc} |")
                    lines.append("")

                    for a_idx, a in enumerate(dim_anomalies, 1):
                        f_code = a.get("f_code", f"{dim_key[:2].upper()}-{a_idx:02d}")
                        name = a.get("item_name", a.get("f_code", "?"))
                        confidence = a.get("confidence", "—")
                        if confidence in ("high", "⚠️", "🔴"):
                            lines.append(f"> [!WARNING]")
                            lines.append(f"> **触发项**：{f_code} {name}")
                            lines.append(f"> **原文定位**：{a.get('original_text_location', a.get('location', '—'))}")
                            lines.append(f"> **证据对照**：{a.get('evidence_reference', a.get('evidence', '—'))}")
                            lines.append(f"> **法理/背景点评**：{a.get('legal_analysis', a.get('background', '—'))}")
                            lines.append(f"> **对抗校验**：Q1替代解释={a.get('q1_alternative', '存在')}；Q2排除主观={a.get('q2_subjective', '未见偏向')}；Q3相反证据={a.get('q3_contradictory', '无')}")
                            lines.append(f"> **校验结论**：{a.get('conclusion', '⚠️ 存疑——需进一步核实')}")
                            lines.append("")
                else:
                    if dim_risk in ("low", "unknown"):
                        lines.append("> 本维度未检出明显异常，文书在此方面表现正常。\n")

            lines.append("> [!TIP]")
            lines.append("> 异常检测与质量评估互补：质量评估侧重文书规范性，异常检测侧重潜在不公与程序瑕疵。")
            lines.append("> 两项结果合并参考，可更全面地评价文书质量。\n")
        else:
            lines.append("## 四、十六维度深度异常剖析\n")
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
            lines.append("## 七、一致性审查\n")
            lines.append("> [!WARNING]")
            lines.append(f"> 检出 {len(cross_check.get('conflicts', []))} 项维度间逻辑矛盾\n")
            for c in cross_check.get("conflicts", []):
                lines.append(f"- **{c.get('rule_name', '')}**：{c.get('message', '')}")
            lines.append("")
        elif cross_check:
            lines.append("## 七、一致性审查\n")
            lines.append("> [!TIP]")
            lines.append("> 各维度评分逻辑一致，未检出矛盾\n")

        # ── 扩展检测功能 ──
        has_extended = any([law_database_result, case_precedent_result,
                            supplementary_docs_result, legal_difficulty_result])
        if has_extended:
            lines.append("## 八、扩展检测功能\n")
            lines.append("> [!NOTE]")
            lines.append("> 本节包含法律法规数据库、类案判例、补充文档及法律适用难点分析，为质量评估提供深度参考。")
            lines.append("> 这些扩展功能通过外部知识库和智能分析，为文书质量评价提供法理支撑和比较法视角。\n")

        if law_database_result:
            matched = law_database_result.get("matched_laws", [])
            priority = law_database_result.get("priority_order", [])
            conflicts = law_database_result.get("conflicts", [])
            retro = law_database_result.get("retroactivity_issues", [])
            principles = law_database_result.get("applicable_principles", [])

            lines.append("### 法律法规数据库查询\n")
            if matched:
                lines.append("| 优先级 | 法律名称 | 层级 | 效力日期 | 适用范围 |")
                lines.append("|:---:|:---|:---|:---|:---|")
                for p in priority:
                    law_info = next((l for l in matched if l["name"] == p["name"]), {})
                    lines.append(f"| {p['rank']} | {p['name']} | {p.get('hierarchy', '')} | {law_info.get('effective_date', '—')} | {'特别法' if law_info.get('scope') == 'special' else '一般法'} |")
                lines.append("")

            if conflicts:
                lines.append("> [!WARNING]")
                lines.append(f"> 检出 {len(conflicts)} 项法律适用冲突\n")
                lines.append("| 冲突类型 | 特别法/地方法 | 一般法/上位法 | 适用规则 | 例外情形 |")
                lines.append("|:---|:---|:---|:---|:---|")
                for c in conflicts:
                    lines.append(f"| {c.get('type', '')} | {c.get('special', c.get('local', ''))} | {c.get('general', c.get('national', ''))} | {c.get('rule', '')} | {c.get('exception', '—')} |")
                lines.append("")

            if retro:
                lines.append("> [!CAUTION]")
                lines.append(f"> 检出 {len(retro)} 项法律溯及力问题\n")
                lines.append("| 法律 | 生效日期 | 案件最早事实 | 问题说明 | 解决建议 |")
                lines.append("|:---|:---|:---|:---|:---|")
                for r in retro:
                    lines.append(f"| {r.get('law', '')} | {r.get('effective_date', '')} | {r.get('case_earliest_fact', '')} | {r.get('issue', '')} | {r.get('resolution', '')} |")
                lines.append("")

            if principles:
                lines.append("#### 可适用的法律原则\n")
                lines.append("| 原则名称 | 来源 | 适用范围 | 约束 |")
                lines.append("|:---|:---|:---|:---|")
                for p in principles:
                    lines.append(f"| {p.get('name', '')} | {p.get('origin', '')} | {p.get('scope', '')} | {p.get('constraint', '')} |")
                lines.append("")

        if case_precedent_result:
            precedents = case_precedent_result.get("precedents", [])
            conflicts = case_precedent_result.get("conflict_points", [])
            deviations = case_precedent_result.get("deviation_points", [])
            innovation = case_precedent_result.get("innovation_space", [])

            lines.append("### 类案判例查询\n")
            if precedents:
                lines.append("| 案例 | 审理法院 | 核心裁判要旨 | 相关性 |")
                lines.append("|:---|:---|:---|:---|")
                for p in precedents:
                    lines.append(f"| {p.get('id', '')}：{p.get('title', '')} | {p.get('court', '')} | {p.get('key_ruling', '')} | {p.get('relevance', '')} |")
                lines.append("")

            if conflicts:
                lines.append("> [!WARNING]")
                lines.append(f"> 检出 {len(conflicts)} 项类案裁判冲突\n")
                lines.append("| 争议问题 | 裁判倾向 | 支持率 | 意义 |")
                lines.append("|:---|:---|:---|:---|")
                for c in conflicts:
                    lines.append(f"| {c.get('issue', '')} | {c.get('tendency', '')} | {c.get('support_rate', '')} | {c.get('significance', '')} |")
                lines.append("")

            if innovation:
                lines.append("#### 突破性创新空间\n")
                for inn in innovation:
                    lines.append(f"- **{inn.get('area', '')}**：{inn.get('innovation_direction', '')}")
                    lines.append(f"  - 约束：{inn.get('constraint', '')}")
                lines.append("")

        if supplementary_docs_result:
            lines.append("### 补充说明文档\n")
            lines.append(f"本案已提交 {len(supplementary_docs_result)} 份补充文档：\n")
            lines.append("| 序号 | 类型 | 标题 | 权威级别 |")
            lines.append("|:---:|:---|:---|:---|")
            for d in supplementary_docs_result:
                lines.append(f"| {d.get('index', '')} | {d.get('doc_type_zh', '')} | {d.get('title', '')} | {d.get('authority_level_zh', '')} |")
            lines.append("")

        if legal_difficulty_result:
            difficulties = legal_difficulty_result.get("difficulties", [])
            app_principles = legal_difficulty_result.get("applicable_principles", [])
            ethics = legal_difficulty_result.get("ethics_considerations", [])
            frontier = legal_difficulty_result.get("frontier_analysis", [])
            inn_space = legal_difficulty_result.get("innovation_space", [])
            constraint = legal_difficulty_result.get("constraint_notice", "")

            lines.append("### 法律适用难点与前沿问题分析\n")
            if difficulties:
                lines.append("| 难点问题 | 难度级别 | 当前法律状态 | 相关条文 |")
                lines.append("|:---|:---:|:---|:---|")
                for d in difficulties:
                    provs = "；".join(d.get("relevant_provisions", [])[:2])
                    lines.append(f"| {d.get('issue', '')} | {d.get('difficulty_level', '')} | {d.get('current_legal_status', '')} | {provs or '—'} |")
                lines.append("")

            if app_principles:
                lines.append("#### 可适用的法谚与法律原则\n")
                lines.append("| 原则 | 来源 | 适用说明 | 约束 |")
                lines.append("|:---|:---|:---|:---|")
                for p in app_principles:
                    lines.append(f"| {p.get('name', '')} | {p.get('origin', '')} | {p.get('application', '')} | {p.get('constraint', '')} |")
                lines.append("")

            if ethics:
                lines.append("#### 社会伦理道德与公序良俗考量\n")
                for e in ethics:
                    lines.append(f"- **{e.get('principle', '')}**：{e.get('application', '')}")
                    lines.append(f"  - 约束：{e.get('constraint', '')}")
                    lines.append(f"  - 来源：{e.get('source', '')}")
                lines.append("")

            if frontier:
                lines.append("#### 前沿问题\n")
                for f in frontier:
                    lines.append(f"- **{f.get('issue', '')}**：{f.get('current_status', '')}")
                    lines.append(f"  - 实践意义：{f.get('practical_significance', '')}")
                lines.append("")

            if inn_space:
                lines.append("> [!TIP]")
                lines.append("> 本案存在突破性创新空间，但须遵守以下约束\n")
                for inn in inn_space:
                    lines.append(f"- **{inn.get('issue', '')}**：{inn.get('innovation_direction', '')}")
                    lines.append(f"  - 法律依据：{inn.get('legal_basis', '')}")
                    lines.append(f"  - 约束：{inn.get('constraint', '')}")
                    lines.append(f"  - 指导案例潜力：{inn.get('precedent_potential', '')}")
                lines.append("")

            if constraint:
                lines.append(f"> [!IMPORTANT]")
                lines.append(f"> {constraint}\n")

        # ── 免责声明 ──
        lines.append("---\n")
        lines.append("> [!IMPORTANT]")
        lines.append("> **免责声明**：本报告由 judicial-doc-quality-mcp 辅助生成，基于七维评分体系和十六维度异常检测的自动化分析。")
        lines.append("> 评估结果仅供参考，不构成法律意见。裁判文书的质量评价涉及复杂的法律判断，")
        lines.append("> 本报告不能替代专业法律人士的审查。\n")

        lines.append(f"*报告由 judicial-doc-quality-mcp v0.1.0 生成 · 检测体系版本 20260519 · 报告编号 {report_id} · 生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

        return json.dumps({
            "success": True,
            "report_markdown": "\n".join(lines),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("generate_report: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"报告生成异常：{e}")


@mcp.tool()
def generate_html_report(
    weighted_total: float,
    grade: str,
    dimension_results: list[dict],
    anomaly_details: list[dict] | None = None,
    innovation_details: list[dict] | None = None,
    anomaly_deduction: float = 0,
    innovation_bonus: float = 0,
    document_meta: dict | None = None,
    timeline_result: dict | None = None,
    evasive_result: dict | None = None,
    evidence_result: dict | None = None,
    cross_check: dict | None = None,
    anomaly_mcp_results: list[dict] | None = None,
    law_database_result: dict | None = None,
    case_precedent_result: dict | None = None,
    supplementary_docs_result: list[dict] | None = None,
    legal_difficulty_result: dict | None = None,
    five_reasoning: dict | None = None,
    four_element: dict | None = None,
    beneficiary_distribution: dict | None = None,
    coupling_analysis: list[dict] | None = None,
    minimum_score_applied: bool = False,
    report_id: str | None = None,
    trial_stage: str = "",
) -> str:
    """生成精美的HTML格式质量评估报告，支持light/dark主题切换（默认dark）。

    参数与 generate_report 完全一致，输出内容严格对应，但排版和设计增强可读性。
    """
    try:
        if not report_id:
            report_id = f"QA-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        md_result = json.loads(generate_report(
            weighted_total=weighted_total,
            grade=grade,
            dimension_results=dimension_results,
            anomaly_details=anomaly_details,
            innovation_details=innovation_details,
            anomaly_deduction=anomaly_deduction,
            innovation_bonus=innovation_bonus,
            document_meta=document_meta,
            timeline_result=timeline_result,
            evasive_result=evasive_result,
            evidence_result=evidence_result,
            cross_check=cross_check,
            anomaly_mcp_results=anomaly_mcp_results,
            law_database_result=law_database_result,
            case_precedent_result=case_precedent_result,
            supplementary_docs_result=supplementary_docs_result,
            legal_difficulty_result=legal_difficulty_result,
            five_reasoning=five_reasoning,
            four_element=four_element,
            beneficiary_distribution=beneficiary_distribution,
            coupling_analysis=coupling_analysis,
            minimum_score_applied=minimum_score_applied,
            report_id=report_id,
            trial_stage=trial_stage,
        ))
        md_content = md_result.get("report_markdown", "")

        html_body = _md_to_rich_html(md_content)

        html_page = _build_html_page(html_body, report_id)

        return json.dumps({
            "success": True,
            "report_html": html_page,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("generate_html_report: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"HTML报告生成异常：{e}")


def _md_to_rich_html(md_text: str) -> str:
    import re as _re

    lines = md_text.split("\n")
    html_parts = []
    in_table = False
    table_rows = []
    table_aligns = []
    in_blockquote = False
    bq_type = ""
    bq_lines = []

    _ALIGN_MAP = {
        ":---": "left", ":--:": "center", "---:": "right",
        ":---:": "center", ":--": "left", "--:": "right",
    }

    def _parse_align(sep_line):
        parts = [c.strip() for c in sep_line.split("|")[1:-1]]
        aligns = []
        for p in parts:
            p = p.strip()
            if p.startswith(":") and p.endswith(":"):
                aligns.append("center")
            elif p.endswith(":"):
                aligns.append("right")
            else:
                aligns.append("left")
        return aligns

    def close_blockquote():
        nonlocal in_blockquote, bq_type, bq_lines
        if not in_blockquote:
            return
        css_class = {
            "NOTE": "alert-note", "TIP": "alert-tip", "IMPORTANT": "alert-important",
            "WARNING": "alert-warning", "CAUTION": "alert-caution",
        }.get(bq_type, "alert-note")
        icon = {
            "NOTE": "ℹ️", "TIP": "💡", "IMPORTANT": "❗",
            "WARNING": "⚠️", "CAUTION": "🔴",
        }.get(bq_type, "ℹ️")
        inner = "<br>\n".join(bq_lines)
        html_parts.append(f'<div class="github-alert {css_class}"><div class="alert-header">{icon} {bq_type}</div><div class="alert-body">{inner}</div></div>')
        in_blockquote = False
        bq_type = ""
        bq_lines = []

    def close_table():
        nonlocal in_table, table_rows, table_aligns
        if not in_table:
            return
        html_parts.append('<div class="table-wrapper"><table>')
        for ri, row in enumerate(table_rows):
            tag = "th" if ri == 0 else "td"
            cells = [_re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', c) for c in row]
            row_html = ""
            for ci, cell in enumerate(cells):
                align = table_aligns[ci] if ci < len(table_aligns) else "left"
                style = f' style="text-align:{align}"'
                row_html += f"<{tag}{style}>{cell}</{tag}>"
            html_parts.append(f"<tr>{row_html}</tr>")
        html_parts.append("</table></div>")
        in_table = False
        table_rows = []
        table_aligns = []

    def inline_format(text):
        text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = _re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        return text

    for line in lines:
        stripped = line.strip()

        bq_match = _re.match(r'^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', stripped)
        if bq_match:
            close_blockquote()
            close_table()
            in_blockquote = True
            bq_type = bq_match.group(1)
            bq_lines = []
            continue

        if in_blockquote:
            if stripped.startswith(">"):
                content = _re.sub(r'^>\s?', '', stripped)
                bq_lines.append(inline_format(content))
                continue
            else:
                close_blockquote()

        if stripped.startswith("|") and "|" in stripped[1:]:
            sep_match = _re.match(r'^\|[\s:|-]+\|$', stripped)
            if sep_match:
                table_aligns = _parse_align(stripped)
                continue
            close_table()
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            table_rows.append(cells)
            in_table = True
            continue
        else:
            close_table()

        if stripped.startswith("### "):
            html_parts.append(f'<h3>{inline_format(stripped[4:])}</h3>')
        elif stripped.startswith("## "):
            html_parts.append(f'<h2>{inline_format(stripped[3:])}</h2>')
        elif stripped.startswith("# "):
            html_parts.append(f'<h1>{inline_format(stripped[2:])}</h1>')
        elif stripped.startswith("#### "):
            html_parts.append(f'<h4>{inline_format(stripped[5:])}</h4>')
        elif stripped == "---":
            html_parts.append("<hr>")
        elif stripped.startswith("- "):
            html_parts.append(f'<ul><li>{inline_format(stripped[2:])}</li></ul>')
        elif stripped == "":
            html_parts.append("")
        else:
            html_parts.append(f'<p>{inline_format(stripped)}</p>')

    close_blockquote()
    close_table()

    merged = "\n".join(html_parts)
    merged = _re.sub(r'</ul>\s*<ul>', '', merged)
    merged = _re.sub(r'<p>\s*</p>', '', merged)

    return merged


def _build_html_page(body_html: str, report_id: str) -> str:
    return f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>司法文书质量评估报告 {report_id}</title>
<style>
:root {{
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --bg-card: #1c2128;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --text-muted: #6e7681;
  --border-color: #30363d;
  --accent-blue: #58a6ff;
  --accent-green: #3fb950;
  --accent-yellow: #d29922;
  --accent-orange: #db6d28;
  --accent-red: #f85149;
  --accent-purple: #bc8cff;
  --link-color: #58a6ff;
  --code-bg: #161b22;
  --table-stripe: rgba(110,118,129,0.1);
  --shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
[data-theme="light"] {{
  --bg-primary: #ffffff;
  --bg-secondary: #f6f8fa;
  --bg-tertiary: #eaeef2;
  --bg-card: #ffffff;
  --text-primary: #1f2328;
  --text-secondary: #656d76;
  --text-muted: #8c959f;
  --border-color: #d0d7de;
  --accent-blue: #0969da;
  --accent-green: #1a7f37;
  --accent-yellow: #9a6700;
  --accent-orange: #bc4c00;
  --accent-red: #cf222e;
  --accent-purple: #8250df;
  --link-color: #0969da;
  --code-bg: #f6f8fa;
  --table-stripe: rgba(175,184,193,0.15);
  --shadow: 0 2px 8px rgba(0,0,0,0.08);
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.75;
  padding: 0;
  -webkit-font-smoothing: antialiased;
}}
.theme-toggle {{
  position: fixed; top: 16px; right: 24px; z-index: 1000;
  background: var(--bg-tertiary); border: 1px solid var(--border-color);
  color: var(--text-primary); padding: 8px 16px; border-radius: 20px;
  cursor: pointer; font-size: 14px; transition: all 0.2s;
  box-shadow: var(--shadow);
}}
.theme-toggle:hover {{ background: var(--accent-blue); color: #fff; }}
.report-container {{
  max-width: 960px; margin: 0 auto; padding: 40px 32px 80px;
}}
h1 {{
  font-size: 1.75em; font-weight: 700; margin: 32px 0 16px;
  padding-bottom: 12px; border-bottom: 2px solid var(--accent-blue);
  color: var(--text-primary);
}}
h2 {{
  font-size: 1.4em; font-weight: 600; margin: 28px 0 14px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border-color);
  color: var(--accent-blue);
}}
h3 {{
  font-size: 1.15em; font-weight: 600; margin: 20px 0 10px;
  color: var(--text-primary);
}}
h4 {{
  font-size: 1.05em; font-weight: 600; margin: 16px 0 8px;
  color: var(--text-secondary);
}}
p {{ margin: 8px 0; color: var(--text-primary); }}
strong {{ color: var(--text-primary); font-weight: 600; }}
em {{ color: var(--text-secondary); }}
code {{
  background: var(--code-bg); padding: 2px 6px; border-radius: 4px;
  font-size: 0.9em; font-family: "Cascadia Code", "Fira Code", monospace;
  border: 1px solid var(--border-color);
}}
a {{ color: var(--link-color); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
hr {{
  border: none; border-top: 1px solid var(--border-color);
  margin: 24px 0;
}}
ul {{ margin: 8px 0 8px 24px; }}
li {{ margin: 4px 0; }}
.table-wrapper {{
  overflow-x: auto; margin: 16px 0;
  border: 1px solid var(--border-color); border-radius: 8px;
  box-shadow: var(--shadow);
}}
table {{
  width: 100%; border-collapse: collapse; font-size: 0.9em;
}}
th {{
  background: var(--bg-tertiary); color: var(--text-primary);
  font-weight: 600; text-align: left; padding: 10px 14px;
  border-bottom: 2px solid var(--border-color); white-space: nowrap;
}}
td {{
  padding: 9px 14px; border-bottom: 1px solid var(--border-color);
  color: var(--text-primary); vertical-align: top;
}}
tr:nth-child(even) td {{ background: var(--table-stripe); }}
tr:hover td {{ background: rgba(88,166,255,0.08); }}
.github-alert {{
  border-radius: 8px; padding: 16px 20px; margin: 16px 0;
  border-left: 4px solid; box-shadow: var(--shadow);
}}
.alert-note {{
  background: rgba(88,166,255,0.1); border-color: var(--accent-blue);
}}
.alert-tip {{
  background: rgba(63,185,80,0.1); border-color: var(--accent-green);
}}
.alert-important {{
  background: rgba(188,140,255,0.1); border-color: var(--accent-purple);
}}
.alert-warning {{
  background: rgba(210,153,34,0.1); border-color: var(--accent-yellow);
}}
.alert-caution {{
  background: rgba(248,81,73,0.1); border-color: var(--accent-red);
}}
.alert-header {{
  font-weight: 700; font-size: 0.95em; margin-bottom: 6px;
  text-transform: uppercase; letter-spacing: 0.5px;
}}
.alert-note .alert-header {{ color: var(--accent-blue); }}
.alert-tip .alert-header {{ color: var(--accent-green); }}
.alert-important .alert-header {{ color: var(--accent-purple); }}
.alert-warning .alert-header {{ color: var(--accent-yellow); }}
.alert-caution .alert-header {{ color: var(--accent-red); }}
.alert-body {{ color: var(--text-primary); font-size: 0.93em; line-height: 1.7; }}
.score-badge {{
  display: inline-block; padding: 4px 14px; border-radius: 16px;
  font-weight: 700; font-size: 1.1em; margin: 4px 2px;
}}
.grade-a {{ background: rgba(63,185,80,0.2); color: var(--accent-green); }}
.grade-b {{ background: rgba(88,166,255,0.2); color: var(--accent-blue); }}
.grade-c {{ background: rgba(210,153,34,0.2); color: var(--accent-yellow); }}
.grade-d {{ background: rgba(219,109,40,0.2); color: var(--accent-orange); }}
.grade-f {{ background: rgba(248,81,73,0.2); color: var(--accent-red); }}
.footer {{
  margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--border-color);
  color: var(--text-muted); font-size: 0.85em; text-align: center;
}}
@media (max-width: 768px) {{
  .report-container {{ padding: 20px 16px 60px; }}
  .theme-toggle {{ top: 8px; right: 12px; padding: 6px 12px; font-size: 12px; }}
  table {{ font-size: 0.82em; }}
  th, td {{ padding: 6px 8px; }}
}}
@media print {{
  .theme-toggle {{ display: none; }}
  body {{ background: #fff; color: #000; }}
  .github-alert {{ break-inside: avoid; }}
  .table-wrapper {{ box-shadow: none; }}
}}
</style>
</head>
<body>
<button class="theme-toggle" onclick="toggleTheme()" id="themeBtn">☀️ Light</button>
<div class="report-container">
{body_html}
</div>
<script>
(function(){{
  const s=localStorage.getItem("report-theme");
  if(s)document.documentElement.setAttribute("data-theme",s);
  updateBtn();
}})();
function toggleTheme(){{
  const h=document.documentElement;
  const cur=h.getAttribute("data-theme");
  const next=cur==="dark"?"light":"dark";
  h.setAttribute("data-theme",next);
  localStorage.setItem("report-theme",next);
  updateBtn();
}}
function updateBtn(){{
  const b=document.getElementById("themeBtn");
  const d=document.documentElement.getAttribute("data-theme");
  b.textContent=d==="dark"?"☀️ Light":"🌙 Dark";
}}
</script>
</body>
</html>'''


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
        dim_to_skill = {
            "procedure": "dimensions/01_procedure",
            "evidence": "dimensions/02_evidence",
            "fact_finding": "dimensions/03_fact_finding",
            "focus_drift": "dimensions/04_focus_drift",
            "law_application": "dimensions/05_law_application",
            "discretion": "dimensions/06_discretion",
            "rhetoric_trick": "dimensions/07_rhetoric_trick",
            "logic": "dimensions/08_logic",
            "temporal": "dimensions/09_temporal",
            "trial_process": "dimensions/10_trial_process",
            "external_interference": "dimensions/11_external_interference",
            "execution": "dimensions/12_execution",
            "negative_space": "dimensions/13_negative_space",
            "semantic_drift": "dimensions/14_semantic_drift",
            "case_deviation": "dimensions/15_case_deviation",
            "coupling": "dimensions/16_coupling",
        }
        for idx, dim in enumerate(dimensions):
            try:
                skill_name = dim_to_skill.get(dim, f"dimensions/{idx+1:02d}_{dim}")
                prompt_json = render_skill(
                    skill_name=skill_name,
                    variables={"materials": document_text},
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

        parsed_data = None
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)```", llm_response, re.DOTALL)
        if json_match:
            try:
                parsed_data = json.loads(json_match.group(1).strip())
                if not isinstance(parsed_data, dict) or "dimension" not in parsed_data:
                    parsed_data = None
            except (json.JSONDecodeError, ValueError):
                parsed_data = None

        if parsed_data is None:
            try:
                candidate = llm_response.strip()
                if candidate.startswith("{"):
                    parsed_data = json.loads(candidate)
                    if not isinstance(parsed_data, dict) or "dimension" not in parsed_data:
                        parsed_data = None
            except (json.JSONDecodeError, ValueError):
                parsed_data = None

        if parsed_data is None:
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
    """从裁判文书中提取时间线事件，检测影响裁判质量的实质时序异常。

    检测范围聚焦于可能影响裁判公正性和文书质量的时序问题：
    1. 程序时序倒置：关键程序节点顺序错误（如判决早于开庭、立案早于起诉）
    2. 证据时序异常：证据形成时间晚于其所证明的事实，或证据在举证期限后提交
    3. 法律溯及力问题：引用的法律条文生效时间晚于案件事实，且未说明溯及力依据
    4. 文书内部时间矛盾：同一事件在不同段落的时间描述不一致

    叙事结构导致的时间倒置（先述裁判结果后回溯事实）不作为异常报告。

    document_text: 裁判文书全文

    返回 JSON 字符串，包含：
    - events: 提取的时间线事件列表
    - anomalies: 实质时序异常列表
    - coverage: 时间线覆盖率评估
    """
    logger.info(
        "extract_timeline: >>> ENTER | doc_len=%d",
        len(document_text),
    )
    try:
        date_pattern = re.compile(
            r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?"
            r"|(\d{4})[./-](\d{1,2})[./-](\d{1,2})?"
        )

        events = []
        for i, m in enumerate(date_pattern.finditer(document_text)):
            pos = m.start()
            context_start = max(0, pos - 60)
            context_end = min(len(document_text), pos + len(m.group()) + 60)
            context = document_text[context_start:context_end].replace("\n", " ").strip()

            if m.group(1):
                year, month = int(m.group(1)), int(m.group(2))
                day = int(m.group(3)) if m.group(3) else 0
            elif m.group(4):
                year, month = int(m.group(4)), int(m.group(5))
                day = int(m.group(6)) if m.group(6) else 0
            else:
                continue

            if year > 0:
                events.append({
                    "index": i + 1,
                    "date": f"{year}-{month:02d}" + (f"-{day:02d}" if day else ""),
                    "year": year,
                    "month": month,
                    "day": day,
                    "context": context,
                    "position": pos,
                })

        anomalies = []

        # ── 1. 程序时序检测 ──
        _PROC_PATTERNS = {
            "立案": [re.compile(r"(?:于|正式)立案"), re.compile(r"受理(?:本案|后)")],
            "开庭": [re.compile(r"公开开庭"), re.compile(r"开庭审理")],
            "判决": [re.compile(r"判决如下"), re.compile(r"本院判决")],
            "上诉": [re.compile(r"提起上诉"), re.compile(r"不服.*向.*上诉")],
            "送达": [re.compile(r"送达判决"), re.compile(r"送达裁定")],
        }
        _PROC_EXCLUDE_CTX = ["出生", "生，", "年生", "日生", "身份证", "住址", "住所",
                             "一审判决", "原审判决", "原审裁定", "初审判决", "号民事判决"]

        proc_events = {}
        for evt in events:
            ctx = evt["context"]
            if any(ex in ctx for ex in _PROC_EXCLUDE_CTX):
                continue
            for proc_name, patterns in _PROC_PATTERNS.items():
                if any(p.search(ctx) for p in patterns):
                    if proc_name not in proc_events:
                        proc_events[proc_name] = evt

        _PROC_ORDER = ["立案", "开庭", "判决", "上诉", "送达"]
        proc_violations = []
        for i in range(len(_PROC_ORDER)):
            for j in range(i + 1, len(_PROC_ORDER)):
                earlier = _PROC_ORDER[i]
                later = _PROC_ORDER[j]
                if earlier in proc_events and later in proc_events:
                    e_earlier = proc_events[earlier]
                    e_later = proc_events[later]
                    if (e_later["year"], e_later["month"], e_later.get("day", 0)) < \
                       (e_earlier["year"], e_earlier["month"], e_earlier.get("day", 0)):
                        proc_violations.append(
                            f"{later}({e_later['date']})早于{earlier}({e_earlier['date']})"
                        )

        if proc_violations:
            anomalies.append({
                "type": "procedural_sequence",
                "severity": "high",
                "message": f"程序时序倒置：{'；'.join(proc_violations)}",
                "evidence": proc_violations,
                "reasoning": "关键程序节点顺序错误可能影响裁判合法性，需核实是否存在程序违法",
            })

        # ── 2. 证据时序检测 ──
        _EVIDENCE_KEYWORDS = ["证据", "证明", "鉴定", "评估报告", "检验报告", "公证书", "合同", "协议"]
        _EVIDENCE_FORMATION = ["签订", "签署", "出具", "形成", "制作", "公证", "鉴定"]

        evidence_events = []
        for evt in events:
            ctx = evt["context"]
            is_evidence = any(kw in ctx for kw in _EVIDENCE_KEYWORDS)
            is_formation = any(kw in ctx for kw in _EVIDENCE_FORMATION)
            if is_evidence and is_formation:
                evidence_events.append(evt)

        if len(evidence_events) >= 2:
            for i in range(1, len(evidence_events)):
                prev = evidence_events[i - 1]
                curr = evidence_events[i]
                if (curr["year"], curr["month"]) < (prev["year"], prev["month"]):
                    anomalies.append({
                        "type": "evidence_temporal",
                        "severity": "medium",
                        "message": f"证据时序疑问：{prev['date']}之后出现{curr['date']}的证据",
                        "evidence": [f"证据时序：{prev['date']}→{curr['date']}"],
                        "reasoning": "证据形成时间倒置可能影响证据采信，需核实是否为补强证据或事后补充",
                    })
                    break

        # ── 3. 法律溯及力检测 ──
        _LAW_PATTERNS = [
            re.compile(r"《([^》]+)》(?:第([一二三四五六七八九十百千零\d]+)条)?"),
        ]
        _LAW_EFFECTIVE_DATES = {
            "民法典": 2021, "中华人民共和国民法典": 2021,
            "劳动合同法": 2008, "中华人民共和国劳动合同法": 2008,
            "劳动争议调解仲裁法": 2008, "中华人民共和国劳动争议调解仲裁法": 2008,
            "民事诉讼法": 2022, "中华人民共和国民事诉讼法": 2022,
            "刑事诉讼法": 2018, "中华人民共和国刑事诉讼法": 2018,
            "行政诉讼法": 2017, "中华人民共和国行政诉讼法": 2017,
            "公司法": 2024, "中华人民共和国公司法": 2024,
            "民法典物权编": 2021, "民法典合同编": 2021,
            "民法典侵权责任编": 2021, "民法典婚姻家庭编": 2021,
            "最高人民法院关于审理劳动争议案件适用法律问题的解释": 2021,
            "最高人民法院关于适用《中华人民共和国民法典》时间效力的若干规定": 2021,
        }

        law_violations = []
        case_event_years = [e["year"] for e in events if e["year"] >= 2000]
        case_earliest = min(case_event_years) if case_event_years else 0

        for pat in _LAW_PATTERNS:
            for m in pat.finditer(document_text):
                law_name = m.group(1).strip()
                effective_year = _LAW_EFFECTIVE_DATES.get(law_name)
                if effective_year and case_earliest > 0 and effective_year > case_earliest:
                    pos = m.start()
                    ctx_start = max(0, pos - 30)
                    ctx_end = min(len(document_text), pos + len(m.group()) + 30)
                    ctx = document_text[ctx_start:ctx_end].replace("\n", " ").strip()
                    law_violations.append(
                        f"《{law_name}》{effective_year}年生效，但案件事实始于{case_earliest}年"
                    )

        if law_violations:
            seen_years = set()
            unique_violations = []
            for v in law_violations:
                year_key = v.split("年生效")[0][-4:] if "年生效" in v else v
                if year_key not in seen_years:
                    seen_years.add(year_key)
                    unique_violations.append(v)
            anomalies.append({
                "type": "law_retroactivity",
                "severity": "medium",
                "message": f"法律溯及力疑问：{'；'.join(unique_violations[:3])}",
                "evidence": unique_violations[:3],
                "reasoning": "引用法律生效时间晚于案件事实发生时间，需核实是否适用溯及力条款或过渡期规定",
            })

        # ── 4. 文书内部时间矛盾检测 ──
        _SAME_EVENT_PATTERNS = [
            re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?\s*(?:立案|受理)"),
            re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})?\s*日?\s*(?:判决|裁定)"),
        ]
        same_event_dates = {}
        for pat in _SAME_EVENT_PATTERNS:
            for m in pat.finditer(document_text):
                date_str = f"{m.group(1)}-{int(m.group(2)):02d}"
                event_type = "立案" if "立案" in m.group() or "受理" in m.group() else "判决"
                if event_type not in same_event_dates:
                    same_event_dates[event_type] = set()
                same_event_dates[event_type].add(date_str)

        contradictions = []
        for event_type, dates in same_event_dates.items():
            if len(dates) > 1:
                contradictions.append(f"{event_type}日期存在矛盾：{', '.join(sorted(dates))}")

        if contradictions:
            anomalies.append({
                "type": "internal_contradiction",
                "severity": "high",
                "message": f"文书内部时间矛盾：{'；'.join(contradictions)}",
                "evidence": contradictions,
                "reasoning": "同一事件在不同段落的时间描述不一致，可能存在笔误或事实认定错误",
            })

        # ── 5. 叙事结构倒置（仅作备注，不作为异常） ──
        inversion_count = 0
        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]
            if curr["year"] < prev["year"] or (
                curr["year"] == prev["year"] and curr["month"] < prev["month"]
            ):
                inversion_count += 1

        coverage = {
            "total_events": len(events),
            "year_range": f"{events[0]['year']}-{events[-1]['year']}" if events else "N/A",
            "anomaly_count": len(anomalies),
            "narrative_inversions": inversion_count,
            "completeness": "high" if len(events) >= 5 and not anomalies else
                           ("medium" if len(events) >= 3 else "low"),
        }

        if inversion_count > 0:
            coverage["note"] = f"文书存在{inversion_count}处叙事结构倒置（属正常叙事结构，非异常）"

        logger.info(
            "extract_timeline: <<< EXIT | events=%d, anomalies=%d, completeness=%s, inversions=%d",
            len(events), len(anomalies), coverage["completeness"], inversion_count,
        )
        if anomalies:
            for a in anomalies:
                logger.info(
                    "extract_timeline: ANOMALY type=%s, severity=%s, msg='%s'",
                    a["type"], a["severity"], a["message"],
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
                "text": ev_text,
                "source": "plaintiff" if is_plaintiff else ("defendant" if is_defendant else "court"),
                "position": pos,
                "context": full_context,
            })

        unaddressed = []
        missing_reasoning = []

        for ev in evidence_items:
            ev_text = ev["text"]
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
                    "evidence_detail": ev["context"],
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
                    "evidence_detail": ev["context"],
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
                    contexts[0] if contexts else "",
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
            "medium": "文书存在部分规避模式，建议大语言模型进一步确认",
            "low": "未检测到明显规避模式，文书写作规范性良好",
        }.get(risk_level, "建议进一步审查")

        logger.info(
            "detect_evasive_patterns: <<< EXIT | detected=%d, risk=%s (high=%d, medium=%d, low=%d), recommendation='%s'",
            len(detected), risk_level, high_count, medium_count, low_count, recommendation,
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


_LAW_DATABASE = {
    "民法典": {
        "full_name": "中华人民共和国民法典",
        "effective_date": "2021-01-01",
        "hierarchy": "法律",
        "scope": "general",
        "predecessor": ["民法通则", "合同法", "物权法", "侵权责任法", "婚姻法", "继承法"],
        "key_provisions": {
            "总则编": "民事活动基本原则、民事主体、民事权利、民事法律行为",
            "物权编": "所有权、用益物权、担保物权",
            "合同编": "合同的订立、效力、履行、变更转让、权利义务终止、违约责任",
            "人格权编": "生命权、身体权、健康权、姓名权、肖像权、名誉权、隐私权",
            "婚姻家庭编": "结婚、家庭关系、离婚、收养",
            "继承编": "法定继承、遗嘱继承和遗赠、遗产的处理",
            "侵权责任编": "损害赔偿、责任构成和方式、不承担责任和减轻责任",
        },
    },
    "劳动合同法": {
        "full_name": "中华人民共和国劳动合同法",
        "effective_date": "2008-01-01",
        "hierarchy": "法律",
        "scope": "special",
        "superior_law": "民法典",
        "key_provisions": {
            "第7条": "劳动关系自用工之日起建立",
            "第10条": "建立劳动关系应订立书面劳动合同",
            "第14条": "无固定期限劳动合同的订立条件",
            "第26条": "劳动合同无效的情形",
            "第30条": "用人单位支付劳动报酬的义务",
            "第82条": "未订立书面劳动合同的二倍工资",
            "第85条": "未支付劳动报酬的加付赔偿金",
            "第87条": "违法解除劳动合同的赔偿金",
        },
    },
    "劳动争议调解仲裁法": {
        "full_name": "中华人民共和国劳动争议调解仲裁法",
        "effective_date": "2008-05-01",
        "hierarchy": "法律",
        "scope": "special",
        "superior_law": "劳动合同法",
        "key_provisions": {
            "第2条": "劳动争议范围",
            "第5条": "劳动争议处理程序",
            "第27条": "仲裁时效（一年）",
            "第47条": "终局裁决情形",
            "第48条": "劳动者对终局裁决的起诉权",
        },
    },
    "民事诉讼法": {
        "full_name": "中华人民共和国民事诉讼法",
        "effective_date": "2022-01-01",
        "hierarchy": "法律",
        "scope": "general",
        "amendment_history": ["1991", "2007", "2012", "2017", "2021", "2023"],
        "key_provisions": {
            "第119条": "起诉条件",
            "第164条": "上诉期限",
            "第170条": "二审审理范围",
            "第175条": "二审裁判方式",
        },
    },
    "公司法": {
        "full_name": "中华人民共和国公司法",
        "effective_date": "2024-07-01",
        "hierarchy": "法律",
        "scope": "special",
        "superior_law": "民法典",
        "amendment_history": ["1993", "1999", "2004", "2005", "2013", "2018", "2023"],
        "key_provisions": {
            "第20条": "公司人格否认（刺破公司面纱）",
            "第21条": "关联交易规制",
            "第63条": "一人公司举证责任倒置",
        },
    },
    "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）": {
        "full_name": "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）",
        "effective_date": "2021-01-01",
        "hierarchy": "司法解释",
        "scope": "special",
        "superior_law": "劳动合同法",
        "key_provisions": {
            "第1条": "劳动争议范围界定",
            "第34条": "未签订书面劳动合同的处理",
            "第43条": "加班工资举证责任",
        },
    },
    "江苏省工资支付条例": {
        "full_name": "江苏省工资支付条例",
        "effective_date": "2005-01-01",
        "hierarchy": "地方性法规",
        "scope": "special",
        "superior_law": "劳动合同法",
        "region": "江苏省",
        "key_provisions": {
            "第31条": "停工停产期间工资支付标准",
            "第32条": "用人单位克扣、无故拖欠工资的责任",
        },
    },
}

_LEGAL_PRINCIPLES = {
    "任何人不得从违法行为中获利": {
        "origin": "罗马法法谚",
        "latin": "Nullus commodum capere potest de injuria sua propria",
        "scope": "民法基本原则",
        "application": "用人单位违法待岗不得因此降低工资标准；违法解除不得因此免除支付义务",
        "constraint": "不突破法律明文规定，仅作为法律解释和漏洞填补的指导原则",
    },
    "诚实信用原则": {
        "origin": "民法典第7条",
        "latin": "Bona fides",
        "scope": "民法基本原则（帝王条款）",
        "application": "用人单位不得以自身违约行为对抗劳动者权利主张",
        "constraint": "仅在法律无明文规定时作为补充解释依据",
    },
    "公平原则": {
        "origin": "民法典第6条",
        "scope": "民法基本原则",
        "application": "合理确定各方权利义务，防止利益严重失衡",
        "constraint": "不突破法律明文规定",
    },
    "公序良俗": {
        "origin": "民法典第8条、第153条",
        "scope": "民法基本原则",
        "application": "违反公序良俗的法律行为无效；社会公共利益优先于个体利益",
        "constraint": "仅在法律行为效力判断时适用，不直接作为裁判依据",
    },
    "举轻以明重": {
        "origin": "罗马法法谚",
        "latin": "A maiore ad minus",
        "scope": "法律解释方法",
        "application": "轻行为尚且禁止，重行为更应禁止",
        "constraint": "仅用于法律解释，不创设新的法律规范",
    },
    "特别法优于一般法": {
        "origin": "立法法第92条",
        "scope": "法律适用规则",
        "application": "同一事项特别规定与一般规定不一致时适用特别规定",
        "constraint": "仅在同一机关制定的法律之间适用",
    },
    "新法优于旧法": {
        "origin": "立法法第92条",
        "scope": "法律适用规则",
        "application": "同一事项新规定与旧规定不一致时适用新规定",
        "constraint": "需注意溯及力问题，新法一般不溯及既往",
    },
    "上位法优于下位法": {
        "origin": "立法法第88条",
        "scope": "法律适用规则",
        "application": "下位法不得抵触上位法，抵触时适用上位法",
        "constraint": "法律 > 行政法规 > 地方性法规 > 规章",
    },
}

_supplementary_docs: dict[str, list[dict]] = {}


@mcp.tool()
def query_law_database(
    law_names: list[str] | None = None,
    case_context: str = "",
    check_conflicts: bool = True,
) -> str:
    """查询法律法规数据库，检测法律适用优先级、冲突和溯及力问题。

    内置法律法规数据库包含：
    - 国家法律（民法典、劳动合同法、劳动争议调解仲裁法等）
    - 司法解释
    - 地方性法规（如江苏省工资支付条例）
    - 法律适用优先级规则（特别法优于一般法、新法优于旧法、上位法优于下位法）

    law_names: 要查询的法律名称列表（为空则根据case_context自动匹配）
    case_context: 案件上下文描述，用于自动匹配相关法律
    check_conflicts: 是否检测法律之间的冲突和溯及力问题

    返回 JSON 字符串，包含：
    - matched_laws: 匹配到的法律列表
    - priority_order: 法律适用优先级排序
    - conflicts: 检测到的法律冲突
    - retroactivity_issues: 溯及力问题
    """
    logger.info(
        "query_law_database: >>> ENTER | law_names=%s, check_conflicts=%s",
        law_names, check_conflicts,
    )
    try:
        matched = []
        search_names = law_names or []
        if case_context:
            for key, info in _LAW_DATABASE.items():
                if any(kw in case_context for kw in [key, info.get("full_name", "")]):
                    if key not in search_names:
                        search_names.append(key)
            if not search_names:
                for key in _LAW_DATABASE:
                    if any(kw in case_context for kw in ["劳动", "合同", "工资", "用工"]):
                        if key in ["劳动合同法", "劳动争议调解仲裁法", "民法典"]:
                            if key not in search_names:
                                search_names.append(key)

        for name in search_names:
            if name in _LAW_DATABASE:
                matched.append({"name": name, **_LAW_DATABASE[name]})

        priority_order = sorted(
            matched,
            key=lambda x: {"法律": 0, "司法解释": 1, "地方性法规": 2}.get(x.get("hierarchy", ""), 3),
        )

        conflicts = []
        retroactivity_issues = []
        if check_conflicts and len(matched) >= 2:
            for i in range(len(matched)):
                for j in range(i + 1, len(matched)):
                    a, b = matched[i], matched[j]
                    if a.get("scope") == "special" and b.get("scope") == "general":
                        conflicts.append({
                            "type": "特别法与一般法",
                            "special": a["name"],
                            "general": b["name"],
                            "rule": "特别法优于一般法，优先适用" + a["name"],
                            "exception": "特别法无规定时适用一般法",
                        })
                    if a.get("region") and not b.get("region"):
                        conflicts.append({
                            "type": "地方性法规与上位法",
                            "local": a["name"],
                            "national": b["name"],
                            "rule": "地方性法规不得抵触上位法",
                        })

            from datetime import datetime
            for law in matched:
                eff_date = law.get("effective_date", "")
                if eff_date and case_context:
                    eff_year = int(eff_date.split("-")[0])
                    year_matches = re.findall(r"(\d{4})年", case_context)
                    if year_matches:
                        earliest = min(int(y) for y in year_matches if int(y) >= 2000)
                        if eff_year > earliest:
                            retroactivity_issues.append({
                                "law": law["name"],
                                "effective_date": eff_date,
                                "case_earliest_fact": f"{earliest}年",
                                "issue": f"《{law['name']}》{eff_date}生效，但案件事实始于{earliest}年",
                                "resolution": "需核实是否适用溯及力条款或过渡期规定",
                                "retroactivity_clause": law.get("full_name") + "关于时间效力的规定",
                            })

        result = {
            "success": True,
            "matched_laws": matched,
            "priority_order": [{"rank": i+1, "name": l["name"], "hierarchy": l.get("hierarchy", "")}
                               for i, l in enumerate(priority_order)],
            "conflicts": conflicts,
            "retroactivity_issues": retroactivity_issues,
            "applicable_principles": [],
        }

        if case_context:
            for pname, pinfo in _LEGAL_PRINCIPLES.items():
                if any(kw in case_context for kw in ["违法获利", "违法", "获利", "诚实", "信用",
                                                      "公平", "公序良俗", "道德"]):
                    result["applicable_principles"].append({"name": pname, **pinfo})

        logger.info(
            "query_law_database: <<< EXIT | matched=%d, conflicts=%d, retro=%d",
            len(matched), len(conflicts), len(retroactivity_issues),
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("query_law_database: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"法律法规查询异常：{e}")


@mcp.tool()
def query_case_precedent(
    case_type: str,
    key_facts: list[str],
    court_level: str = "",
) -> str:
    """查询类案判例数据库，检测类案冲突和偏离。

    基于案件类型和关键事实，检索类案判例，分析裁判倾向和偏离点。
    支持指导性案例、公报案例、参考案例等多层级判例检索。

    case_type: 案件类型（如"劳动争议"、"合同纠纷"）
    key_facts: 关键事实列表
    court_level: 审理法院层级（如"中级人民法院"）

    返回 JSON 字符串，包含：
    - precedents: 检索到的类案判例
    - tendency: 裁判倾向分析
    - deviation_points: 偏离点
    - conflict_points: 类案冲突点
    """
    logger.info(
        "query_case_precedent: >>> ENTER | case_type=%s, facts=%d",
        case_type, len(key_facts),
    )
    try:
        _CASE_TYPE_PRECEDENTS = {
            "劳动争议": {
                "guiding_cases": [
                    {
                        "id": "指导案例18号",
                        "title": "中兴通讯诉王鹏劳动合同纠纷案",
                        "court": "最高人民法院",
                        "key_ruling": "劳动者在用人单位等级考核中居于末位等次，不等同于'不能胜任工作'",
                        "relevance": "绩效考核与不能胜任的区分",
                    },
                    {
                        "id": "指导案例94号",
                        "title": "重庆市涪陵志大物业诉何某某劳动争议案",
                        "court": "最高人民法院",
                        "key_ruling": "见义勇为受伤应视同工伤",
                        "relevance": "工伤认定标准",
                    },
                ],
                "common_issues": [
                    {"issue": "未签书面劳动合同的二倍工资", "tendency": "支持，但高管兼人事负责人除外", "rate": "约85%支持"},
                    {"issue": "违法待岗期间的工资标准", "tendency": "分歧较大，部分按最低工资、部分按原工资", "rate": "约55%按原工资"},
                    {"issue": "混同用工的连带责任", "tendency": "支持关联企业承担连带责任", "rate": "约78%支持"},
                    {"issue": "加班工资的举证责任", "tendency": "劳动者主张加班事实需初步举证", "rate": "约70%要求劳动者举证"},
                ],
            },
        }

        precedents = []
        conflict_points = []
        deviation_points = []

        type_data = _CASE_TYPE_PRECEDENTS.get(case_type, {})
        if type_data:
            for gc in type_data.get("guiding_cases", []):
                precedents.append({
                    "level": "指导性案例",
                    **gc,
                })

            for ci in type_data.get("common_issues", []):
                if any(kw in ci["issue"] for kw in key_facts):
                    if "分歧" in ci.get("tendency", ""):
                        conflict_points.append({
                            "issue": ci["issue"],
                            "tendency": ci["tendency"],
                            "support_rate": ci.get("rate", ""),
                            "significance": "类案裁判存在分歧，需注意法律适用一致性",
                        })
                    deviation_points.append({
                        "issue": ci["issue"],
                        "mainstream_tendency": ci["tendency"],
                        "support_rate": ci.get("rate", ""),
                    })

        result = {
            "success": True,
            "case_type": case_type,
            "precedents": precedents,
            "deviation_points": deviation_points,
            "conflict_points": conflict_points,
            "innovation_space": [],
        }

        if conflict_points:
            result["innovation_space"] = [{
                "area": cp["issue"],
                "current_status": cp["tendency"],
                "innovation_direction": "存在突破类案裁判分歧、创设新裁判规则的空间",
                "constraint": "突破类案需充分说理，不得违反法律明文规定",
            }]

        logger.info(
            "query_case_precedent: <<< EXIT | precedents=%d, conflicts=%d, deviations=%d",
            len(precedents), len(conflict_points), len(deviation_points),
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("query_case_precedent: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"类案查询异常：{e}")


@mcp.tool()
def submit_supplementary_doc(
    case_id: str,
    doc_type: str,
    doc_content: str,
    doc_title: str = "",
    authority_level: str = "reference",
) -> str:
    """针对特定案例提交补充说明文件，可在报告中引用作为说明基础。

    支持的文档类型：
    - law_analysis: 法律适用分析说明
    - academic_opinion: 学术论文或观点
    - precedent_comparison: 类案对比分析
    - legal_maxim: 法谚或法律原则适用说明
    - ethics_morality: 社会伦理道德和公序良俗规则适用说明
    - frontier_issue: 法律适用前沿问题分析
    - innovation_argument: 突破性创新论证

    case_id: 案件标识（如案号）
    doc_type: 文档类型
    doc_content: 文档内容
    doc_title: 文档标题
    authority_level: 权威级别（binding/authoritative/reference/persuasive）

    返回 JSON 字符串，包含提交确认和文档索引。
    """
    logger.info(
        "submit_supplementary_doc: >>> ENTER | case_id=%s, doc_type=%s, authority=%s",
        case_id, doc_type, authority_level,
    )
    try:
        _VALID_TYPES = {
            "law_analysis": "法律适用分析说明",
            "academic_opinion": "学术论文或观点",
            "precedent_comparison": "类案对比分析",
            "legal_maxim": "法谚或法律原则适用说明",
            "ethics_morality": "社会伦理道德和公序良俗规则适用说明",
            "frontier_issue": "法律适用前沿问题分析",
            "innovation_argument": "突破性创新论证",
        }
        _VALID_LEVELS = ["binding", "authoritative", "reference", "persuasive"]

        if doc_type not in _VALID_TYPES:
            return _make_error(
                ErrorCode.INVALID_INPUT,
                f"不支持的文档类型：{doc_type}，可选：{list(_VALID_TYPES.keys())}",
            )
        if authority_level not in _VALID_LEVELS:
            authority_level = "reference"

        if case_id not in _supplementary_docs:
            _supplementary_docs[case_id] = []

        doc_index = len(_supplementary_docs[case_id]) + 1
        doc_entry = {
            "index": doc_index,
            "doc_type": doc_type,
            "doc_type_zh": _VALID_TYPES[doc_type],
            "title": doc_title or f"补充文档-{doc_index}",
            "content": doc_content,
            "authority_level": authority_level,
            "authority_level_zh": {"binding": "约束性", "authoritative": "权威性",
                                   "reference": "参考性", "persuasive": "说服性"}[authority_level],
        }
        _supplementary_docs[case_id].append(doc_entry)

        result = {
            "success": True,
            "case_id": case_id,
            "doc_index": doc_index,
            "doc_type_zh": doc_entry["doc_type_zh"],
            "title": doc_entry["title"],
            "authority_level_zh": doc_entry["authority_level_zh"],
            "total_docs_for_case": len(_supplementary_docs[case_id]),
            "message": f"补充文档已提交：{doc_entry['title']}（{doc_entry['doc_type_zh']}，{doc_entry['authority_level_zh']}）",
        }

        logger.info(
            "submit_supplementary_doc: <<< EXIT | index=%d, total=%d",
            doc_index, len(_supplementary_docs[case_id]),
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("submit_supplementary_doc: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"补充文档提交异常：{e}")


@mcp.tool()
def analyze_legal_difficulty(
    case_context: str,
    legal_issues: list[str],
    allow_innovation: bool = False,
) -> str:
    """分析法律适用难点和前沿问题，允许在疑难案件中突破性创新。

    功能：
    1. 识别法律适用中的模糊地带和疑难问题
    2. 引用法谚、法律原则、社会伦理道德和公序良俗规则
    3. 分析前沿法律问题，提供学术论文或观点参考
    4. 在允许创新时，为创造新的典型案例或指导案例留有空间

    约束：上述分析不得突破现有法律法规的明确规定。

    case_context: 案件上下文描述
    legal_issues: 法律适用难点列表
    allow_innovation: 是否允许突破性创新论证

    返回 JSON 字符串，包含：
    - difficulties: 法律适用难点分析
    - applicable_principles: 可适用的法谚和法律原则
    - ethics_considerations: 社会伦理道德和公序良俗考量
    - frontier_analysis: 前沿问题分析
    - innovation_space: 突破性创新空间（仅当allow_innovation=True）
    """
    logger.info(
        "analyze_legal_difficulty: >>> ENTER | issues=%d, innovation=%s",
        len(legal_issues), allow_innovation,
    )
    try:
        difficulties = []
        for issue in legal_issues:
            diff_entry = {
                "issue": issue,
                "difficulty_level": "high",
                "current_legal_status": "法律适用存在模糊地带",
                "relevant_provisions": [],
                "analysis": "",
            }
            for law_name, law_info in _LAW_DATABASE.items():
                for prov_name, prov_desc in law_info.get("key_provisions", {}).items():
                    if any(kw in issue for kw in prov_desc.split("、")):
                        diff_entry["relevant_provisions"].append(
                            f"《{law_info.get('full_name', law_name)}》{prov_name}：{prov_desc}"
                        )
            if not diff_entry["relevant_provisions"]:
                diff_entry["difficulty_level"] = "frontier"
                diff_entry["current_legal_status"] = "法律尚无明确规定，属于前沿问题"
            difficulties.append(diff_entry)

        applicable_principles = []
        principle_keywords = {
            "违法": ["任何人不得从违法行为中获利", "诚实信用原则"],
            "获利": ["任何人不得从违法行为中获利"],
            "待岗": ["任何人不得从违法行为中获利", "公平原则"],
            "混同": ["诚实信用原则", "公序良俗"],
            "人格": ["公序良俗", "诚实信用原则"],
            "工资": ["公平原则", "任何人不得从违法行为中获利"],
            "加班": ["公平原则"],
        }
        seen = set()
        for issue in legal_issues:
            for kw, principles in principle_keywords.items():
                if kw in issue or kw in case_context:
                    for p in principles:
                        if p not in seen and p in _LEGAL_PRINCIPLES:
                            seen.add(p)
                            applicable_principles.append({
                                "name": p,
                                **_LEGAL_PRINCIPLES[p],
                                "applicable_to": issue,
                            })

        ethics_considerations = []
        if any(kw in case_context for kw in ["违法", "待岗", "拒绝", "剥夺"]):
            ethics_considerations.append({
                "principle": "任何人不得从违法行为中获利",
                "application": "用人单位违法拒绝提供劳动条件，不得因此降低工资标准；违法在先者不得因自身违法行为获益",
                "constraint": "此原则不创设新的法律规范，仅在法律解释存在模糊时作为补充依据",
                "source": "罗马法法谚，已被中国司法实践广泛采纳",
            })
        if any(kw in case_context for kw in ["混同", "关联", "人格"]):
            ethics_considerations.append({
                "principle": "诚实信用原则（帝王条款）",
                "application": "关联企业不得利用人格混同规避法律义务",
                "constraint": "仅在法律无明文规定时作为补充解释依据",
                "source": "民法典第7条",
            })

        frontier_analysis = []
        for diff in difficulties:
            if diff["difficulty_level"] == "frontier":
                frontier_analysis.append({
                    "issue": diff["issue"],
                    "current_status": diff["current_legal_status"],
                    "academic_views": "学界存在不同观点，需结合具体案情判断",
                    "practical_significance": "该问题的裁判规则尚在发展中，具有创设指导案例的潜力",
                })

        innovation_space = []
        if allow_innovation:
            for diff in difficulties:
                if diff["difficulty_level"] in ("high", "frontier"):
                    innovation_space.append({
                        "issue": diff["issue"],
                        "current_limitation": diff["current_legal_status"],
                        "innovation_direction": "存在突破现有裁判惯例、创设新裁判规则的空间",
                        "legal_basis": "在法律框架内，通过法律解释和类推适用填补法律漏洞",
                        "constraint": "不得违反法律明文规定，需充分说理，确保裁判公正",
                        "precedent_potential": "若裁判理由充分，具有成为指导性案例的潜力",
                    })

        result = {
            "success": True,
            "difficulties": difficulties,
            "applicable_principles": applicable_principles,
            "ethics_considerations": ethics_considerations,
            "frontier_analysis": frontier_analysis,
            "innovation_space": innovation_space,
            "constraint_notice": "所有分析均不得突破现有法律法规的明确规定，法谚和法律原则仅在法律解释存在模糊时作为补充依据",
        }

        logger.info(
            "analyze_legal_difficulty: <<< EXIT | difficulties=%d, principles=%d, ethics=%d, innovation=%d",
            len(difficulties), len(applicable_principles),
            len(ethics_considerations), len(innovation_space),
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("analyze_legal_difficulty: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"法律适用难点分析异常：{e}")


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
