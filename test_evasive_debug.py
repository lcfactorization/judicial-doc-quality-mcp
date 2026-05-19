import json
from judicial_quality_mcp.server import detect_evasive_patterns

doc_path = r"C:\Users\stere\WorkBuddy\2026-05-18-task-3\workbuddyKimiK26_完美模拟二审判决书_苏06民终6271号_20260518.md"
with open(doc_path, encoding="utf-8") as f:
    doc_text = f.read()

evasive = json.loads(detect_evasive_patterns(doc_text))
patterns = evasive.get("detected_patterns", [])
print(f"Patterns count: {len(patterns)}")
for p in patterns:
    print(f"  keys: {list(p.keys())}")
    print(f"  data: {json.dumps(p, ensure_ascii=False)[:200]}")
