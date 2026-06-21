"""Quick test: verify anomaly_mcp_results is populated."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Load the mock data
MOCK_ANOMALY_RESPONSES = {
    "procedure": """```json
{"dimension": "procedure", "anomalies": [{"item_name": "test"}], "summary": "test", "risk_level": "medium", "anomaly_count": 1}
```""",
}

anomaly_mcp_results = []
try:
    from judicial_lint_mcp.server import render_skill
    for dim_key in ["procedure"]:
        try:
            prompt_json = render_skill(
                skill_name="dimensions/01_procedure",
                variables={"materials": "test document text"},
            )
            prompt_data = json.loads(prompt_json)
            print(f"  {dim_key}: prompt rendered OK")

            mock_response = MOCK_ANOMALY_RESPONSES.get(dim_key, None)
            if mock_response:
                json_match = re.search(r"```(?:json)?\s*\n?(.*?)```", mock_response, re.DOTALL)
                if json_match:
                    parsed_data = json.loads(json_match.group(1).strip())
                else:
                    parsed_data = json.loads(mock_response)
            else:
                parsed_data = {"dimension": dim_key, "anomalies": [], "summary": "OK", "risk_level": "low", "anomaly_count": 0}

            anomaly_mcp_results.append(parsed_data)
            print(f"  {dim_key}: {parsed_data.get('anomaly_count', 0)} anomalies, risk={parsed_data.get('risk_level', 'unknown')}")
        except Exception as e:
            print(f"  {dim_key}: ERROR - {e}")

    print(f"\nanomaly_mcp_results length: {len(anomaly_mcp_results)}")
    print(f"anomaly_mcp_results truthy: {bool(anomaly_mcp_results)}")
    print(f"First item: {json.dumps(anomaly_mcp_results[0], ensure_ascii=False)}")
except ImportError as e:
    print(f"Import error: {e}")
