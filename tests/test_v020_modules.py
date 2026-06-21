"""Unit tests for v0.2.0 new modules.

Covers: token_estimator, section_extractor, rule_engine, prompt_builder,
anomaly_bridge, report_builder, pipeline_state, material_preprocessor.
"""

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure src is importable
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from judicial_quality_mcp.token_estimator import estimate_tokens, estimate_token_budget
from judicial_quality_mcp.section_extractor import extract_document_sections
from judicial_quality_mcp.rule_engine import run_rule_engine, detect_evasive_patterns
from judicial_quality_mcp.prompt_builder import (
    infer_trial_stage,
    get_stage_terms,
    build_system_prompt,
    STAGE_TERMS,
)
from judicial_quality_mcp.anomaly_bridge import (
    detect_anomaly_mcp,
    query_anomaly_mcp,
    finalize_anomaly_detection,
    check_anomaly_mcp_status,
    SUPPORTED_DIMENSIONS,
)
from judicial_quality_mcp.report_builder import (
    build_report_markdown,
    md_to_rich_html,
    build_html_page,
)
from judicial_quality_mcp.pipeline_state import PipelineStateManager
from judicial_quality_mcp.material_preprocessor import (
    compact_materials,
    redact_pii,
    preprocess_document,
)
from judicial_quality_mcp.law_reference import (
    query_law_database,
    query_case_precedent,
    submit_supplementary_doc,
    analyze_legal_difficulty,
    LAW_DATABASE,
    LEGAL_PRINCIPLES,
    CASE_TYPE_PRECEDENTS,
    _supplementary_docs,
)


# ═══════════════════════════════════════════════════════════════
# Sample document for testing
# ═══════════════════════════════════════════════════════════════

SAMPLE_DOC = """
（2023）苏0602民初1234号

原告张某诉称：原告于2020年3月1日入职被告某科技有限公司，担任软件工程师，月工资12000元。入职以来，被告从未与原告签订书面劳动合同，也未依法为原告缴纳社会保险。2023年8月31日，被告以"公司业务调整"为由口头通知原告解除劳动关系，未支付任何经济补偿。原告请求：一、确认原告与被告自2020年3月1日至2023年8月31日期间存在劳动关系；二、被告支付未签订书面劳动合同二倍工资差额44000元；三、被告支付解除劳动关系经济补偿金18000元。

被告某科技有限公司辩称：原告系劳务关系而非劳动关系，被告无需签订书面劳动合同。原告系主动离职，被告无需支付经济补偿金。

本院查明：原告于2020年3月1日起在被告处从事软件研发工作，接受被告的考勤管理，按月领取报酬。原告提交的考勤记录、银行流水相互印证。

上述事实，有原告提交的考勤记录、银行流水等证据在卷佐证。

本院认为，关于劳动关系的认定，根据《中华人民共和国劳动合同法》第七条规定，用人单位自用工之日起即与劳动者建立劳动关系。本案中，原告接受被告的考勤管理、按月领取报酬，符合劳动关系的基本特征。依照《中华人民共和国劳动合同法》第七条、第十条、第八十二条、第四十六条、第四十七条，《中华人民共和国社会保险法》第五十八条之规定，判决如下：

一、确认原告张某与被告某科技有限公司自2020年3月1日至2023年8月31日期间存在劳动关系；
二、被告于本判决生效之日起十日内支付原告未签订书面劳动合同二倍工资差额44000元；
三、驳回原告其他诉讼请求。

2023年12月15日
"""


# ═══════════════════════════════════════════════════════════════
# 1. token_estimator
# ═══════════════════════════════════════════════════════════════


class TestTokenEstimator:
    def test_pure_chinese(self):
        result = estimate_tokens("中华人民共和国")
        assert result > 0
        # 7 chars / 1.5 ≈ 4-5 tokens
        assert 3 <= result <= 6

    def test_pure_english(self):
        result = estimate_tokens("Hello World")
        assert result > 0
        # 11 chars / 4.0 ≈ 2-3 tokens
        assert 2 <= result <= 4

    def test_mixed_cjk_latin(self):
        result = estimate_tokens("根据Article 7的规定")
        assert result > 0

    def test_cjk_punctuation(self):
        # CJK punctuation should be counted as CJK
        text = "、。《》「」"
        result = estimate_tokens(text)
        assert result > 0

    def test_fullwidth_chars(self):
        # Fullwidth forms should be counted as CJK
        text = "ＡＢＣ１２３"
        result = estimate_tokens(text)
        assert result > 0

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_estimate_token_budget(self):
        result = estimate_token_budget(char_count=1000)
        assert result > 0
        assert result < 1000  # Always fewer tokens than chars


# ═══════════════════════════════════════════════════════════════
# 2. section_extractor
# ═══════════════════════════════════════════════════════════════


