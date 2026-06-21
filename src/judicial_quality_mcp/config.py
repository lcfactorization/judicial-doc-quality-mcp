"""Configuration management for judicial-doc-quality-mcp v0.2.0"""

import importlib
import logging
import os
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
]

QUALITY_WEIGHTS = {
    "formal_specification": 0.03,
    "clear_facts": 0.12,
    "sufficient_evidence": 0.12,
    "correct_law_application": 0.18,
    "thorough_reasoning": 0.22,
    "substantive_resolution": 0.25,
    "concise_language": 0.08,
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
}

DIMENSION_ORDER = {
    "formal_specification": 1,
    "clear_facts": 2,
    "sufficient_evidence": 3,
    "correct_law_application": 4,
    "thorough_reasoning": 5,
    "substantive_resolution": 6,
    "concise_language": 7,
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
]

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
ANCHORS_DIR = Path(__file__).resolve().parent.parent.parent / "anchors"

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
