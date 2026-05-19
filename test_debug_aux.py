import json
from judicial_quality_mcp.server import extract_timeline, detect_evasive_patterns, trace_evidence_references

doc_path = r"C:\Users\stere\WorkBuddy\2026-05-18-task-3\workbuddyKimiK26_完美模拟二审判决书_苏06民终6271号_20260518.md"
with open(doc_path, encoding="utf-8") as f:
    doc_text = f.read()

timeline = json.loads(extract_timeline(doc_text))
print("Timeline keys:", list(timeline.keys()))
print("total_events:", timeline.get("total_events"))
print("anomaly_count:", timeline.get("anomaly_count"))
print("completeness:", timeline.get("completeness"))
if timeline.get("anomalies"):
    print("First anomaly:", json.dumps(timeline["anomalies"][0], ensure_ascii=False)[:200])

print("\n---")

evasive = json.loads(detect_evasive_patterns(doc_text))
print("Evasive keys:", list(evasive.keys()))
print("risk_level:", evasive.get("risk_level"))
print("detected_count:", evasive.get("detected_count"))

print("\n---")

evidence = json.loads(trace_evidence_references(doc_text))
print("Evidence keys:", list(evidence.keys()))
print("total_evidence:", evidence.get("total_evidence"))
print("unaddressed_count:", evidence.get("unaddressed_count"))
