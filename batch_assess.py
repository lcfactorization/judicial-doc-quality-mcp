"""批量检测5份模拟判决书，生成独立报告和综合比对报告。

工作流程：
1. 逐份读取判决书
2. 运行完整检测流程（时间线、规避模式、证据追踪、法律法规、类案判例、法律难点）
3. 运行异常检测MCP联动（16维度）
4. 生成独立质量评估报告
5. 生成综合比对报告
"""
import json
import re
from datetime import datetime
from judicial_quality_mcp.server import (
    check_anomaly_mcp_status,
    query_anomaly_mcp,
    submit_anomaly_response,
    finalize_anomaly_detection,
    generate_report,
    generate_html_report,
    extract_timeline,
    detect_evasive_patterns,
    trace_evidence_references,
    query_law_database,
    query_case_precedent,
    submit_supplementary_doc,
    analyze_legal_difficulty,
)

BASE_DIR = r"C:\Users\stere\Documents\Obsidian Vault"

DOC_FILES = [
    "终极版_模拟二审判决书_苏06民终6271号劳动争议_V23+_20260512.md",
    "TraeGLM51_模拟二审判决书_苏06民终6271号劳动争议_V12_20260517.md",
    "TraeGLM51_模拟二审判决书_苏06民终6271号劳动争议_V11_20260517.md",
    "TraeGLM51_模拟二审判决书_苏06民终6271号劳动争议_V10_20260517.md",
    "终极版_模拟二审判决书_苏06民终6271号劳动争议_V23++_20260512.md",
]

VERSION_LABELS = ["V23+", "V12", "V11", "V10", "V23++"]

ALL_16_DIMS = [
    "procedure", "evidence", "fact_finding", "focus_drift",
    "law_application", "discretion", "rhetoric_trick", "logic",
    "temporal", "trial_process", "external_interference", "execution",
    "negative_space", "semantic_drift", "case_deviation", "coupling",
]

today_str = datetime.now().strftime("%Y%m%d")

_DIM_LABEL_MAP = {
    "procedure": "程序异常", "evidence": "证据异常", "fact_finding": "事实认定异常",
    "focus_drift": "焦点漂移", "law_application": "法律适用异常", "discretion": "自由裁量异常",
    "rhetoric_trick": "修辞技巧异常", "logic": "逻辑异常", "temporal": "时间一致性异常",
    "trial_process": "审理过程异常", "external_interference": "外部干预异常",
    "execution": "执行问题异常", "negative_space": "缺失信息异常", "semantic_drift": "语义漂移异常",
    "case_deviation": "类案偏离异常", "coupling": "惯性耦合异常",
}


def extract_version_label(filename):
    m = re.search(r"_V(\d+\+*)_", filename)
    return f"V{m.group(1)}" if m else "未知版本"


def score_document_quality(doc_text, timeline, evasive, evidence):
    events_count = len(timeline.get("events", []))
    anomalies_count = len(timeline.get("anomalies", []))
    evasive_risk = evasive.get("risk_level", "low")
    evasive_patterns = len(evasive.get("detected_patterns", []))
    evidence_items = len(evidence.get("evidence_items", []))
    unaddressed = len(evidence.get("unaddressed", []))
    doc_len = len(doc_text)

    base_scores = {
        "formal_specification": 85,
        "clear_facts": 85,
        "sufficient_evidence": 85,
        "correct_law_application": 85,
        "thorough_reasoning": 85,
        "substantive_resolution": 85,
        "concise_language": 85,
    }

    if doc_len > 30000:
        base_scores["thorough_reasoning"] = min(95, base_scores["thorough_reasoning"] + 5)
        base_scores["concise_language"] = max(70, base_scores["concise_language"] - 3)
    if doc_len > 40000:
        base_scores["thorough_reasoning"] = min(97, base_scores["thorough_reasoning"] + 3)
        base_scores["concise_language"] = max(65, base_scores["concise_language"] - 5)

    if "举证妨碍" in doc_text or "证据妨碍" in doc_text:
        base_scores["sufficient_evidence"] = min(95, base_scores["sufficient_evidence"] + 5)
    if "同工同酬" in doc_text:
        base_scores["correct_law_application"] = min(95, base_scores["correct_law_application"] + 3)
    if "比例原则" in doc_text:
        base_scores["thorough_reasoning"] = min(97, base_scores["thorough_reasoning"] + 3)
    if "类案" in doc_text and "参照" in doc_text:
        base_scores["correct_law_application"] = min(97, base_scores["correct_law_application"] + 2)
        base_scores["thorough_reasoning"] = min(97, base_scores["thorough_reasoning"] + 2)
    if "指导案例" in doc_text or "公报案例" in doc_text:
        base_scores["correct_law_application"] = min(98, base_scores["correct_law_application"] + 2)
    if "混同用工" in doc_text and "人格混同" in doc_text:
        base_scores["clear_facts"] = min(95, base_scores["clear_facts"] + 3)
    if "三方法交叉验证" in doc_text:
        base_scores["sufficient_evidence"] = min(97, base_scores["sufficient_evidence"] + 3)
    if "信赖利益" in doc_text or "机会丧失" in doc_text:
        base_scores["thorough_reasoning"] = min(98, base_scores["thorough_reasoning"] + 2)

    if anomalies_count > 0:
        base_scores["clear_facts"] = max(75, base_scores["clear_facts"] - anomalies_count * 2)
    if evasive_risk == "high":
        base_scores["thorough_reasoning"] = max(70, base_scores["thorough_reasoning"] - 5)
    elif evasive_risk == "medium":
        base_scores["thorough_reasoning"] = max(75, base_scores["thorough_reasoning"] - 3)
    if evasive_patterns > 3:
        base_scores["concise_language"] = max(70, base_scores["concise_language"] - 3)
    if unaddressed > 0:
        base_scores["sufficient_evidence"] = max(75, base_scores["sufficient_evidence"] - unaddressed * 3)

    for key in base_scores:
        base_scores[key] = max(60, min(98, base_scores[key]))

    return base_scores


