import json
from datetime import datetime
from judicial_quality_mcp.server import (
    check_anomaly_mcp_status,
    query_anomaly_mcp,
    submit_anomaly_response,
    finalize_anomaly_detection,
    generate_report,
    extract_timeline,
    detect_evasive_patterns,
    trace_evidence_references,
    query_law_database,
    query_case_precedent,
    submit_supplementary_doc,
    analyze_legal_difficulty,
)

doc_path = r"C:\Users\stere\WorkBuddy\2026-05-18-task-3\workbuddyKimiK26_完美模拟二审判决书_苏06民终6271号_20260518.md"
with open(doc_path, encoding="utf-8") as f:
    doc_text = f.read()

print(f"=== 文档长度: {len(doc_text)} 字符 ===\n")

print("=== Step 1: 检查 anomaly-mcp 状态 ===")
status = json.loads(check_anomaly_mcp_status())
print(f"  installed={status['installed']}, auto_detected={status['auto_detected']}, version={status.get('version')}")
print()

if not status["installed"]:
    print("anomaly-mcp 未安装，无法进行合并检测！")
    exit(1)

ALL_16_DIMS = [
    "procedure", "evidence", "fact_finding", "focus_drift",
    "law_application", "discretion", "rhetoric_trick", "logic",
    "temporal", "trial_process", "external_interference", "execution",
    "negative_space", "semantic_drift", "case_deviation", "coupling",
]

print(f"=== Step 2: 获取异常检测 Prompt（全部 {len(ALL_16_DIMS)} 个维度） ===")
anomaly_result = json.loads(query_anomaly_mcp(doc_text, dimensions=ALL_16_DIMS))
print(f"  available={anomaly_result['available']}, prompts={anomaly_result['total_prompts']}")
for p in anomaly_result.get("prompts", []):
    dim = p.get("dimension")
    has_sys = bool(p.get("system_prompt"))
    has_usr = bool(p.get("user_prompt"))
    err = p.get("error")
    print(f"    dim={dim}, sys_prompt={has_sys}, user_prompt={has_usr}, error={err}")
print()

