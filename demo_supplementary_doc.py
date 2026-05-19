"""演示补充说明文档提交与报告引用流程。

本脚本演示：
1. 提交多份不同类型的补充文档
2. 在报告中引用并展示这些文档
3. 验证扩展检测功能的完整协作流程
"""
import json
from datetime import datetime
from judicial_quality_mcp.server import (
    submit_supplementary_doc,
    query_law_database,
    query_case_precedent,
    analyze_legal_difficulty,
    generate_report,
)

CASE_ID = "苏06民终6271号"

print("=" * 60)
print("补充说明文档提交与报告引用 — 完整演示")
print("=" * 60)
print()

# ── Step 1: 提交多份不同类型的补充文档 ──
print("=== Step 1: 提交补充说明文档 ===\n")

docs_to_submit = [
    {
        "doc_type": "law_analysis",
        "doc_title": "混同用工与人格混同的法律适用分析",
        "doc_content": (
            "一、混同用工与人格混同的区分\n"
            "混同用工侧重事实层面，指关联企业间交叉使用劳动者，未签订书面劳动合同或签订但不实际履行；"
            "人格混同侧重法人人格独立性层面，指关联公司之间人员、业务、财务高度混同，导致无法区分。\n"
            "二、法律适用\n"
            "混同用工适用《劳动合同法》相关规定，由实际用工单位承担劳动法义务；"
            "人格混同适用《公司法》第20条公司人格否认制度，由关联公司承担连带责任。\n"
            "三、本案分析\n"
            "本案认定两被上诉人存在混同用工，但未对人格混同进行独立认定，"
            "可能导致法律适用不完整，影响连带责任的法律基础。"
        ),
        "authority_level": "authoritative",
    },
    {
        "doc_type": "academic_opinion",
        "doc_title": "加班工资计算基数的学术观点综述",
        "doc_content": (
            "关于加班工资计算基数，学界存在三种观点：\n"
            "1. 基本工资说：以劳动者正常工作时间提供劳动的工资为基数，不包括奖金、津贴等。\n"
            "2. 应发工资说：以劳动者应得的全部工资收入为基数，包括基本工资、奖金、津贴、补贴等。\n"
            "3. 约定优先说：劳动合同有约定的从约定，无约定的按应发工资确定。\n"
            "主流观点倾向于应发工资说，理由是加班工资是对劳动者超时劳动的补偿，"
            "应以劳动者正常工作时间的全部收入为计算基础。"
        ),
        "authority_level": "persuasive",
    },
    {
        "doc_type": "legal_maxim",
        "doc_title": "法谚'任何人不得从违法行为中获利'在本案中的适用说明",
        "doc_content": (
            "一、法谚来源\n"
            "该法谚源于罗马法'Nullus commodum capere potest de injuria sua propria'，"
            "已被中国司法实践广泛采纳。\n"
            "二、本案适用\n"
            "用人单位拒不提供同岗位薪酬数据，属于举证妨碍行为。"
            "若因此减轻用人单位的举证责任和支付义务，则用人单位从自身的违法行为中获利，"
            "违反该法谚的基本精神。\n"
            "三、约束\n"
            "该法谚不创设新的法律规范，仅在法律解释存在模糊时作为补充依据，"
            "不突破《劳动争议调解仲裁法》第6条等法律明文规定。"
        ),
        "authority_level": "persuasive",
    },
    {
        "doc_type": "innovation_argument",
        "doc_title": "关于举证妨碍规则适用力度的突破性创新论证",
        "doc_content": (
            "一、现有裁判惯例\n"
            "当前司法实践中，对举证妨碍规则的适用力度偏弱，多数法院仅作不利推定，"
            "较少直接推定劳动者主张成立。\n"
            "二、突破方向\n"
            "在用人单位明确掌握关键证据（如工资台账、考勤记录）且拒不提供的情况下，"
            "应更积极地适用举证妨碍规则，推定劳动者的主张成立，而非仅作不利推定。\n"
            "三、法律依据\n"
            "《劳动争议调解仲裁法》第6条、《劳动争议司法解释（一）》第43条，"
            "均规定了举证妨碍的不利后果。在法律框架内，通过扩大解释'不利后果'的范围，"
            "可以填补当前裁判规则中的漏洞。\n"
            "四、约束\n"
            "不得违反法律明文规定，需充分说理，确保裁判公正。"
        ),
        "authority_level": "persuasive",
    },
]

