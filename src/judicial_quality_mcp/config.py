"""Configuration management for judicial-doc-quality-mcp v0.4.0"""

import importlib
import logging
import os
import re
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

logger = logging.getLogger("judicial-quality")


def _detect_anomaly_mcp() -> bool:
    """Auto-detect whether judicial-doc-anomaly-mcp is installed and importable."""
    try:
        mod = importlib.import_module("judicial_lint_mcp")
        has_server = hasattr(mod, "server") or importlib.util.find_spec("judicial_lint_mcp.server") is not None
        if has_server:
            logger.info("_detect_anomaly_mcp: judicial-lint-mcp detected and importable")
            return True
        logger.info("_detect_anomaly_mcp: judicial-lint-mcp found but server module missing")
        return False
    except ImportError:
        logger.info("_detect_anomaly_mcp: judicial-lint-mcp not installed")
        return False
    except Exception as e:
        logger.warning("_detect_anomaly_mcp: detection error: %s", e)
        return False


ANOMALY_MCP_AUTO_DETECTED = _detect_anomaly_mcp()

QUALITY_DIMENSIONS = [
    "formal_specification",
    "clear_facts",
    "sufficient_evidence",
    "correct_law_application",
    "thorough_reasoning",
    "substantive_resolution",
    "concise_language",
    "claim_support",
]

QUALITY_WEIGHTS = {
    "formal_specification": 0.03,
    "clear_facts": 0.10,
    "sufficient_evidence": 0.10,
    "correct_law_application": 0.15,
    "thorough_reasoning": 0.20,
    "substantive_resolution": 0.22,
    "concise_language": 0.05,
    "claim_support": 0.15,
}

QUALITY_FULL_SCORES = {dim: 100 for dim in QUALITY_DIMENSIONS}

QUALITY_GRADES = {
    "A": (95, 100, "优秀"),
    "A-": (90, 94, "优良"),
    "B+": (85, 89, "良好"),
    "B": (80, 84, "中上"),
    "C+": (75, 79, "中等"),
    "C": (70, 74, "中下"),
    "D": (60, 69, "及格"),
    "F": (0, 59, "不及格"),
}

DIMENSION_TITLES = {
    "formal_specification": "形式规范",
    "clear_facts": "事实清楚",
    "sufficient_evidence": "证据确实充分",
    "correct_law_application": "法律适用正确",
    "thorough_reasoning": "说理充分透彻",
    "substantive_resolution": "实质解纷效果",
    "concise_language": "语言精练流畅",
    "claim_support": "当事人预期与诉请支持度",
}

DIMENSION_ORDER = {
    "formal_specification": 1,
    "clear_facts": 2,
    "sufficient_evidence": 3,
    "correct_law_application": 4,
    "thorough_reasoning": 5,
    "substantive_resolution": 6,
    "concise_language": 7,
    "claim_support": 8,
}

ANOMALY_DEDUCTION = {
    "procedural_anomaly": {
        "label": "程序异常",
        "per_item_deduction": 5,
        "max_deduction": 25,
        "severity_map": {"low": 3, "medium": 5, "high": 10},
    },
    "evidence_anomaly": {
        "label": "证据异常",
        "per_item_deduction": 6,
        "max_deduction": 30,
        "severity_map": {"low": 4, "medium": 6, "high": 12},
    },
    "fact_anomaly": {
        "label": "事实认定异常",
        "per_item_deduction": 7,
        "max_deduction": 35,
        "severity_map": {"low": 5, "medium": 7, "high": 15},
    },
    "law_application_anomaly": {
        "label": "法律适用异常",
        "per_item_deduction": 8,
        "max_deduction": 40,
        "severity_map": {"low": 5, "medium": 8, "high": 18},
    },
    "reasoning_anomaly": {
        "label": "说理异常",
        "per_item_deduction": 6,
        "max_deduction": 30,
        "severity_map": {"low": 4, "medium": 6, "high": 12},
    },
    "logic_anomaly": {
        "label": "逻辑异常",
        "per_item_deduction": 7,
        "max_deduction": 35,
        "severity_map": {"low": 5, "medium": 7, "high": 15},
    },
}

