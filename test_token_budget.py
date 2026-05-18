from judicial_quality_mcp.server import estimate_token_budget
import json

r = json.loads(estimate_token_budget())
print(json.dumps({
    k: r[k] for k in [
        "success", "total_input_tokens", "available_context",
        "context_utilization", "budget_feasible",
        "recommended_strategy", "overflow_risk"
    ]
}, indent=2, ensure_ascii=False))

print("\nPer-dimension breakdown:")
for d in r["per_dimension_estimate"]:
    print(f"  {d['dimension']}: {d.get('total_input_tokens', '?')} tokens "
          f"(sys={d.get('system_prompt_tokens',0)}, "
          f"prompt={d.get('user_prompt_tokens',0)}, "
          f"doc={d.get('document_tokens',0)}, "
          f"anchor={d.get('anchor_tokens',0)})")

print(f"\nRecommendation: {r['recommendations']}")
