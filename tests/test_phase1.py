"""End-to-end test for Phase 1 MVP — All 7 Dimensions

Tests cover:
1. SkillLoader & TemplateRenderer (all 7 dimensions)
2. Anchor loading (all 7 dimensions)
3. ResponseParser (including JSON tolerance)
4. Cross-check consistency (10 rules)
5. Document section extraction
6. render_dimension_prompt (core tool, all 7 dimensions)
7. parse_score_result with mock LLM responses
8. calculate_weighted_score with anomaly deduction & innovation bonus
9. apply_anomaly_deduction & apply_innovation_bonus tools
10. generate_report tool
11. Full pipeline dry-run (all 7 dimensions)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from judicial_quality_mcp.skill_runner import SkillLoader, TemplateRenderer, build_system_prompt
from judicial_quality_mcp.response_parser import ResponseParser
from judicial_quality_mcp.config import (
    ANOMALY_DEDUCTION,
    ANOMALY_TOTAL_MAX_DEDUCTION,
    CROSS_CHECK_RULES,
    INNOVATION_BONUS,
    INNOVATION_TOTAL_MAX_BONUS,
    QUALITY_WEIGHTS,
)


SAMPLE_DOC = """
（2023）苏0602民初1234号

原告张某诉称：原告于2020年3月1日入职被告某科技有限公司，担任软件工程师，月工资12000元。入职以来，被告从未与原告签订书面劳动合同，也未依法为原告缴纳社会保险。2023年8月31日，被告以"公司业务调整"为由口头通知原告解除劳动关系，未支付任何经济补偿。原告请求：一、确认原告与被告自2020年3月1日至2023年8月31日期间存在劳动关系；二、被告支付未签订书面劳动合同二倍工资差额44000元；三、被告支付解除劳动关系经济补偿金18000元；四、被告为原告办理社会保险补缴手续。

被告某科技有限公司辩称：原告系劳务关系而非劳动关系，被告无需签订书面劳动合同。原告系主动离职，被告无需支付经济补偿金。关于社会保险，被告同意配合办理。

本院查明：原告于2020年3月1日起在被告处从事软件研发工作，接受被告的考勤管理，按月领取报酬。原告提交的考勤记录、银行流水、微信工作群聊天记录相互印证，足以证明原告与被告之间存在劳动关系。被告虽辩称系劳务关系，但未能提交劳务协议等证据予以证明。

上述事实，有原告提交的考勤记录、银行流水、微信工作群聊天记录、证人张某的证言等证据在卷佐证。

本院认为，关于劳动关系的认定，根据《中华人民共和国劳动合同法》第七条规定，用人单位自用工之日起即与劳动者建立劳动关系。本案中，原告接受被告的考勤管理、按月领取报酬，符合劳动关系的基本特征。被告辩称系劳务关系，但未提交劳务协议等证据，其抗辩理由不能成立。关于未签订书面劳动合同的二倍工资差额，根据《中华人民共和国劳动合同法》第八十二条规定，用人单位自用工之日起超过一个月不满一年未与劳动者订立书面劳动合同的，应当向劳动者每月支付二倍的工资。被告自用工之日起未与原告签订书面劳动合同，应支付二倍工资差额。关于经济补偿金，被告以"公司业务调整"为由解除劳动关系，属于《中华人民共和国劳动合同法》第四十条规定的情形，应当支付经济补偿金。依照《中华人民共和国劳动合同法》第七条、第十条、第八十二条、第四十六条、第四十七条，《中华人民共和国社会保险法》第五十八条之规定，判决如下：