class TestSectionExtractor:
    def test_extract_all_sections(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "plaintiff_claim" in result
        assert "defendant_defense" in result
        assert "court_finding" in result
        assert "reasoning" in result
        assert "judgment_main" in result

    def test_plaintiff_claim_extracted(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "入职" in result["plaintiff_claim"]

    def test_defendant_defense_extracted(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "劳务关系" in result["defendant_defense"]

    def test_court_finding_extracted(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "考勤管理" in result["court_finding"]

    def test_reasoning_extracted(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "劳动关系" in result["reasoning"]

    def test_judgment_main_extracted(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "确认" in result["judgment_main"]

    def test_case_info(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert "case_info" in result
        assert result["case_info"].get("case_number") is not None

    def test_trial_stage(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert result["trial_stage"] == "一审"

    def test_confidence(self):
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=False)
        assert 0 <= result["extraction_confidence"] <= 1.0

    def test_with_rule_engine(self):
        mock_fn = MagicMock(return_value=[{"rule_id": "test", "severity": "low"}])
        result = extract_document_sections(SAMPLE_DOC, run_rule_engine=True, rule_engine_fn=mock_fn)
        assert "rule_engine_flags" in result

    def test_empty_document(self):
        result = extract_document_sections("", run_rule_engine=False)
        assert result["extraction_confidence"] == 0.0


# ═══════════════════════════════════════════════════════════════
# 3. rule_engine
# ═══════════════════════════════════════════════════════════════


class TestRuleEngine:
    def test_complete_document_no_flags(self):
        # A well-formed document should have few or no flags
        flags = run_rule_engine(SAMPLE_DOC, {})
        # May have some flags depending on patterns, but should not crash
        assert isinstance(flags, list)

    def test_missing_court_name(self):
        doc = "这是一个没有法院名称的文书。本院认为，应当判决如下："
        flags = run_rule_engine(doc, {})
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_court_name" in rule_ids

    def test_missing_case_number(self):
        doc = "某人民法院\n原告张三诉称：...\n本院认为...\n判决如下："
        flags = run_rule_engine(doc, {})
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_case_number" in rule_ids

    def test_missing_judgment_main(self):
        doc = "（2023）苏0602民初1234号\n某人民法院\n原告张三诉称：...\n本院认为...\n"
        flags = run_rule_engine(doc, {})
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_judgment_main" in rule_ids

    def test_missing_reasoning(self):
        doc = "（2023）苏0602民初1234号\n某人民法院\n原告张三诉称：...\n判决如下：\n一、驳回。"
        flags = run_rule_engine(doc, {})
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_reasoning" in rule_ids


class TestEvasivePatterns:
    def test_vague_subject(self):
        doc = "相关单位应当承担责任。"
        detections = detect_evasive_patterns(doc)
        pattern_ids = [d["pattern_id"] for d in detections]
        assert "vague_subject" in pattern_ids

    def test_evasive_timing(self):
        doc = "此后，原告提起了诉讼。"
        detections = detect_evasive_patterns(doc)
        pattern_ids = [d["pattern_id"] for d in detections]
        assert "evasive_timing" in pattern_ids

    def test_evasive_timing_no_false_positive(self):
        # "此后" followed by general text should NOT trigger
        doc = "此后，当事人提起了诉讼。"
        detections = detect_evasive_patterns(doc)
        pattern_ids = [d["pattern_id"] for d in detections]
        assert "evasive_timing" not in pattern_ids

    def test_template_language(self):
        doc = "本院认为，原告的诉讼请求于法有据，予以支持。"
        detections = detect_evasive_patterns(doc)
        pattern_ids = [d["pattern_id"] for d in detections]
        assert "template_language" in pattern_ids

    def test_template_language_exception(self):
        # "并无不当...但..." should NOT trigger template_language
        doc = "本院认为，原审法院的认定并无不当，但应进一步审查。"
        detections = detect_evasive_patterns(doc)
        template_detections = [d for d in detections if d["pattern_id"] == "template_language"]
        # The exception pattern should suppress the detection
        assert len(template_detections) == 0

    def test_clean_document(self):
        doc = "本院认为，根据《劳动合同法》第七条的规定，用人单位自用工之日起即与劳动者建立劳动关系。本案中，原告张某于2020年3月1日入职被告某科技有限公司。"
        detections = detect_evasive_patterns(doc)
        # Should have few or no detections
        assert isinstance(detections, list)


class TestRuleEngineEnhanced:
    """Tests for Phase 3-3 rule engine enhancements: rule_type, exceptions, requires_absent."""

    def test_absence_rule_type_in_patterns(self):
        """All RULE_ENGINE_PATTERNS should have rule_type='absence'."""
        from judicial_quality_mcp.rule_engine import RULE_ENGINE_PATTERNS
        for rule_id, rule_def in RULE_ENGINE_PATTERNS.items():
            assert rule_def.get("rule_type") == "absence", f"{rule_id} should be absence type"

    def test_presence_rule_type_in_evasive(self):
        """All EVASIVE_PATTERNS should have rule_type='presence'."""
        from judicial_quality_mcp.rule_engine import EVASIVE_PATTERNS
        for pattern_id, pattern_def in EVASIVE_PATTERNS.items():
            assert pattern_def.get("rule_type") == "presence", f"{pattern_id} should be presence type"

    def test_requires_absent_vague_subject_suppressed(self):
        """vague_subject should be suppressed when specific subject is mentioned nearby."""
        # "被告某公司，相关单位应当..." — specific subject present, should suppress
        doc = "被告某科技有限公司应承担相应责任。相关单位应当配合执行。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) == 0, "vague_subject should be suppressed by requires_absent"

    def test_requires_absent_vague_subject_not_suppressed(self):
        """vague_subject should trigger when no specific subject is nearby."""
        doc = "经审理查明，相关单位应当承担连带责任。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) >= 1, "vague_subject should trigger without specific subject"

    def test_exception_selective_citation_with_counter(self):
        """selective_citation should be suppressed when '但/然而' follows."""
        doc = "仅依据原告的陈述，但被告亦提供了反驳证据。"
        detections = detect_evasive_patterns(doc)
        selective = [d for d in detections if d["pattern_id"] == "selective_citation"]
        assert len(selective) == 0, "selective_citation should be suppressed by exception"

    def test_exception_selective_citation_without_counter(self):
        """selective_citation should trigger when no counter-argument follows."""
        doc = "仅依据原告的陈述认定事实。"
        detections = detect_evasive_patterns(doc)
        selective = [d for d in detections if d["pattern_id"] == "selective_citation"]
        assert len(selective) >= 1, "selective_citation should trigger without exception"

    def test_run_rule_engine_absence_no_exception_check(self):
        """Absence rules should not check exceptions (they flag on missing patterns)."""
        # A document missing court name should still flag, regardless of any text
        doc = "这是一个没有任何法院名称的文书。本院认为，应当判决如下："
        flags = run_rule_engine(doc, {})
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_court_name" in rule_ids

    def test_run_rule_engine_presence_with_requires_absent(self):
        """Presence rules in RULE_ENGINE_PATTERNS should support requires_absent."""
        # Currently all RULE_ENGINE_PATTERNS are absence type,
        # but the engine should handle presence type correctly if added
        from judicial_quality_mcp.rule_engine import RULE_ENGINE_PATTERNS
        # Verify the engine handles rule_type correctly
        doc = "（2023）苏0602民初1234号\n某人民法院\n本院认为...\n判决如下："
        flags = run_rule_engine(doc, {})
        # Should not flag missing items that are present
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_case_number" not in rule_ids
        assert "missing_court_name" not in rule_ids

    def test_detection_rule_dataclass(self):
        """DetectionRule dataclass should support all new fields."""
        from judicial_quality_mcp.rule_engine import DetectionRule
        rule = DetectionRule(
            rule_id="test_rule",
            pattern=r"test",
            rule_type="presence",
            severity="high",
            message="Test rule",
            exceptions=[r"exception1"],
            requires_absent=[r"absent1"],
        )
        assert rule.rule_type == "presence"
        assert len(rule.exceptions) == 1
        assert len(rule.requires_absent) == 1


class TestRequiresAbsentEdgeCases:
    """Edge-case tests for requires_absent logic in detect_evasive_patterns and run_rule_engine."""

    # ── requires_absent boundary: distance ──────────────────────

    def test_requires_absent_within_distance(self):
        """Subject within 15 chars of '相关单位' should suppress."""
        doc = "被告某公司，相关单位应当承担责任。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) == 0

    def test_requires_absent_beyond_distance(self):
        """Subject beyond 15 chars of '相关单位' should NOT suppress."""
        doc = "被告某科技有限公司经审理查明应承担相应责任，经合议庭评议，相关单位应当配合执行。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) >= 1, "Subject too far away, should still trigger"

    # ── requires_absent boundary: multiple subjects ─────────────

    def test_requires_absent_multiple_subjects_one_nearby(self):
        """If ANY subject is within distance, suppress (requires_absent is OR-checked)."""
        doc = "原告张某与被告某公司，相关单位应当承担责任。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) == 0, "At least one subject nearby, should suppress"

    # ── requires_absent boundary: different subject types ───────

    def test_requires_absent_appellant_nearby(self):
        """上诉人 within distance should also suppress vague_subject."""
        doc = "上诉人李某不服一审判决，相关单位应当承担连带责任。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) == 0

    def test_requires_absent_third_party_nearby(self):
        """第三人 within distance should also suppress vague_subject."""
        doc = "第三人王某述称，相关单位应当承担连带责任。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) == 0

    # ── requires_absent boundary: no requires_absent defined ────

    def test_no_requires_absent_always_triggers(self):
        """Patterns without requires_absent should always trigger on match."""
        doc = "此后，原告向法院提起诉讼。"
        detections = detect_evasive_patterns(doc)
        timing = [d for d in detections if d["pattern_id"] == "evasive_timing"]
        assert len(timing) >= 1, "evasive_timing has no requires_absent, should trigger"

    # ── requires_absent boundary: empty requires_absent list ────

    def test_empty_requires_absent_list(self):
        """Pattern with requires_absent=[] should behave like no requires_absent."""
        from judicial_quality_mcp.rule_engine import EVASIVE_PATTERNS
        # missing_response has no requires_absent key — same as empty list
        doc = "原告主张赔偿，不予回应。"
        # This won't match missing_response pattern (different structure),
        # so test the data structure instead
        assert "requires_absent" not in EVASIVE_PATTERNS["missing_response"] or \
               EVASIVE_PATTERNS["missing_response"].get("requires_absent") == []

    # ── requires_absent + exceptions interaction ────────────────

    def test_requires_absent_and_exceptions_both_suppress(self):
        """When both exceptions and requires_absent could suppress, exceptions checked first."""
        # selective_citation has exceptions but no requires_absent
        # vague_subject has requires_absent but no exceptions
        # Test that they work independently
        doc = "仅依据原告的陈述，但被告亦提供了证据。"
        detections = detect_evasive_patterns(doc)
        selective = [d for d in detections if d["pattern_id"] == "selective_citation"]
        assert len(selective) == 0, "Exception should suppress selective_citation"

    # ── requires_absent in run_rule_engine ──────────────────────

    def test_run_rule_engine_absence_type_ignores_requires_absent(self):
        """Absence rules should ignore requires_absent even if defined."""
        # All RULE_ENGINE_PATTERNS are absence type — they never check requires_absent
        doc = "这是一个缺少案号和法院名称的文书。"
        flags = run_rule_engine(doc, {})
        rule_ids = [f["rule_id"] for f in flags]
        assert "missing_case_number" in rule_ids
        assert "missing_court_name" in rule_ids

    def test_run_rule_engine_presence_type_with_requires_absent_suppressed(self):
        """Presence rule in run_rule_engine should be suppressed by requires_absent."""
        # Inject a temporary presence rule into RULE_ENGINE_PATTERNS
        from judicial_quality_mcp import rule_engine as re_mod
        original = re_mod.RULE_ENGINE_PATTERNS.copy()
        try:
            re_mod.RULE_ENGINE_PATTERNS["test_presence_absent"] = {
                "pattern": r"测试存在型规则",
                "rule_type": "presence",
                "section": "body",
                "severity": "low",
                "message": "测试存在型规则触发",
                "requires_absent": [r"抑制标记"],
            }
            # With suppressor present → should NOT flag
            doc1 = "测试存在型规则匹配。抑制标记在此。"
            flags1 = run_rule_engine(doc1, {})
            assert "test_presence_absent" not in [f["rule_id"] for f in flags1]

            # Without suppressor → should flag
            doc2 = "测试存在型规则匹配。没有抑制词。"
            flags2 = run_rule_engine(doc2, {})
            assert "test_presence_absent" in [f["rule_id"] for f in flags2]
        finally:
            re_mod.RULE_ENGINE_PATTERNS.clear()
            re_mod.RULE_ENGINE_PATTERNS.update(original)

    def test_run_rule_engine_presence_type_with_exception_suppressed(self):
        """Presence rule in run_rule_engine should be suppressed by exceptions."""
        from judicial_quality_mcp import rule_engine as re_mod
        original = re_mod.RULE_ENGINE_PATTERNS.copy()
        try:
            re_mod.RULE_ENGINE_PATTERNS["test_presence_exc"] = {
                "pattern": r"异常模式匹配",
                "rule_type": "presence",
                "section": "body",
                "severity": "medium",
                "message": "测试例外规则",
                "exceptions": [r"异常模式匹配.*?但"],
            }
            # Exception matches → suppressed
            doc1 = "异常模式匹配，但已有合理解释。"
            flags1 = run_rule_engine(doc1, {})
            assert "test_presence_exc" not in [f["rule_id"] for f in flags1]

            # No exception → flag
            doc2 = "异常模式匹配，无任何解释。"
            flags2 = run_rule_engine(doc2, {})
            assert "test_presence_exc" in [f["rule_id"] for f in flags2]
        finally:
            re_mod.RULE_ENGINE_PATTERNS.clear()
            re_mod.RULE_ENGINE_PATTERNS.update(original)

    # ── requires_absent: multiple absent patterns (AND logic) ───

    def test_requires_absent_multiple_all_absent(self):
        """When requires_absent has multiple patterns, ALL must be absent to trigger."""
        from judicial_quality_mcp import rule_engine as re_mod
        original = re_mod.RULE_ENGINE_PATTERNS.copy()
        try:
            re_mod.RULE_ENGINE_PATTERNS["test_multi_absent"] = {
                "pattern": r"多重缺失测试",
                "rule_type": "presence",
                "section": "body",
                "severity": "low",
                "message": "测试多重requires_absent",
                "requires_absent": [r"抑制词A", r"抑制词B"],
            }
            # Both absent → trigger
            doc1 = "多重缺失测试匹配。没有抑制词。"
            flags1 = run_rule_engine(doc1, {})
            assert "test_multi_absent" in [f["rule_id"] for f in flags1]

            # One present → suppressed (AND logic: all must be absent)
            doc2 = "多重缺失测试匹配。抑制词A在此。"
            flags2 = run_rule_engine(doc2, {})
            assert "test_multi_absent" not in [f["rule_id"] for f in flags2]

            # Both present → suppressed
            doc3 = "多重缺失测试匹配。抑制词A和抑制词B都在。"
            flags3 = run_rule_engine(doc3, {})
            assert "test_multi_absent" not in [f["rule_id"] for f in flags3]
        finally:
            re_mod.RULE_ENGINE_PATTERNS.clear()
            re_mod.RULE_ENGINE_PATTERNS.update(original)

    # ── detect_evasive_patterns: multiple matches per pattern ───

    def test_requires_absent_multiple_matches_document_wide(self):
        """requires_absent is document-wide: if subject appears anywhere, ALL matches suppressed."""
        # "被告某公司" appears in the doc → all "相关单位" suppressed (document-wide check)
        doc = "被告某公司，相关单位应当承担责任。经合议庭评议后认为，相关单位应当配合执行。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        # Both suppressed because subject exists somewhere in the document
        assert len(vague) == 0, "requires_absent is document-wide, subject anywhere suppresses all"

    def test_requires_absent_no_subject_anywhere_triggers_all(self):
        """When no subject appears anywhere, all vague_subject matches should trigger."""
        doc = "经审理查明，相关单位应当承担连带责任。此外，相关单位应当配合执行。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) >= 2, "No subject anywhere, all matches should trigger"

    # ── requires_absent: no pattern match at all ────────────────

    def test_requires_absent_no_pattern_match(self):
        """If the main pattern doesn't match, requires_absent is irrelevant."""
        doc = "这是一份正常的判决书，没有任何模糊表述。"
        detections = detect_evasive_patterns(doc)
        vague = [d for d in detections if d["pattern_id"] == "vague_subject"]
        assert len(vague) == 0, "No pattern match, no detection"


# ═══════════════════════════════════════════════════════════════
# 4. prompt_builder
# ═══════════════════════════════════════════════════════════════


class TestPromptBuilder:
    def test_infer_trial_stage_yishen(self):
        assert infer_trial_stage("(2023)苏0602民初1234号") == "一审"

    def test_infer_trial_stage_ershen(self):
        assert infer_trial_stage("(2024)苏06民终6271号") == "二审"

    def test_infer_trial_stage_zaishen(self):
        assert infer_trial_stage("(2024)苏06民再1号") == "再审"

    def test_infer_trial_stage_zhongcai(self):
        assert infer_trial_stage("(2024)通劳仲字第123号") == "仲裁"

    def test_infer_trial_stage_xingzheng(self):
        assert infer_trial_stage("(2024)通行罚字第1号") == "行政"

    def test_infer_trial_stage_fallback_text(self):
        # No case number, but document has 上诉人
        doc = "上诉人张三因与被上诉人李四劳动争议一案..."
        assert infer_trial_stage("", doc) == "二审"

    def test_infer_trial_stage_unknown(self):
        assert infer_trial_stage("") == "未知"

    def test_get_stage_terms(self):
        terms = get_stage_terms("二审")
        assert terms["plaintiff"] == "上诉人"
        assert terms["defendant"] == "被上诉人"

    def test_get_stage_terms_unknown(self):
        terms = get_stage_terms("未知")
        assert terms["plaintiff"] == "当事人"

    def test_build_system_prompt_basic(self):
        meta = MagicMock()
        meta.name = "thorough_reasoning"
        meta.title = "说理充分透彻"
        meta.weight = 0.25
        meta.full_score = 100
        prompt = build_system_prompt(meta)
        assert "说理充分透彻" in prompt
        assert "25" in prompt  # weight * 100

    def test_build_system_prompt_with_trial_stage(self):
        meta = MagicMock()
        meta.name = "thorough_reasoning"
        meta.title = "说理充分透彻"
        meta.weight = 0.25
        meta.full_score = 100
        prompt = build_system_prompt(meta, trial_stage="二审")
        assert "上诉人/被上诉人" in prompt
        assert "二审" in prompt

    def test_build_system_prompt_clear_facts(self):
        meta = MagicMock()
        meta.name = "clear_facts"
        meta.title = "事实认定清晰"
        meta.weight = 0.20
        meta.full_score = 100
        prompt = build_system_prompt(meta)
        assert "F编号" in prompt
        assert "四元结构" in prompt


# ═══════════════════════════════════════════════════════════════
# 5. anomaly_bridge
# ═══════════════════════════════════════════════════════════════


class TestAnomalyBridge:
    def test_detect_anomaly_mcp(self):
        # In test env, anomaly-mcp is likely not installed
        result = detect_anomaly_mcp()
        assert isinstance(result, bool)

    def test_query_anomaly_mcp_unavailable(self):
        result = query_anomaly_mcp(
            document_text="test",
            anomaly_mcp_available=False,
        )
        assert result["success"] is True
        assert result["available"] is False
        assert "fallback_mode" in result

    def test_query_anomaly_mcp_with_dimensions(self):
        result = query_anomaly_mcp(
            document_text="test",
            dimensions=["procedure", "evidence"],
            anomaly_mcp_available=False,
        )
        assert result["dimensions"] == ["procedure", "evidence"]

    def test_supported_dimensions(self):
        assert len(SUPPORTED_DIMENSIONS) == 16

    def test_check_anomaly_mcp_status(self):
        result = check_anomaly_mcp_status()
        assert "success" in result
        assert "installed" in result

    def test_finalize_anomaly_detection(self):
        result = finalize_anomaly_detection()
        assert result["success"] is True
        assert "anomaly_results" in result


# ═══════════════════════════════════════════════════════════════
# 6. report_builder
# ═══════════════════════════════════════════════════════════════


class TestReportBuilder:
    @pytest.fixture
    def dimension_results(self):
        return [
            {
                "dimension": "formal_specification",
                "score": 82,
                "weighted_score": 8.2,
                "quote": "首部格式规范",
                "reasoning": "格式基本规范",
                "deduction_items": [],
                "bonus_items": [],
            },
            {
                "dimension": "clear_facts",
                "score": 75,
                "weighted_score": 15.0,
                "quote": "事实认定清晰",
                "reasoning": "事实认定基本清晰",
                "deduction_items": [],
                "bonus_items": [],
            },
            {
                "dimension": "sufficient_evidence",
                "score": 70,
                "weighted_score": 14.0,
                "quote": "证据充分",
                "reasoning": "证据基本充分",
                "deduction_items": [],
                "bonus_items": [],
            },
            {
                "dimension": "correct_law_application",
                "score": 85,
                "weighted_score": 17.0,
                "quote": "法律适用正确",
                "reasoning": "法律适用正确",
                "deduction_items": [],
                "bonus_items": [],
            },
            {
                "dimension": "thorough_reasoning",
                "score": 78,
                "weighted_score": 19.5,
                "quote": "说理充分",
                "reasoning": "说理基本充分",
                "deduction_items": [],
                "bonus_items": [],
            },
            {
                "dimension": "substantive_resolution",
                "score": 72,
                "weighted_score": 14.4,
                "quote": "实体处理得当",
                "reasoning": "实体处理基本得当",
                "deduction_items": [],
                "bonus_items": [],
            },
            {
                "dimension": "concise_language",
                "score": 80,
                "weighted_score": 8.0,
                "quote": "语言简洁",
                "reasoning": "语言基本简洁",
                "deduction_items": [],
                "bonus_items": [],
            },
        ]

    def test_build_report_markdown(self, dimension_results):
        result_json = build_report_markdown(
            dimension_results=dimension_results,
            weighted_total=75.5,
            grade="C+",
        )
        result = json.loads(result_json)
        assert result["success"] is True
        assert "report_markdown" in result
        md = result["report_markdown"]
        assert "质量评估报告" in md
        assert "75.5" in md
        assert "C+" in md

    def test_build_report_markdown_with_anomaly(self, dimension_results):
        result_json = build_report_markdown(
            dimension_results=dimension_results,
            weighted_total=75.5,
            grade="C+",
            anomaly_deduction=10,
            anomaly_details=[{"type": "procedural", "severity": "high", "description": "程序异常"}],
        )
        result = json.loads(result_json)
        assert result["success"] is True
        md = result["report_markdown"]
        assert "10" in md

    def test_build_report_markdown_with_innovation(self, dimension_results):
        result_json = build_report_markdown(
            dimension_results=dimension_results,
            weighted_total=75.5,
            grade="C+",
            innovation_bonus=5,
            innovation_details=[{"type": "legal_gap_filling", "bonus": 5, "description": "法律漏洞填补"}],
        )
        result = json.loads(result_json)
        assert result["success"] is True

    def test_md_to_rich_html(self):
        md = "# 测试标题\n\n这是一段**加粗**文字。\n\n- 列表项1\n- 列表项2"
        html = md_to_rich_html(md)
        assert "<h1" in html
        assert "<strong>加粗</strong>" in html
        assert "<li>" in html

    def test_build_html_page(self, dimension_results):
        result_json = build_report_markdown(
            dimension_results=dimension_results,
            weighted_total=75.5,
            grade="C+",
        )
        md = json.loads(result_json)["report_markdown"]
        html = build_html_page(md, "QA-TEST-001")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "dark" in html  # theme toggle

    def test_report_with_trial_stage(self, dimension_results):
        result_json = build_report_markdown(
            dimension_results=dimension_results,
            weighted_total=75.5,
            grade="C+",
            trial_stage="二审",
        )
        result = json.loads(result_json)
        md = result["report_markdown"]
        assert "二审" in md


# ═══════════════════════════════════════════════════════════════
# 7. pipeline_state
# ═══════════════════════════════════════════════════════════════


class TestPipelineState:
    @pytest.fixture
    def mgr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield PipelineStateManager(ttl=60, persist_dir=tmpdir)

    def test_start_session(self, mgr):
        state = mgr.start("test-1", ["a", "b", "c"])
        assert state["dimensions"] == ["a", "b", "c"]
        assert state["completed"] == []
        assert "started_at" in state

    def test_complete_dimension(self, mgr):
        mgr.start("test-1", ["a", "b", "c"])
        state = mgr.complete("test-1", "a", "score=80")
        assert "a" in state["completed"]
        assert state["results"]["a"] == "score=80"

    def test_complete_nonexistent_session(self, mgr):
        state = mgr.complete("nonexistent", "a")
        assert state is None

    def test_get_session(self, mgr):
        mgr.start("test-1", ["a", "b"])
        state = mgr.get("test-1")
        assert state is not None
        assert state["dimensions"] == ["a", "b"]

    def test_get_nonexistent_session(self, mgr):
        state = mgr.get("nonexistent")
        assert state is None

    def test_reset_session(self, mgr):
        mgr.start("test-1", ["a", "b"])
        mgr.complete("test-1", "a", "done")
        state = mgr.reset("test-1")
        assert state["completed"] == []
        assert state["results"] == {}

    def test_reset_nonexistent_session(self, mgr):
        state = mgr.reset("nonexistent")
        assert state is None

    def test_persistence_to_disk(self, mgr):
        mgr.start("persist-1", ["x", "y"])
        mgr.complete("persist-1", "x", "ok")
        # Verify file exists
        path = mgr._persist_path("persist-1")
        assert path.exists()

    def test_load_from_disk(self, mgr):
        mgr.start("persist-2", ["x", "y"])
        mgr.complete("persist-2", "x", "ok")
        # Clear in-memory state
        mgr._state.clear()
        # Should load from disk
        state = mgr.get("persist-2")
        assert state is not None
        assert "x" in state["completed"]

    def test_ttl_expiration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PipelineStateManager(ttl=1, persist_dir=tmpdir)  # 1 second TTL
            mgr.start("expire-1", ["a"])
            time.sleep(1.5)
            state = mgr.get("expire-1")
            assert state is None

    def test_cleanup_expired(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PipelineStateManager(ttl=1, persist_dir=tmpdir)
            mgr.start("expire-1", ["a"])
            mgr.start("expire-2", ["b"])
            time.sleep(1.5)
            cleaned = mgr.cleanup_expired()
            assert cleaned == 2

    def test_thread_safety(self, mgr):
        import threading

        errors = []

        def worker(dim_name):
            try:
                mgr.start(f"thread-{dim_name}", ["a", "b"])
                mgr.complete(f"thread-{dim_name}", "a", f"result-{dim_name}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"d{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All 10 sessions should exist
        for i in range(10):
            state = mgr.get(f"thread-d{i}")
            assert state is not None

    def test_list_sessions(self, mgr):
        mgr.start("list-1", ["a", "b"])
        mgr.start("list-2", ["x", "y", "z"])
        mgr.complete("list-1", "a")
        sessions = mgr.list_sessions()
        assert len(sessions) >= 2
        s1 = next(s for s in sessions if s["session_id"] == "list-1")
        assert s1["completed_count"] == 1
        assert s1["total_count"] == 2
        s2 = next(s for s in sessions if s["session_id"] == "list-2")
        assert s2["completed_count"] == 0
        assert s2["total_count"] == 3

    def test_save_checkpoint(self, mgr):
        mgr.start("ckpt-1", ["a", "b"])
        mgr.complete("ckpt-1", "a", "done")
        result = mgr.save_checkpoint("ckpt-1")
        assert result is True
        # Verify disk file exists
        path = mgr._persist_path("ckpt-1")
        assert path.exists()

    def test_save_checkpoint_nonexistent(self, mgr):
        result = mgr.save_checkpoint("nonexistent")
        assert result is False

    def test_restore_checkpoint(self, mgr):
        mgr.start("restore-1", ["a", "b"])
        mgr.complete("restore-1", "a", "ok")
        # Clear memory
        mgr._state.clear()
        # Restore from disk
        state = mgr.restore_checkpoint("restore-1")
        assert state is not None
        assert "a" in state["completed"]
        # Should now be in memory too
        assert "restore-1" in mgr._state

    def test_restore_checkpoint_already_in_memory(self, mgr):
        mgr.start("restore-2", ["a"])
        state = mgr.restore_checkpoint("restore-2")
        assert state is not None

    def test_cleanup_expired_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = PipelineStateManager(ttl=1, persist_dir=tmpdir)
            mgr.start("disk-expire-1", ["a"])
            mgr.start("disk-expire-2", ["b"])
            time.sleep(1.5)
            # Clear memory so only disk files remain
            mgr._state.clear()
            cleaned = mgr.cleanup_expired_disk()
            assert cleaned == 2


# ═══════════════════════════════════════════════════════════════
# 8. material_preprocessor
# ═══════════════════════════════════════════════════════════════


class TestMaterialPreprocessor:
    def test_compact_multiple_blank_lines(self):
        text = "line1\n\n\n\nline2"
        result = compact_materials(text)
        assert result == "line1\n\nline2"

    def test_compact_trailing_spaces(self):
        text = "line1   \nline2  \n"
        result = compact_materials(text)
        assert "   " not in result

    def test_compact_tabs(self):
        text = "line1\tline2"
        result = compact_materials(text)
        assert "\t" not in result

    def test_compact_empty_string(self):
        assert compact_materials("") == ""

    def test_compact_none(self):
        assert compact_materials("") == ""

    def test_redact_id_card(self):
        text = "身份证号：320123199001011234"
        result = redact_pii(text)
        assert "320123199001011234" not in result
        assert "[身份证号]" in result

    def test_redact_mobile(self):
        text = "联系电话：13812345678"
        result = redact_pii(text)
        assert "13812345678" not in result
        assert "[手机号]" in result

    def test_redact_email(self):
        text = "邮箱：test@example.com"
        result = redact_pii(text)
        assert "test@example.com" not in result
        assert "[邮箱]" in result

    def test_redact_name_plaintiff(self):
        text = "原告：张三"
        result = redact_pii(text)
        assert "[当事人姓名]" in result

    def test_redact_name_defendant(self):
        text = "被告：李四"
        result = redact_pii(text)
        assert "[当事人姓名]" in result

    def test_redact_address(self):
        text = "住址：江苏省南京市鼓楼区北京路1号"
        result = redact_pii(text)
        assert "[地址]" in result

    def test_redact_skip_patterns(self):
        text = "原告：张三，身份证号：320123199001011234"
        result = redact_pii(text, skip_patterns=["name_plaintiff"])
        assert "张三" in result  # Name NOT redacted
        assert "[身份证号]" in result  # ID card still redacted

    def test_redact_disabled(self):
        text = "身份证号：320123199001011234"
        result = redact_pii(text, enabled=False)
        assert "320123199001011234" in result

    def test_redact_empty_string(self):
        assert redact_pii("") == ""

    def test_preprocess_document(self):
        text = "原告：张三\n\n\n\n身份证号：320123199001011234"
        result = preprocess_document(text)
        assert "[当事人姓名]" in result
        assert "[身份证号]" in result
        assert "\n\n\n" not in result  # compacted

    def test_preprocess_compact_only(self):
        text = "line1\n\n\n\nline2"
        result = preprocess_document(text, compact=True, redact=False)
        assert "\n\n\n" not in result

    def test_preprocess_redact_only(self):
        text = "身份证号：320123199001011234"
        result = preprocess_document(text, compact=False, redact=True)
        assert "[身份证号]" in result

    def test_bank_card_redaction(self):
        text = "银行卡号：6222021234567890123"
        result = redact_pii(text)
        assert "[银行卡号]" in result


class TestLawReferenceDatabase:
    """Tests for law_reference module data integrity."""

    def test_law_database_has_required_laws(self):
        required = ["民法典", "劳动合同法", "劳动争议调解仲裁法", "民事诉讼法", "公司法"]
        for name in required:
            assert name in LAW_DATABASE, f"Missing law: {name}"

    def test_law_database_entries_have_required_fields(self):
        for name, info in LAW_DATABASE.items():
            assert "full_name" in info, f"{name} missing full_name"
            assert "effective_date" in info, f"{name} missing effective_date"
            assert "hierarchy" in info, f"{name} missing hierarchy"
            assert "key_provisions" in info, f"{name} missing key_provisions"

    def test_legal_principles_has_required_entries(self):
        required = ["任何人不得从违法行为中获利", "诚实信用原则", "公平原则", "公序良俗"]
        for name in required:
            assert name in LEGAL_PRINCIPLES, f"Missing principle: {name}"

    def test_case_type_precedents_has_labor(self):
        assert "劳动争议" in CASE_TYPE_PRECEDENTS
        labor = CASE_TYPE_PRECEDENTS["劳动争议"]
        assert "guiding_cases" in labor
        assert "common_issues" in labor
        assert len(labor["guiding_cases"]) > 0


class TestQueryLawDatabase:
    """Tests for query_law_database function."""

    def test_query_by_name(self):
        result = json.loads(query_law_database(law_names=["劳动合同法"]))
        assert result["success"] is True
        assert len(result["matched_laws"]) >= 1
        assert any(l["name"] == "劳动合同法" for l in result["matched_laws"])

    def test_query_by_context_auto_match(self):
        result = json.loads(query_law_database(case_context="劳动争议工资纠纷"))
        assert result["success"] is True
        assert len(result["matched_laws"]) >= 1

    def test_query_conflict_detection(self):
        result = json.loads(query_law_database(
            law_names=["劳动合同法", "民法典"],
            check_conflicts=True,
        ))
        assert result["success"] is True
        assert len(result["conflicts"]) >= 1
        assert any(c["type"] == "特别法与一般法" for c in result["conflicts"])

    def test_query_no_conflicts_when_disabled(self):
        result = json.loads(query_law_database(
            law_names=["劳动合同法", "民法典"],
            check_conflicts=False,
        ))
        assert result["success"] is True
        assert len(result["conflicts"]) == 0

    def test_query_retroactivity_detection(self):
        result = json.loads(query_law_database(
            law_names=["民法典"],
            case_context="案件事实始于2019年",
            check_conflicts=True,
        ))
        assert result["success"] is True
        # 民法典2021生效，案件事实始于2019年，应检测到溯及力问题
        assert len(result["retroactivity_issues"]) >= 1

    def test_query_empty_names_no_context(self):
        result = json.loads(query_law_database(law_names=[], case_context=""))
        assert result["success"] is True
        assert len(result["matched_laws"]) == 0

    def test_query_priority_order(self):
        result = json.loads(query_law_database(
            law_names=["江苏省工资支付条例", "劳动合同法", "民法典"],
        ))
        assert result["success"] is True
        # 法律 > 司法解释 > 地方性法规
        hierarchies = [r["hierarchy"] for r in result["priority_order"]]
        assert hierarchies.index("法律") < hierarchies.index("地方性法规")


class TestQueryCasePrecedent:
    """Tests for query_case_precedent function."""

    def test_query_labor_case(self):
        result = json.loads(query_case_precedent(
            case_type="劳动争议",
            key_facts=["二倍工资"],
        ))
        assert result["success"] is True
        assert result["case_type"] == "劳动争议"
        assert len(result["precedents"]) >= 1

    def test_query_deviation_points(self):
        result = json.loads(query_case_precedent(
            case_type="劳动争议",
            key_facts=["二倍工资"],
        ))
        assert result["success"] is True
        assert len(result["deviation_points"]) >= 1

    def test_query_conflict_points(self):
        result = json.loads(query_case_precedent(
            case_type="劳动争议",
            key_facts=["待岗"],
        ))
        assert result["success"] is True
        # "违法待岗期间的工资标准" tendency包含"分歧"，应产生conflict_point
        assert len(result["conflict_points"]) >= 1

    def test_query_innovation_space(self):
        result = json.loads(query_case_precedent(
            case_type="劳动争议",
            key_facts=["待岗"],
        ))
        assert result["success"] is True
        if result["conflict_points"]:
            assert len(result["innovation_space"]) >= 1

    def test_query_unknown_case_type(self):
        result = json.loads(query_case_precedent(
            case_type="合同纠纷",
            key_facts=["违约"],
        ))
        assert result["success"] is True
        assert len(result["precedents"]) == 0

    def test_query_no_matching_facts(self):
        result = json.loads(query_case_precedent(
            case_type="劳动争议",
            key_facts=["不存在的关键词"],
        ))
        assert result["success"] is True
        assert len(result["deviation_points"]) == 0


class TestSubmitSupplementaryDoc:
    """Tests for submit_supplementary_doc function."""

    def setup_method(self):
        # Clear shared state before each test
        _supplementary_docs.clear()

    def test_submit_valid_doc(self):
        result = json.loads(submit_supplementary_doc(
            case_id="test-case-001",
            doc_type="law_analysis",
            doc_content="分析内容",
            doc_title="法律适用分析",
        ))
        assert result["success"] is True
        assert result["doc_index"] == 1
        assert result["doc_type_zh"] == "法律适用分析说明"

    def test_submit_multiple_docs(self):
        submit_supplementary_doc(case_id="test-case-002", doc_type="law_analysis", doc_content="doc1")
        result = json.loads(submit_supplementary_doc(
            case_id="test-case-002", doc_type="academic_opinion", doc_content="doc2",
        ))
        assert result["success"] is True
        assert result["doc_index"] == 2
        assert result["total_docs_for_case"] == 2

    def test_submit_invalid_doc_type(self):
        result = json.loads(submit_supplementary_doc(
            case_id="test-case-003",
            doc_type="invalid_type",
            doc_content="content",
        ))
        assert result["success"] is False

    def test_submit_default_authority(self):
        result = json.loads(submit_supplementary_doc(
            case_id="test-case-004",
            doc_type="legal_maxim",
            doc_content="法谚内容",
        ))
        assert result["success"] is True
        assert result["authority_level_zh"] == "参考性"

    def test_submit_binding_authority(self):
        result = json.loads(submit_supplementary_doc(
            case_id="test-case-005",
            doc_type="law_analysis",
            doc_content="约束性文档",
            authority_level="binding",
        ))
        assert result["success"] is True
        assert result["authority_level_zh"] == "约束性"

    def test_submit_default_title(self):
        result = json.loads(submit_supplementary_doc(
            case_id="test-case-006",
            doc_type="frontier_issue",
            doc_content="前沿问题",
        ))
        assert result["success"] is True
        assert "补充文档" in result["title"]


class TestAnalyzeLegalDifficulty:
    """Tests for analyze_legal_difficulty function."""

    def test_basic_analysis(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="用人单位违法待岗",
            legal_issues=["违法待岗期间工资标准"],
        ))
        assert result["success"] is True
        assert len(result["difficulties"]) >= 1

    def test_applicable_principles(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="用人单位违法待岗",
            legal_issues=["违法待岗期间工资标准"],
        ))
        assert result["success"] is True
        assert len(result["applicable_principles"]) >= 1

    def test_ethics_considerations(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="用人单位违法拒绝提供劳动条件",
            legal_issues=["违法待岗"],
        ))
        assert result["success"] is True
        assert len(result["ethics_considerations"]) >= 1

    def test_frontier_analysis(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="新型用工关系",
            legal_issues=["量子计算相关法律问题"],  # unlikely to match any provision
        ))
        assert result["success"] is True
        # Should detect frontier issue since no provisions match
        assert any(d["difficulty_level"] == "frontier" for d in result["difficulties"])

    def test_innovation_space_disabled(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="劳动争议",
            legal_issues=["违法待岗"],
            allow_innovation=False,
        ))
        assert result["success"] is True
        assert len(result["innovation_space"]) == 0

    def test_innovation_space_enabled(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="劳动争议",
            legal_issues=["违法待岗"],
            allow_innovation=True,
        ))
        assert result["success"] is True
        assert len(result["innovation_space"]) >= 1

    def test_constraint_notice_present(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="劳动争议",
            legal_issues=["工资问题"],
        ))
        assert "constraint_notice" in result
        assert "不得突破" in result["constraint_notice"]

    def test_mixed_difficulty_levels(self):
        result = json.loads(analyze_legal_difficulty(
            case_context="劳动争议",
            legal_issues=["工资支付", "量子法律问题"],
        ))
        assert result["success"] is True
        levels = [d["difficulty_level"] for d in result["difficulties"]]
        assert "high" in levels or "frontier" in levels


class TestConcurrencySafety:
    """Tests for thread safety of shared mutable state."""

    def test_pipeline_concurrent_start_complete(self):
        """Multiple threads starting and completing pipeline sessions concurrently."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        mgr = PipelineStateManager(ttl=3600, persist_dir=tempfile.mkdtemp())
        errors = []
        results = []

        def worker(session_suffix: int):
            try:
                sid = f"concurrent-test-{session_suffix}"
                mgr.start(sid, ["dim_a", "dim_b", "dim_c"])
                mgr.complete(sid, "dim_a", f"result-{session_suffix}")
                state = mgr.get(sid)
                return (session_suffix, state)
            except Exception as e:
                errors.append((session_suffix, str(e)))
                return (session_suffix, None)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(worker, i) for i in range(20)]
            for f in as_completed(futures):
                results.append(f.result())

        assert len(errors) == 0, f"Concurrent errors: {errors}"
        # Verify all sessions are independent
        for suffix, state in results:
            assert state is not None, f"Session {suffix} lost"
            assert "dim_a" in state["completed"]

    def test_supplementary_docs_concurrent_submit(self):
        """Multiple threads submitting supplementary docs to the same case_id concurrently."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Use a fresh module-level state by importing and resetting
        from judicial_quality_mcp import law_reference
        original_docs = law_reference._supplementary_docs.copy()
        law_reference._supplementary_docs.clear()

        errors = []
        results = []

        def worker(idx: int):
            try:
                result = json.loads(law_reference.submit_supplementary_doc(
                    case_id="concurrent-case-001",
                    doc_type="law_analysis",
                    doc_content=f"Concurrent doc content #{idx}",
                    doc_title=f"并发测试文档-{idx}",
                ))
                return (idx, result)
            except Exception as e:
                errors.append((idx, str(e)))
                return (idx, None)

        try:
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = [pool.submit(worker, i) for i in range(30)]
                for f in as_completed(futures):
                    results.append(f.result())

            assert len(errors) == 0, f"Concurrent errors: {errors}"
            # All submissions should succeed
            successful = [r for _, r in results if r is not None and r.get("success")]
            assert len(successful) == 30, f"Expected 30 successes, got {len(successful)}"

            # Verify total count is exactly 30 by checking the final state
            with law_reference._docs_lock:
                final_count = len(law_reference._supplementary_docs.get("concurrent-case-001", []))
            assert final_count == 30, f"Expected 30 docs, got {final_count} (race condition?)"
        finally:
            law_reference._supplementary_docs.clear()
            law_reference._supplementary_docs.update(original_docs)

    def test_pipeline_concurrent_same_session(self):
        """Multiple threads completing different dimensions on the same session."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        mgr = PipelineStateManager(ttl=3600, persist_dir=tempfile.mkdtemp())
        sid = "shared-session-001"
        dims = ["dim_1", "dim_2", "dim_3", "dim_4", "dim_5"]
        mgr.start(sid, dims)

        errors = []

        def complete_dim(dim_name: str):
            try:
                state = mgr.complete(sid, dim_name, f"result-{dim_name}")
                return (dim_name, state is not None)
            except Exception as e:
                errors.append((dim_name, str(e)))
                return (dim_name, False)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(complete_dim, d) for d in dims]
            results = [f.result() for f in as_completed(futures)]

        assert len(errors) == 0, f"Concurrent errors: {errors}"
        # All dimensions should be completed
        final_state = mgr.get(sid)
        assert final_state is not None
        for d in dims:
            assert d in final_state["completed"], f"Dimension {d} not completed"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
