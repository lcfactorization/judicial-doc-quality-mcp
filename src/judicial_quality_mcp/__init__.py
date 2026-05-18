"""judicial-doc-quality-mcp v0.1.0 — Bridge Architecture for Judicial Document Quality Assessment."""

__version__ = "0.1.0"

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
    "build_system_prompt",
    "main",
    "mcp",
]