ANOMALY_TOTAL_MAX_DEDUCTION = 50

BATCH_CONFIG = {
    "max_documents": 50,
    "concurrent_limit": 5,
    "timeout_seconds": 300,
}

REPORT_CONFIG = {
    "template_dir": "templates",
    "output_formats": ["markdown", "json", "html"],
    "max_report_size_mb": 10,
}

COMPARISON_CONFIG = {
    "similarity_threshold": 0.85,
    "max_comparisons": 10,
}

ANOMALY_MCP_CONFIG = {
    "server_name": "judicial-lint",
    "available": ANOMALY_MCP_AUTO_DETECTED,
    "auto_detected": ANOMALY_MCP_AUTO_DETECTED,
    "fallback_mode": "blank",
    "recommended_install": "https://github.com/lcfactorization/judicial-doc-anomaly-mcp",
    "pip_install": "pip install judicial-lint-mcp",
    "supported_dimensions": [
        "procedure", "evidence", "fact_finding", "focus_drift",
        "law_application", "discretion", "rhetoric_trick", "logic",
        "temporal", "trial_process", "external_interference", "execution",
        "negative_space", "semantic_drift", "case_deviation", "coupling",
    ],
    "dimension_mapping": {
        "procedural_anomaly": "procedure",
        "evidence_anomaly": "evidence",
        "fact_anomaly": "fact_finding",
        "law_application_anomaly": "law_application",
        "reasoning_anomaly": "logic",
        "logic_anomaly": "logic",
    },
}

RULE_ENGINE_PATTERNS = {
    "missing_court_name": {
        "pattern": r"人民法院|仲裁委员会",
        "section": "header",
        "severity": "high",
        "message": "首部缺少法院名称",
    },
    "missing_case_number": {
        "pattern": r"[（(]\d{4}[）)]\w+\d+号",
        "section": "header",
        "severity": "high",
        "message": "首部缺少案号或案号格式错误",
    },
    "missing_judgment_main": {
        "pattern": r"判决如下|裁定如下|决定如下",
        "section": "footer",
        "severity": "high",
        "message": "缺少判决主文",
    },
    "missing_reasoning": {
        "pattern": r"本院认为",
        "section": "body",
        "severity": "high",
        "message": "缺少'本院认为'说理部分",
    },
    "missing_law_basis": {
        "pattern": r"依照|根据.*规定",
        "section": "body",
        "severity": "medium",
        "message": "缺少法律依据引用",
    },
    "missing_evidence_section": {
        "pattern": r"上述事实|证据如下|有下列证据",
        "section": "body",
        "severity": "medium",
        "message": "缺少证据分析部分",
    },
}

EVASIVE_PATTERNS = {
    "vague_subject": {
        "pattern": r"相关(?:单位|人员|部门|机构)|(?:上述|该|此)(?:单位|人员|公司)",
        "severity": "medium",
        "message": "主体模糊：使用'相关单位/人员'等模糊表述代替具体主体名称",
    },
    "evasive_timing": {
        "pattern": r"(?:此后|随后|之后|不久|事后|期间)(?:[，。,；;]|\s)",
        "severity": "low",
        "message": "时间模糊：使用'此后/随后'等模糊时间表述，缺少具体日期",
    },
    "selective_citation": {
        "pattern": r"(?:仅|只|单)[据依]?(?:原告|被告|申请人|被申请人)",
        "severity": "high",
        "message": "选择性引用：仅依据单方证据或陈述",
    },
    "template_language": {
        "pattern": r"本院认为[，,].*?(?:并无不当|于法有据|予以支持|不予支持)",
        "severity": "medium",
        "message": "模板化说理：使用'并无不当/于法有据'等套话，缺乏具体论证",
    },
    "missing_response": {
        "pattern": r"(?:原告|被告|申请人|被申请人).{0,5}(?:主张|请求|抗辩|辩称).{0,30}(?:不予|无需|没有必要)(?:回应|评述|审查)",
        "severity": "high",
        "message": "回避回应：明确表示不予回应当事人主张",
    },
}

