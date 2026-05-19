from judicial_quality_mcp.server import generate_report
import json

dimension_results = [
    {"dimension": "formal_specification", "score": 85, "deduction_items": [], "bonus_items": []},
    {"dimension": "clear_facts", "score": 88, "deduction_items": [], "bonus_items": []},
    {"dimension": "sufficient_evidence", "score": 90, "deduction_items": [], "bonus_items": []},
    {"dimension": "correct_law_application", "score": 82, "deduction_items": [{"item": "法律适用争议"}], "bonus_items": []},
    {"dimension": "thorough_reasoning", "score": 87, "deduction_items": [], "bonus_items": []},
    {"dimension": "substantive_resolution", "score": 92, "deduction_items": [], "bonus_items": [{"item": "证据妨碍规则适用"}]},
    {"dimension": "concise_language", "score": 80, "deduction_items": [{"item": "语言冗长"}], "bonus_items": []},
]

anomaly_mcp_results = [
    {
        "dimension": "procedure",
        "anomaly_count": 1,
        "risk_level": "low",
        "summary": "程序基本规范，无重大异常",
        "anomalies": [
            {"item_name": "送达程序", "beneficiary": "被告", "confidence": "0.6", "description": "送达回证缺失", "f_code": "P-03", "a_code": "A-01"}
        ]
    },
    {
        "dimension": "evidence",
        "anomaly_count": 2,
        "risk_level": "medium",
        "summary": "证据采信存在轻微双标倾向",
        "anomalies": [
            {"item_name": "证据采信双标", "beneficiary": "用人单位", "confidence": "0.75", "description": "对被告证据采信标准高于原告", "f_code": "E-05", "a_code": "A-03"},
            {"item_name": "举证责任分配", "beneficiary": "用人单位", "confidence": "0.65", "description": "举证责任倒置适用不当", "f_code": "E-08", "a_code": "A-05"}
        ]
    },
    {
        "dimension": "fact_finding",
        "anomaly_count": 0,
        "risk_level": "low",
        "summary": "事实认定清晰，无明显异常",
        "anomalies": []
    },
    {
        "dimension": "logic",
        "anomaly_count": 1,
        "risk_level": "high",
        "summary": "存在逻辑闭环断裂风险",
        "anomalies": [
            {"item_name": "逻辑闭环断裂", "beneficiary": "用人单位", "confidence": "0.8", "description": "认定劳动关系存在但未回应人格混同问题", "f_code": "L-02", "a_code": "A-07"}
        ]
    }
]

result = generate_report(
    dimension_results=dimension_results,
    weighted_total=88.31,
    grade="B+",
    anomaly_deduction=5,
    innovation_bonus=3,
    anomaly_details=[{"label": "逻辑异常", "severity": "high", "deduction": 5, "description": "逻辑闭环断裂"}],
    innovation_details=[{"label": "证据妨碍规则", "bonus": 3, "description": "适用证据妨碍规则"}],
    anomaly_mcp_results=anomaly_mcp_results,
    document_meta={"案号": "[匿名化案号]", "法院": "[匿名化法院]"},
)

data = json.loads(result)
report = data.get("report_markdown", "")
print(report[:3000])
print("\n\n... [TRUNCATED] ...")
print(report[-1000:])
