from judicial_quality_mcp.server import generate_report
import json

r = json.loads(generate_report(
    dimension_results=[
        {'dimension':'clear_facts','score':82,'deduction_items':[{'item':'x','deduction':8,'reason':'','suggestion':''}],'bonus_items':[{'item':'x','bonus':5,'reason':''}]},
        {'dimension':'legal_basis','score':88,'deduction_items':[{'item':'x','deduction':5,'reason':'real','suggestion':'real'}],'bonus_items':[{'item':'x','bonus':3,'reason':'real'}]},
    ],
    weighted_total=85.5, grade='B+', anomaly_deduction=8, innovation_bonus=3,
    anomaly_details=[{'label':'x','severity':'high','deduction':5,'description':'x','item_name':'F-07','beneficiary':'用人单位','original_text':'...','legal_analysis':'...','conclusion':'存疑','net_anomaly':'成立'}],
    innovation_details=[{'label':'x','bonus':3,'description':'test'}],
    trial_stage='二审',
    five_reasoning={'overall_summary':'test','dimensions':{}},
    four_element={'structure_summary':'test','elements':{}},
    beneficiary_distribution={'用人单位':2},
    coupling_analysis=[{'desc':'test','beneficiary':'用人单位'}],
    cross_check={'conflict_detected':True,'conflicts':[{'rule_name':'x','message':'test'}]},
    supplementary_docs_result=[{'title':'x','content':'test'}],
))

md = r['report_markdown']

checks = [
    '报告概览',
    '一、核心异常总览',
    '二、异常项深度剖析',
    '三、十六维度深度异常剖析',
    '四、七维质量评分详情',
    '五、创新亮点与加分项',
    '六、辅助检测结果',
    '七、一致性审查',
    '八、扩展检测功能',
    '总结与建议',
]

all_ok = True
for s in checks:
    found = f'## {s}' in md
    if not found:
        all_ok = False
    print(f"  {'✅' if found else '❌'}  {s}")

print()

cq = {
    '空白扣分→警告': '未提供具体扣分原因' in md,
    '空白加分→警告': '未提供具体加分原因' in md,
    '空白改进→警告': '未提供具体改进建议' in md,
    '实质扣分原因保留': 'real' in md,
    '实质改进建议保留': 'real' in md,
    '实质加分原因保留': 'real' in md,
    '获益方标注': '用人单位' in md,
    '审级标注': '二审' in md,
    '责任界定': '责任界定' in md,
}

for k, v in cq.items():
    print(f"  {'✅' if v else '❌'}  cq: {k}")

print()
if all_ok:
    print("ALL SECTIONS PRESENT")
else:
    print("SOME SECTIONS MISSING")

# Show the section order
import re
titles = re.findall(r'^## (.+)$', md, re.MULTILINE)
print("\nSection order:")
for t in titles:
    print(f"  ## {t}")