INNOVATION_BONUS = {
    "mediation_success": {
        "label": "调解成功/促成和解",
        "bonus_range": (5, 10),
        "description": "法官通过调解或促成当事人和解，实质性化解矛盾，实现案结事了",
    },
    "legal_gap_filling": {
        "label": "法律漏洞填补",
        "bonus_range": (8, 12),
        "description": "在法律未有明确规定时，通过法律解释方法填补漏洞，创造性解决法律适用疑难问题",
    },
    "framework_breakthrough": {
        "label": "创造性突破既有框架/打破陈规",
        "bonus_range": (10, 15),
        "description": "打破既有裁判惯例或陈旧框架，在法律允许范围内作出创新性裁判，推动司法进步",
    },
    "judicial_logic": {
        "label": "体现司法底层逻辑",
        "bonus_range": (5, 8),
        "description": "裁判深刻体现了司法的底层逻辑——公平正义、权利保障、权力制约，而非机械适用法条",
    },
    "complex_dispute_resolution": {
        "label": "复杂纠纷一揽子解决",
        "bonus_range": (5, 10),
        "description": "对涉及多重法律关系的复杂纠纷，通过一个裁判一揽子解决，避免程序空转",
    },
}

INNOVATION_TOTAL_MAX_BONUS = 30


class ErrorCode(str, Enum):
    SKILL_NOT_FOUND = "SKILL_404"
    TOKEN_OVERFLOW = "TOKEN_500"
    PARSE_FAILED = "PARSE_400"
    SCORE_OUT_OF_BOUNDS = "SCORE_400"
    INVALID_INPUT = "INPUT_400"
    INTERNAL_ERROR = "INTERNAL_500"
    ANCHOR_NOT_FOUND = "ANCHOR_404"
    DIMENSION_NOT_FOUND = "DIM_404"


class StructuredError(BaseModel):
    code: str = Field(description="Error code from ErrorCode enum")
    message: str = Field(description="Human-readable error message")
    details: dict = Field(default_factory=dict, description="Additional context")
    retryable: bool = Field(default=False, description="Whether the caller should retry")


