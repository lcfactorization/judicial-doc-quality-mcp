import json
from judicial_quality_mcp.server import detect_evasive_patterns

doc_path = r"[匿名化路径]"
with open(doc_path, encoding="utf-8") as f:
    doc_text = f.read()

evasive = json.loads(detect_evasive_patterns(doc_text))
patterns = evasive.get("detected_patterns", [])
print(f"Patterns count: {len(patterns)}")
for p in patterns:
    print(f"  keys: {list(p.keys())}")
    print(f"  data: {json.dumps(p, ensure_ascii=False)[:200]}")