一、确认原告张某与被告某科技有限公司自2020年3月1日至2023年8月31日期间存在劳动关系；
二、被告于本判决生效之日起十日内支付原告未签订书面劳动合同二倍工资差额44000元；
三、被告于本判决生效之日起十日内支付原告解除劳动关系经济补偿金18000元；
四、被告于本判决生效之日起十日内为原告办理社会保险补缴手续；
五、驳回原告其他诉讼请求。
"""

MOCK_LLM_RESPONSE_REASONING = json.dumps({
    "quote": "关于劳动关系的认定，根据《中华人民共和国劳动合同法》第七条规定，用人单位自用工之日起即与劳动者建立劳动关系。本案中，原告接受被告的考勤管理、按月领取报酬，符合劳动关系的基本特征。",
    "reasoning": "说理逐层展开，对劳动关系认定、二倍工资差额、经济补偿金三个焦点逐一论证，但部分说理略显模板化",
    "score": 78,
    "deduction_items": [
        {
            "item": "R-07 说理模板化",
            "deduction": 8,
            "quote": "其抗辩理由不能成立",
            "basis": "对被告抗辩的否定过于简单，未深入分析劳务关系与劳动关系的区分标准"
        },
        {
            "item": "R-09 对抗辩意见仅简单否定",
            "deduction": 8,
            "quote": "被告辩称系劳务关系，但未提交劳务协议等证据，其抗辩理由不能成立",
            "basis": "仅以证据缺失否定抗辩，未从法律层面分析劳务关系与劳动关系的本质区别"
        }
    ],
    "bonus_items": [
        {
            "item": "R-B01 争议焦点逐一回应",
            "bonus": 8,
            "quote": "关于劳动关系的认定……关于未签订书面劳动合同的二倍工资差额……关于经济补偿金……",
            "reason": "三个争议焦点均有独立论证段落"
        },
        {
            "item": "R-B02 多层次说理",
            "bonus": 5,
            "quote": "根据《中华人民共和国劳动合同法》第七条规定……符合劳动关系的基本特征",
            "reason": "综合运用事理（事实认定）和法理（法条适用）"
        }
    ],
    "innovation_bonus_items": [],
    "five_principles_assessment": {
        "事理": "评估等级：良，事实认定清晰但未深入分析",
        "法理": "评估等级：良，法条引用正确但解释不够深入",
        "学理": "评估等级：中，未引用学理支撑",
        "情理": "评估等级：中，未体现司法温度",
        "文理": "评估等级：良，说理层次分明"
    }
}, ensure_ascii=False)

MOCK_LLM_RESPONSE_SUBSTANTIVE = json.dumps({
    "quote": "一、确认原告张某与被告某科技有限公司自2020年3月1日至2023年8月31日期间存在劳动关系；二、被告于本判决生效之日起十日内支付原告未签订书面劳动合同二倍工资差额44000元；",
    "reasoning": "判决主文明确具体，五个判项逐一列明，确认之诉与给付之诉分离处理，但社会保险补缴判项可执行性略有瑕疵",
    "score": 82,
    "data_completeness": "partial",
    "sub_scores": {
        "服判息诉效果": {"score": 27, "max": 30, "items": ["SR-01: +30（全部诉讼请求均作裁判）", "扣除3分：社保补缴判项可能引发执行争议"]},
        "矛盾化解程度": {"score": 20, "max": 25, "items": ["SR-06: +25（论证回应了核心诉求）", "扣除5分：部分争议焦点说理可更充分"]},
        "法律适用创新性": {"score": 10, "max": 20, "items": ["SR-12: +10（法律适用正确但无创新）"]},
        "价值衡量与社会效果": {"score": 12, "max": 15, "items": ["SR-14: +8（考量了劳动者权益保护）", "SR-15: +4（维护了劳动法秩序）"]},
        "可执行性": {"score": 8, "max": 10, "items": ["SR-18: +10（判决主文明确可操作）", "扣除2分：社保补缴判项可执行性略有瑕疵"]}
    },
    "deduction_items": [],
    "bonus_items": [
        {
            "item": "SR-10 对法律空白或冲突有创新性解释",
            "bonus": 0,
            "quote": "",
            "reason": "本案法律适用保守但正确，无创新性解释"
        }
    ],
    "innovation_bonus_items": [],
    "anomaly_deduction_items": []
}, ensure_ascii=False)

MOCK_LLM_RESPONSE_REASONING_INNOVATIVE = json.dumps({
    "quote": "关于新型用工关系的认定，虽然现行法律未对'平台用工'模式作出明确规定，但本院认为，判断是否构成劳动关系，不应仅以形式上的合同名称为依据，而应从实质上考察劳动者对用人单位的从属性。本案中，原告虽与被告签订了'合作协议'，但从实际履行情况看……",
    "reasoning": "说理极具创新性：在法律空白领域通过目的解释方法填补漏洞，创造性提出'实质从属性'判断标准，打破仅看合同名称的形式审查框架",
    "score": 92,
    "deduction_items": [],
    "bonus_items": [
        {
            "item": "R-B01 争议焦点逐一回应",
            "bonus": 10,
            "quote": "关于新型用工关系的认定……关于劳动报酬的计算……关于社会保险的补缴……",
            "reason": "所有争议焦点逐一深入论证"
        },
        {
            "item": "R-B02 多层次说理",
            "bonus": 8,
            "quote": "不应仅以形式上的合同名称为依据，而应从实质上考察劳动者对用人单位的从属性",
            "reason": "综合运用事理、法理、学理、情理、文理五理说理"
        },
        {
            "item": "R-B04 价值衡量公开",
            "bonus": 5,
            "quote": "判断是否构成劳动关系，不应仅以形式上的合同名称为依据",
            "reason": "公开进行形式正义与实质正义的利益衡量"
        }
    ],
    "innovation_bonus_items": [
        {
            "item": "R-IB02 法律漏洞填补",
            "bonus": 10,
            "quote": "虽然现行法律未对'平台用工'模式作出明确规定，但本院认为……",
            "reason": "在法律空白领域通过目的解释方法填补漏洞，创造性解决新型用工关系认定问题"
        },
        {
            "item": "R-IB03 创造性突破既有框架/打破陈规",
            "bonus": 12,
            "quote": "不应仅以形式上的合同名称为依据，而应从实质上考察劳动者对用人单位的从属性",
            "reason": "打破仅看合同名称的形式审查框架，建立实质从属性判断标准"
        },
        {
            "item": "R-IB04 体现司法底层逻辑",
            "bonus": 7,
            "quote": "判断是否构成劳动关系……从实质上考察",
            "reason": "裁判深刻体现了公平正义、权利保障的司法底层逻辑，而非机械适用法条"
        }
    ],
    "five_principles_assessment": {
        "事理": "评估等级：优，事实认定深入细致",
        "法理": "评估等级：优，法条解释创新且正当",
        "学理": "评估等级：优，目的解释方法运用得当",
        "情理": "评估等级：良，体现了对劳动者的关怀",
        "文理": "评估等级：优，说理方式综合且流畅"
    }
}, ensure_ascii=False)

MOCK_ANOMALY_RESULTS = [
    {
        "type": "procedural_anomaly",
        "severity": "medium",
        "description": "法院未对原告提出的调查取证申请作出回应",
        "evidence": "原告在庭审中申请法院调取被告的工资发放记录，但判决书未予回应",
        "reasoning": "当事人申请法院调查取证，法院应当作出是否准许的决定"
    },
    {
        "type": "evidence_anomaly",
        "severity": "high",
        "description": "对关键证据的采信缺乏说理",
        "evidence": "被告提交的《合作协议》未被采信，但判决书未说明不予采信的理由",
        "reasoning": "证据不予采信应当说明理由"
    },
    {
        "type": "fact_anomaly",
        "severity": "low",
        "description": "事实认定中遗漏了部分时间节点",
        "evidence": "原告主张2020年3月1日入职，但未查明具体入职日期的证据",
        "reasoning": "入职时间认定仅有原告单方陈述"
    }
]

MOCK_INNOVATION_ITEMS = [
    {
        "type": "legal_gap_filling",
        "bonus": 10,
        "description": "在法律空白领域通过目的解释方法填补漏洞，创造性解决新型用工关系认定问题",
        "quote": "虽然现行法律未对'平台用工'模式作出明确规定，但本院认为……"
    },
    {
        "type": "framework_breakthrough",
        "bonus": 12,
        "description": "打破仅看合同名称的形式审查框架，建立实质从属性判断标准",
        "quote": "不应仅以形式上的合同名称为依据，而应从实质上考察劳动者对用人单位的从属性"
    },
    {
        "type": "judicial_logic",
        "bonus": 7,
        "description": "裁判深刻体现了公平正义、权利保障的司法底层逻辑",
        "quote": "判断是否构成劳动关系……从实质上考察"
    }
]


ALL_DIMENSIONS = [
    "formal_specification",
    "clear_facts",
    "sufficient_evidence",
    "correct_law_application",
    "thorough_reasoning",
    "substantive_resolution",
    "concise_language",
]


def test_skill_loader():
    print("=" * 60)
    print("Test 1: SkillLoader (All 7 Dimensions)")
    print("=" * 60)

    loader = SkillLoader()

    dims = loader.list_dimensions()
    print(f"Found {len(dims)} dimensions:")
    for d in dims:
        print(f"  - {d['name']}: {d['title']} (weight={d['weight']}, full_score={d['full_score']})")

    assert len(dims) == 7, f"Expected 7 dimensions, got {len(dims)}"

    for dim_name in ALL_DIMENSIONS:
        meta, body = loader.load(f"dimensions/{dim_name}")
        print(f"\nLoaded {dim_name}:")
        print(f"  title={meta.title}, weight={meta.weight}, full_score={meta.full_score}")
        assert meta.name == dim_name, f"Expected name={dim_name}, got {meta.name}"
        assert len(body) > 100, f"Body too short for {dim_name}: {len(body)}"

    print("\n✅ SkillLoader test passed\n")


def test_template_renderer():
    print("=" * 60)
    print("Test 2: TemplateRenderer")
    print("=" * 60)

    loader = SkillLoader()
    renderer = TemplateRenderer(loader)

    meta, body = loader.load("dimensions/thorough_reasoning")

    variables = {
        "reasoning_text": "本院认为，关于劳动关系的认定...",
        "judgment_basis_text": "依照《中华人民共和国劳动合同法》...",
        "judgment_main_text": "判决如下：一、确认...",
        "plaintiff_claim_text": "原告诉称...",
        "defendant_defense_text": "被告辩称...",
    }

    rendered = renderer.render(body, variables)
    print(f"Rendered length: {len(rendered)} chars")
    assert "本院认为，关于劳动关系的认定..." in rendered
    assert "{{reasoning_text}}" not in rendered

    system_prompt = build_system_prompt(meta)
    print(f"System prompt length: {len(system_prompt)} chars")
    assert "说理充分透彻" in system_prompt

    print("\n✅ TemplateRenderer test passed\n")


def test_anchor_loading():
    print("=" * 60)
    print("Test 3: Anchor Loading (All 7 Dimensions)")
    print("=" * 60)

    loader = SkillLoader()

    for dim_name in ALL_DIMENSIONS:
        anchors = loader.load_anchors(dim_name)
        print(f"\n{dim_name} anchors: {len(anchors)}")
        for a in anchors:
            print(f"  - [{a['level']}] score={a['score']}: {a['reasoning'][:60]}...")
        assert len(anchors) >= 3, f"Expected at least 3 anchors for {dim_name}, got {len(anchors)}"

    print("\n✅ Anchor Loading test passed\n")


def test_response_parser():
    print("=" * 60)
    print("Test 4: ResponseParser")
    print("=" * 60)

    parser = ResponseParser()

    valid_response = json.dumps({
        "quote": "本院认为，关于劳动关系的认定...",
        "reasoning": "说理逐层展开，逻辑严密",
        "score": 85,
        "deduction_items": [
            {"item": "R-07 说理模板化", "deduction": 5, "quote": "...", "basis": "部分段落模板化"}
        ],
        "bonus_items": [
            {"item": "R-B01 争议焦点逐一回应", "bonus": 8, "quote": "...", "reason": "三个焦点逐一论证"}
        ],
    })

    result = parser.parse_score_result("thorough_reasoning", valid_response)
    print(f"Parsed score: {result['parsed'].get('score')}")
    print(f"Validation: {result['validation']}")
    assert result["validation"]["format_valid"]
    assert result["validation"]["score_in_bounds"]
    assert result["validation"]["required_fields_present"]

    out_of_bounds = json.dumps({"quote": "test", "reasoning": "test", "score": 150})
    result2 = parser.parse_score_result("thorough_reasoning", out_of_bounds)
    print(f"\nOut-of-bounds score calibrated to: {result2['parsed'].get('score')}")
    assert result2["parsed"]["score"] == 100

    weighted = parser.calculate_weighted_score({
        "thorough_reasoning": 85,
        "substantive_resolution": 70,
    })
    print(f"\nWeighted total: {weighted['weighted_total']}, grade: {weighted['grade']}")
    assert weighted["grade"] in ["A", "B", "C", "D", "F"]

    print("\n✅ ResponseParser test passed\n")


def test_json_tolerance():
    print("=" * 60)
    print("Test 5: JSON Tolerance (Robustness)")
    print("=" * 60)

    parser = ResponseParser()

    markdown_wrapped = '```json\n{"quote": "test", "reasoning": "test", "score": 75}\n```'
    result = parser.parse_score_result("thorough_reasoning", markdown_wrapped)
    print(f"Markdown-wrapped JSON: parsed={result['validation']['format_valid']}, score={result['parsed'].get('score')}")
    assert result["validation"]["format_valid"]
    assert result["parsed"]["score"] == 75

    trailing_comma = '{"quote": "test", "reasoning": "test", "score": 80,}'
    result2 = parser.parse_score_result("thorough_reasoning", trailing_comma)
    print(f"Trailing comma JSON: parsed={result2['validation']['format_valid']}, score={result2['parsed'].get('score')}")
    assert result2["validation"]["format_valid"]

    with_chatter = 'Here is my assessment:\n{"quote": "test", "reasoning": "test", "score": 65}\nHope this helps!'
    result3 = parser.parse_score_result("thorough_reasoning", with_chatter)
    print(f"JSON with chatter: parsed={result3['validation']['format_valid']}, score={result3['parsed'].get('score')}")
    assert result3["validation"]["format_valid"]
    assert result3["parsed"]["score"] == 65

    single_quotes = "{'quote': 'test', 'reasoning': 'test', 'score': 70}"
    result4 = parser.parse_score_result("thorough_reasoning", single_quotes)
    print(f"Single-quoted JSON: parsed={result4['validation']['format_valid']}, score={result4['parsed'].get('score')}")
    assert result4["validation"]["format_valid"]

    print("\n✅ JSON Tolerance test passed\n")


def test_cross_check():
    print("=" * 60)
    print("Test 6: Cross Check Consistency")
    print("=" * 60)

    consistent_scores = {
        "thorough_reasoning": 75,
        "substantive_resolution": 70,
        "correct_law_application": 80,
        "clear_facts": 72,
        "sufficient_evidence": 68,
    }

    for rule in CROSS_CHECK_RULES:
        triggered = rule["check"](consistent_scores)
        print(f"  {rule['id']} {rule['name']}: {'TRIGGERED' if triggered else 'OK'}")

    inconsistent_scores = {
        "thorough_reasoning": 90,
        "correct_law_application": 45,
        "clear_facts": 55,
        "sufficient_evidence": 80,
        "substantive_resolution": 85,
    }

    conflicts = []
    for rule in CROSS_CHECK_RULES:
        if rule["check"](inconsistent_scores):
            conflicts.append(rule["id"])
    print(f"\nInconsistent scores triggered rules: {conflicts}")
    assert len(conflicts) >= 2, f"Expected at least 2 conflicts, got {len(conflicts)}"

    print("\n✅ Cross Check test passed\n")


def test_extract_sections():
    print("=" * 60)
    print("Test 7: Extract Document Sections")
    print("=" * 60)

    from judicial_quality_mcp.server import extract_document_sections

    result_json = extract_document_sections(SAMPLE_DOC)
    result = json.loads(result_json)

    print(f"plaintiff_claim: {result.get('plaintiff_claim', '')[:50]}...")
    print(f"defendant_defense: {result.get('defendant_defense', '')[:50]}...")
    print(f"court_finding: {result.get('court_finding', '')[:50]}...")
    print(f"reasoning: {result.get('reasoning', '')[:50]}...")
    print(f"judgment_basis: {result.get('judgment_basis', '')[:50]}...")
    print(f"judgment_main: {result.get('judgment_main', '')[:50]}...")
    print(f"case_info: {result.get('case_info', {})}")
    print(f"extraction_confidence: {result.get('extraction_confidence', 0)}")

    assert len(result.get("plaintiff_claim", "")) > 10
    assert len(result.get("reasoning", "")) > 10
    assert result.get("extraction_confidence", 0) > 0.5

    print("\n✅ Extract Sections test passed\n")


def test_render_dimension_prompt():
    print("=" * 60)
    print("Test 8: render_dimension_prompt (All 7 Dimensions)")
    print("=" * 60)

    from judicial_quality_mcp.server import extract_document_sections, render_dimension_prompt

    sections_json = extract_document_sections(SAMPLE_DOC)
    sections = json.loads(sections_json)

    section_mapping = {
        "document_full_text": SAMPLE_DOC,
        "header_text": SAMPLE_DOC[:200],
        "footer_text": SAMPLE_DOC[-200:],
        "reasoning_text": sections.get("reasoning", ""),
        "judgment_basis_text": sections.get("judgment_basis", ""),
        "judgment_main_text": sections.get("judgment_main", ""),
        "plaintiff_claim_text": sections.get("plaintiff_claim", ""),
        "defendant_defense_text": sections.get("defendant_defense", ""),
        "court_finding_text": sections.get("court_finding", ""),
        "evidence_analysis_text": sections.get("evidence_analysis", ""),
        "case_followup_text": "",
    }

    for dim in ALL_DIMENSIONS:
        result_json = render_dimension_prompt(
            dimension=dim,
            sections=section_mapping,
            include_anchors=True,
            anchor_count=3,
        )
        result = json.loads(result_json)

        if "error" in result:
            print(f"  ❌ {dim}: {result['error']}")
            continue

        print(f"\n{dim}:")
        print(f"  title: {result['dimension_title']}")
        print(f"  weight: {result['weight']}")
        print(f"  system_prompt length: {len(result['system_prompt'])}")
        print(f"  user_prompt length: {len(result['user_prompt'])}")
        print(f"  anchor count: {len(result.get('anchor_examples', []))}")
        print(f"  token estimate: {result['token_estimate']}")
        print(f"  user_prompt preview: {result['user_prompt'][:100]}...")

        assert result["dimension"] == dim
        assert len(result["system_prompt"]) > 50
        assert len(result["user_prompt"]) > 200
        assert len(result.get("anchor_examples", [])) >= 1

        assert "anti-laziness" in result["system_prompt"].lower() or "强制执行" in result["system_prompt"]

    print("\n✅ render_dimension_prompt test passed\n")


def test_parse_score_result_with_mock():
    print("=" * 60)
    print("Test 9: parse_score_result with Mock LLM Responses")
    print("=" * 60)

    from judicial_quality_mcp.server import parse_score_result

    result_json = parse_score_result("thorough_reasoning", MOCK_LLM_RESPONSE_REASONING)
    result = json.loads(result_json)
    assert result["success"]
    assert result["parsed"]["score"] == 78
    assert len(result["parsed"]["deduction_items"]) == 2
    assert len(result["parsed"]["bonus_items"]) == 2
    print(f"  thorough_reasoning: score={result['parsed']['score']}, deductions={len(result['parsed']['deduction_items'])}, bonuses={len(result['parsed']['bonus_items'])}")

    result_json2 = parse_score_result("substantive_resolution", MOCK_LLM_RESPONSE_SUBSTANTIVE)
    result2 = json.loads(result_json2)
    assert result2["success"]
    assert result2["parsed"]["score"] == 82
    assert result2["parsed"]["data_completeness"] == "partial"
    print(f"  substantive_resolution: score={result2['parsed']['score']}, data_completeness={result2['parsed']['data_completeness']}")

    result_json3 = parse_score_result("thorough_reasoning", MOCK_LLM_RESPONSE_REASONING_INNOVATIVE)
    result3 = json.loads(result_json3)
    assert result3["success"]
    assert result3["parsed"]["score"] == 92
    assert len(result3["parsed"]["innovation_bonus_items"]) == 3
    print(f"  thorough_reasoning (innovative): score={result3['parsed']['score']}, innovation_items={len(result3['parsed']['innovation_bonus_items'])}")

    print("\n✅ parse_score_result with mock responses test passed\n")


def test_calculate_weighted_score_with_adjustments():
    print("=" * 60)
    print("Test 10: calculate_weighted_score with Anomaly & Innovation")
    print("=" * 60)

    from judicial_quality_mcp.server import calculate_weighted_score

    base_scores = {
        "formal_specification": 85,
        "clear_facts": 72,
        "sufficient_evidence": 68,
        "correct_law_application": 80,
        "thorough_reasoning": 78,
        "substantive_resolution": 82,
        "concise_language": 75,
    }

    result_base_json = calculate_weighted_score(base_scores)
    result_base = json.loads(result_base_json)
    assert result_base["success"]
    print(f"  Base weighted total: {result_base['weighted_total']}, grade: {result_base['grade']}")

    result_with_anomaly_json = calculate_weighted_score(
        base_scores,
        anomaly_items=MOCK_ANOMALY_RESULTS,
    )
    result_with_anomaly = json.loads(result_with_anomaly_json)
    assert result_with_anomaly["success"]
    assert result_with_anomaly["anomaly_deduction"] > 0
    print(f"  With anomaly: total={result_with_anomaly['weighted_total']}, deduction={result_with_anomaly['anomaly_deduction']}, grade={result_with_anomaly['grade']}")

    result_with_innovation_json = calculate_weighted_score(
        base_scores,
        innovation_items=MOCK_INNOVATION_ITEMS,
    )
    result_with_innovation = json.loads(result_with_innovation_json)
    assert result_with_innovation["success"]
    assert result_with_innovation["innovation_bonus"] > 0
    print(f"  With innovation: total={result_with_innovation['weighted_total']}, bonus={result_with_innovation['innovation_bonus']}, grade={result_with_innovation['grade']}")

    result_full_json = calculate_weighted_score(
        base_scores,
        anomaly_items=MOCK_ANOMALY_RESULTS,
        innovation_items=MOCK_INNOVATION_ITEMS,
    )
    result_full = json.loads(result_full_json)
    assert result_full["success"]
    print(f"  Full (anomaly+innovation): total={result_full['weighted_total']}, base={result_full['base_weighted_total']}, deduction={result_full['anomaly_deduction']}, bonus={result_full['innovation_bonus']}, grade={result_full['grade']}")

    assert result_full["weighted_total"] == result_full["base_weighted_total"] - result_full["anomaly_deduction"] + result_full["innovation_bonus"]

    print("\n✅ calculate_weighted_score with adjustments test passed\n")


def test_apply_anomaly_deduction():
    print("=" * 60)
    print("Test 11: apply_anomaly_deduction Tool")
    print("=" * 60)

    from judicial_quality_mcp.server import apply_anomaly_deduction

    result_json = apply_anomaly_deduction(MOCK_ANOMALY_RESULTS)
    result = json.loads(result_json)
    assert result["success"]
    assert result["total_deduction"] > 0
    assert len(result["items"]) == 3
    print(f"  Total deduction: {result['total_deduction']}")
    print(f"  Capped: {result['capped']}")
    for item in result["items"]:
        print(f"    - {item['label']} ({item['severity']}): -{item['deduction']} | {item['description'][:40]}")

    print("\n✅ apply_anomaly_deduction test passed\n")


def test_apply_innovation_bonus():
    print("=" * 60)
    print("Test 12: apply_innovation_bonus Tool")
    print("=" * 60)

    from judicial_quality_mcp.server import apply_innovation_bonus

    result_json = apply_innovation_bonus(MOCK_INNOVATION_ITEMS)
    result = json.loads(result_json)
    assert result["success"]
    assert result["total_bonus"] > 0
    assert len(result["items"]) == 3
    print(f"  Total bonus: {result['total_bonus']}")
    print(f"  Capped: {result['capped']}")
    for item in result["items"]:
        print(f"    - {item['label']}: +{item['actual_bonus']} (requested: {item['requested_bonus']}) | {item['description'][:40]}")

    print("\n✅ apply_innovation_bonus test passed\n")


def test_cross_check_server_tool():
    print("=" * 60)
    print("Test 13: cross_check_consistency Server Tool")
    print("=" * 60)

    from judicial_quality_mcp.server import cross_check_consistency

    consistent = {
        "thorough_reasoning": 75,
        "substantive_resolution": 70,
        "correct_law_application": 80,
        "clear_facts": 72,
        "sufficient_evidence": 68,
    }
    result_json = cross_check_consistency(consistent)
    result = json.loads(result_json)
    assert result["success"]
    print(f"  Consistent scores: conflicts={result['conflict_count']}")

    inconsistent = {
        "thorough_reasoning": 90,
        "correct_law_application": 45,
        "clear_facts": 55,
        "sufficient_evidence": 80,
        "substantive_resolution": 85,
    }
    result_json2 = cross_check_consistency(inconsistent)
    result2 = json.loads(result_json2)
    assert result2["success"]
    assert result2["conflict_detected"]
    print(f"  Inconsistent scores: conflicts={result2['conflict_count']}")
    for c in result2["conflicts"]:
        print(f"    - {c['rule_id']} {c['rule_name']}: {c['message'][:60]}...")

    print("\n✅ cross_check_consistency server tool test passed\n")


def test_generate_report():
    print("=" * 60)
    print("Test 14: generate_report Tool")
    print("=" * 60)

    from judicial_quality_mcp.server import generate_report

    dimension_results = [
        {
            "dimension": "thorough_reasoning",
            "score": 78,
            "deduction_items": [{"item": "说理模板化", "deduction": 8}],
            "bonus_items": [{"item": "争议焦点逐一回应", "bonus": 8}],
        },
        {
            "dimension": "substantive_resolution",
            "score": 82,
            "deduction_items": [],
            "bonus_items": [{"item": "法律适用正确", "bonus": 10}],
        },
    ]

    result_json = generate_report(
        dimension_results=dimension_results,
        weighted_total=76.5,
        grade="C",
        cross_check={"conflict_detected": False, "conflicts": []},
        anomaly_deduction=12,
        innovation_bonus=8,
        anomaly_details=[
            {"label": "程序异常", "severity": "medium", "deduction": 5, "description": "未回应调查取证申请"},
            {"label": "证据异常", "severity": "high", "deduction": 7, "description": "关键证据采信缺乏说理"},
        ],
        innovation_details=[
            {"label": "法律漏洞填补", "bonus": 5, "description": "通过目的解释填补法律空白"},
            {"label": "体现司法底层逻辑", "bonus": 3, "description": "裁判体现公平正义精神"},
        ],
    )
    result = json.loads(result_json)
    assert result["success"]
    assert "report_markdown" in result
    report = result["report_markdown"]
    assert "司法/行政文书程序与实体异常深度检测与质量评估报告" in report
    assert "异常扣分" in report
    assert "创新" in report and "加分" in report
    print(f"  Report length: {len(report)} chars")
    print(f"  Report preview (first 300 chars):\n{report[:300]}...")

    print("\n✅ generate_report test passed\n")


def test_full_pipeline_dryrun():
    print("=" * 60)
    print("Test 15: Full Pipeline Dry-Run (All 7 Dimensions)")
    print("=" * 60)

    from judicial_quality_mcp.server import (
        extract_document_sections,
        render_dimension_prompt,
        parse_score_result,
        calculate_weighted_score,
        cross_check_consistency,
        apply_anomaly_deduction,
        apply_innovation_bonus,
        generate_report,
    )

    print("  Step 1: Extract document sections...")
    sections_json = extract_document_sections(SAMPLE_DOC)
    sections = json.loads(sections_json)
    assert sections.get("extraction_confidence", 0) > 0.5
    print(f"    Confidence: {sections['extraction_confidence']}")

    section_mapping = {
        "document_full_text": SAMPLE_DOC,
        "header_text": SAMPLE_DOC[:200],
        "footer_text": SAMPLE_DOC[-200:],
        "reasoning_text": sections.get("reasoning", ""),
        "judgment_basis_text": sections.get("judgment_basis", ""),
        "judgment_main_text": sections.get("judgment_main", ""),
        "plaintiff_claim_text": sections.get("plaintiff_claim", ""),
        "defendant_defense_text": sections.get("defendant_defense", ""),
        "court_finding_text": sections.get("court_finding", ""),
        "evidence_analysis_text": sections.get("evidence_analysis", ""),
        "case_followup_text": "",
    }

    print("  Step 2: Render dimension prompts (all 7 dimensions)...")
    for dim in ALL_DIMENSIONS:
        prompt_json = render_dimension_prompt(
            dimension=dim,
            sections=section_mapping,
            include_anchors=True,
            anchor_count=3,
        )
        prompt_result = json.loads(prompt_json)
        assert prompt_result.get("success", False) or "dimension_title" in prompt_result
        print(f"    {dim}: prompt rendered, token_estimate={prompt_result.get('token_estimate', 0)}")

    print("  Step 3: Parse mock LLM responses...")
    parse_json1 = parse_score_result("thorough_reasoning", MOCK_LLM_RESPONSE_REASONING)
    parse1 = json.loads(parse_json1)
    dimension_scores = {"thorough_reasoning": parse1["parsed"]["score"]}
    print(f"    thorough_reasoning: score={parse1['parsed']['score']}")

    parse_json2 = parse_score_result("substantive_resolution", MOCK_LLM_RESPONSE_SUBSTANTIVE)
    parse2 = json.loads(parse_json2)
    dimension_scores["substantive_resolution"] = parse2["parsed"]["score"]
    print(f"    substantive_resolution: score={parse2['parsed']['score']}")

    dimension_scores.update({
        "formal_specification": 85,
        "clear_facts": 72,
        "sufficient_evidence": 68,
        "correct_law_application": 80,
        "concise_language": 75,
    })

    print("  Step 4: Apply anomaly deduction...")
    anomaly_json = apply_anomaly_deduction(MOCK_ANOMALY_RESULTS)
    anomaly_result = json.loads(anomaly_json)
    print(f"    Anomaly deduction: {anomaly_result['total_deduction']}")

    print("  Step 5: Apply innovation bonus...")
    innovation_json = apply_innovation_bonus(MOCK_INNOVATION_ITEMS)
    innovation_result = json.loads(innovation_json)
    print(f"    Innovation bonus: {innovation_result['total_bonus']}")

    print("  Step 6: Calculate weighted score...")
    score_json = calculate_weighted_score(
        dimension_scores,
        anomaly_items=MOCK_ANOMALY_RESULTS,
        innovation_items=MOCK_INNOVATION_ITEMS,
    )
    score_result = json.loads(score_json)
    print(f"    Weighted total: {score_result['weighted_total']}, grade: {score_result['grade']}")
    print(f"    Base: {score_result['base_weighted_total']}, Deduction: {score_result['anomaly_deduction']}, Bonus: {score_result['innovation_bonus']}")

    print("  Step 7: Cross-check consistency...")
    check_json = cross_check_consistency(dimension_scores)
    check_result = json.loads(check_json)
    print(f"    Conflicts: {check_result['conflict_count']}")

    print("  Step 8: Generate report...")
    report_json = generate_report(
        dimension_results=[
            {"dimension": "thorough_reasoning", "score": dimension_scores["thorough_reasoning"],
             "deduction_items": parse1["parsed"].get("deduction_items", []),
             "bonus_items": parse1["parsed"].get("bonus_items", [])},
            {"dimension": "substantive_resolution", "score": dimension_scores["substantive_resolution"],
             "deduction_items": parse2["parsed"].get("deduction_items", []),
             "bonus_items": parse2["parsed"].get("bonus_items", [])},
            {"dimension": "formal_specification", "score": 85, "deduction_items": [], "bonus_items": []},
            {"dimension": "clear_facts", "score": 72, "deduction_items": [], "bonus_items": []},
            {"dimension": "sufficient_evidence", "score": 68, "deduction_items": [], "bonus_items": []},
            {"dimension": "correct_law_application", "score": 80, "deduction_items": [], "bonus_items": []},
            {"dimension": "concise_language", "score": 75, "deduction_items": [], "bonus_items": []},
        ],
        weighted_total=score_result["weighted_total"],
        grade=score_result["grade"],
        cross_check=check_result,
        anomaly_deduction=score_result["anomaly_deduction"],
        innovation_bonus=score_result["innovation_bonus"],
        anomaly_details=score_result.get("anomaly_details", []),
        innovation_details=score_result.get("innovation_details", []),
    )
    report_result = json.loads(report_json)
    assert report_result["success"]
    print(f"    Report generated: {len(report_result['report_markdown'])} chars")

    print("\n✅ Full Pipeline Dry-Run test passed\n")


def main():
    print("\n" + "=" * 60)
    print("Phase 1 MVP — End-to-End Test Suite (Enhanced)")
    print("=" * 60 + "\n")

    test_skill_loader()
    test_template_renderer()
    test_anchor_loading()
    test_response_parser()
    test_json_tolerance()
    test_cross_check()
    test_extract_sections()
    test_render_dimension_prompt()
    test_parse_score_result_with_mock()
    test_calculate_weighted_score_with_adjustments()
    test_apply_anomaly_deduction()
    test_apply_innovation_bonus()
    test_cross_check_server_tool()
    test_generate_report()
    test_full_pipeline_dryrun()

    print("\n" + "=" * 60)
    print("🎉 All Phase 1 MVP tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