CROSS_CHECK_RULES = [
    {
        "id": "R1",
        "name": "说理高但法律适用低",
        "check": lambda s: s.get("thorough_reasoning", 0) >= 80 and s.get("correct_law_application", 0) < 60,
        "message": "说理得分高(≥80)但法律适用得分低(<60)，逻辑矛盾：说理充分却法律适用错误，建议重评法律适用或降低说理分。",
        "conflict_dims": ["thorough_reasoning", "correct_law_application"],
    },
    {
        "id": "R2",
        "name": "证据高但事实低",
        "check": lambda s: s.get("sufficient_evidence", 0) >= 80 and s.get("clear_facts", 0) < 60,
        "message": "证据得分高(≥80)但事实得分低(<60)，逻辑矛盾：证据充分却事实不清，建议重评事实认定。",
        "conflict_dims": ["sufficient_evidence", "clear_facts"],
    },
    {
        "id": "R3",
        "name": "说理高但事实或证据很低",
        "check": lambda s: s.get("thorough_reasoning", 0) >= 80 and (s.get("clear_facts", 0) < 60 or s.get("sufficient_evidence", 0) < 60),
        "message": "说理得分高(≥80)但事实或证据根基薄弱(<60)，逻辑矛盾：无事实基础的说理是空中楼阁，建议重评相关维度。",
        "conflict_dims": ["thorough_reasoning", "clear_facts", "sufficient_evidence"],
    },
    {
        "id": "R4",
        "name": "语言满分但形式低",
        "check": lambda s: s.get("concise_language", 0) >= 95 and s.get("formal_specification", 0) < 70,
        "message": "语言得分极高(≥95)但形式规范得分低(<70)，矛盾：语言精练却格式不规范，建议重评形式规范。",
        "conflict_dims": ["concise_language", "formal_specification"],
    },
    {
        "id": "R5",
        "name": "事实与证据分差过大",
        "check": lambda s: abs(s.get("clear_facts", 0) - s.get("sufficient_evidence", 0)) >= 25,
        "message": "事实与证据得分差距过大(≥25分)，建议复核两者评分依据。",
        "conflict_dims": ["clear_facts", "sufficient_evidence"],
    },
    {
        "id": "R6",
        "name": "实质解纷高但说理低",
        "check": lambda s: s.get("substantive_resolution", 0) >= 80 and s.get("thorough_reasoning", 0) < 60,
        "message": "实质解纷得分高(≥80)但说理得分低(<60)，逻辑矛盾：解纷效果好却说理不充分，可能存在'结果正确但论证不足'的情况，建议复核。",
        "conflict_dims": ["substantive_resolution", "thorough_reasoning"],
    },
    {
        "id": "R7",
        "name": "法律适用满分但说理极低",
        "check": lambda s: s.get("correct_law_application", 0) >= 90 and s.get("thorough_reasoning", 0) < 50,
        "message": "法律适用得分极高(≥90)但说理得分极低(<50)，矛盾：法条引用正确却完全未说理，建议重评说理维度。",
        "conflict_dims": ["correct_law_application", "thorough_reasoning"],
    },
    {
        "id": "R8",
        "name": "所有实质维度均低但形式高",
        "check": lambda s: (
            s.get("formal_specification", 0) >= 80
            and s.get("clear_facts", 0) < 60
            and s.get("sufficient_evidence", 0) < 60
            and s.get("thorough_reasoning", 0) < 60
        ),
        "message": "形式规范得分高(≥80)但事实、证据、说理均低(<60)，典型'金玉其外败絮其中'，建议重点关注实质维度。",
        "conflict_dims": ["formal_specification", "clear_facts", "sufficient_evidence", "thorough_reasoning"],
    },
    {
        "id": "R9",
        "name": "实质解纷极低但法律适用不低",
        "check": lambda s: s.get("substantive_resolution", 0) < 40 and s.get("correct_law_application", 0) >= 70,
        "message": "实质解纷得分极低(<40)但法律适用得分不低(≥70)，矛盾：法律适用正确却未能实质解纷，可能存在'法律适用正确但裁判方式不当'的情况，建议复核。",
        "conflict_dims": ["substantive_resolution", "correct_law_application"],
    },
    {
        "id": "R10",
        "name": "创新性加分与低分矛盾",
        "check": lambda s: s.get("substantive_resolution", 0) >= 85 and s.get("thorough_reasoning", 0) >= 80 and s.get("correct_law_application", 0) < 60,
        "message": "实质解纷和说理均高但法律适用低，若存在创新性加分，需核实法律适用创新是否真正成立，建议仲裁重评。",
        "conflict_dims": ["substantive_resolution", "thorough_reasoning", "correct_law_application"],
    },
    {
        # R11 依赖 claim_support 维度解析结果中的 expectation_gap.overall_ratio。
        # 调用方应将 overall_ratio 以键 "claim_support_overall_ratio" 传入
        # cross_check_consistency（浮点，0-1）；缺省 1.0 表示无数据、不触发。
        "id": "R11",
        "name": "诉请支持率极低且说理不足",
        "check": lambda s: (
            float(s.get("claim_support_overall_ratio", 1.0)) < 0.3
            and s.get("thorough_reasoning", 0) < 70
        ),
        "message": "诉请总体支持率极低(<30%)且说理得分不足(<70)，当事人预期与裁判结果落差大：建议强化说理/判后答疑，降低上诉申诉风险。",
        "conflict_dims": ["claim_support", "thorough_reasoning"],
    },
    {
        # R12 依赖 claim_support 维度解析结果中的扣分编号（CS-B02/CS-B03）与审级。
        # 调用方应将命中编号（如 "CS-B02,CS-B03"）以键 "claim_support_hit_codes" 传入，
        # 并将审级以键 "trial_stage" 传入；缺省不触发。
        "id": "R12",
        "name": "二审遗漏诉讼请求程序风险",
        "check": lambda s: (
            s.get("trial_stage", "") == "二审"
            and any(code in str(s.get("claim_support_hit_codes", "")) for code in ("CS-B02", "CS-B03"))
        ),
        "message": "遗漏诉讼请求程序风险提示（参照民事诉讼法及司法解释对遗漏诉请二审处理的规定）：二审对诉请零回应或对变更/增加诉请未审理且无程序处理，存在漏审程序违法风险，建议核查是否应当发回重审或一并审理。",
        "conflict_dims": ["claim_support"],
    },
]

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
ANCHORS_DIR = Path(__file__).resolve().parent.parent.parent / "anchors"