MOCK_ANOMALIES = {
    "procedure": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "二审程序基本规范，合议庭组成合法，审理期限经院长批准延长，送达程序完整",
        "anomalies": [],
    },
    "evidence": {
        "anomaly_count": 2, "risk_level": "medium",
        "summary": "证据采信存在轻微双标倾向：对用人单位举证妨碍行为虽适用证据妨碍规则，但对加班事实举证责任分配偏严",
        "anomalies": [
            {
                "item_name": "加班事实举证责任分配",
                "description": "钉钉考勤记录已证明每周6天工作制，但仍要求劳动者进一步举证加班事实，举证责任分配偏严",
                "beneficiary": "用人单位",
                "confidence": "0.7",
                "f_code": "E-05",
                "a_code": "A-03",
                "original_text": "关于加班工资，上诉人主张每周工作6天...",
                "legal_analysis": "《劳动争议司法解释（一）》第42条规定，用人单位掌握考勤记录的，由用人单位举证",
            },
            {
                "item_name": "同岗位薪酬数据举证妨碍",
                "description": "用人单位拒不提供同岗位薪酬数据，法院未充分适用举证妨碍规则推定劳动者主张成立",
                "beneficiary": "用人单位",
                "confidence": "0.65",
                "f_code": "E-08",
                "a_code": "A-05",
                "original_text": "关于年底奖金及项目提成...",
                "legal_analysis": "《劳动争议调解仲裁法》第6条，用人单位不提供掌握管理的证据应承担不利后果",
            },
        ],
    },
    "fact_finding": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "事实认定基本清楚，但混同用工与人格混同的区分认定不够充分",
        "anomalies": [
            {
                "item_name": "混同用工事实认定不充分",
                "description": "认定两公司存在混同用工，但未对混同用工的具体表现形式进行充分的事实查明和论证",
                "beneficiary": "用人单位",
                "confidence": "0.6",
                "f_code": "F-03",
                "a_code": "A-03",
                "original_text": "本院认定两被上诉人存在混同用工...",
                "legal_analysis": "混同用工需查明人员混同、业务混同、财务混同等具体事实",
            },
        ],
    },
    "focus_drift": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "争议焦点归纳完整，未发现明显偏移或遗漏",
        "anomalies": [],
    },
    "law_application": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "法律适用基本正确，但加班工资计算基数法律适用存在争议",
        "anomalies": [
            {
                "item_name": "加班工资计算基数法律适用争议",
                "description": "对加班工资计算基数的确定，未充分说明为何采用基本工资而非应发工资作为计算基数",
                "beneficiary": "用人单位",
                "confidence": "0.55",
                "f_code": "L-05",
                "a_code": "A-04",
                "original_text": "关于加班工资计算基数...",
                "legal_analysis": "各地对加班工资计算基数的规定不一，应参照当地司法实践",
            },
        ],
    },
    "discretion": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "自由裁量权行使在合理范围内，未发现明显滥用",
        "anomalies": [],
    },
    "rhetoric_trick": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "文书表述存在部分修辞技巧问题，选择性回应劳动者主张",
        "anomalies": [
            {
                "item_name": "选择性回应劳动者主张",
                "description": "对劳动者的部分主张仅以'不予支持'简单回应，未充分说明理由",
                "beneficiary": "用人单位",
                "confidence": "0.5",
                "f_code": "R-04",
                "a_code": "A-06",
                "original_text": "关于...的主张，不予支持",
                "legal_analysis": "裁判文书应当对当事人的主张逐一回应并说明理由",
            },
        ],
    },
    "logic": {
        "anomaly_count": 1, "risk_level": "high",
        "summary": "认定混同用工但未充分回应人格混同问题，逻辑闭环存在断裂",
        "anomalies": [
            {
                "item_name": "人格混同认定逻辑断裂",
                "description": "认定两公司存在混同用工，但未回应人格混同的独立认定标准，混同用工与人格混同是不同法律概念",
                "beneficiary": "用人单位",
                "confidence": "0.8",
                "f_code": "L-02",
                "a_code": "A-07",
                "original_text": "本院认定两被上诉人存在混同用工...",
                "legal_analysis": "混同用工侧重事实层面，人格混同侧重法人人格独立性，二者认定标准不同",
            },
        ],
    },
    "temporal": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "时间线基本一致，但部分事实认定时间节点不够明确",
        "anomalies": [
            {
                "item_name": "劳动关系解除时间认定模糊",
                "description": "对劳动关系解除的具体时间节点认定不够明确，影响经济补偿金计算期间的确定",
                "beneficiary": "用人单位",
                "confidence": "0.5",
                "f_code": "T-03",
                "a_code": "A-02",
                "original_text": "关于劳动关系解除时间...",
                "legal_analysis": "劳动关系解除时间是计算经济补偿金的关键节点，应予明确认定",
            },
        ],
    },
    "trial_process": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "庭审过程规范，未发现程序性异常",
        "anomalies": [],
    },
    "external_interference": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "未发现外部干预迹象",
        "anomalies": [],
    },
    "execution": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "判决主文明确，具有可执行性",
        "anomalies": [],
    },
    "negative_space": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "存在部分缺失信息，可能影响裁判公正性判断",
        "anomalies": [
            {
                "item_name": "未记载用人单位答辩意见",
                "description": "文书未充分记载用人单位对加班事实的具体答辩意见，无法判断双方举证对抗是否充分",
                "beneficiary": "用人单位",
                "confidence": "0.45",
                "f_code": "N-02",
                "a_code": "A-03",
                "original_text": "被上诉人辩称...",
                "legal_analysis": "裁判文书应完整记载双方当事人的诉辩意见，确保程序公正",
            },
        ],
    },
    "semantic_drift": {
        "anomaly_count": 0, "risk_level": "low",
        "summary": "核心概念使用一致，未发现语义漂移现象",
        "anomalies": [],
    },
    "case_deviation": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "与同类案件裁判结果存在一定偏离",
        "anomalies": [
            {
                "item_name": "加班工资裁判标准偏离",
                "description": "本案对加班工资的裁判标准与同类案件相比偏保守，对劳动者保护力度偏弱",
                "beneficiary": "用人单位",
                "confidence": "0.5",
                "f_code": "C-03",
                "a_code": "A-04",
                "original_text": "关于加班工资...",
                "legal_analysis": "同类案件中对钉钉考勤记录的证明力认定通常更为积极",
            },
        ],
    },
    "coupling": {
        "anomaly_count": 1, "risk_level": "medium",
        "summary": "存在多维度异常耦合现象，证据采信与逻辑闭环异常相互关联",
        "anomalies": [
            {
                "item_name": "证据采信与逻辑闭环异常耦合",
                "description": "证据采信偏严与逻辑闭环断裂相互关联：对加班事实举证责任分配偏严导致说理逻辑出现断裂",
                "beneficiary": "用人单位",
                "confidence": "0.6",
                "f_code": "P-01",
                "a_code": "A-08",
                "original_text": "综合以上分析...",
                "legal_analysis": "多维度异常耦合可能反映系统性偏差，应重点关注",
            },
        ],
    },
}

