"""Material preprocessing v0.2.0 — compact + PII redaction for document text.

Provides two preprocessing functions before sending document text to LLM:
1. compact_materials: Strip excessive whitespace, normalize formatting
2. redact_pii: Replace personally identifiable information with placeholders

Bridge Architecture: NO LLM calls. Pure regex-based preprocessing.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── PII patterns ──────────────────────────────────────────────

_PII_PATTERNS: list[tuple[str, str, str]] = [
    # (name, regex, replacement)
    # Chinese ID card (18 digits, last char may be X)
    ("id_card", r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b", "[身份证号]"),
    # Chinese mobile phone
    ("mobile", r"\b1[3-9]\d{9}\b", "[手机号]"),
    # Bank card number (16-19 digits)
    ("bank_card", r"\b[3-6]\d{15,18}\b", "[银行卡号]"),
    # Email
    ("email", r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[邮箱]"),
    # Chinese name pattern: 2-4 CJK chars preceded by common name prefixes
    # This is conservative — only matches when preceded by explicit labels
    ("name_plaintiff", r"(?:原告|上诉人|申请人|起诉人)\s*[:：]?\s*[\u4e00-\u9fff]{2,4}", "[当事人姓名]"),
    ("name_defendant", r"(?:被告|被上诉人|被申请人|被起诉人)\s*[:：]?\s*[\u4e00-\u9fff]{2,4}", "[当事人姓名]"),
    # Chinese address (conservative: only when labeled)
    ("address", r"(?:住址|住所地|住所|地址|居住地)\s*[:：]?\s*[\u4e00-\u9fff\d]+(?:省|市|区|县|路|街|号|室|栋|单元)[\u4e00-\u9fff\d\-]*", "[地址]"),
]

# ── Compact patterns ──────────────────────────────────────────

_COMPACT_RULES = [
    # Multiple blank lines → single blank line
    (r"\n{3,}", "\n\n"),
    # Multiple spaces → single space (except leading whitespace)
    (r"(?<=\S) {2,}", " "),
    # Trailing whitespace on lines
    (r" +\n", "\n"),
    # Tab → space
    (r"\t", "  "),
]


def compact_materials(text: str) -> str:
    """Strip excessive whitespace and normalize formatting.

    Reduces token count by removing redundant whitespace while
    preserving all semantic content.

    Args:
        text: Raw document text.

    Returns:
        Compacted text with normalized whitespace.
    """
    if not text:
        return text

    result = text
    for pattern, replacement in _COMPACT_RULES:
        result = re.sub(pattern, replacement, result)

    # Remove leading/trailing blank lines
    result = result.strip()

    saved = len(text) - len(result)
    if saved > 0:
        logger.debug("compact_materials: saved %d chars (%.1f%%)", saved, saved / len(text) * 100)

    return result


def redact_pii(
    text: str,
    *,
    enabled: bool = True,
    skip_patterns: list[str] | None = None,
) -> str:
    """Replace personally identifiable information with placeholders.

    Args:
        text: Raw document text.
        enabled: Whether PII redaction is enabled (default True).
        skip_patterns: List of PII pattern names to skip (e.g., ["name_plaintiff"]).

    Returns:
        Text with PII replaced by descriptive placeholders.
    """
    if not text or not enabled:
        return text

    skip = set(skip_patterns or [])
    result = text
    redaction_count = 0

    for name, pattern, replacement in _PII_PATTERNS:
        if name in skip:
            continue
        matches = re.findall(pattern, result)
        if matches:
            result = re.sub(pattern, replacement, result)
            redaction_count += len(matches)

    if redaction_count > 0:
        logger.info("redact_pii: %d PII items redacted", redaction_count)

    return result


def preprocess_document(
    text: str,
    *,
    compact: bool = True,
    redact: bool = True,
    skip_pii_patterns: list[str] | None = None,
) -> str:
    """Combined preprocessing: compact + redact.

    Args:
        text: Raw document text.
        compact: Whether to compact whitespace (default True).
        redact: Whether to redact PII (default True).
        skip_pii_patterns: PII pattern names to skip.

    Returns:
        Preprocessed text.
    """
    result = text
    if compact:
        result = compact_materials(result)
    if redact:
        result = redact_pii(result, enabled=True, skip_patterns=skip_pii_patterns)
    return result
