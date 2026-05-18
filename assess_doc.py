"""评估脚本：对（2025）苏06民终6271号判决书进行七维质量评估"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from judicial_quality_mcp.server import (
    extract_document_sections,
    extract_timeline,
    detect_evasive_patterns,
    trace_evidence_references,
    query_anomaly_mcp,
    list_dimensions,
    estimate_token_budget,
    get_dimension_standards,
    cross_check_consistency,
    calculate_weighted_score,
    generate_report,
    pipeline_progress,
)

DOC_PATH = r"C:\Users\stere\WorkBuddy\2026-05-18-task-3\workbuddyKimiK26_完美模拟二审判决书_苏06民终6271号_20260518.md"

with open(DOC_PATH, "r", encoding="utf-8") as f:
    doc_text = f.read()

print(f"文档长度: {len(doc_text)} 字符")
print("=" * 80)

print("\n[1/8] 提取文书段落...")
sections_result = json.loads(extract_document_sections(doc_text))
print(f"  置信度: {sections_result.get('confidence', 'N/A')}")
print(f"  段落数: {len(sections_result.get('sections', {}))}")
for k, v in sections_result.get("sections", {}).items():
    preview = v[:80].replace("\n", " ") if v else "(空)"
    print(f"    {k}: {preview}...")

print("\n[2/8] 列出评分维度...")
dims_result = json.loads(list_dimensions())
for d in dims_result.get("dimensions", []):
    print(f"  {d['name']}: {d['title']} (权重{d['weight']}, 满分{d['full_score']})")

print("\n[3/8] 预估Token消耗...")
budget_result = json.loads(estimate_token_budget(include_anchors=True, anchor_count=2))
print(f"  总Token: {budget_result.get('total_tokens', 'N/A')}")
for d in budget_result.get("dimensions", []):
    print(f"    {d['name']}: {d['tokens']} tokens")

print("\n[4/8] 提取时间线...")
timeline_result = json.loads(extract_timeline(doc_text))
print(f"  事件数: {timeline_result.get('total_events', 0)}")
print(f"  异常数: {timeline_result.get('anomaly_count', 0)}")
print(f"  完整性: {timeline_result.get('completeness', 'N/A')}")
for evt in timeline_result.get("events", [])[:5]:
    print(f"    {evt.get('date', '?')}: {evt.get('text', '')[:60]}...")
for anom in timeline_result.get("anomalies", []):
    print(f"  ⚠ [{anom.get('severity', '?')}] {anom.get('type', '?')}: {anom.get('message', '')[:80]}")

print("\n[5/8] 检测规避模式...")
evasive_result = json.loads(detect_evasive_patterns(doc_text))
print(f"  风险等级: {evasive_result.get('risk_level', 'N/A')}")
print(f"  检出数: {evasive_result.get('detected_count', 0)}")
for p in evasive_result.get("patterns", []):
    print(f"  [{p.get('severity', '?')}] {p.get('name', '?')}: {p.get('description', '')[:80]}")
    print(f"    匹配数: {p.get('match_count', 0)}, 示例: {p.get('sample', '')[:60]}...")
print(f"  建议: {evasive_result.get('recommendation', 'N/A')}")

print("\n[6/8] 追踪证据引用...")
evidence_result = json.loads(trace_evidence_references(doc_text))
print(f"  证据项数: {evidence_result.get('total_evidence', 0)}")
print(f"  未回应数: {evidence_result.get('unaddressed_count', 0)}")
print(f"  缺说理数: {evidence_result.get('missing_reasoning_count', 0)}")
print(f"  完整性: {evidence_result.get('completeness', 'N/A')}")
for ev in evidence_result.get("evidence_items", [])[:5]:
    print(f"    [{ev.get('status', '?')}] {ev.get('reference', '')[:60]}...")

print("\n[7/8] 异常MCP联动查询...")
anomaly_result = json.loads(query_anomaly_mcp(doc_text))
print(f"  可用: {anomaly_result.get('available', False)}")
if anomaly_result.get("anomaly_results"):
    for a in anomaly_result["anomaly_results"][:5]:
        print(f"  [{a.get('severity', '?')}] {a.get('dimension', '?')}: {a.get('description', '')[:60]}")
else:
    print("  (异常MCP不可用，返回空白结果)")

print("\n[8/8] 获取维度评分标准（样例）...")
for dim in ["formal_specification", "clear_facts", "sufficient_evidence",
            "correct_law_application", "thorough_reasoning",
            "substantive_resolution", "concise_language"]:
    std = json.loads(get_dimension_standards(dim))
    deductions = std.get("deductions", [])
    bonuses = std.get("bonuses", [])
    print(f"  {dim}: 扣分项{len(deductions)}个, 加分项{len(bonuses)}个")

print("\n" + "=" * 80)
print("工具调用全部完成，准备生成评估报告...")