# ── 红旗预警与一票否决机制（v0.4.0）─────────────────────────────
# 设计原则：加权综合分会稀释致命信号（如遗漏诉请该发回重审的判决可能拿 B+）。
# LLM 只提名（red_flag_candidates），规则层按下列确定性规则裁决封顶：
#   Veto 级（一票否决）：final = min(加权分, 59)，等级强制 F + 红旗标注
#   Warning 级（预警）：  final = min(加权分, 74)，C+ 预警标注
# 红旗封顶优先于 MINIMUM_SCORE 托底（托底是防过低、红旗是强制足够低，红旗赢）。

RED_FLAG_VETO_CAP = 59
RED_FLAG_WARNING_CAP = 74

DOCUMENT_TYPE_JUDGMENT = "judgment"
DOCUMENT_TYPE_ADMINISTRATIVE = "administrative_decision"

# 行政决定书标题关键词（document_type 自动检测兜底）
ADMIN_DOC_TITLE_PATTERN = r"行政处理决定书|行政处罚决定书|责令改正|复议决定"
JUDGMENT_DOC_TITLE_PATTERN = r"判决书|裁定书"


def _rf_cs_counts(claim_support: dict) -> dict:
    """从 claim_support 解析结果的 deduction_items 中统计 CS-Bxx 命中次数（每个扣分项同一编号只计1次）。"""
    counts: dict = {}
    for it in (claim_support or {}).get("deduction_items") or []:
        if not isinstance(it, dict):
            continue
        text = " ".join(str(it.get(k, "")) for k in ("item", "basis", "reason", "quote"))
        for code in set(re.findall(r"CS-B\d{2}", text)):
            counts[code] = counts.get(code, 0) + 1
    return counts


def _rf_cs_claims(claim_support: dict, code: str) -> list:
    """提取某 CS-Bxx 扣分项关联的诉请编号（claim_ref 字段或 item 文本中的 CS-\d+）。"""
    claim_ids: list = []
    for it in (claim_support or {}).get("deduction_items") or []:
        if not isinstance(it, dict):
            continue
        text = " ".join(str(it.get(k, "")) for k in ("item", "basis", "reason", "quote"))
        if code not in text:
            continue
        explicit = it.get("claim_ref") or it.get("claim_id")
        if explicit:
            claim_ids.append(str(explicit))
        claim_ids.extend(re.findall(r"CS-\d+", text))
    seen, unique = set(), []
    for cid in claim_ids:
        if cid not in seen:
            seen.add(cid)
            unique.append(cid)
    return unique


def _rf_cs_evidence(claim_support: dict, code: str) -> str:
    """提取某 CS-Bxx 扣分项的证据摘录（item 名称 + quote）。"""
    parts: list = []
    for it in (claim_support or {}).get("deduction_items") or []:
        if not isinstance(it, dict):
            continue
        text = " ".join(str(it.get(k, "")) for k in ("item", "basis", "reason", "quote"))
        if code in text:
            seg = str(it.get("item", "")).strip() or text[:60]
            quote = str(it.get("quote", "")).strip()
            parts.append(f"{seg}（{quote[:40]}…）" if quote else seg)
    return "；".join(parts[:3])


def _rf_findings(red_flag_inputs: dict) -> list:
    """归一化 red_flag_inputs 中的 critical 发现列表（容忍多种联动输入形态）。"""
    if not red_flag_inputs:
        return []
    findings: list = []
    if isinstance(red_flag_inputs, list):
        return [f for f in red_flag_inputs if isinstance(f, dict)]
    for key in ("findings", "critical_findings", "hallucination_findings",
                "anomaly_findings", "hallucination", "anomaly", "items"):
        val = red_flag_inputs.get(key)
        if isinstance(val, list):
            findings.extend(f for f in val if isinstance(f, dict))
    for key, val in red_flag_inputs.items():
        if re.match(r"^(H-\d+|A\d+)$", str(key)) and isinstance(val, dict):
            findings.append({"code": key, **val})
    return findings


