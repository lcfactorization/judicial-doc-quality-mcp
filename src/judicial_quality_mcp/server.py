"""MCP Server v0.2.0 — Bridge Architecture for Judicial Document Quality Assessment.

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
import threading
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
from . import report_builder as _report_builder
from .pipeline_state import PipelineStateManager
from . import law_reference as _law_ref

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
    """Delegate to prompt_builder.infer_trial_stage."""
    from .prompt_builder import infer_trial_stage
    return infer_trial_stage(case_name, document_text)


def _estimate_tokens(text: str) -> int:
    """Delegate to token_estimator.estimate_tokens."""
    from .token_estimator import estimate_tokens
    return estimate_tokens(text)


def _make_error(code: ErrorCode, message: str, details: dict | None = None, retryable: bool = False) -> str:
    err = StructuredError(code=code.value, message=message, details=details or {}, retryable=retryable)
    return json.dumps({"success": False, "error": err.model_dump()}, ensure_ascii=False, indent=2)


def _run_rule_engine(document_text: str, sections: dict) -> list[dict]:
    """Delegate to rule_engine.run_rule_engine."""
    from .rule_engine import run_rule_engine
    return run_rule_engine(document_text, sections)


_pipeline_mgr = PipelineStateManager()

# Global lock for server-level shared mutable state.
# Sub-modules (PipelineStateManager, law_reference) have their own internal locks;
# this lock guards cross-cutting operations that touch multiple shared resources.
_state_lock = threading.Lock()


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
        from .section_extractor import extract_document_sections as _extract
        from .rule_engine import run_rule_engine
        result = _extract(document_full_text, run_rule_engine=True, rule_engine_fn=run_rule_engine)
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
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
        from .prompt_builder import render_dimension_prompt as _render
        result = _render(
            dimension=dimension,
            sections=sections,
            include_anchors=include_anchors,
            anchor_count=anchor_count,
            loader=_loader,
            renderer=_renderer,
        )
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
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
        from .rule_engine import cross_check_consistency as _cross_check
        int_scores = {}
        for k, v in scores.items():
            try:
                int_scores[k] = int(v)
            except (ValueError, TypeError):
                int_scores[k] = 0
        result = _cross_check(int_scores)
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
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
        from .anomaly_bridge import apply_anomaly_deduction as _apply_deduction
        result = _apply_deduction(anomaly_results)
        return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
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
    return _report_builder.build_report_markdown(
        dimension_results=dimension_results,
        weighted_total=weighted_total,
        grade=grade,
        cross_check=cross_check,
        anomaly_deduction=anomaly_deduction,
        innovation_bonus=innovation_bonus,
        anomaly_details=anomaly_details,
        innovation_details=innovation_details,
        anomaly_mcp_results=anomaly_mcp_results,
        timeline_result=timeline_result,
        evasive_result=evasive_result,
        evidence_result=evidence_result,
        document_meta=document_meta,
        law_database_result=law_database_result,
        case_precedent_result=case_precedent_result,
        supplementary_docs_result=supplementary_docs_result,
        legal_difficulty_result=legal_difficulty_result,
        five_reasoning=five_reasoning,
        four_element=four_element,
        beneficiary_distribution=beneficiary_distribution,
        coupling_analysis=coupling_analysis,
        report_id=report_id,
        minimum_score_applied=minimum_score_applied,
        trial_stage=trial_stage,
    )


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

        md_result = json.loads(_report_builder.build_report_markdown(
            dimension_results=dimension_results,
            weighted_total=weighted_total,
            grade=grade,
            cross_check=cross_check,
            anomaly_deduction=anomaly_deduction,
            innovation_bonus=innovation_bonus,
            anomaly_details=anomaly_details,
            innovation_details=innovation_details,
            anomaly_mcp_results=anomaly_mcp_results,
            timeline_result=timeline_result,
            evasive_result=evasive_result,
            evidence_result=evidence_result,
            document_meta=document_meta,
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

        html_body = _report_builder.md_to_rich_html(md_content)
        html_page = _report_builder.build_html_page(html_body, report_id)

        return json.dumps({
            "success": True,
            "report_html": html_page,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("generate_html_report: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"HTML报告生成异常：{e}")



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
    try:
        from .anomaly_bridge import query_anomaly_mcp as _query
        if dimensions is None:
            dimensions = ANOMALY_MCP_CONFIG["supported_dimensions"]
        result = _query(
            document_text=document_text,
            dimensions=dimensions,
            anomaly_mcp_available=ANOMALY_MCP_CONFIG["available"],
            anomaly_mcp_auto_detected=ANOMALY_MCP_CONFIG.get("auto_detected", False),
            server_name=ANOMALY_MCP_CONFIG["server_name"],
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("query_anomaly_mcp: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"异常MCP查询异常：{e}", retryable=True)


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
    try:
        from .anomaly_bridge import submit_anomaly_response as _submit
        result = _submit(dimension=dimension, llm_response=llm_response, dimension_index=dimension_index)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("submit_anomaly_response: %s", e, exc_info=True)
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
    try:
        from .anomaly_bridge import finalize_anomaly_detection as _finalize
        result = _finalize()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("finalize_anomaly_detection: %s", e, exc_info=True)
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
    try:
        from .anomaly_bridge import check_anomaly_mcp_status as _check
        result = _check(
            auto_detected=ANOMALY_MCP_CONFIG.get("auto_detected", False),
            server_name=ANOMALY_MCP_CONFIG["server_name"],
            supported_dimensions=ANOMALY_MCP_CONFIG["supported_dimensions"],
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("check_anomaly_mcp_status: %s", e, exc_info=True)
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
    try:
        from .rule_engine import detect_evasive_patterns as _detect
        detections = _detect(document_text)

        high_count = sum(1 for d in detections if d["severity"] == "high")
        medium_count = sum(1 for d in detections if d["severity"] == "medium")
        low_count = sum(1 for d in detections if d["severity"] == "low")

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

        return json.dumps({
            "success": True,
            "detected_patterns": detections,
            "risk_level": risk_level,
            "recommendation": recommendation,
            "summary": {
                "total_patterns": len(detections),
                "high_severity": high_count,
                "medium_severity": medium_count,
                "low_severity": low_count,
            },
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("detect_evasive_patterns: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"规避模式检测异常：{e}", retryable=True)


# Re-export from law_reference module for backward compatibility
_LAW_DATABASE = _law_ref.LAW_DATABASE
_LEGAL_PRINCIPLES = _law_ref.LEGAL_PRINCIPLES
_supplementary_docs = _law_ref._supplementary_docs


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
    return _law_ref.query_law_database(law_names=law_names, case_context=case_context, check_conflicts=check_conflicts)


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
    return _law_ref.query_case_precedent(case_type=case_type, key_facts=key_facts, court_level=court_level)


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
    return _law_ref.submit_supplementary_doc(case_id=case_id, doc_type=doc_type,
                                              doc_content=doc_content, doc_title=doc_title,
                                              authority_level=authority_level)


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
    return _law_ref.analyze_legal_difficulty(case_context=case_context, legal_issues=legal_issues,
                                              allow_innovation=allow_innovation)


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
            state = _pipeline_mgr.start(session_id, list(QUALITY_WEIGHTS.keys()))
        else:
            state = _pipeline_mgr.get(session_id)
            if state is None:
                return _make_error(
                    ErrorCode.INVALID_INPUT,
                    f"会话不存在或已过期：{session_id}，请先使用 action='start' 创建会话",
                )

        if action == "complete":
            if not dimension_name:
                return _make_error(ErrorCode.INVALID_INPUT, "action='complete' 需要 dimension_name")
            state = _pipeline_mgr.complete(session_id, dimension_name, result_summary)
            if state is None:
                return _make_error(ErrorCode.INVALID_INPUT, f"会话已过期：{session_id}")

        elif action == "reset":
            state = _pipeline_mgr.reset(session_id)
            if state is None:
                return _make_error(ErrorCode.INVALID_INPUT, f"会话不存在：{session_id}")

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


@mcp.tool()
def compact_materials(text: str) -> str:
    """压缩文书文本中的冗余空白，减少Token消耗。

    去除多余空行、行尾空格、连续空格等，保留全部语义内容。
    建议在将文书文本发送给LLM之前调用此工具。

    text: 原始文书文本

    返回 JSON 字符串，包含 compacted_text 和 saved_chars 字段。
    """
    try:
        from .material_preprocessor import compact_materials as _compact
        original_len = len(text)
        result = _compact(text)
        saved = original_len - len(result)
        return json.dumps({
            "success": True,
            "compacted_text": result,
            "original_chars": original_len,
            "compacted_chars": len(result),
            "saved_chars": saved,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("compact_materials: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"文本压缩异常：{e}")


@mcp.tool()
def redact_pii(
    text: str,
    skip_patterns: list[str] | None = None,
) -> str:
    """脱敏文书中的个人身份信息（PII），保护隐私。

    自动检测并替换身份证号、手机号、银行卡号、邮箱、当事人姓名、地址等敏感信息。
    建议在将文书文本发送给外部LLM之前调用此工具。

    text: 原始文书文本
    skip_patterns: 要跳过的PII类型列表（可选），可选值：
        id_card, mobile, bank_card, email, name_plaintiff, name_defendant, address

    返回 JSON 字符串，包含 redacted_text 和 redaction_count 字段。
    """
    try:
        from .material_preprocessor import redact_pii as _redact
        result = _redact(text, enabled=True, skip_patterns=skip_patterns)
        return json.dumps({
            "success": True,
            "redacted_text": result,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("redact_pii: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"PII脱敏异常：{e}")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
