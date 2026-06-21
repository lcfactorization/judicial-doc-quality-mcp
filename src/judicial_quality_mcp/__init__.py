"""judicial-doc-quality-mcp v0.2.0 — Bridge Architecture for Judicial Document Quality Assessment."""

__version__ = "0.2.0"

from .config import (
    ANOMALY_DEDUCTION,
    ANOMALY_TOTAL_MAX_DEDUCTION,
    CROSS_CHECK_RULES,
    DIMENSION_ORDER,
    DIMENSION_TITLES,
    INNOVATION_BONUS,
    INNOVATION_TOTAL_MAX_BONUS,
    QUALITY_DIMENSIONS,
    QUALITY_GRADES,
    QUALITY_WEIGHTS,
    AppConfig,
    ErrorCode,
    StructuredError,
)
from .models import (
    BonusItem,
    CrossCheckConflict,
    CrossCheckResult,
    DeductionItem,
    DimensionScore,
    ParsedScoreResult,
    QualityAssessmentResult,
    SectionExtractionResult,
)
from .response_parser import ResponseParser
from .skill_runner import SkillLoader, TemplateRenderer, build_system_prompt
from .token_estimator import estimate_tokens, estimate_token_budget as _estimate_token_budget
from .section_extractor import extract_document_sections as _extract_document_sections
from .rule_engine import run_rule_engine, detect_evasive_patterns as _detect_evasive_patterns
from .prompt_builder import infer_trial_stage, build_system_prompt as build_quality_prompt
from .anomaly_bridge import query_anomaly_mcp as _query_anomaly_mcp_bridge
from .report_builder import build_report_markdown, md_to_rich_html, build_html_page
from .server import mcp, main

__all__ = [
    "ANOMALY_DEDUCTION",
    "ANOMALY_TOTAL_MAX_DEDUCTION",
    "AppConfig",
    "BonusItem",
    "CROSS_CHECK_RULES",
    "CrossCheckConflict",
    "CrossCheckResult",
    "DeductionItem",
    "DIMENSION_ORDER",
    "DIMENSION_TITLES",
    "DimensionScore",
    "ErrorCode",
    "INNOVATION_BONUS",
    "INNOVATION_TOTAL_MAX_BONUS",
    "ParsedScoreResult",
    "QUALITY_DIMENSIONS",
    "QUALITY_GRADES",
    "QUALITY_WEIGHTS",
    "QualityAssessmentResult",
    "ResponseParser",
    "SectionExtractionResult",
    "SkillLoader",
    "StructuredError",
    "TemplateRenderer",
    "build_html_page",
    "build_quality_prompt",
    "build_report_markdown",
    "build_system_prompt",
    "estimate_tokens",
    "infer_trial_stage",
    "main",
    "md_to_rich_html",
    "mcp",
    "run_rule_engine",
]
