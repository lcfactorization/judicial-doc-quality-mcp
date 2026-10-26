"""v0.4.0 red-flag veto/warning layer tests.

Covers:
1. RF-V1/RF-V2 veto cap (82 -> 59) with F label
2. RF-W1/RF-W2 warning cap (82 -> 74)
3. Red-flag cap beats MINIMUM_SCORE floor (weighted 82 scenario)
4. Report banner rendering with legal refs and endline display
5. administrative_decision mode: AV rule switching + unified consequence text
6. red_flag_candidates field in output schema + nomination discipline in prompts
7. document_type auto-detection from document title
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from judicial_quality_mcp.config import (
    ADMIN_RED_FLAG_RULES,
    DOCUMENT_TYPE_ADMINISTRATIVE,
    DOCUMENT_TYPE_JUDGMENT,
    QUALITY_DIMENSIONS,
    RED_FLAG_RULES,
)
from judicial_quality_mcp.response_parser import ResponseParser
from judicial_quality_mcp.skill_runner import SkillLoader, TemplateRenderer, build_system_prompt
from judicial_quality_mcp import prompt_builder, report_builder, server as server_module


def _scores(value: float) -> dict:
    return {dim: value for dim in QUALITY_DIMENSIONS}


def _cs(deduction_items=None, discretion_points=None, expectation_gap=None):
    data = {"deduction_items": deduction_items or [], "discretion_points": discretion_points or []}
    if expectation_gap is not None:
        data["expectation_gap"] = expectation_gap
    return data


def test_rf_v1_veto_cap_and_f_label():
    parser = ResponseParser()
    result = parser.calculate_weighted_score(
        _scores(82),
        claim_support_result=_cs(
            deduction_items=[{"item": "CS-B03（CS-2）变更/增加诉请未审理且无程序处理",
                              "deduction": 20, "quote": "增加的诉讼请求既未审理亦无程序处理",
                              "basis": "CS-B03"}],
        ),
    )
    assert result["weighted_raw_score"] == 82.0
    assert result["final_score"] == 59.0
    assert result["weighted_total"] == 59.0
    assert result["grade"] == "F"
    assert result["red_flag_level"] == "veto"
    flag = next(f for f in result["red_flags"] if f["rule_id"] == "RF-V1")
    assert flag["level"] == "veto"
    assert "发回重审" in flag["consequence"]
    assert any("第一百七十七条" in ref for ref in flag["legal_refs"])
    assert "CS-2" in flag["claim_ref"]
    assert "CS-B03" in flag["evidence"]
    print("\n✅ RF-V1 veto cap test passed (82 -> 59, F)")


def test_rf_v2_two_paths():
    parser = ResponseParser()
    # 路径1：CS-B02 命中 >= 2 项
    r1 = parser.calculate_weighted_score(
        _scores(80),
        claim_support_result=_cs(deduction_items=[
            {"item": "CS-B02（CS-1）诉请零回应", "deduction": 15, "quote": "q1", "basis": "CS-B02"},
            {"item": "CS-B02（CS-3）诉请零回应", "deduction": 15, "quote": "q2", "basis": "CS-B02"},
        ]),
    )
    ids1 = {f["rule_id"] for f in r1["red_flags"]}
    assert "RF-V2" in ids1 and r1["final_score"] == 59.0
    # 单项 CS-B02 不触发
    r1b = parser.calculate_weighted_score(
        _scores(80),
        claim_support_result=_cs(deduction_items=[
            {"item": "CS-B02（CS-1）诉请零回应", "deduction": 15, "quote": "q1", "basis": "CS-B02"},
        ]),
    )
    assert "RF-V2" not in {f["rule_id"] for f in r1b["red_flags"]}
    # 路径2：联动输入 A9/critical 程序类
    r2 = parser.calculate_weighted_score(
        _scores(80),
        red_flag_inputs={"findings": [{"code": "A9", "severity": "critical",
                                       "type": "procedural_anomaly", "description": "剥夺辩论权"}]},
    )
    ids2 = {f["rule_id"] for f in r2["red_flags"]}
    assert "RF-V2" in ids2 and r2["final_score"] == 59.0
    print("\n✅ RF-V2 dual-path test passed")


def test_rf_w_cap74():
    parser = ResponseParser()
    # RF-W1: CS-B05 命中且关联诉请 ∈ high_gap_claims
    r1 = parser.calculate_weighted_score(
        _scores(82),
        claim_support_result=_cs(
            deduction_items=[{"item": "CS-B05（CS-2）结论式驳斥", "deduction": 15,
                              "quote": "于法无据，不予支持", "basis": "CS-B05"}],
            expectation_gap={"performance_claims_total": 80000, "awarded_total": 0,
                             "overall_ratio": 0.0, "high_gap_claims": ["CS-2"]},
        ),
    )
    assert "RF-W1" in {f["rule_id"] for f in r1["red_flags"]}
    assert r1["final_score"] == 74.0 and r1["red_flag_level"] == "warning"
    # RF-W2: overall_ratio<0.3 且 thorough_reasoning<70
    scores = _scores(82)
    scores["thorough_reasoning"] = 65
    r2 = parser.calculate_weighted_score(
        scores,
        claim_support_result=_cs(expectation_gap={"overall_ratio": 0.2}),
    )
    assert "RF-W2" in {f["rule_id"] for f in r2["red_flags"]}
    assert r2["final_score"] == 74.0
    # RF-W2 不触发：说理足够
    scores2 = _scores(82)
    r2b = parser.calculate_weighted_score(
        scores2,
        claim_support_result=_cs(expectation_gap={"overall_ratio": 0.2}),
    )
    assert "RF-W2" not in {f["rule_id"] for f in r2b["red_flags"]}
    assert r2b["final_score"] == 82.0
    print("\n✅ RF-W cap-74 test passed")


def test_red_flag_beats_floor():
    parser = ResponseParser()
    # 加权 82 + 显式托底 + Veto：红旗赢，终分 59 而非 82
    r = parser.calculate_weighted_score(
        _scores(82),
        has_favorable_finding=True,
        claim_support_result=_cs(deduction_items=[
            {"item": "CS-B03（CS-2）变更诉请未审理", "deduction": 20, "quote": "q", "basis": "CS-B03"},
        ]),
    )
    assert r["weighted_raw_score"] == 82.0
    assert r["final_score"] == 59.0
    assert r["score_floor_applied"] is False  # 82 不需要托底
    # 加权 30 + 显式托底 + Veto：托底先到 40，红旗封顶 min(40,59)=40，红旗仍并列展示
    r_low = parser.calculate_weighted_score(
        _scores(30),
        has_favorable_finding=True,
        claim_support_result=_cs(deduction_items=[
            {"item": "CS-B03（CS-2）变更诉请未审理", "deduction": 20, "quote": "q", "basis": "CS-B03"},
        ]),
    )
    assert r_low["weighted_raw_score"] == 30.0
    assert r_low["final_score"] == 40.0
    assert r_low["score_floor_applied"] is True
    assert r_low["red_flag_level"] == "veto"
    # 无红旗时托底行为不变：82 + favorable → 82
    r_plain = parser.calculate_weighted_score(_scores(82), has_favorable_finding=True)
    assert r_plain["final_score"] == 82.0 and not r_plain["red_flags"]
    print("\n✅ floor vs red-flag conflict test passed (82 -> 59, red flag wins)")


def test_report_banner_and_endline():
    parser = ResponseParser()
    result = parser.calculate_weighted_score(
        _scores(82),
        claim_support_result=_cs(deduction_items=[
            {"item": "CS-B03（CS-2）变更/增加诉请未审理", "deduction": 20,
             "quote": "庭审增加的诉讼请求未作处理", "basis": "CS-B03"},
        ]),
    )
    dim_results = [{"dimension": dim, "score": 82, "deduction_items": [], "bonus_items": []}
                   for dim in QUALITY_DIMENSIONS]
    md = json.loads(report_builder.build_report_markdown(
        dimension_results=dim_results,
        weighted_total=result["final_score"],
        grade=result["grade"],
        red_flags=result["red_flags"],
        weighted_raw_score=result["weighted_raw_score"],
        report_id="QA-FLAG-TEST",
        document_meta={"案号": "（20XX）X民终XXXX号", "法院": "某市中级人民法院"},
    ))["report_markdown"]
    assert "🚩" in md and "红旗预警与一票否决" in md
    assert "RF-V1（一票否决级）" in md
    assert "证据摘录" in md and "CS-B03" in md
    assert "后果" in md and "发回重审" in md
    assert "法条依据" in md and "《民事诉讼法》第一百七十七条第一款第四项" in md
    assert "加权 **82** → 终评 **59**（红旗封顶）" in md
    assert "F（红旗）" in md
    # 仅 Warning 级：⚠️ 图标与 C+（预警）标注
    r_w = parser.calculate_weighted_score(
        _scores(82),
        claim_support_result=_cs(
            deduction_items=[{"item": "CS-B05（CS-2）结论式驳斥", "deduction": 15,
                              "quote": "q", "basis": "CS-B05"}],
            expectation_gap={"overall_ratio": 0.1, "high_gap_claims": ["CS-2"]},
        ),
    )
    md2 = json.loads(report_builder.build_report_markdown(
        dimension_results=dim_results,
        weighted_total=r_w["final_score"],
        grade=r_w["grade"],
        red_flags=r_w["red_flags"],
        weighted_raw_score=r_w["weighted_raw_score"],
        report_id="QA-FLAG-W",
    ))["report_markdown"]
    assert "⚠️" in md2 and "C+（预警）" in md2
    assert "加权 **82** → 终评 **74**（红旗封顶）" in md2
    # 无红旗时保持原展示
    md3 = json.loads(report_builder.build_report_markdown(
        dimension_results=dim_results, weighted_total=88.0, grade="B+",
        report_id="QA-NOFLAG",
    ))["report_markdown"]
    assert "红旗" not in md3.split("八维质量评分详情")[0].split("综合评级")[0] or "红旗预警与一票否决" not in md3
    print("\n✅ banner/endline rendering test passed")


def test_administrative_mode():
    parser = ResponseParser()
    # AV1: sufficient_evidence < 60 → Veto 59 + 统一文案 + 双法条
    scores = _scores(80)
    scores["sufficient_evidence"] = 55
    r1 = parser.calculate_weighted_score(scores, document_type=DOCUMENT_TYPE_ADMINISTRATIVE)
    av1 = next(f for f in r1["red_flags"] if f["rule_id"] == "AV1")
    assert r1["final_score"] == 59.0 and r1["grade"] == "F"
    assert "存在被行政复议撤销/变更" in av1["consequence"]
    assert any("《行政诉讼法》第七十条第一项" in ref for ref in av1["legal_refs"])
    assert any("《行政复议法》（2023修订）第六十四条第一项" in ref for ref in av1["legal_refs"])
    # AV2 双路径：分数 OR H-2 critical
    scores2 = _scores(80)
    scores2["correct_law_application"] = 58
    r2 = parser.calculate_weighted_score(scores2, document_type=DOCUMENT_TYPE_ADMINISTRATIVE)
    assert "AV2" in {f["rule_id"] for f in r2["red_flags"]}
    r2b = parser.calculate_weighted_score(
        _scores(80),
        document_type=DOCUMENT_TYPE_ADMINISTRATIVE,
        red_flag_inputs={"findings": [{"code": "H-2", "severity": "critical",
                                       "description": "引用已废止条文"}]},
    )
    assert "AV2" in {f["rule_id"] for f in r2b["red_flags"]}
    # AV4: 裁量点 issue 含职权类且 grade 不充分
    r4 = parser.calculate_weighted_score(
        _scores(80),
        document_type=DOCUMENT_TYPE_ADMINISTRATIVE,
        claim_support_result=_cs(discretion_points=[
            {"issue": "处罚幅度超越职权裁量", "legal_basis_cited": "", "factors_disclosed": "",
             "adversarial_response": "", "grade": "不充分"},
        ]),
    )
    assert "AV4" in {f["rule_id"] for f in r4["red_flags"]}
    assert r4["final_score"] == 59.0
    # AV6: CS-B08 类案偏离 → Warning 74
    r6 = parser.calculate_weighted_score(
        _scores(80),
        document_type=DOCUMENT_TYPE_ADMINISTRATIVE,
        claim_support_result=_cs(deduction_items=[
            {"item": "CS-B08 裁判口径偏离类案", "deduction": 10, "quote": "q", "basis": "CS-B08"},
        ]),
    )
    assert "AV6" in {f["rule_id"] for f in r6["red_flags"]}
    assert r6["final_score"] == 74.0 and r6["red_flag_level"] == "warning"
    # 模式隔离：判决模式规则（RF-V1）不在行政模式评估；行政规则不在判决模式评估
    cs_b03 = _cs(deduction_items=[{"item": "CS-B03（CS-2）变更诉请未审理", "deduction": 20,
                                   "quote": "q", "basis": "CS-B03"}])
    r_j = parser.calculate_weighted_score(_scores(80), claim_support_result=cs_b03,
                                          document_type=DOCUMENT_TYPE_JUDGMENT)
    assert {f["rule_id"] for f in r_j["red_flags"]} == {"RF-V1"}
    r_a = parser.calculate_weighted_score(_scores(80), claim_support_result=cs_b03,
                                          document_type=DOCUMENT_TYPE_ADMINISTRATIVE)
    assert "RF-V1" not in {f["rule_id"] for f in r_a["red_flags"]}
    assert not any(f["rule_id"].startswith("RF-") for f in r_a["red_flags"])
    # 行政模式统一文案出现在每条 AV 红旗
    assert all("存在被行政复议撤销/变更" in f["consequence"] for f in r_a["red_flags"]) or not r_a["red_flags"]
    print("\n✅ administrative mode test passed")


def test_red_flag_candidates_schema_and_discipline():
    loader = SkillLoader()
    renderer = TemplateRenderer(loader)
    result = prompt_builder.render_dimension_prompt(
        dimension="thorough_reasoning", sections={}, include_anchors=False,
        loader=loader, renderer=renderer,
    )
    cands = result["output_schema"]["properties"]["red_flag_candidates"]
    assert cands["items"]["required"] == ["item", "quote", "reason", "suggested_level"]
    assert cands["items"]["properties"]["suggested_level"]["enum"] == ["veto", "warning"]
    assert "红旗提名纪律" in result["system_prompt"]
    assert "宁缺毋滥" in result["system_prompt"]
    # skill_runner 版 system prompt 同样包含
    meta, _ = loader.load("dimensions/thorough_reasoning")
    sp = build_system_prompt(meta)
    assert "红旗提名纪律" in sp and "red_flag_candidates" in sp
    print("\n✅ red_flag_candidates schema/discipline test passed")


def test_document_type_autodetect():
    # 行政决定书标题
    assert server_module._infer_document_type(
        {"标题": "某局行政处罚决定书"}) == DOCUMENT_TYPE_ADMINISTRATIVE
    assert server_module._infer_document_type(
        {"案号": "X复决字〔20XX〕X号", "标题": "行政复议决定书"}) == DOCUMENT_TYPE_ADMINISTRATIVE
    assert server_module._infer_document_type(
        {"标题": "责令改正通知书"}) == DOCUMENT_TYPE_ADMINISTRATIVE
    # 判决/裁定
    assert server_module._infer_document_type(
        {"标题": "民事判决书"}) == DOCUMENT_TYPE_JUDGMENT
    assert server_module._infer_document_type(
        {"标题": "行政裁定书"}) == DOCUMENT_TYPE_JUDGMENT
    # 无命中 → 判决默认
    assert server_module._infer_document_type({"案号": "（20XX）X民终XXXX号"}) == DOCUMENT_TYPE_JUDGMENT
    assert server_module._infer_document_type(None) == DOCUMENT_TYPE_JUDGMENT
    # 规则集存在性与结构
    assert {r["id"] for r in RED_FLAG_RULES} == {"RF-V1", "RF-V2", "RF-V3", "RF-V4",
                                                 "RF-W1", "RF-W2", "RF-W3"}
    assert {r["id"] for r in ADMIN_RED_FLAG_RULES} == {"AV1", "AV2", "AV3", "AV4", "AV5", "AV6"}
    assert all(r["level"] in ("veto", "warning") for r in RED_FLAG_RULES + ADMIN_RED_FLAG_RULES)
    veto_ids = {r["id"] for r in ADMIN_RED_FLAG_RULES if r["level"] == "veto"}
    assert veto_ids == {"AV1", "AV2", "AV3", "AV4", "AV5"}
    print("\n✅ document-type autodetect/rules test passed")


if __name__ == "__main__":
    test_rf_v1_veto_cap_and_f_label()
    test_rf_v2_two_paths()
    test_rf_w_cap74()
    test_red_flag_beats_floor()
    test_report_banner_and_endline()
    test_administrative_mode()
    test_red_flag_candidates_schema_and_discipline()
    test_document_type_autodetect()
    print("\nAll red-flag tests passed.")