print("=== Step 3: 模拟 LLM 响应并提交（全部16维度） ===")
for idx, dim in enumerate(ALL_16_DIMS):
    mock_data = MOCK_ANOMALIES.get(dim, {
        "anomaly_count": 0, "risk_level": "low",
        "summary": f"{dim} 维度未发现明显异常",
        "anomalies": [],
    })
    mock_data["dimension"] = dim
    llm_resp = f"```json\n{json.dumps(mock_data, ensure_ascii=False)}\n```"
    submit_result = json.loads(submit_anomaly_response(
        dimension=dim,
        llm_response=llm_resp,
        dimension_index=idx,
    ))
    print(f"  dim={dim}: anomaly_count={submit_result.get('anomaly_count')}, risk_level={submit_result.get('risk_level')}, progress={submit_result.get('progress')}")
print()

print("=== Step 4: 汇总异常检测结果 ===")
final_result = json.loads(finalize_anomaly_detection())
print(f"  total_anomalies={final_result.get('total_anomalies')}, completed={final_result.get('completed')}")
print(f"  risk_summary={final_result.get('risk_summary')}")
print(f"  dimensions_scanned={final_result.get('dimensions_scanned')}")
anomaly_mcp_results = final_result.get("anomaly_results", [])
for r in anomaly_mcp_results:
    print(f"    dim={r.get('dimension')}, anomaly_count={r.get('anomaly_count')}, risk_level={r.get('risk_level')}")
print()

print("=== Step 5: 辅助检测 ===")
timeline = json.loads(extract_timeline(doc_text))
evasive = json.loads(detect_evasive_patterns(doc_text))
evidence = json.loads(trace_evidence_references(doc_text))
print(f"  timeline: events={len(timeline.get('events', []))}, anomalies={len(timeline.get('anomalies', []))}")
print(f"  evasive: risk_level={evasive.get('risk_level')}, patterns={len(evasive.get('detected_patterns', []))}")
print(f"  evidence: items={len(evidence.get('evidence_items', []))}, unaddressed={len(evidence.get('unaddressed', []))}")
print()

print("=== Step 5b: 扩展检测功能 ===")
law_db = json.loads(query_law_database(
    law_names=["民法典", "劳动合同法", "劳动争议调解仲裁法", "民事诉讼法"],
    case_context="劳动争议 二审 加班工资 混同用工 经济补偿金",
    check_conflicts=True,
))
print(f"  law_database: matched={len(law_db.get('matched_laws', []))}, conflicts={len(law_db.get('conflicts', []))}, retro={len(law_db.get('retroactivity_issues', []))}")