def _rf_has_critical_code(red_flag_inputs: dict, code: str) -> bool:
    """是否存在指定编号（如 H-1/H-2/H-7/A9）的 critical 发现。"""
    for f in _rf_findings(red_flag_inputs):
        if str(f.get("severity", "")).lower() != "critical":
            continue
        fcode = str(f.get("code", f.get("a_code", "")))
        if fcode == code:
            return True
    return False


def _rf_has_procedural_critical(red_flag_inputs: dict) -> bool:
    """是否存在程序类 critical 异常（A9 或 type 含程序/procedur）。"""
    for f in _rf_findings(red_flag_inputs):
        if str(f.get("severity", "")).lower() != "critical":
            continue
        fcode = str(f.get("code", f.get("a_code", "")))
        ftype = str(f.get("type", ""))
        if fcode == "A9" or "procedur" in ftype.lower() or "程序" in ftype:
            return True
    return False


def _rf_overall_ratio(claim_support: dict):
    """读取 claim_support.expectation_gap.overall_ratio，缺数据返回 None。"""
    gap = (claim_support or {}).get("expectation_gap") or {}
    ratio = gap.get("overall_ratio")
    try:
        return float(ratio) if ratio is not None else None
    except (ValueError, TypeError):
        return None


def _rf_discretion_hit(claim_support: dict, keywords: list) -> bool:
    """裁量点 issue 含指定职权类关键词且 grade 不合格（不充分）。"""
    for dp in (claim_support or {}).get("discretion_points") or []:
        if not isinstance(dp, dict):
            continue
        issue = str(dp.get("issue", ""))
        grade = str(dp.get("grade", ""))
        if any(kw in issue for kw in keywords) and grade == "不充分":
            return True
    return False


def _rf_high_gap_claims(claim_support: dict) -> list:
    gap = (claim_support or {}).get("expectation_gap") or {}
    return [str(c) for c in (gap.get("high_gap_claims") or [])]


def _rf_score_below(scores: dict, dim: str, threshold: float) -> bool:
    try:
        return float(scores.get(dim, 100)) < threshold
    except (ValueError, TypeError):
        return False


