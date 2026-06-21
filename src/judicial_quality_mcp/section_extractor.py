"""Document section extractor v0.2.0 — extract structured sections from judicial documents.

Unified implementation merging the two duplicate extract_sections implementations
that previously existed in server.py (one for rule_engine pre-screening, one for
pipeline stages). Now a single implementation serves both use cases via the
`purpose` parameter.

Bridge Architecture: NO LLM calls.
"""

import json
import logging
import re
from typing import Any

from .config import ErrorCode, StructuredError
from .prompt_builder import infer_trial_stage

logger = logging.getLogger(__name__)


def _make_error(code: ErrorCode, message: str, details: dict | None = None, retryable: bool = False) -> str:
    err = StructuredError(code=code.value, message=message, details=details or {}, retryable=retryable)
    return json.dumps({"success": False, "error": err.model_dump()}, ensure_ascii=False, indent=2)


def extract_document_sections(
    document_full_text: str,
    *,
    run_rule_engine: bool = True,
    rule_engine_fn: Any | None = None,
) -> dict:
    """Extract structured sections from a judicial document.

    This is the unified implementation that replaces the two duplicate
    extract_sections functions previously in server.py.

    Args:
        document_full_text: Full text of the judicial document.
        run_rule_engine: Whether to run rule engine pre-screening on the result.
        rule_engine_fn: Callable for rule engine (injected to avoid circular import).

    Returns:
        dict with keys: plaintiff_claim, defendant_defense, court_finding,
        evidence_analysis, reasoning, judgment_basis, judgment_main,
        case_info, extraction_confidence, trial_stage,
        and optionally rule_engine_flags.
    """
    sections: dict[str, Any] = {}

    # ── Plaintiff claim ────────────────────────────────────────
    plaintiff = re.search(
        r"(?:原告|公诉机关|申请人|起诉人).{0,10}(?:诉称|指控|称)[：:]\s*(.*?)(?=\n\n|被告.{0,10}辩称)",
        document_full_text, re.DOTALL,
    )
    sections["plaintiff_claim"] = plaintiff.group(1).strip() if plaintiff else ""

    # ── Defendant defense ──────────────────────────────────────
    defendant = re.search(
        r"(?:被告|被申请人).{0,10}辩称[：:]\s*(.*?)(?=\n\n|本院查明|经审理)",
        document_full_text, re.DOTALL,
    )
    sections["defendant_defense"] = defendant.group(1).strip() if defendant else ""

    # ── Court finding ──────────────────────────────────────────
    court_finding = re.search(
        r"(?:本院查明|经审理查明|经审理认定)[：:]\s*(.*?)(?=\n\n|上述事实|证据如下|本院认为)",
        document_full_text, re.DOTALL,
    )
    sections["court_finding"] = court_finding.group(1).strip() if court_finding else ""

    # ── Evidence analysis ──────────────────────────────────────
    evidence = re.search(
        r"(?:上述事实|证据如下|有下列证据)[，：:]\s*(.*?)(?=\n\n|本院认为|判决如下)",
        document_full_text, re.DOTALL,
    )
    sections["evidence_analysis"] = evidence.group(1).strip() if evidence else ""

    # ── Reasoning ──────────────────────────────────────────────
    reasoning = re.search(
        r"本院认为[，：:]\s*(.*?)(?=依照|判决如下|裁定如下)",
        document_full_text, re.DOTALL,
    )
    sections["reasoning"] = reasoning.group(1).strip() if reasoning else ""

    # ── Legal basis ────────────────────────────────────────────
    law_basis = re.search(
        r"依照[《][^》]+》[^。]*。[^。]*。(?:[^。]*。)*",
        document_full_text, re.DOTALL,
    )
    sections["judgment_basis"] = law_basis.group(0).strip() if law_basis else ""

    # ── Judgment main ──────────────────────────────────────────
    judgment_main = re.search(
        r"(?:判决如下|裁定如下)[：:]\s*(.*)",
        document_full_text, re.DOTALL,
    )
    sections["judgment_main"] = judgment_main.group(1).strip() if judgment_main else ""

    # ── Case info ──────────────────────────────────────────────
    case_info: dict[str, str] = {}
    case_num = re.search(r"（\d{4}）[\u4e00-\u9fff\d]+号|\(\d{4}\)[\u4e00-\u9fff\d]+号", document_full_text[:500])
    if case_num:
        case_info["case_number"] = case_num.group(0)
    court_match = re.search(r"(?:不服|上诉至|向)?([\u4e00-\u9fff]{2,}(?:中级人民法院|基层人民法院|高级人民法院|人民法院|仲裁委员会))", document_full_text[:500])
    if court_match:
        case_info["court"] = court_match.group(1)
    date_match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", document_full_text[-500:])
    if date_match:
        case_info["judge_date"] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
    sections["case_info"] = case_info

    # ── Confidence ─────────────────────────────────────────────
    filled = sum(
        1 for v in sections.values()
        if v and (isinstance(v, str) and len(v) > 10 or isinstance(v, dict) and v)
    )
    total = 7
    sections["extraction_confidence"] = round(filled / total, 2) if total > 0 else 0.0

    # ── Trial stage ────────────────────────────────────────────
    case_number = case_info.get("case_number", "")
    sections["trial_stage"] = infer_trial_stage(case_number, document_full_text)

    logger.info(
        "extract_document_sections: confidence=%.2f, sections_found=%d/%d, trial_stage=%s",
        sections["extraction_confidence"], filled, total, sections["trial_stage"],
    )

    # ── Rule engine pre-screening (optional) ───────────────────
    if run_rule_engine and rule_engine_fn is not None:
        rule_engine_flags = rule_engine_fn(document_full_text, sections)
        if rule_engine_flags:
            sections["rule_engine_flags"] = rule_engine_flags
            logger.info(
                "extract_document_sections: rule_engine found %d flags",
                len(rule_engine_flags),
            )

    return sections