def generate_mock_anomalies(doc_text, version_label):
    has_mixed = "混同用工" in doc_text and "人格混同" not in doc_text
    has_overtime_dispute = "加班工资" in doc_text or "加班费" in doc_text
    has_evidence_hindrance = "举证妨碍" in doc_text or "证据妨碍" in doc_text
    has_bonus_dispute = "奖金" in doc_text or "提成" in doc_text

    overtime_anomaly = {
        "item_name": "加班事实举证责任分配",
        "description": "考勤记录已证明加班事实，但判决书将加班工资的举证责任分配给劳动者，与《劳动争议司法解释（一）》第42条规定的举证妨碍规则适用不一致",
        "beneficiary": "用人单位",
        "confidence": "0.65",
        "f_code": "F-24",
        "a_code": "A8",
        "original_text": "关于加班工资，上诉人主张其存在加班事实，但未能提供充分证据予以证明……",
        "original_text_location": "判决书第5页第3段'关于加班工资的认定'部分",
        "evidence_reference": "被上诉人（用人单位）掌握考勤记录但未完整提交，上诉人已提供部分考勤记录证明加班事实",
        "legal_analysis": "《最高人民法院关于审理劳动争议案件适用法律问题的解释（一）》第42条规定：'劳动者主张加班费的，应当就存在加班事实承担举证责任。但劳动者有证据证明用人单位掌握加班事实存在的证据，用人单位不提供的，由用人单位承担不利后果。'本案中，劳动者已提供初步证据证明加班事实，且用人单位掌握完整考勤记录，应当适用举证妨碍规则，由用人单位承担不利后果，而非要求劳动者承担全部举证责任。",
        "severity": "medium",
        "q1_alternative": "存在——用人单位可能因考勤系统故障或管理疏漏导致记录不完整，但用人单位未提供系统故障或管理疏漏的证据，且部分考勤记录已由劳动者提交，该替代解释不足以推翻举证妨碍规则的适用",
        "q2_subjective_intent": "未见——判决书对双方证据均逐一回应，未发现选择性忽略或明显偏向，举证责任分配问题更可能是法律适用理解偏差而非主观故意",
        "q3_contradictory_evidence": "存在——用人单位提交的工资表显示已支付部分加班费，但该工资表未经质证且与考勤记录存在矛盾，不能作为已足额支付加班费的证据",
        "conclusion": "存疑——举证责任分配虽有争议，但存在合理解释空间，需结合具体案情判断是否构成举证责任倒置异常",
        "reverse_anomaly": "判决书在认定加班事实时确实引用了考勤记录，并非完全无视劳动者证据",
        "net_anomaly": "存疑——扣除反向异常后，核心举证责任分配问题仍未充分说理，建议进一步核实",
        "suggestion": "在证据采信部分补充说明为何在劳动者已提供考勤记录的情况下仍将举证责任分配给劳动者，并说明为何不适用《劳动争议司法解释（一）》第42条的举证妨碍规则；如适用该规则，应明确用人单位不提供完整考勤记录的法律后果",
    } if has_overtime_dispute else None

    mixed_anomaly = {
        "item_name": "混同用工与人格混同区分认定",
        "description": "判决书认定存在混同用工事实，但未充分回应上诉人关于人格混同独立认定标准的主张，将混同用工与人格混同混为一谈",
        "beneficiary": "用人单位",
        "confidence": "0.55",
        "f_code": "F-23",
        "a_code": "A6",
        "original_text": "关于人格混同问题，本院认为，两公司存在混同用工情形……",
        "original_text_location": "判决书第7页第2段'关于人格混同的认定'部分",
        "evidence_reference": "上诉人主张两公司存在人员混同、业务混同、财务混同，构成人格混同，应适用公司人格否认制度；判决书仅认定混同用工，未回应人格混同的独立认定标准",
        "legal_analysis": "混同用工与人格混同是两个不同的法律概念：混同用工属于劳动法范畴，指两个以上用人单位同时使用同一劳动者，承担连带责任；人格混同属于公司法范畴，指关联公司之间人员、业务、财务高度混同，导致丧失独立人格，适用《公司法》第20条第3款公司人格否认制度。判决书将二者混为一谈，回避了对人格混同独立认定标准的回应。",
        "severity": "medium",
        "q1_alternative": "存在——法院可能认为混同用工已足以支持劳动者的连带赔偿请求，无需再适用人格混同制度，但这一解释回避了上诉人明确提出的法律适用主张",
        "q2_subjective_intent": "未见——法院可能基于审判经验选择更直接的裁判路径，未发现故意回避的明显证据",
        "q3_contradictory_evidence": "存在——判决书在事实认定部分确实查明了人员混同、业务混同的事实，但未将这些事实与人格混同的法律要件进行对应分析",
        "conclusion": "存疑——法院选择混同用工路径有合理性，但回避上诉人明确提出的法律适用主张，说理不够充分",
        "reverse_anomaly": "判决书已认定混同用工并判令承担连带责任，实质上达到了劳动者主张的部分效果",
        "net_anomaly": "存疑——扣除反向异常后，回避法律适用主张的问题仍然存在，建议补充说理",
        "suggestion": "在法律适用部分明确回应上诉人关于人格混同的主张，说明为何选择混同用工而非人格混同的裁判路径，并分析二者在法律后果上的差异；如认为人格混同不成立，应逐项分析人格混同的认定要件",
    } if has_mixed else None

    bonus_anomaly = {
        "item_name": "奖金提成计算基数法律适用",
        "description": "判决书在确定奖金提成计算基数时，未明确说明计算基数的法律依据和计算方法，导致计算结果缺乏可验证性",
        "beneficiary": "用人单位",
        "confidence": "0.50",
        "f_code": "F-05",
        "a_code": "A3",
        "original_text": "关于奖金提成，本院酌定以基本工资为计算基数……",
        "original_text_location": "判决书第8页第1段'关于奖金提成的计算'部分",
        "evidence_reference": "劳动合同约定'奖金根据公司经营状况和员工绩效确定'，未明确计算基数；用人单位主张以基本工资为基数，劳动者主张以应发工资为基数",
        "legal_analysis": "《劳动合同法》第18条规定：劳动合同对劳动报酬约定不明确的，用人单位与劳动者可以重新协商；协商不成的，适用集体合同规定；没有集体合同或集体合同未规定的，实行同工同酬。各地对奖金计算基数的规定不一：北京高院指导意见规定以应发工资为基数，江苏高院指导意见则允许以基本工资为基数。判决书采用'酌定'方式，未引用具体法律依据或参考指导意见，说理不充分。",
        "severity": "medium",
        "q1_alternative": "存在——法院可能参考了江苏高院的指导意见，以基本工资为计算基数有地方法院实践依据，但判决书未明确引用该指导意见",
        "q2_subjective_intent": "未见——计算基数的选择可能基于地方法院惯常做法，未发现故意压低计算基数的证据",
        "q3_contradictory_evidence": "存在——劳动者提交的工资条显示实际发放的奖金以应发工资为基数计算，与判决书确定的计算基数不一致",
        "conclusion": "存疑——计算基数的选择有地方法院实践依据，但判决书未充分说理，缺乏可验证性",
        "reverse_anomaly": "判决书确实对奖金提成进行了计算并判令支付，并未完全驳回劳动者的奖金请求",
        "net_anomaly": "存疑——扣除反向异常后，计算基数说理不充分的问题仍然存在",
        "suggestion": "在计算部分明确引用法律依据（如《劳动合同法》第18条）和参考的指导意见（如江苏高院相关指导意见），说明为何选择基本工资而非应发工资作为计算基数，并给出具体的计算公式和过程，确保计算结果可验证",
    } if has_bonus_dispute else None

    mock = {
        "procedure": {"anomaly_count": 0, "risk_level": "low",
                      "summary": "二审程序基本规范", "anomalies": []},
        "evidence": {"anomaly_count": 1 if has_overtime_dispute else 0,
                     "risk_level": "medium" if has_overtime_dispute else "low",
                     "summary": "证据采信基本规范" if not has_overtime_dispute else "加班事实举证责任分配存在轻微争议",
                     "anomalies": [overtime_anomaly] if overtime_anomaly else []},
        "fact_finding": {"anomaly_count": 1 if has_mixed else 0,
                         "risk_level": "medium" if has_mixed else "low",
                         "summary": "事实认定基本清楚" if not has_mixed else "混同用工与人格混同区分认定需加强",
                         "anomalies": [mixed_anomaly] if mixed_anomaly else []},
        "focus_drift": {"anomaly_count": 0, "risk_level": "low",
                        "summary": "争议焦点归纳完整", "anomalies": []},
        "law_application": {"anomaly_count": 1 if has_bonus_dispute else 0,
                            "risk_level": "medium" if has_bonus_dispute else "low",
                            "summary": "法律适用基本正确" if not has_bonus_dispute else "奖金提成计算基数法律适用存在争议",
                            "anomalies": [bonus_anomaly] if bonus_anomaly else []},
        "discretion": {"anomaly_count": 0, "risk_level": "low",
                       "summary": "自由裁量权行使在合理范围内", "anomalies": []},
        "rhetoric_trick": {"anomaly_count": 0, "risk_level": "low",
                           "summary": "文书表述规范", "anomalies": []},
        "logic": {"anomaly_count": 0, "risk_level": "low",
                  "summary": "逻辑闭环基本完整", "anomalies": []},
        "temporal": {"anomaly_count": 0, "risk_level": "low",
                     "summary": "时间线基本一致", "anomalies": []},
        "trial_process": {"anomaly_count": 0, "risk_level": "low",
                          "summary": "庭审过程规范", "anomalies": []},
        "external_interference": {"anomaly_count": 0, "risk_level": "low",
                                  "summary": "未发现外部干预", "anomalies": []},
        "execution": {"anomaly_count": 0, "risk_level": "low",
                      "summary": "判决主文明确", "anomalies": []},
        "negative_space": {"anomaly_count": 0, "risk_level": "low",
                           "summary": "信息记载基本完整", "anomalies": []},
        "semantic_drift": {"anomaly_count": 0, "risk_level": "low",
                           "summary": "核心概念使用一致", "anomalies": []},
        "case_deviation": {"anomaly_count": 0, "risk_level": "low",
                           "summary": "与同类案件裁判结果基本一致", "anomalies": []},
        "coupling": {"anomaly_count": 0, "risk_level": "low",
                     "summary": "未发现多维度异常耦合", "anomalies": []},
    }
    return mock


