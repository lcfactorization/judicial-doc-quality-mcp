import json
from judicial_quality_mcp.response_parser import ResponseParser
from judicial_quality_mcp.server import generate_report, _infer_trial_stage

p = ResponseParser()
test_json = json.dumps({
    "quote": "test",
    "reasoning": "test",
    "score": 80,
    "deduction_items": [{
        "item": "test",
        "deduction": 10,
        "a_code": "A1",
        "beneficiary": "上诉人",
        "conclusion": "成立",
        "net_anomaly": "成立",
        "stage_scope": "二审",
        "stage_unclear": False
    }],
    "bonus_items": []
})
r = p.parse_score_result("clear_facts", test_json)
print("response_parser OK")
print("  format_valid:", r["validation"]["format_valid"])
print("  warnings:", len(r["validation"]["warnings"]))

report = generate_report(
    dimension_results=[{"dimension": "clear_facts", "score": 80}],
    weighted_total=80.0,
    grade="B+",
    document_meta={"案号": "[匿名化案号]"},
    trial_stage="二审",
)
report_data = json.loads(report)
md = report_data.get("report_markdown", "")
print("\ngenerate_report with trial_stage OK")
print("  审级 in report:", "审级" in md)
print("  二审 in report:", "二审" in md)
print("  责任界定 in report:", "责任界定" in md)

print("\n_infer_trial_stage tests:")
print("  民终6271号:", _infer_trial_stage("（2025）苏06民终6271号"))
print("  民初1234号:", _infer_trial_stage("（2025）苏06民初1234号"))
print("  民再56号:", _infer_trial_stage("（2025）苏06民再56号"))
print("  content test:", _infer_trial_stage("", "上诉人xxx因不服一审判决"))

print("\n=== All dryrun tests passed ===")
