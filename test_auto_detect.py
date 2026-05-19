from judicial_quality_mcp.server import query_anomaly_mcp
import json

test_doc = "江苏省[匿名化]中级人民法院民事判决书[匿名化案号]"
result = query_anomaly_mcp(test_doc, dimensions=["procedure", "evidence"])
data = json.loads(result)
print("available:", data.get("available"))
print("auto_detected:", data.get("auto_detected"))
print("total_prompts:", data.get("total_prompts"))
if data.get("prompts"):
    for p in data["prompts"]:
        dim = p.get("dimension")
        has_sys = bool(p.get("system_prompt"))
        has_usr = bool(p.get("user_prompt"))
        err = p.get("error")
        print(f"  dim={dim}, sys_prompt={has_sys}, user_prompt={has_usr}, error={err}")