submitted_docs = []
for i, doc in enumerate(docs_to_submit, 1):
    result = json.loads(submit_supplementary_doc(
        case_id=CASE_ID,
        doc_type=doc["doc_type"],
        doc_title=doc["doc_title"],
        doc_content=doc["doc_content"],
        authority_level=doc["authority_level"],
    ))
    submitted_docs.append(result)
    print(f"  文档{i}: {result.get('doc_type_zh', '')}")
    print(f"    标题: {result.get('title', '')}")
    print(f"    权威级别: {result.get('authority_level_zh', '')}")
    print(f"    索引: {result.get('doc_index', '')}")
    print(f"    状态: {'✅ 已提交' if result.get('success') else '❌ 失败'}")
    print()

# ── Step 2: 查询法律法规数据库 ──
print("=== Step 2: 查询法律法规数据库 ===\n")
law_db = json.loads(query_law_database(
    law_names=["民法典", "劳动合同法", "劳动争议调解仲裁法", "公司法", "江苏省工资支付条例"],
    case_context="劳动争议 混同用工 人格混同 加班工资 举证妨碍 违法获利",
    check_conflicts=True,
))
print(f"  匹配法律: {len(law_db.get('matched_laws', []))} 部")
print(f"  法律冲突: {len(law_db.get('conflicts', []))} 项")
print(f"  溯及力问题: {len(law_db.get('retroactivity_issues', []))} 项")
print(f"  可适用原则: {len(law_db.get('applicable_principles', []))} 项")
for p in law_db.get("applicable_principles", []):
    print(f"    - {p.get('name', '')}（{p.get('origin', '')}）")
print()

# ── Step 3: 查询类案判例 ──
print("=== Step 3: 查询类案判例 ===\n")
case_prec = json.loads(query_case_precedent(
    case_type="劳动争议",
    key_facts=["加班工资", "混同用工", "经济补偿金", "举证妨碍"],
    court_level="中级人民法院",
))
print(f"  类案判例: {len(case_prec.get('precedents', []))} 件")
print(f"  冲突点: {len(case_prec.get('conflict_points', []))} 项")
print(f"  偏离点: {len(case_prec.get('deviation_points', []))} 项")
print(f"  创新空间: {len(case_prec.get('innovation_space', []))} 项")
for p in case_prec.get("precedents", []):
    print(f"    - {p.get('id', '')}：{p.get('title', '')}")
print()

# ── Step 4: 分析法律适用难点 ──
print("=== Step 4: 分析法律适用难点 ===\n")
legal_diff = json.loads(analyze_legal_difficulty(
    case_context="劳动争议二审：混同用工与人格混同的区分认定、加班工资计算基数的确定、举证妨碍规则的适用力度",
    legal_issues=[
        "混同用工与人格混同的区分标准",
        "加班工资计算基数的确定规则",
        "举证妨碍规则的适用力度",
    ],
    allow_innovation=True,
))
print(f"  难点问题: {len(legal_diff.get('difficulties', []))} 项")
print(f"  可适用原则: {len(legal_diff.get('applicable_principles', []))} 项")
print(f"  伦理考量: {len(legal_diff.get('ethics_considerations', []))} 项")
print(f"  前沿问题: {len(legal_diff.get('frontier_analysis', []))} 项")
print(f"  创新空间: {len(legal_diff.get('innovation_space', []))} 项")
print()