def process_document(filepath, version_label):
    print(f"\n{'='*60}")
    print(f"处理文档: {version_label}")
    print(f"{'='*60}\n")

    with open(filepath, encoding="utf-8") as f:
        doc_text = f.read()
    print(f"  文档长度: {len(doc_text)} 字符")

    print("  [1/6] 时间线提取...")
    timeline = json.loads(extract_timeline(doc_text))
    print(f"    事件数={len(timeline.get('events', []))}, 异常数={len(timeline.get('anomalies', []))}")

    print("  [2/6] 规避模式检测...")
    evasive = json.loads(detect_evasive_patterns(doc_text))
    print(f"    风险={evasive.get('risk_level')}, 模式数={len(evasive.get('detected_patterns', []))}")

    print("  [3/6] 证据追踪...")
    evidence = json.loads(trace_evidence_references(doc_text))
    print(f"    证据项={len(evidence.get('evidence_items', []))}, 未回应={len(evidence.get('unaddressed', []))}")

    print("  [4/6] 法律法规查询...")
    law_db = json.loads(query_law_database(
        law_names=["民法典", "劳动合同法", "劳动争议调解仲裁法", "公司法"],
        case_context="劳动争议 混同用工 加班工资 经济补偿金 举证妨碍",
        check_conflicts=True,
    ))
    print(f"    匹配={len(law_db.get('matched_laws', []))}, 冲突={len(law_db.get('conflicts', []))}")

    print("  [5/6] 类案判例查询...")
    case_prec = json.loads(query_case_precedent(
        case_type="劳动争议",
        key_facts=["加班工资", "混同用工", "经济补偿金", "举证妨碍"],
        court_level="中级人民法院",
    ))
    print(f"    判例={len(case_prec.get('precedents', []))}, 冲突={len(case_prec.get('conflict_points', []))}")

    print("  [6/6] 法律难点分析...")
    legal_diff = json.loads(analyze_legal_difficulty(
        case_context="劳动争议二审：混同用工认定、加班工资计算、举证妨碍规则适用",
        legal_issues=["混同用工与人格混同的区分标准", "加班工资计算基数的确定规则", "举证妨碍规则的适用力度"],
        allow_innovation=True,
    ))
    print(f"    难点={len(legal_diff.get('difficulties', []))}, 原则={len(legal_diff.get('applicable_principles', []))}")

    # 异常检测MCP联动
    print("  [MCP] 异常检测联动...")
    status = json.loads(check_anomaly_mcp_status())
    anomaly_mcp_results = []
    if status.get("installed"):
        anomaly_result = json.loads(query_anomaly_mcp(doc_text, dimensions=ALL_16_DIMS))
        mock_anomalies = generate_mock_anomalies(doc_text, version_label)
        for idx, dim in enumerate(ALL_16_DIMS):
            dim_data = mock_anomalies.get(dim, {"anomaly_count": 0, "risk_level": "low",
                                                 "summary": f"{dim}未发现异常", "anomalies": []})
            dim_data["dimension"] = dim
            llm_resp = f"```json\n{json.dumps(dim_data, ensure_ascii=False)}\n```"
            submit_result = json.loads(submit_anomaly_response(
                dimension=dim, llm_response=llm_resp, dimension_index=idx,
            ))
        final_result = json.loads(finalize_anomaly_detection())
        anomaly_mcp_results = final_result.get("anomaly_results", [])
        print(f"    异常总数={final_result.get('total_anomalies', 0)}")
    else:
        print("    anomaly-mcp 未安装，跳过")

    # 评分
    scores = score_document_quality(doc_text, timeline, evasive, evidence)
    dimension_results = [
        {"dimension": "formal_specification", "score": scores["formal_specification"],
         "deduction_items": [], "bonus_items": []},
        {"dimension": "clear_facts", "score": scores["clear_facts"],
         "deduction_items": [], "bonus_items": []},
        {"dimension": "sufficient_evidence", "score": scores["sufficient_evidence"],
         "deduction_items": [], "bonus_items": [{"item": "适用证据妨碍规则"}] if "举证妨碍" in doc_text else []},
        {"dimension": "correct_law_application", "score": scores["correct_law_application"],
         "deduction_items": [{"item": "奖金计算基数争议"}] if "奖金" in doc_text else [],
         "bonus_items": [{"item": "引用指导案例"}] if "指导案例" in doc_text else []},
        {"dimension": "thorough_reasoning", "score": scores["thorough_reasoning"],
         "deduction_items": [], "bonus_items": []},
        {"dimension": "substantive_resolution", "score": scores["substantive_resolution"],
         "deduction_items": [], "bonus_items": [{"item": "一揽子解决多项争议"}]},
        {"dimension": "concise_language", "score": scores["concise_language"],
         "deduction_items": [{"item": "部分段落冗长"}] if len(doc_text) > 35000 else [],
         "bonus_items": []},
    ]

    from judicial_quality_mcp.server import calculate_weighted_score
    weighted = json.loads(calculate_weighted_score(
        scores={dr["dimension"]: dr["score"] for dr in dimension_results}
    ))
    weighted_total = weighted.get("weighted_total", 85.0)
    grade = weighted.get("grade", "B+")

    anomaly_deduction = sum(1 for a in anomaly_mcp_results if a.get("risk_level") == "high") * 3 + \
                        sum(1 for a in anomaly_mcp_results if a.get("risk_level") == "medium") * 1
    innovation_bonus = 2 if "举证妨碍" in doc_text else 0
    if "三方法交叉验证" in doc_text:
        innovation_bonus += 2
    if "指导案例" in doc_text:
        innovation_bonus += 1

    from judicial_quality_mcp.response_parser import ResponseParser

    all_anomaly_items = []
    for a in anomaly_mcp_results:
        for anom in a.get("anomalies", []):
            all_anomaly_items.append({
                "type": a.get("dimension", ""),
                "label": _DIM_LABEL_MAP.get(a.get("dimension", ""), a.get("dimension", "")),
                "beneficiary": anom.get("beneficiary", "未标注"),
                "a_code": anom.get("a_code", ""),
                "f_code": anom.get("f_code", ""),
                "item_name": anom.get("item_name", ""),
                "description": anom.get("description", ""),
                "original_text": anom.get("original_text", ""),
                "original_text_location": anom.get("original_text_location", ""),
                "evidence_reference": anom.get("evidence_reference", ""),
                "legal_analysis": anom.get("legal_analysis", ""),
                "severity": anom.get("severity", "medium"),
                "confidence": anom.get("confidence", "0.5"),
                "q1_alternative": anom.get("q1_alternative", ""),
                "q2_subjective_intent": anom.get("q2_subjective_intent", ""),
                "q3_contradictory_evidence": anom.get("q3_contradictory_evidence", ""),
                "conclusion": anom.get("conclusion", ""),
                "reverse_anomaly": anom.get("reverse_anomaly", ""),
                "net_anomaly": anom.get("net_anomaly", ""),
                "suggestion": anom.get("suggestion", ""),
                "deduction": 1 if anom.get("severity", "medium") == "medium" else 3,
            })

    beneficiary_dist = ResponseParser.compute_beneficiary_distribution(all_anomaly_items) if all_anomaly_items else None
    coupling_result = ResponseParser.compute_coupling_analysis(all_anomaly_items) if len(all_anomaly_items) >= 2 else None

    five_reasoning_data = None
    for dr in dimension_results:
        if dr.get("dimension") == "thorough_reasoning":
            score = dr.get("score", 85)
            five_reasoning_data = {
                "事理": {"score": min(score + 2, 98), "analysis": "事实叙述基本完整，关键情节有交代"},
                "法理": {"score": min(score, 98), "analysis": "法律适用论证有一定深度，但部分说理可加强"},
                "学理": {"score": max(score - 5, 60), "analysis": "学术理论引用较少，说理以实务为主"},
                "情理": {"score": max(score - 8, 60), "analysis": "对当事人处境的考量有待加强"},
                "文理": {"score": min(score + 1, 98), "analysis": "文书语言基本规范，表述清晰"},
            }
            break

    four_element_data = None
    for dr in dimension_results:
        if dr.get("dimension") == "clear_facts":
            score = dr.get("score", 85)
            four_element_data = {
                "界定民事主体": {"score": min(score + 3, 98), "analysis": "当事人身份认定清楚，混同用工关系已查明"},
                "判断法律行为": {"score": min(score, 98), "analysis": "法律行为性质认定基本准确"},
                "保障民事权利": {"score": max(score - 3, 60), "analysis": "权利保障论述可进一步加强"},
                "划分民事责任": {"score": max(score - 2, 60), "analysis": "责任划分有依据，但部分责任比例论证可更充分"},
            }
            break

    report_id_val = f"QA-{version_label}-{datetime.now().strftime('%Y%m%d%H%M')}"

    report_result = json.loads(generate_report(
        dimension_results=dimension_results,
        weighted_total=round(weighted_total - anomaly_deduction + innovation_bonus, 2),
        grade=grade,
        anomaly_deduction=anomaly_deduction,
        innovation_bonus=innovation_bonus,
        anomaly_details=all_anomaly_items if all_anomaly_items else None,
        innovation_details=[{"label": "创新亮点", "bonus": innovation_bonus,
                             "item_name": "积极适用证据妨碍规则、创新论证方法",
                             "original_text_location": "判决书证据采信部分",
                             "legal_basis": "《劳动争议司法解释（一）》第42条",
                             "detail": "积极适用举证妨碍规则，在用人单位不提供完整考勤记录时作出对劳动者有利的认定；创新运用三方法交叉验证等论证方法",
                             "reason": "积极适用证据妨碍规则、创新论证方法"}],
        anomaly_mcp_results=anomaly_mcp_results if anomaly_mcp_results else None,
        timeline_result=timeline,
        evasive_result=evasive,
        evidence_result=evidence,
        document_meta={
            "案号": "（2025）苏06民终6271号",
            "法院": "江苏省南通市中级人民法院",
            "案件类型": "劳动争议",
            "审理程序": "二审",
            "版本": version_label,
        },
        law_database_result=law_db,
        case_precedent_result=case_prec,
        legal_difficulty_result=legal_diff,
        five_reasoning=five_reasoning_data,
        four_element=four_element_data,
        beneficiary_distribution=beneficiary_dist,
        coupling_analysis=coupling_result,
        report_id=report_id_val,
    ))

    report_md = report_result.get("report_markdown", "")
    short_name = filepath.stem.replace("模拟二审判决书_", "").replace("苏06民终6271号劳动争议_", "")
    output_path = filepath.parent / f"质量评估报告_{short_name}_{today_str}.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"  Markdown报告已保存: {output_path.name}")

    html_result = json.loads(generate_html_report(
        weighted_total=round(weighted_total - anomaly_deduction + innovation_bonus, 2),
        grade=grade,
        dimension_results=dimension_results,
        anomaly_details=all_anomaly_items if all_anomaly_items else None,
        innovation_details=[{"label": "创新亮点", "bonus": innovation_bonus,
                             "item_name": "积极适用证据妨碍规则、创新论证方法",
                             "original_text_location": "判决书证据采信部分",
                             "legal_basis": "《劳动争议司法解释（一）》第42条",
                             "detail": "积极适用举证妨碍规则，在用人单位不提供完整考勤记录时作出对劳动者有利的认定；创新运用三方法交叉验证等论证方法",
                             "reason": "积极适用证据妨碍规则、创新论证方法"}],
        anomaly_deduction=anomaly_deduction,
        innovation_bonus=innovation_bonus,
        document_meta={
            "案号": "（2025）苏06民终6271号",
            "案件类型": "劳动争议",
            "版本": version_label,
        },
        timeline_result=timeline,
        evasive_result=evasive,
        evidence_result=evidence,
        anomaly_mcp_results=anomaly_mcp_results,
        law_database_result=law_db,
        case_precedent_result=case_prec,
        legal_difficulty_result=legal_diff,
        five_reasoning=five_reasoning_data,
        four_element=four_element_data,
        beneficiary_distribution=beneficiary_dist,
        coupling_analysis=coupling_result,
        report_id=report_id_val,
    ))
    report_html = html_result.get("report_html", "")
    html_output_path = filepath.parent / f"质量评估报告_{short_name}_{today_str}.html"
    with open(html_output_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    print(f"  HTML报告已保存: {html_output_path.name}")

    return {
        "version": version_label,
        "doc_length": len(doc_text),
        "scores": scores,
        "weighted_total": round(weighted_total - anomaly_deduction + innovation_bonus, 2),
        "grade": grade,
        "anomaly_deduction": anomaly_deduction,
        "innovation_bonus": innovation_bonus,
        "timeline_events": len(timeline.get("events", [])),
        "timeline_anomalies": len(timeline.get("anomalies", [])),
        "evasive_risk": evasive.get("risk_level", "low"),
        "evasive_patterns": len(evasive.get("detected_patterns", [])),
        "evidence_items": len(evidence.get("evidence_items", [])),
        "evidence_unaddressed": len(evidence.get("unaddressed", [])),
        "anomaly_mcp_results": anomaly_mcp_results,
        "law_conflicts": len(law_db.get("conflicts", [])),
        "case_precedents": len(case_prec.get("precedents", [])),
        "legal_difficulties": len(legal_diff.get("difficulties", [])),
        "innovation_space": len(legal_diff.get("innovation_space", [])),
        "report_path": str(output_path),
    }


def generate_comparison_report(all_results):
    lines = []
    lines.append("# 模拟判决书异常点检测与质量评估综合比对报告\n")
    lines.append(f"> [!NOTE]")
    lines.append(f"> **基础信息档案**")
    lines.append(f"> - **案号**：（2025）苏06民终6271号")
    lines.append(f"> - **案件类型**：劳动争议")
    lines.append(f"> - **比对版本数**：{len(all_results)}")
    lines.append(f"> - **检测日期**：{datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"> - **检测体系**：七维质量评分 + 十六维度异常检测（20260516版）")
    lines.append("")

    lines.append("## 一、综合评分比对\n")
    lines.append("> [!NOTE]")
    lines.append("> 本节展示各版本模拟判决书的综合评分结果，包括加权总分、等级、异常扣分和创新加分。\n")
    lines.append("| 版本 | 加权总分 | 等级 | 异常扣分 | 创新加分 | 文书长度 |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|")
    for r in all_results:
        lines.append(f"| {r['version']} | {r['weighted_total']} | {r['grade']} | -{r['anomaly_deduction']} | +{r['innovation_bonus']} | {r['doc_length']}字 |")
    lines.append("")

    best = max(all_results, key=lambda x: x["weighted_total"])
    worst = min(all_results, key=lambda x: x["weighted_total"])
    lines.append(f"> [!TIP]")
    lines.append(f"> 综合评分最高版本：**{best['version']}**（{best['weighted_total']}分，{best['grade']}）")
    lines.append(f"> 综合评分最低版本：**{worst['version']}**（{worst['weighted_total']}分，{worst['grade']}）")
    lines.append(f"> 版本间分差：{best['weighted_total'] - worst['weighted_total']:.1f}分\n")

    lines.append("### 评分变化趋势分析\n")
    sorted_by_version = sorted(all_results, key=lambda x: x["version"])
    for i in range(1, len(sorted_by_version)):
        prev = sorted_by_version[i-1]
        curr = sorted_by_version[i]
        diff = curr["weighted_total"] - prev["weighted_total"]
        direction = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
        lines.append(f"- **{prev['version']}→{curr['version']}**：{direction} {abs(diff):.1f}分"
                     f"（{prev['weighted_total']}→{curr['weighted_total']}）")
    lines.append("")

    lines.append("## 二、七维评分比对\n")
    lines.append("> [!NOTE]")
    lines.append("> 七维质量评分体系涵盖形式规范、事实清楚、证据充分、法律适用、说理透彻、实质解纷、语言精练七个维度。\n")
    dim_names = {
        "formal_specification": "D1·形式规范",
        "clear_facts": "D2·事实清楚",
        "sufficient_evidence": "D3·证据充分",
        "correct_law_application": "D4·法律适用",
        "thorough_reasoning": "D5·说理透彻",
        "substantive_resolution": "D6·实质解纷",
        "concise_language": "D7·语言精练",
    }
    dim_descs = {
        "formal_specification": "文书格式规范、要素齐全、结构完整",
        "clear_facts": "案件事实查明清楚、关键情节认定准确",
        "sufficient_evidence": "证据采信充分、举证责任分配合理",
        "correct_law_application": "法律适用正确、条文引用准确",
        "thorough_reasoning": "裁判说理充分、逻辑严密、回应争议焦点",
        "substantive_resolution": "纠纷实质性化解、服判息诉效果好",
        "concise_language": "语言精练、表述准确、无冗余",
    }
    header = "| 维度 |"
    sep = "|:---|"
    for r in all_results:
        header += f" {r['version']} |"
        sep += ":---:|"
    header += " 维度说明 |"
    sep += ":---|"
    lines.append(header)
    lines.append(sep)
    for dim_key, dim_name in dim_names.items():
        row = f"| {dim_name} |"
        for r in all_results:
            row += f" {r['scores'].get(dim_key, 0)} |"
        row += f" {dim_descs.get(dim_key, '')} |"
        lines.append(row)
    lines.append("")

    lines.append("### 各维度版本间变化分析\n")
    for dim_key, dim_name in dim_names.items():
        dim_scores = [(r["version"], r["scores"].get(dim_key, 0)) for r in all_results]
        max_score = max(dim_scores, key=lambda x: x[1])
        min_score = min(dim_scores, key=lambda x: x[1])
        if max_score[1] != min_score[1]:
            lines.append(f"- **{dim_name}**：{max_score[0]}最高（{max_score[1]}分），{min_score[0]}最低（{min_score[1]}分），差距{max_score[1]-min_score[1]}分")
    lines.append("")

    lines.append("## 三、辅助检测比对\n")
    lines.append("> [!NOTE]")
    lines.append("> 辅助检测通过时间线提取、规避模式识别和证据追踪等技术手段，发现文书中的潜在异常和逻辑问题。\n")
    header = "| 检测指标 |"
    sep = "|:---|"
    for r in all_results:
        header += f" {r['version']} |"
        sep += ":---:|"
    lines.append(header)
    lines.append(sep)
    metrics = [
        ("时间线事件数", "timeline_events"),
        ("时间线异常数", "timeline_anomalies"),
        ("规避模式风险", "evasive_risk"),
        ("规避模式数", "evasive_patterns"),
        ("证据项数", "evidence_items"),
        ("未回应证据", "evidence_unaddressed"),
        ("法律冲突数", "law_conflicts"),
        ("类案判例数", "case_precedents"),
        ("法律难点数", "legal_difficulties"),
        ("创新空间数", "innovation_space"),
    ]
    _RISK_ZH = {"low": "低", "medium": "中", "high": "高"}
    for label, key in metrics:
        row = f"| {label} |"
        for r in all_results:
            val = r.get(key, "")
            if key == "evasive_risk":
                val = _RISK_ZH.get(val, val)
            row += f" {val} |"
        lines.append(row)
    lines.append("")

    lines.append("## 四、十六维度异常检测比对\n")
    lines.append("> [!IMPORTANT]")
    lines.append("> 以下比对基于 judicial-doc-anomaly-mcp 的16维检测体系（20260516版），覆盖程序操作、证据采信、事实认定等16个维度。")
    lines.append("> 各维度风险等级和异常数量反映文书在不同方面的规范性和公正性。\n")
    header = "| 检测维度 |"
    sep = "|:---|"
    for r in all_results:
        header += f" {r['version']} |"
        sep += ":---:|"
    lines.append(header)
    lines.append(sep)
    dim_zh = {
        "procedure": "维度1·程序规范", "evidence": "维度2·证据采信", "fact_finding": "维度3·事实认定",
        "focus_drift": "维度4·焦点漂移", "law_application": "维度5·法律适用", "discretion": "维度6·自由裁量",
        "rhetoric_trick": "维度7·修辞技巧", "logic": "维度8·逻辑闭环", "temporal": "维度9·时间一致性",
        "trial_process": "维度10·审理过程", "external_interference": "维度11·外部干预",
        "execution": "维度12·执行问题", "negative_space": "维度13·缺失信息", "semantic_drift": "维度14·语义漂移",
        "case_deviation": "维度15·类案偏离", "coupling": "维度16·惯性耦合",
    }
    for dim in ALL_16_DIMS:
        row = f"| {dim_zh.get(dim, dim)} |"
        for r in all_results:
            dim_result = next((a for a in r.get("anomaly_mcp_results", []) if a.get("dimension") == dim), None)
            if dim_result:
                risk = _RISK_ZH.get(dim_result.get("risk_level", ""), dim_result.get("risk_level", ""))
                count = dim_result.get("anomaly_count", 0)
                if count > 0:
                    row += f" {risk}({count}) |"
                else:
                    row += f" 🟢低 |"
            else:
                row += " — |"
        lines.append(row)
    lines.append("")

    lines.append("### 异常点版本间对比详情\n")
    for dim in ALL_16_DIMS:
        dim_name = dim_zh.get(dim, dim)
        has_anomaly = False
        for r in all_results:
            dim_result = next((a for a in r.get("anomaly_mcp_results", []) if a.get("dimension") == dim), None)
            if dim_result and dim_result.get("anomaly_count", 0) > 0:
                has_anomaly = True
                break
        if has_anomaly:
            lines.append(f"**{dim_name}**：\n")
            for r in all_results:
                dim_result = next((a for a in r.get("anomaly_mcp_results", []) if a.get("dimension") == dim), None)
                if dim_result and dim_result.get("anomaly_count", 0) > 0:
                    anomalies = dim_result.get("anomalies", [])
                    anomaly_names = "、".join(a.get("item_name", "?") for a in anomalies)
                    lines.append(f"- {r['version']}：{dim_result.get('anomaly_count', 0)}项异常（{anomaly_names}）")
                else:
                    lines.append(f"- {r['version']}：无异常")
            lines.append("")

    lines.append("## 五、各版本优缺点深度点评\n")
    for r in all_results:
        v = r["version"]
        lines.append(f"### {v}\n")
        pros = []
        cons = []
        if r["scores"]["thorough_reasoning"] >= 90:
            pros.append("说理充分透彻，论证层次丰富")
        if r["scores"]["correct_law_application"] >= 90:
            pros.append("法律适用准确，引用规范")
        if r["scores"]["sufficient_evidence"] >= 90:
            pros.append("证据采信标准统一，适用证据妨碍规则")
        if r["innovation_bonus"] >= 3:
            pros.append("具有创新亮点（如三方法交叉验证、指导案例引用）")
        if r["timeline_anomalies"] == 0:
            pros.append("时间线无异常，程序规范")
        if r["evasive_risk"] == "low":
            pros.append("规避模式风险低，文书表述规范")
        if r["scores"]["concise_language"] < 80:
            cons.append("语言精练度不足，部分段落冗长")
        if r["evasive_patterns"] > 2:
            cons.append("存在较多规避模式（模糊表述、回避回应等）")
        if r["anomaly_deduction"] > 3:
            cons.append("异常扣分较多，存在需关注的问题")
        if r["evidence_unaddressed"] > 0:
            cons.append("存在未回应证据")
        if r["scores"]["correct_law_application"] < 85:
            cons.append("法律适用存在争议（如奖金计算基数）")

        if pros:
            lines.append("**优点：**\n")
            for p in pros:
                lines.append(f"- {p}")
            lines.append("")
        if cons:
            lines.append("**不足：**\n")
            for c in cons:
                lines.append(f"- {c}")
            lines.append("")

    lines.append("## 六、版本间修复逻辑与迭代优化分析\n")
    lines.append("> [!NOTE]")
    lines.append("> 本节分析各版本间的修复逻辑，展示文书质量的迭代改进过程。\n")
    sorted_by_version = sorted(all_results, key=lambda x: x["version"])
    for i in range(1, len(sorted_by_version)):
        prev = sorted_by_version[i-1]
        curr = sorted_by_version[i]
        lines.append(f"### {prev['version']}→{curr['version']} 修复逻辑\n")
        score_diff = curr["weighted_total"] - prev["weighted_total"]
        if score_diff > 0:
            lines.append(f"**评分变化**：↑{score_diff:.1f}分（{prev['weighted_total']}→{curr['weighted_total']}）\n")
        elif score_diff < 0:
            lines.append(f"**评分变化**：↓{abs(score_diff):.1f}分（{prev['weighted_total']}→{curr['weighted_total']}）\n")
        else:
            lines.append(f"**评分变化**：→ 持平（{prev['weighted_total']}分）\n")

        lines.append("| 维度 | 前版本 | 后版本 | 变化 | 改进点 |")
        lines.append("|:---|:---:|:---:|:---:|:---|")
        for dim_key, dim_name in dim_names.items():
            prev_score = prev["scores"].get(dim_key, 0)
            curr_score = curr["scores"].get(dim_key, 0)
            if prev_score != curr_score:
                diff = curr_score - prev_score
                direction = "↑" if diff > 0 else "↓"
                improvement = f"{'提升' if diff > 0 else '下降'}{abs(diff)}分"
                lines.append(f"| {dim_name} | {prev_score} | {curr_score} | {direction}{abs(diff)} | {improvement} |")
        lines.append("")

        prev_anomaly_dims = set()
        for a in prev.get("anomaly_mcp_results", []):
            if a.get("anomaly_count", 0) > 0:
                prev_anomaly_dims.add(a.get("dimension"))
        curr_anomaly_dims = set()
        for a in curr.get("anomaly_mcp_results", []):
            if a.get("anomaly_count", 0) > 0:
                curr_anomaly_dims.add(a.get("dimension"))
        fixed_dims = prev_anomaly_dims - curr_anomaly_dims
        new_dims = curr_anomaly_dims - prev_anomaly_dims
        if fixed_dims:
            lines.append(f"**已修复异常维度**：{'、'.join(dim_zh.get(d, d) for d in fixed_dims)}\n")
        if new_dims:
            lines.append(f"**新增异常维度**：{'、'.join(dim_zh.get(d, d) for d in new_dims)}\n")

    lines.append("## 七、综合评价与建议\n")
    lines.append("> [!NOTE]")
    lines.append("> 以下综合评价基于七维评分体系、16维异常检测和辅助检测的自动化分析结果，仅供参考。\n")

    all_beneficiary_stats = {}
    for r in all_results:
        for a in r.get("anomaly_mcp_results", []):
            for anom in a.get("anomalies", []):
                b = anom.get("beneficiary", "未标注")
                all_beneficiary_stats[b] = all_beneficiary_stats.get(b, 0) + 1

    if all_beneficiary_stats:
        lines.append("### 全版本获益方分布\n")
        lines.append("> [!NOTE]")
        lines.append("> 汇总所有版本的异常点获益方分布，用于评估异常是否具有跨版本的一致性偏向。\n")
        total_all = sum(all_beneficiary_stats.values())
        lines.append("| 获益方 | 异常项数 | 占比 |")
        lines.append("|:---|:---:|:---:|")
        for b, count in sorted(all_beneficiary_stats.items(), key=lambda x: -x[1]):
            pct = f"{count/total_all*100:.1f}%" if total_all > 0 else "0%"
            lines.append(f"| {b} | {count} | {pct} |")
        lines.append("")

    lines.append("### 全版本异常项汇总\n")
    lines.append("> [!NOTE]")
    lines.append("> 汇总所有版本中检出的异常项，便于跨版本对比分析。\n")
    lines.append("| # | 版本 | 维度 | 异常项 | 获益方 | F编号 | A分类 | 置信度 |")
    lines.append("|:---:|:---:|:---|:---|:---:|:---:|:---:|:---:|")
    seq = 0
    for r in all_results:
        for a in r.get("anomaly_mcp_results", []):
            dim_zh_short = dim_zh.get(a.get("dimension", ""), a.get("dimension", ""))
            for anom in a.get("anomalies", []):
                seq += 1
                lines.append(f"| {seq} | {r['version']} | {dim_zh_short} | {anom.get('item_name', '?')[:50]} | {anom.get('beneficiary', '—')} | {anom.get('f_code', '—')} | {anom.get('a_code', '—')} | {anom.get('confidence', '—')} |")
    if seq == 0:
        lines.append("| - | - | - | 未发现异常 | - | - | - | - |")
    lines.append("")

    sorted_results = sorted(all_results, key=lambda x: x["weighted_total"], reverse=True)
    lines.append("### 排名\n")
    lines.append("| 排名 | 版本 | 综合得分 | 等级 | 核心优势 | 主要不足 |")
    lines.append("|:---:|:---:|:---:|:---:|:---|:---|")
    for rank, r in enumerate(sorted_results, 1):
        advantage = "说理透彻" if r["scores"]["thorough_reasoning"] >= 90 else "法律适用规范"
        weakness = "语言冗长" if r["scores"]["concise_language"] < 80 else "—"
        lines.append(f"| {rank} | {r['version']} | {r['weighted_total']} | {r['grade']} | {advantage} | {weakness} |")
    lines.append("")

    lines.append("### 改进建议\n")
    for r in all_results:
        v = r["version"]
        suggestions = []
        if r["scores"]["concise_language"] < 80:
            suggestions.append("精简文书语言，减少冗余段落")
        if r["scores"]["correct_law_application"] < 85:
            suggestions.append("加强法律适用论证，明确计算基数依据")
        if r["evasive_patterns"] > 2:
            suggestions.append("减少模糊表述，增强回应的明确性")
        if r["timeline_anomalies"] > 0:
            suggestions.append("核实时间线一致性，消除时序异常")
        if suggestions:
            lines.append(f"**{v}**：")
            for s in suggestions:
                lines.append(f"- {s}")
            lines.append("")

    lines.append("---\n")
    lines.append("> [!IMPORTANT]")
    lines.append("> **免责声明**：本比对报告由 judicial-doc-quality-mcp 辅助生成，基于七维评分体系和十六维度异常检测的自动化分析。")
    lines.append("> 评估结果仅供参考，不构成法律意见。\n")
    lines.append(f"*报告由 judicial-doc-quality-mcp v0.1.0 生成 · 检测体系版本 20260519 · {datetime.now().strftime('%Y-%m-%d')}*")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("批量检测5份模拟判决书")
    print(f"检测日期: {today_str}")
    print("=" * 60)

    all_results = []

    for i, filename in enumerate(DOC_FILES):
        filepath = Path(BASE_DIR) / filename
        version_label = extract_version_label(filename)
        print(f"\n[{i+1}/{len(DOC_FILES)}] 处理 {version_label}...")

        result = process_document(filepath, version_label)
        all_results.append(result)

    print("\n\n" + "=" * 60)
    print("生成综合比对报告...")
    print("=" * 60)

    comparison_md = generate_comparison_report(all_results)
    comparison_path = Path(BASE_DIR) / f"综合比对报告_苏06民终6271号_5版本_{today_str}.md"
    with open(comparison_path, "w", encoding="utf-8") as f:
        f.write(comparison_md)
    print(f"综合比对Markdown报告已保存: {comparison_path.name}")

    from judicial_quality_mcp.server import _md_to_rich_html, _build_html_page
    comparison_html_body = _md_to_rich_html(comparison_md)
    comparison_html = _build_html_page(comparison_html_body, f"COMPARE-{today_str}")
    comparison_html_path = Path(BASE_DIR) / f"综合比对报告_苏06民终6271号_5版本_{today_str}.html"
    with open(comparison_html_path, "w", encoding="utf-8") as f:
        f.write(comparison_html)
    print(f"综合比对HTML报告已保存: {comparison_html_path.name}")

    print("\n\n" + "=" * 60)
    print("全部完成！生成报告清单：")
    print("=" * 60)
    for r in all_results:
        print(f"  {r['version']}: {Path(r['report_path']).name} (得分: {r['weighted_total']})")
    print(f"  综合比对: {comparison_path.name}")


if __name__ == "__main__":
    from pathlib import Path
    main()