RED_FLAG_RULES = [
    # ── Veto 级（任一触发 → final=min(加权分,59)，等级强制F+红旗标注）──
    {
        "id": "RF-V1",
        "level": "veto",
        "name": "变更/增加诉讼请求未审理且无程序处理",
        "cs_code": "CS-B03",
        "check": lambda ctx: _rf_cs_counts(ctx.get("claim_support")).get("CS-B03", 0) >= 1,
        "consequence": "存在二审撤销原判发回重审的强信号（《民事诉讼法》第一百七十七条第一款第四项及遗漏诉讼请求的司法解释口径）",
        "legal_refs": ["《民事诉讼法》第一百七十七条第一款第四项"],
    },
    {
        "id": "RF-V2",
        "level": "veto",
        "name": "诉讼请求零回应≥2项或程序类critical异常",
        "cs_code": "CS-B02",
        "check": lambda ctx: (
            _rf_cs_counts(ctx.get("claim_support")).get("CS-B02", 0) >= 2
            or _rf_has_procedural_critical(ctx.get("red_flag_inputs"))
        ),
        "consequence": "存在二审撤销原判发回重审的强信号（《民事诉讼法》第一百七十七条第一款第四项及遗漏诉讼请求的司法解释口径）",
        "legal_refs": ["《民事诉讼法》第一百七十七条第一款第四项"],
    },
    {
        "id": "RF-V3",
        "level": "veto",
        "name": "无源编造（引用不实法条/案号）",
        "check": lambda ctx: _rf_has_critical_code(ctx.get("red_flag_inputs"), "H-1"),
        "consequence": "存在引用不实法条/案号的强信号，属再审监督/依职权纠正情形",
        "legal_refs": [],
    },
    {
        "id": "RF-V4",
        "level": "veto",
        "name": "裁判结果无支撑",
        "check": lambda ctx: _rf_has_critical_code(ctx.get("red_flag_inputs"), "H-7"),
        "consequence": "存在裁判结果缺乏依据支撑的强信号，上诉/再审改判风险高",
        "legal_refs": [],
    },
    # ── Warning 级（任一触发 → final=min(加权分,74)，C+预警标注）──
    {
        "id": "RF-W1",
        "level": "warning",
        "name": "核心诉请结论式驳斥",
        "cs_code": "CS-B05",
        "check": lambda ctx: (
            _rf_cs_counts(ctx.get("claim_support")).get("CS-B05", 0) >= 1
            and (
                bool(set(_rf_cs_claims(ctx.get("claim_support"), "CS-B05"))
                     & set(_rf_high_gap_claims(ctx.get("claim_support"))))
                # CS-B05 扣分项未标注诉请编号时，只要存在高落差诉请即触发（保守联动）
                or (not _rf_cs_claims(ctx.get("claim_support"), "CS-B05")
                    and bool(_rf_high_gap_claims(ctx.get("claim_support"))))
            )
        ),
        "consequence": "核心诉请结论式驳斥，上诉争点强化风险",
        "legal_refs": [],
    },
    {
        "id": "RF-W2",
        "level": "warning",
        "name": "预期落差大且说理不足",
        "check": lambda ctx: (
            (_rf_overall_ratio(ctx.get("claim_support")) is not None
             and _rf_overall_ratio(ctx.get("claim_support")) < 0.3
             and _rf_score_below(ctx.get("scores"), "thorough_reasoning", 70))
        ),
        "consequence": "预期落差大且说理不足，建议判后答疑与说理补强（与交叉校验R11衔接：R11为提示，RF-W2为封顶）",
        "legal_refs": [],
    },
    {
        "id": "RF-W3",
        "level": "warning",
        "name": "主文不明确/不可执行≥2项",
        "cs_code": "CS-B10",
        "check": lambda ctx: _rf_cs_counts(ctx.get("claim_support")).get("CS-B10", 0) >= 2,
        "consequence": "主文不明确/不可执行，执源治理风险（法发〔2024〕16号第十五条）",
        "legal_refs": ["《最高人民法院关于在审判工作中促进提质增效 推动实质性化解矛盾纠纷的指导意见》（法发〔2024〕16号）第十五条"],
    },
]

# 行政决定模式（document_type=administrative_decision）专用规则，法条已核验原文。
# 统一后果文案 + AV1-AV5 Veto 级（封顶59）、AV6 Warning 级（封顶74）。
_ADMIN_CONSEQUENCE = "存在被行政复议撤销/变更（《行政复议法》第六十三条、第六十四条）或行政诉讼撤销/变更（《行政诉讼法》第七十条、第七十七条）的强信号"