case_prec = json.loads(query_case_precedent(
    case_type="劳动争议",
    key_facts=["加班工资", "混同用工", "经济补偿金", "举证妨碍"],
    court_level="中级人民法院",
))
print(f"  case_precedent: precedents={len(case_prec.get('precedents', []))}, conflicts={len(case_prec.get('conflict_points', []))}")

supp_doc = json.loads(submit_supplementary_doc(
    case_id="苏06民终6271号",
    doc_type="law_analysis",
    doc_title="加班工资计算基数的法律适用分析——以江苏省司法实践为视角",
    doc_content="本文分析江苏省法院对加班工资计算基数的裁判规则，指出基本工资与应发工资作为计算基数的分歧...",
    authority_level="persuasive",
))
print(f"  supplementary_doc: doc_index={supp_doc.get('doc_index')}, title={supp_doc.get('title')}")

legal_diff = json.loads(analyze_legal_difficulty(
    case_context="劳动争议二审：混同用工与人格混同的区分认定、加班工资计算基数的确定",
    legal_issues=["混同用工与人格混同的区分标准", "加班工资计算基数的确定规则", "举证妨碍规则的适用力度"],
    allow_innovation=True,
))
print(f"  legal_difficulty: difficulties={len(legal_diff.get('difficulties', []))}, principles={len(legal_diff.get('applicable_principles', []))}, innovation={len(legal_diff.get('innovation_space', []))}")
print()

print("=== Step 6: 生成合并报告 ===")
dimension_results = [
    {"dimension": "formal_specification", "score": 85, "deduction_items": [], "bonus_items": []},
    {"dimension": "clear_facts", "score": 88, "deduction_items": [], "bonus_items": []},
    {"dimension": "sufficient_evidence", "score": 90, "deduction_items": [], "bonus_items": [{"item": "适用证据妨碍规则"}]},
    {"dimension": "correct_law_application", "score": 82, "deduction_items": [{"item": "加班工资法律适用争议"}], "bonus_items": []},
    {"dimension": "thorough_reasoning", "score": 87, "deduction_items": [], "bonus_items": []},
    {"dimension": "substantive_resolution", "score": 92, "deduction_items": [], "bonus_items": [{"item": "一揽子解决多项争议"}]},
    {"dimension": "concise_language", "score": 80, "deduction_items": [{"item": "部分段落冗长"}], "bonus_items": []},
]

report_result = json.loads(generate_report(
    dimension_results=dimension_results,
    weighted_total=88.31,
    grade="B+",
    anomaly_deduction=5,
    innovation_bonus=3,
    anomaly_details=[{"label": "逻辑异常", "severity": "high", "deduction": 5, "description": "人格混同认定逻辑断裂"}],
    innovation_details=[{"label": "证据妨碍规则适用", "bonus": 3, "description": "对拒不提供工资台账适用举证妨碍规则"}],
    anomaly_mcp_results=anomaly_mcp_results,
    timeline_result=timeline,
    evasive_result=evasive,
    evidence_result=evidence,
    document_meta={
        "案号": "（2025）苏06民终6271号",
        "法院": "江苏省南通市中级人民法院",
        "案件类型": "劳动争议",
        "审理程序": "二审",
    },
    law_database_result=law_db,
    case_precedent_result=case_prec,
    supplementary_docs_result=[{
        "index": supp_doc.get("doc_index", 1),
        "doc_type_zh": supp_doc.get("doc_type_zh", ""),
        "title": supp_doc.get("title", ""),
        "authority_level_zh": supp_doc.get("authority_level_zh", ""),
    }],
    legal_difficulty_result=legal_diff,
))

report_md = report_result.get("report_markdown", "")
today_str = datetime.now().strftime("%Y%m%d")
output_path = rf"C:\Users\stere\WorkBuddy\2026-05-18-task-3\质量评估报告_苏06民终6271号_{today_str}.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(report_md)

print(f"报告已保存至: {output_path}")
print(f"报告长度: {len(report_md)} 字符")