# ── Step 5: 生成包含补充文档引用的报告 ──
print("=== Step 5: 生成包含补充文档引用的报告 ===\n")

supplementary_docs_for_report = []
for sd in submitted_docs:
    supplementary_docs_for_report.append({
        "index": sd.get("doc_index", 0),
        "doc_type_zh": sd.get("doc_type_zh", ""),
        "title": sd.get("title", ""),
        "authority_level_zh": sd.get("authority_level_zh", ""),
    })

report_result = json.loads(generate_report(
    dimension_results=[
        {"dimension": "formal_specification", "score": 85, "deduction_items": [], "bonus_items": []},
        {"dimension": "clear_facts", "score": 88, "deduction_items": [], "bonus_items": []},
        {"dimension": "sufficient_evidence", "score": 90, "deduction_items": [], "bonus_items": [{"item": "适用证据妨碍规则"}]},
        {"dimension": "correct_law_application", "score": 82, "deduction_items": [{"item": "加班工资法律适用争议"}], "bonus_items": []},
        {"dimension": "thorough_reasoning", "score": 87, "deduction_items": [], "bonus_items": []},
        {"dimension": "substantive_resolution", "score": 92, "deduction_items": [], "bonus_items": [{"item": "一揽子解决多项争议"}]},
        {"dimension": "concise_language", "score": 80, "deduction_items": [{"item": "部分段落冗长"}], "bonus_items": []},
    ],
    weighted_total=88.31,
    grade="B+",
    anomaly_deduction=5,
    innovation_bonus=3,
    anomaly_details=[{"label": "逻辑异常", "severity": "high", "deduction": 5, "description": "人格混同认定逻辑断裂"}],
    innovation_details=[{"label": "证据妨碍规则适用", "bonus": 3, "description": "对拒不提供工资台账适用举证妨碍规则"}],
    document_meta={
        "案号": "（2025）苏06民终6271号",
        "法院": "江苏省南通市中级人民法院",
        "案件类型": "劳动争议",
        "审理程序": "二审",
    },
    law_database_result=law_db,
    case_precedent_result=case_prec,
    supplementary_docs_result=supplementary_docs_for_report,
    legal_difficulty_result=legal_diff,
))

report_md = report_result.get("report_markdown", "")
today_str = datetime.now().strftime("%Y%m%d")
output_path = rf"C:\Users\stere\WorkBuddy\2026-05-18-task-3\补充文档演示报告_苏06民终6271号_{today_str}.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(report_md)

print(f"报告已保存至: {output_path}")
print(f"报告长度: {len(report_md)} 字符")
print()

# ── Step 6: 验证补充文档在报告中的展示 ──
print("=== Step 6: 验证补充文档在报告中的展示 ===\n")

if "补充说明文档" in report_md:
    print("✅ 报告中包含'补充说明文档'章节")
else:
    print("❌ 报告中未找到'补充说明文档'章节")

for sd in submitted_docs:
    title = sd.get("title", "")
    if title and title in report_md:
        print(f"✅ 文档标题'{title}'已在报告中引用")
    else:
        print(f"❌ 文档标题'{title}'未在报告中找到")

doc_count = report_md.count("法律适用分析说明") + report_md.count("学术论文或观点") + \
            report_md.count("法谚或法律原则适用说明") + report_md.count("突破性创新论证")
print(f"\n报告中共引用了 {doc_count} 种不同类型的补充文档")

if "任何人不得从违法行为中获利" in report_md:
    print("✅ 法谚'任何人不得从违法行为中获利'已在报告中展示")
if "诚实信用原则" in report_md:
    print("✅ 诚实信用原则已在报告中展示")
if "突破性创新" in report_md or "创新空间" in report_md:
    print("✅ 突破性创新空间已在报告中展示")

print()
print("=" * 60)
print("演示完成！")
print("=" * 60)
