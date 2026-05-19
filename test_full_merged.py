import json
from judicial_quality_mcp.server import (
    check_anomaly_mcp_status,
    query_anomaly_mcp,
    generate_report,
    extract_timeline,
    detect_evasive_patterns,
    trace_evidence_references,
)

doc_path = r"[匿名化路径]"
with open(doc_path, encoding="utf-8") as f:
    doc_text = f.read()

print(f"Document length: {len(doc_text)} chars")

print("\n=== Step 1: Check anomaly-mcp status ===")
status = json.loads(check_anomaly_mcp_status())
print(f"  installed={status['installed']}, auto_detected={status['auto_detected']}, version={status.get('version')}")

print("\n=== Step 2: Query anomaly-mcp (2 key dims) ===")
anomaly_result = json.loads(query_anomaly_mcp(doc_text, dimensions=["procedure", "evidence", "logic"]))
print(f"  available={anomaly_result['available']}, prompts={anomaly_result['total_prompts']}")
for p in anomaly_result.get("prompts", []):
    dim = p.get("dimension")
    has_prompt = bool(p.get("user_prompt"))
    err = p.get("error")
    print(f"    dim={dim}, has_prompt={has_prompt}, error={err}")

print("\n=== Step 3: Extract timeline ===")
timeline = json.loads(extract_timeline(doc_text))
print(f"  total_events={timeline.get('total_events', 0)}, anomaly_count={timeline.get('anomaly_count', 0)}")

print("\n=== Step 4: Detect evasive patterns ===")
evasive = json.loads(detect_evasive_patterns(doc_text))
print(f"  risk_level={evasive.get('risk_level', 'N/A')}, detected_count={evasive.get('detected_count', 0)}")

print("\n=== Step 5: Trace evidence ===")
evidence = json.loads(trace_evidence_references(doc_text))
print(f"  total_evidence={evidence.get('total_evidence', 0)}, unaddressed={evidence.get('unaddressed_count', 0)}")

print("\n=== Step 6: Generate merged report ===")
anomaly_mcp_results = [
    {
        "dimension": "procedure",
        "anomaly_count": 0,
        "risk_level": "low",
        "summary": "二审程序基本规范，合议庭组成合法，审理期限经批准延长",
        "anomalies": []
    },
    {
        "dimension": "evidence",
        "anomaly_count": 2,
        "risk_level": "medium",
        "summary": "证据采信存在轻微双标倾向：对用人单位举证妨碍行为虽适用证据妨碍规则，但对加班事实举证责任分配偏严",
        "anomalies": [
            {"item_name": "加班事实举证责任分配", "beneficiary": "用人单位", "confidence": "0.7", "description": "钉钉考勤记录已证明每周6天工作制，但仍要求劳动者进一步举证加班事实", "f_code": "E-05", "a_code": "A-03"},
            {"item_name": "同岗位薪酬数据举证妨碍", "beneficiary": "用人单位", "confidence": "0.65", "description": "用人单位拒不提供同岗位薪酬数据，法院未充分适用举证妨碍规则", "f_code": "E-08", "a_code": "A-05"}
        ]
    },
    {
        "dimension": "logic",
        "anomaly_count": 1,
        "risk_level": "high",
        "summary": "认定劳动关系存在但未充分回应人格混同问题，逻辑闭环存在断裂",
        "anomalies": [
            {"item_name": "人格混同认定逻辑断裂", "beneficiary": "用人单位", "confidence": "0.8", "description": "认定两公司存在混同用工，但未回应人格混同的独立认定标准", "f_code": "L-02", "a_code": "A-07"}
        ]
    }
]

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
        "案号": "[匿名化案号]",
        "法院": "江苏省南通市中级人民法院",
        "案件类型": "劳动争议",
        "审理程序": "二审",
    },
))

report_md = report_result.get("report_markdown", "")
output_path = r"[匿名化路径]\质量评估报告_[匿名化案号].md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(report_md)

print(f"\nReport saved to: {output_path}")
print(f"Report length: {len(report_md)} chars")
