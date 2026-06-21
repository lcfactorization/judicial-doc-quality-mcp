"""Quick test: check parse_response output structure."""
import json
from judicial_lint_mcp.server import parse_response

mock_response = """```json
{
  "dimension": "procedure",
  "anomalies": [
    {
      "item_name": "test anomaly",
      "description": "test desc",
      "beneficiary": "test",
      "confidence": "high",
      "f_code": "P-01",
      "a_code": "A-01"
    }
  ],
  "summary": "test summary text",
  "risk_level": "medium",
  "anomaly_count": 1
}
```"""

result = parse_response(dimension="procedure", response=mock_response, dimension_index=0)
data = json.loads(result)
print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
