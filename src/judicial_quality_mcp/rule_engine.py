"""Rule engine v0.3.0 — pattern-based structural anomaly detection for judicial documents.

Extracted from server.py and enhanced with `exceptions`, `requires_absent`, and
`rule_type` fields ported from hallucination-mcp's rule engine
(as identified in MCP-COMPARE-20260601).

Bridge Architecture: NO LLM calls. Pure regex-based pre-screening.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── Rule data structure (enhanced) ─────────────────────────────

@dataclass
class DetectionRule:
    """A single detection rule for the rule engine.

    Enhanced with `exceptions`, `requires_absent`, and `rule_type` fields
    ported from hallucination-mcp. These prevent false positives from legal
    terminology (e.g. "恶意串通" should NOT trigger a rhetoric-detection
    rule on "恶意").

    rule_type:
      - "absence": Flag when pattern is NOT found (structural missing elements).
                   exceptions/requires_absent are NOT applicable to absence rules.
      - "presence": Flag when pattern IS found (evasive patterns, anomalies).
                    exceptions and requires_absent apply to suppress false positives.
    """
    rule_id: str
    pattern: str
    rule_type: str = "absence"   # "absence" or "presence"
    section: str = "body"        # header / body / footer
    severity: str = "medium"     # critical / high / medium / low
    message: str = ""
    exceptions: list[str] = field(default_factory=list)       # Patterns to EXCLUDE (presence rules only)
    requires_absent: list[str] = field(default_factory=list)  # Must NOT be present (presence rules only)


# ── Built-in rule sets ─────────────────────────────────────────

RULE_ENGINE_PATTERNS: dict[str, dict] = {
    "missing_court_name": {
        "pattern": r"人民法院|仲裁委员会",
        "rule_type": "absence",
        "section": "header",
        "severity": "high",
        "message": "首部缺少法院名称",
    },
    "missing_case_number": {
        "pattern": r"[（(]\d{4}[）)]\w+\d+号",
        "rule_type": "absence",
        "section": "header",
        "severity": "high",
        "message": "首部缺少案号或案号格式错误",
    },
    "missing_judgment_main": {
        "pattern": r"判决如下|裁定如下|决定如下",
        "rule_type": "absence",
        "section": "footer",
        "severity": "high",
        "message": "缺少判决主文",
    },
    "missing_reasoning": {
        "pattern": r"本院认为",
        "rule_type": "absence",
        "section": "body",
        "severity": "high",
        "message": "缺少'本院认为'说理部分",
    },
    "missing_law_basis": {
        "pattern": r"依照|根据.*规定",
        "rule_type": "absence",
        "section": "body",
        "severity": "medium",
        "message": "缺少法律依据引用",
    },
    "missing_evidence_section": {
        "pattern": r"上述事实|证据如下|有下列证据",
        "rule_type": "absence",
        "section": "body",
        "severity": "medium",
        "message": "缺少证据分析部分",
    },
}

EVASIVE_PATTERNS: dict[str, dict] = {
    "vague_subject": {
        "pattern": r"相关(?:单位|人员|部门|机构)(?:应当|应|必须|需|负有|承担)",
        "rule_type": "presence",
        "severity": "medium",
        "message": "主体模糊：使用'相关单位/人员应当...'等模糊表述代替具体主体名称，且涉及义务或责任分配",
        "requires_absent": [
            r"(?:原告|被告|上诉人|被上诉人|第三人).{0,15}相关(?:单位|人员|部门|机构)",
        ],
    },
    "evasive_timing": {
        "pattern": r"(?:此后|随后|之后|不久|事后)(?:[，。,；;]\s*(?:原告|被告|上诉人|被上诉人|申请人|被申请人))",
        "rule_type": "presence",
        "severity": "low",
        "message": "时间模糊：使用'此后/随后'等模糊时间表述引出当事人行为，缺少具体日期",
    },
    "selective_citation": {
        "pattern": r"(?:仅|只|单)(?:依据|根据|据|依)?(?:原告|被告|申请人|被申请人)",
        "rule_type": "presence",
        "severity": "high",
        "message": "选择性引用：仅依据单方证据或陈述",
        "exceptions": [
            r"(?:仅|只|单)(?:依据|根据|据|依)?.*?(?:但|然而|不过|但是)",  # "仅依据...但..." has counter-argument
        ],
    },
    "template_language": {
        "pattern": r"本院认为[，,].*?(?:并无不当|于法有据|予以支持|不予支持)",
        "rule_type": "presence",
        "severity": "medium",
        "message": "模板化说理：使用'并无不当/于法有据'等套话，缺乏具体论证",
        "exceptions": [
            r"本院认为[，,].*?并无不当.*?但",  # "并无不当...但..." is nuanced, not template
        ],
    },
    "missing_response": {
        "pattern": r"(?:原告|被告|申请人|被申请人).{0,5}(?:主张|请求|抗辩|辩称).{0,30}(?:不予|无需|没有必要)(?:回应|评述|审查)",
        "rule_type": "presence",
        "severity": "high",
        "message": "回避回应：明确表示不予回应当事人主张",
    },
}


# ── Engine functions ────────────────────────────────────────────

def run_rule_engine(document_text: str, sections: dict) -> list[dict]:
    """Rule Engine pre-screening: detect structural anomalies via regex.

    Handles two rule types:
    - "absence" rules: Flag when pattern is NOT found (missing elements).
      exceptions/requires_absent do not apply.
    - "presence" rules: Flag when pattern IS found (evasive patterns).
      exceptions suppress matches; requires_absent requires certain patterns
      to be absent for the flag to trigger.

    Args:
        document_text: Full document text.
        sections: Pre-extracted sections dict (for section-scoped search).

    Returns:
        List of flag dicts with rule_id, severity, message, section, evidence, reasoning.
    """
    flags = []
    for rule_id, rule_def in RULE_ENGINE_PATTERNS.items():
        pattern = rule_def["pattern"]
        section = rule_def["section"]
        severity = rule_def["severity"]
        message = rule_def["message"]
        rule_type = rule_def.get("rule_type", "absence")

        search_text = document_text
        if section == "header":
            search_text = document_text[:500]
        elif section == "footer":
            search_text = document_text[-500:]

        match = re.search(pattern, search_text)

        if rule_type == "absence":
            # Absence rules: flag when pattern NOT found
            if not match:
                flags.append({
                    "rule_id": rule_id,
                    "severity": severity,
                    "message": message,
                    "section": section,
                    "evidence": f"在文书{section}部分未找到匹配模式: {pattern[:30]}...",
                    "reasoning": f"规则引擎初筛：文书{section}部分缺少必要要素，需LLM进一步确认",
                })
                logger.debug("run_rule_engine: flag rule=%s, severity=%s", rule_id, severity)
        else:
            # Presence rules: flag when pattern IS found (with exceptions/requires_absent)
            if match:
                exceptions = rule_def.get("exceptions", [])
                requires_absent = rule_def.get("requires_absent", [])

                # Check exceptions — if any matches, suppress
                suppressed = False
                for exc_pattern in exceptions:
                    if re.search(exc_pattern, search_text):
                        logger.debug(
                            "run_rule_engine: rule=%s suppressed by exception=%s",
                            rule_id, exc_pattern,
                        )
                        suppressed = True
                        break

                if suppressed:
                    continue

                # Check requires_absent — ALL must be absent for flag to trigger
                absent_ok = True
                for absent_pattern in requires_absent:
                    if re.search(absent_pattern, search_text):
                        logger.debug(
                            "run_rule_engine: rule=%s suppressed by requires_absent=%s",
                            rule_id, absent_pattern,
                        )
                        absent_ok = False
                        break

                if not absent_ok:
                    continue

                flags.append({
                    "rule_id": rule_id,
                    "severity": severity,
                    "message": message,
                    "section": section,
                    "evidence": f"在文书{section}部分匹配到模式: {match.group(0)[:50]}...",
                    "reasoning": f"规则引擎初筛：文书{section}部分存在异常模式，需LLM进一步确认",
                })
                logger.debug("run_rule_engine: flag rule=%s, severity=%s", rule_id, severity)

    return flags


def detect_evasive_patterns(document_text: str) -> list[dict]:
    """Detect evasive rhetorical patterns in judicial documents.

    Enhanced with exception matching and requires_absent from hallucination-mcp.

    - exceptions: If any exception pattern matches in the context, suppress the detection.
    - requires_absent: ALL absent patterns must NOT be present for the detection to trigger.
      This prevents false positives when the document has already clarified the ambiguity.

    Args:
        document_text: Full document text.

    Returns:
        List of detection dicts.
    """
    detections = []
    for pattern_id, pattern_def in EVASIVE_PATTERNS.items():
        pattern = pattern_def["pattern"]
        severity = pattern_def["severity"]
        message = pattern_def["message"]
        exceptions = pattern_def.get("exceptions", [])
        requires_absent = pattern_def.get("requires_absent", [])

        matches = list(re.finditer(pattern, document_text))
        if not matches:
            continue

        for match in matches:
            matched_text = match.group(0)
            start = max(0, match.start() - 30)
            end = min(len(document_text), match.end() + 30)
            context = document_text[start:end]

            # Check exceptions — if any matches, suppress
            suppressed = False
            for exc_pattern in exceptions:
                if re.search(exc_pattern, context):
                    logger.debug(
                        "detect_evasive_patterns: pattern=%s suppressed by exception=%s",
                        pattern_id, exc_pattern,
                    )
                    suppressed = True
                    break

            if suppressed:
                continue

            # Check requires_absent — ALL must be absent for detection to trigger
            absent_ok = True
            for absent_pattern in requires_absent:
                if re.search(absent_pattern, document_text):
                    logger.debug(
                        "detect_evasive_patterns: pattern=%s suppressed by requires_absent=%s",
                        pattern_id, absent_pattern,
                    )
                    absent_ok = False
                    break

            if not absent_ok:
                continue

            detections.append({
                "pattern_id": pattern_id,
                "severity": severity,
                "message": message,
                "matched_text": matched_text,
                "context": context,
                "position": match.start(),
            })

    logger.info("detect_evasive_patterns: found %d detections", len(detections))
    return detections


# ── Cross-check consistency ────────────────────────────────────

def cross_check_consistency(int_scores: dict) -> dict:
    """Check logical consistency across dimension scores.

    Migrated from server.py inline implementation. Pure rule-based,
    zero token consumption.

    Args:
        int_scores: Dict of dimension -> integer score.

    Returns:
        Dict with conflict_detected, conflicts, score_summary, suggestion.
    """
    from .config import CROSS_CHECK_RULES, DIMENSION_TITLES, QUALITY_WEIGHTS

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

    return result
