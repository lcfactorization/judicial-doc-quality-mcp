import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from judicial_quality_mcp.server import (
    extract_document_sections,
    extract_timeline,
    detect_evasive_patterns,
    trace_evidence_references,
    check_anomaly_mcp_status,
    query_anomaly_mcp,
    submit_anomaly_response,
    finalize_anomaly_detection,
    generate_report,
    generate_html_report,
    _infer_trial_stage,
)

DOC_PATH = r"C:\Users\stere\Documents\Obsidian Vault\TraeGLM51_模拟二审判决书_苏06民终6271号劳动争议_V12_20260517.md"

with open(DOC_PATH, "r", encoding="utf-8") as f:
    doc_text = f.read()

print(f"=== V12二审判决书完整测试 ===")
print(f"文档长度: {len(doc_text)} 字符")
print()

# ── Step 0: 审级推断 ──
print("[Step 0] 审级推断测试")
sections_result = json.loads(extract_document_sections(doc_text))
trial_stage = sections_result.get("trial_stage", "")
print(f"  自动推断审级: {trial_stage}")
print(f"  期望审级: 二审")
print(f"  审级推断: {'PASS' if trial_stage == '二审' else 'FAIL'}")
print()

# ── Step 1: 异常检测（先进行） ──
print("[Step 1] 异常检测MCP联动")
anomaly_status = json.loads(check_anomaly_mcp_status())
print(f"  anomaly-mcp 可用: {anomaly_status.get('installed', False)}")

anomaly_query = json.loads(query_anomaly_mcp(doc_text))
anomaly_available = anomaly_query.get("available", False)
print(f"  异常检测可用: {anomaly_available}")

anomaly_mcp_results = []
if anomaly_available:
    prompts = anomaly_query.get("prompts", [])
    print(f"  检测维度数: {len(prompts)}")
    for i, prompt_info in enumerate(prompts):
        dim = prompt_info.get("dimension", f"dim_{i}")
        anomaly_mcp_results.append({
            "dimension": dim,
            "anomaly_count": 0,
            "risk_level": "low",
            "summary": f"{dim}维度检测完成（dryrun模式）",
            "anomalies": []
        })
    finalize = json.loads(finalize_anomaly_detection())
    print(f"  异常检测汇总: {finalize.get('total_anomalies', 0)} 个异常")
else:
    print("  anomaly-mcp 不可用，使用辅助检测替代")
    timeline = json.loads(extract_timeline(doc_text))
    evasive = json.loads(detect_evasive_patterns(doc_text))
    evidence = json.loads(trace_evidence_references(doc_text))
    print(f"  时间线事件: {timeline.get('total_events', 0)}")
    print(f"  时间线异常: {timeline.get('anomaly_count', 0)}")
    print(f"  规避模式风险: {evasive.get('risk_level', 'N/A')}")
    print(f"  证据项数: {evidence.get('total_evidence', 0)}")
print()

# ── Step 2: 质量评估 ──
print("[Step 2] 质量评估报告生成（含审级信息）")
dimension_results = [
    {"dimension": "formal_specification", "score": 82},
    {"dimension": "clear_facts", "score": 78},
    {"dimension": "sufficient_evidence", "score": 75},
    {"dimension": "correct_law_application", "score": 80},
    {"dimension": "thorough_reasoning", "score": 76},
    {"dimension": "substantive_resolution", "score": 85},
    {"dimension": "concise_language", "score": 79},
]

report_result = json.loads(generate_report(
    dimension_results=dimension_results,
    weighted_total=79.5,
    grade="B+",
    anomaly_deduction=3,
    innovation_bonus=2,
    anomaly_details=[{"label": "证据采信", "severity": "medium", "deduction": 3, "description": "部分证据采信说理不充分"}],
    innovation_details=[{"label": "证据妨碍规则", "bonus": 2, "description": "适用举证妨碍规则"}],
    anomaly_mcp_results=anomaly_mcp_results if anomaly_mcp_results else None,
    timeline_result=timeline if not anomaly_available else None,
    evasive_result=evasive if not anomaly_available else None,
    evidence_result=evidence if not anomaly_available else None,
    document_meta={
        "案号": "[匿名化案号]",
        "法院": "[匿名化法院]",
        "案件类型": "劳动争议",
        "审理程序": "二审",
    },
    trial_stage=trial_stage,
))

report_md = report_result.get("report_markdown", "")
print(f"  报告长度: {len(report_md)} 字符")
print(f"  审级信息: {'PASS' if '审级' in report_md else 'FAIL'}")
print(f"  责任界定: {'PASS' if '责任界定' in report_md else 'FAIL'}")
print(f"  二审标注: {'PASS' if '二审' in report_md else 'FAIL'}")
print()

# ── Step 3: HTML报告生成 ──
print("[Step 3] HTML报告生成")
html_result = json.loads(generate_html_report(
    weighted_total=79.5,
    grade="B+",
    dimension_results=dimension_results,
    anomaly_details=[{"label": "证据采信", "severity": "medium", "deduction": 3, "description": "部分证据采信说理不充分"}],
    innovation_details=[{"label": "证据妨碍规则", "bonus": 2, "description": "适用举证妨碍规则"}],
    anomaly_deduction=3,
    innovation_bonus=2,
    document_meta={
        "案号": "[匿名化案号]",
        "法院": "[匿名化法院]",
        "案件类型": "劳动争议",
        "审理程序": "二审",
    },
    trial_stage=trial_stage,
))
html_content = html_result.get("report_html", "")
print(f"  HTML长度: {len(html_content)} 字符")
print(f"  HTML生成: {'PASS' if len(html_content) > 1000 else 'FAIL'}")
print()

# ── Step 4: 保存报告 ──
today_str = datetime.now().strftime("%Y%m%d")
output_dir = os.path.dirname(DOC_PATH)
report_path = os.path.join(output_dir, f"质量评估报告_V12_审级测试_{today_str}.md")
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report_md)
print(f"[Step 4] 报告已保存: {os.path.basename(report_path)}")

html_path = os.path.join(output_dir, f"质量评估报告_V12_审级测试_{today_str}.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)
print(f"  HTML已保存: {os.path.basename(html_path)}")
print()

# ── Step 5: 脱敏验证 ──
print("[Step 5] 脱敏验证")
sensitive_patterns = ["苏06民终6271号", "苏01民终6271号", "南通市中级人民法院"]
found_sensitive = []
for pattern in sensitive_patterns:
    if pattern in report_md:
        found_sensitive.append(pattern)
if found_sensitive:
    print(f"  FAIL: 报告中发现敏感信息: {found_sensitive}")
else:
    print("  PASS: 报告中未发现敏感信息")
print()

print("=" * 60)
print("=== V12完整测试完成 ===")
print("=" * 60)