ADMIN_RED_FLAG_RULES = [
    {
        "id": "AV1",
        "level": "veto",
        "name": "主要证据不足",
        "check": lambda ctx: _rf_score_below(ctx.get("scores"), "sufficient_evidence", 60),
        "consequence": _ADMIN_CONSEQUENCE,
        "legal_refs": ["《行政诉讼法》第七十条第一项", "《行政复议法》（2023修订）第六十四条第一项"],
    },
    {
        "id": "AV2",
        "level": "veto",
        "name": "适用法律法规错误",
        "check": lambda ctx: (
            _rf_score_below(ctx.get("scores"), "correct_law_application", 60)
            or _rf_has_critical_code(ctx.get("red_flag_inputs"), "H-2")
        ),
        "consequence": _ADMIN_CONSEQUENCE,
        "legal_refs": ["《行政诉讼法》第七十条第二项", "《行政复议法》（2023修订）第六十四条第三项（适用的依据不合法）"],
    },
    {
        "id": "AV3",
        "level": "veto",
        "name": "违反法定程序",
        "check": lambda ctx: _rf_has_procedural_critical(ctx.get("red_flag_inputs")),
        "consequence": _ADMIN_CONSEQUENCE,
        "legal_refs": ["《行政诉讼法》第七十条第三项", "《行政复议法》（2023修订）第六十四条第二项"],
    },
    {
        "id": "AV4",
        "level": "veto",
        "name": "超越职权",
        "check": lambda ctx: _rf_discretion_hit(ctx.get("claim_support"), ["超越职权", "越权", "无权限"]),
        "consequence": _ADMIN_CONSEQUENCE,
        "legal_refs": ["《行政诉讼法》第七十条第四项", "《行政复议法》（2023修订）第六十四条第四项"],
    },
    {
        "id": "AV5",
        "level": "veto",
        "name": "滥用职权",
        "check": lambda ctx: _rf_discretion_hit(ctx.get("claim_support"), ["滥用职权"]),
        "consequence": _ADMIN_CONSEQUENCE,
        "legal_refs": ["《行政诉讼法》第七十条第五项", "《行政复议法》（2023修订）第六十四条第四项"],
    },
    {
        "id": "AV6",
        "level": "warning",
        "name": "明显不当/款额确定错误",
        "check": lambda ctx: (
            _rf_cs_counts(ctx.get("claim_support")).get("CS-B04", 0) >= 1
            or _rf_cs_counts(ctx.get("claim_support")).get("CS-B08", 0) >= 1
        ),
        "consequence": _ADMIN_CONSEQUENCE,
        "legal_refs": ["《行政诉讼法》第七十条第六项", "《行政诉讼法》第七十七条", "《行政复议法》（2023修订）第六十三条"],
    },
]

_CHARS_PER_TOKEN_ZH = 1.5
_CHARS_PER_TOKEN_EN = 4.0


class AppConfig(BaseModel):
    skills_dir: str = Field(default=str(SKILLS_DIR), description="Skills directory path")
    anchors_dir: str = Field(default=str(ANCHORS_DIR), description="Anchors directory path")
    weights: dict[str, float] = Field(default=QUALITY_WEIGHTS, description="Dimension weights")
    grades: dict[str, tuple] = Field(default=QUALITY_GRADES, description="Grade thresholds")
    verbose: bool = Field(default=False, description="Verbose logging")
    anomaly_max_deduction: int = Field(default=ANOMALY_TOTAL_MAX_DEDUCTION, description="Max total anomaly deduction")
    innovation_max_bonus: int = Field(default=INNOVATION_TOTAL_MAX_BONUS, description="Max total innovation bonus")
    anomaly_mcp_available: bool = Field(default=False, description="Whether judicial-doc-anomaly-mcp is available")
    rule_engine_enabled: bool = Field(default=True, description="Enable rule engine pre-screening")
    evasive_detection_enabled: bool = Field(default=True, description="Enable evasive pattern detection")

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()
        return cls(
            skills_dir=os.getenv("JQ_SKILLS_DIR", os.getenv("SKILLS_DIR", str(SKILLS_DIR))),
            anchors_dir=os.getenv("JQ_ANCHORS_DIR", os.getenv("ANCHORS_DIR", str(ANCHORS_DIR))),
            verbose=os.getenv("JQ_VERBOSE", os.getenv("VERBOSE", "false")).lower() == "true",
            anomaly_max_deduction=int(os.getenv("JQ_ANOMALY_MAX_DEDUCTION", os.getenv("ANOMALY_MAX_DEDUCTION", str(ANOMALY_TOTAL_MAX_DEDUCTION)))),
            innovation_max_bonus=int(os.getenv("JQ_INNOVATION_MAX_BONUS", os.getenv("INNOVATION_MAX_BONUS", str(INNOVATION_TOTAL_MAX_BONUS)))),
            anomaly_mcp_available=os.getenv("JQ_ANOMALY_MCP_AVAILABLE", os.getenv("ANOMALY_MCP_AVAILABLE", "false")).lower() == "true",
            rule_engine_enabled=os.getenv("JQ_RULE_ENGINE_ENABLED", os.getenv("RULE_ENGINE_ENABLED", "true")).lower() == "true",
            evasive_detection_enabled=os.getenv("JQ_EVASIVE_DETECTION_ENABLED", os.getenv("EVASIVE_DETECTION_ENABLED", "true")).lower() == "true",
        )
