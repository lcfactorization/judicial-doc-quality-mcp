"""v0.4.0 claim_support (8th dimension) + P0 fix tests.

Covers:
1. Weight rebalance: 8 dimensions, weights sum to 1.00
2. 08_claim_support.md parseable, uses the same template variables as 06
3. anchors/claim_support_examples.json: excellent/medium/poor levels present
4. R11/R12 cross-check rules exist and can trigger
5. response_parser: 40-point floor only with explicit has_favorable_finding=True,
   score_floor_applied flag reported
6. prompt_builder: claim_support output_schema + framework guidance
7. report_builder: dynamic dimension count, claim_ledger/discretion tables rendered
8. batch_assess: heuristic mock paths gated behind --mock
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from judicial_quality_mcp.config import (
    CROSS_CHECK_RULES,
    DIMENSION_ORDER,
    DIMENSION_TITLES,
    QUALITY_DIMENSIONS,
    QUALITY_WEIGHTS,
)
from judicial_quality_mcp.response_parser import ResponseParser
from judicial_quality_mcp.skill_runner import SkillLoader, TemplateRenderer
from judicial_quality_mcp import prompt_builder
from judicial_quality_mcp import report_builder


def test_weights_sum_to_one_and_eight_dimensions():
    assert len(QUALITY_DIMENSIONS) == 8, f"Expected 8 dimensions, got {len(QUALITY_DIMENSIONS)}"
    assert set(QUALITY_DIMENSIONS) == set(QUALITY_WEIGHTS.keys())
    assert "claim_support" in QUALITY_DIMENSIONS
    total = round(sum(QUALITY_WEIGHTS.values()), 6)
    assert abs(total - 1.00) < 1e-9, f"Weights must sum to 1.00, got {total}"
    assert abs(QUALITY_WEIGHTS["claim_support"] - 0.15) < 1e-9
    assert abs(QUALITY_WEIGHTS["formal_specification"] - 0.03) < 1e-9
    assert abs(QUALITY_WEIGHTS["clear_facts"] - 0.10) < 1e-9
    assert abs(QUALITY_WEIGHTS["sufficient_evidence"] - 0.10) < 1e-9
    assert abs(QUALITY_WEIGHTS["correct_law_application"] - 0.15) < 1e-9
    assert abs(QUALITY_WEIGHTS["thorough_reasoning"] - 0.20) < 1e-9
    assert abs(QUALITY_WEIGHTS["substantive_resolution"] - 0.22) < 1e-9
    assert abs(QUALITY_WEIGHTS["concise_language"] - 0.05) < 1e-9
    assert DIMENSION_TITLES["claim_support"] == "当事人预期与诉请支持度"
    assert DIMENSION_ORDER["claim_support"] == 8
    print("\n✅ weights/dimensions test passed")


def test_dimension_file_loads_with_same_template_vars_as_06():
    loader = SkillLoader()
    meta, body = loader.load("dimensions/claim_support")
    assert meta.name == "claim_support"
    assert meta.title == "当事人预期与诉请支持度"
    assert meta.order == 8
    assert abs(meta.weight - 0.15) < 1e-9
    assert meta.full_score == 100
    assert len(body) > 1000

    # 与 06 维度文件使用相同的模板变量惯例
    _, body_06 = loader.load("dimensions/substantive_resolution")
    import re
    vars_06 = set(re.findall(r"\{\{([_a-zA-Z][_a-zA-Z0-9]*)\}\}", body_06))
    vars_08 = set(re.findall(r"\{\{([_a-zA-Z][_a-zA-Z0-9]*)\}\}", body))
    system_vars = {"_system", "_output_format"}
    assert system_vars.issubset(vars_08), f"missing system vars: {system_vars - vars_08}"
    assert vars_06 - system_vars == vars_08 - system_vars, (
        f"variable mismatch: 06-only={vars_06 - vars_08}, 08-only={vars_08 - vars_06}"
    )
    # 规范依据只引规范文件（法发字号），禁引真实个案案号
    assert "法发〔2018〕10号" in body
    assert "法发〔2024〕16号" in body
    for cs_code in ["CS-B01", "CS-B02", "CS-B03", "CS-B04", "CS-B05",
                    "CS-B06", "CS-B07", "CS-B08", "CS-B09", "CS-B10",
                    "CS-IB01", "CS-IB02", "CS-IB03"]:
        assert cs_code in body, f"{cs_code} missing from 08_claim_support.md"
    print("\n✅ dimension file test passed")


def test_claim_support_anchors_three_levels():
    loader = SkillLoader()
    anchors = loader.load_anchors("claim_support")
    assert len(anchors) == 3, f"Expected 3 anchors, got {len(anchors)}"
    levels = {a["level"]: a for a in anchors}
    assert set(levels) == {"excellent", "medium", "poor"}
    assert levels["excellent"]["score"] >= 90
    assert 60 <= levels["medium"]["score"] <= 70
    assert levels["poor"]["score"] < 40
    for a in anchors:
        assert a.get("quote") and a.get("reasoning")
        assert "claim_ledger" in a and isinstance(a["claim_ledger"], list)
        assert "discretion_points" in a
        assert "expectation_gap" in a
        assert a.get("data_completeness") in ("complete", "partial", "insufficient")
    # 脱敏红线：不得出现完整真实案号
    raw = json.dumps(anchors, ensure_ascii=False)
    assert "（20XX）X民终XXXX号" in raw  # medium 锚点使用占位案号
    import re
    real_case_no = re.findall(r"[（(]20\d{2}[）)][^，。」』\s]{0,10}\d{2,5}号", raw.replace("（20XX）X民终XXXX号", ""))
    assert not real_case_no, f"anchors contain real-looking case numbers: {real_case_no}"
    print("\n✅ anchors test passed")


def test_r11_r12_exist_and_trigger():
    rules = {r["id"]: r for r in CROSS_CHECK_RULES}
    assert "R11" in rules and "R12" in rules
    assert len(CROSS_CHECK_RULES) == 12, f"Expected 12 rules, got {len(CROSS_CHECK_RULES)}"

    # R11: overall_ratio < 0.3 且 thorough_reasoning < 70
    trigger_scores = {"claim_support_overall_ratio": 0.25, "thorough_reasoning": 65,
                      "substantive_resolution": 60, "clear_facts": 60,
                      "sufficient_evidence": 60, "correct_law_application": 60,
                      "concise_language": 60, "formal_specification": 60}
    assert rules["R11"]["check"](trigger_scores) is True
    assert "建议强化说理/判后答疑" in rules["R11"]["message"]

    # R11 不触发：支持率高
    ok_scores = dict(trigger_scores, claim_support_overall_ratio=0.8)
    assert rules["R11"]["check"](ok_scores) is False
    # R11 不触发：说理足够
    ok_scores2 = dict(trigger_scores, thorough_reasoning=75)
    assert rules["R11"]["check"](ok_scores2) is False
    # R11 不触发：无 overall_ratio 数据（缺省1.0）
    no_data = {k: v for k, v in trigger_scores.items() if k != "claim_support_overall_ratio"}
    assert rules["R11"]["check"](no_data) is False

    # R12: CS-B02/B03 命中且审级=二审
    r12_scores = {"trial_stage": "二审", "claim_support_hit_codes": "CS-B02,CS-B05",
                  "thorough_reasoning": 60}
    assert rules["R12"]["check"](r12_scores) is True
    assert "遗漏诉讼请求程序风险提示" in rules["R12"]["message"]
    assert rules["R12"]["check"](dict(r12_codes_b03(), trial_stage="二审")) is True
    # 不触发：一审
    assert rules["R12"]["check"](dict(r12_scores, trial_stage="一审")) is False
    # 不触发：未命中 B02/B03
    assert rules["R12"]["check"]({"trial_stage": "二审", "claim_support_hit_codes": "CS-B05"}) is False
    # 不触发：无数据
    assert rules["R12"]["check"]({}) is False

    # 通过 rule_engine.cross_check_consistency 可触发
    from judicial_quality_mcp.rule_engine import cross_check_consistency as cc
    result = cc({"thorough_reasoning": 60, "claim_support_overall_ratio": 0.2,
                 "trial_stage": "二审", "claim_support_hit_codes": ["CS-B03"]})
    triggered = {c["rule_id"] for c in result["conflicts"]}
    assert "R11" in triggered and "R12" in triggered, f"triggered={triggered}"

    # 通过 server 工具调用（浮点与辅助键保留）也可触发
    from judicial_quality_mcp.server import cross_check_consistency as cc_tool
    tool_result = json.loads(cc_tool({"thorough_reasoning": 60, "claim_support_overall_ratio": 0.25,
                                      "trial_stage": "二审", "claim_support_hit_codes": "CS-B02"}))
    assert tool_result["success"]
    tool_triggered = {c["rule_id"] for c in tool_result["conflicts"]}
    assert "R11" in tool_triggered and "R12" in tool_triggered
    print("\n✅ R11/R12 rules test passed")


def r12_codes_b03():
    return {"trial_stage": "二审", "claim_support_hit_codes": "CS-B03"}


def test_score_floor_only_with_explicit_flag():
    parser = ResponseParser()
    # 极低分：默认（无显式 favorable finding）不托底
    low_scores = {dim: 10 for dim in QUALITY_DIMENSIONS}
    result_default = parser.calculate_weighted_score(low_scores)
    assert result_default["weighted_total"] < 40, "default must NOT apply the 40-point floor"
    assert result_default["score_floor_applied"] is False
    assert result_default["minimum_score_applied"] is False

    # 显式 True：托底生效并带 score_floor_applied 标记
    result_floor = parser.calculate_weighted_score(low_scores, has_favorable_finding=True)
    assert result_floor["weighted_total"] == 40, "explicit favorable finding must raise total to 40"
    assert result_floor["score_floor_applied"] is True
    assert result_floor["minimum_score_applied"] is True

    # 分数本身已达标时不触发托底
    high_scores = {dim: 80 for dim in QUALITY_DIMENSIONS}
    result_high = parser.calculate_weighted_score(high_scores, has_favorable_finding=True)
    assert result_high["score_floor_applied"] is False
    print("\n✅ score floor test passed")


def test_claim_support_prompt_schema_and_framework():
    loader = SkillLoader()
    renderer = TemplateRenderer(loader)
    result = prompt_builder.render_dimension_prompt(
        dimension="claim_support",
        sections={"reasoning_text": "本院认为……", "judgment_main_text": "判决如下……",
                  "judgment_basis_text": "依照……", "plaintiff_claim_text": "原告诉称……",
                  "defendant_defense_text": "被告辩称……", "case_followup_text": ""},
        include_anchors=True,
        anchor_count=3,
        loader=loader,
        renderer=renderer,
    )
    assert result["dimension"] == "claim_support"
    assert result["dimension_title"] == "当事人预期与诉请支持度"
    props = result["output_schema"]["properties"]
    for key in ("claim_ledger", "discretion_points", "expectation_gap",
                "litigation_followup", "data_completeness", "sub_scores"):
        assert key in props, f"output_schema missing {key}"
    assert result["output_schema"]["properties"]["claim_ledger"]["items"]["properties"]["disposition"]["enum"] == \
        ["支持", "部分支持", "驳回", "未回应", "另案"]
    assert "claim_ledger" in result["system_prompt"]
    assert "台账" in result["system_prompt"]
    assert len(result["anchor_examples"]) == 3
    print("\n✅ prompt schema/framework test passed")


def test_report_builder_renders_claim_ledger_tables():
    dim_results = [
        {"dimension": "thorough_reasoning", "score": 60, "deduction_items": [], "bonus_items": []},
        {
            "dimension": "claim_support",
            "score": 65,
            "deduction_items": [{"item": "CS-B03 变更诉请未审理", "deduction": 20,
                                 "quote": "增加的诉讼请求未作处理", "basis": "CS-B03"}],
            "bonus_items": [],
            "claim_ledger": [
                {"claim_id": "CS-1", "type": "给付之诉", "subject": "某劳动者请求支付加班工资",
                 "claimed_amount": 80000, "awarded_amount": 20000, "support_ratio": 0.25,
                 "disposition": "部分支持", "reasoning_quality": "算式透明"},
                {"claim_id": "CS-2", "type": "确认之诉", "subject": "请求确认劳动关系",
                 "claimed_amount": None, "awarded_amount": None, "support_ratio": 1.0,
                 "disposition": "支持", "reasoning_quality": "说理充分"},
            ],
            "discretion_points": [
                {"issue": "加班费计算基数", "legal_basis_cited": "《劳动合同法》第30条",
                 "factors_disclosed": "工资构成", "adversarial_response": "已回应", "grade": "充分"},
            ],
            "expectation_gap": {
                "performance_claims_total": 80000, "awarded_total": 20000,
                "overall_ratio": 0.25, "high_gap_claims": ["CS-1"],
            },
            "litigation_followup": {"internal_signals": "另案处理1件", "external_query": ""},
        },
    ]
    md_json = report_builder.build_report_markdown(
        dimension_results=dim_results,
        weighted_total=60.0,
        grade="D",
        report_id="QA-TEST-CS",
    )
    payload = json.loads(md_json)
    md = payload["report_markdown"]

    # 动态维度计数（8维）
    assert "八维质量评分详情" in md
    assert "八维质量评分体系涵盖" in md
    assert "当事人预期与诉请支持度" in md
    # 诉请台账表
    assert "诉请台账表" in md
    assert "| 诉请编号 | 类型 | 事项 | 请求金额(元) | 判付金额(元) | 支持比例 | 处理结果 | 说理质量 |" in md
    assert "CS-1" in md and "部分支持" in md
    # 裁量点评级表
    assert "裁量点评级表" in md
    assert "加班费计算基数" in md and "充分" in md
    # 预期落差核算
    assert "预期落差核算" in md and "25.0%" in md
    # 无 claim_support 数据时不渲染
    md_json2 = report_builder.build_report_markdown(
        dimension_results=[{"dimension": "thorough_reasoning", "score": 80,
                            "deduction_items": [], "bonus_items": []}],
        weighted_total=88.0, grade="B+", report_id="QA-TEST-NOCS",
    )
    md2 = json.loads(md_json2)["report_markdown"]
    assert "诉请台账表" not in md2
    assert "裁量点评级表" not in md2
    print("\n✅ report builder claim tables test passed")


def test_batch_assess_mock_gating():
    import batch_assess

    # 默认非 mock：启发式打分被禁止
    assert batch_assess.MOCK_MODE is False
    try:
        batch_assess.score_document_quality("text", {"events": [], "anomalies": []}, {}, {})
        raise AssertionError("score_document_quality must raise without --mock")
    except RuntimeError as e:
        assert "mock" in str(e)

    try:
        batch_assess.generate_mock_anomalies("text", "V1")
        raise AssertionError("generate_mock_anomalies must raise without --mock")
    except RuntimeError as e:
        assert "mock" in str(e)

    # mock 模式：可调用且盖章常量正确
    batch_assess.MOCK_MODE = True
    try:
        scores = batch_assess.score_document_quality("某劳动者主张加班工资", {"events": [], "anomalies": []}, {}, {})
        assert set(scores.keys()) == set(QUALITY_DIMENSIONS), "heuristic scores must cover all 8 dimensions"
        mock_anoms = batch_assess.generate_mock_anomalies("加班工资", "V1")
        assert isinstance(mock_anoms, dict) and "evidence" in mock_anoms
    finally:
        batch_assess.MOCK_MODE = False

    assert batch_assess.MOCK_STAMP == "非LLM评分（启发式mock）——不可与LLM评分结果混用"
    stamped = batch_assess._prepend_mock_stamp("# 报告\n内容")
    assert stamped.startswith("> [!Danger]") and "非LLM评分（启发式mock）" in stamped
    html_stamped = batch_assess._prepend_mock_stamp_html("<html><body><p>x</p></body></html>")
    assert "非LLM评分（启发式mock）" in html_stamped
    print("\n✅ batch_assess mock gating test passed")


if __name__ == "__main__":
    test_weights_sum_to_one_and_eight_dimensions()
    test_dimension_file_loads_with_same_template_vars_as_06()
    test_claim_support_anchors_three_levels()
    test_r11_r12_exist_and_trigger()
    test_score_floor_only_with_explicit_flag()
    test_claim_support_prompt_schema_and_framework()
    test_report_builder_renders_claim_ledger_tables()
    test_batch_assess_mock_gating()
    print("\nAll claim_support tests passed.")
