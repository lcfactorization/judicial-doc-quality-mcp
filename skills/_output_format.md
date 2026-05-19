# 输出格式规范

## 通用输出格式

所有维度的评分结果必须输出为严格的 JSON 对象，包含以下核心字段：

```json
{
    "quote": "从文书中摘录一处最能体现该维度质量（好或差）的原文段落，不超过200字",
    "reasoning": "一句话概括评分理由，包含主要扣分项或加分项",
    "score": 78,
    "stage_scope": "二审",
    "stage_unclear": false,
    "deduction_items": [
        {
            "item": "扣分项名称（对应编号）",
            "item_name": "扣分项简要名称",
            "deduction": 15,
            "quote": "原文引用",
            "original_text_location": "原文定位（页码/段落/行号）",
            "basis": "判定依据",
            "legal_basis": "法条依据（具体法条编号及版本）",
            "suggestion": "修复建议",
            "a_code": "A系列分类编号（A1-A8）",
            "f_code": "F编号（仅事实认定维度，F-01至F-26）",
            "beneficiary": "获益方（根据程序阶段使用对应术语）",
            "confidence": "置信度（0.0-1.0）",
            "severity": "严重度（疑似/可能/高度可能/确定）",
            "stage_scope": "审级归属（一审/二审/再审/仲裁/行政/未知）",
            "stage_unclear": false,
            "q1_alternative": "是否存在合理解释？如有，说明",
            "q2_subjective_intent": "是否存在主观恶意证据？如有，说明",
            "q3_contradictory_evidence": "是否存在反向证据？如有，说明",
            "conclusion": "对抗校验结论（成立/存疑/不成立）",
            "reverse_anomaly": "反向异常点（如存在，描述对应异常）",
            "net_anomaly": "净异常判定（成立/存疑/不成立）"
        }
    ],
    "bonus_items": [
        {
            "item": "加分项名称（对应编号）",
            "item_name": "加分项简要名称",
            "bonus": 5,
            "quote": "原文引用",
            "original_text_location": "原文定位",
            "reason": "加分理由",
            "legal_basis": "法条依据",
            "detail": "详细说明"
        }
    ]
}
```

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| quote | string | 是 | 原文摘录，无瑕疵时填"无" |
| reasoning | string | 是 | 评分理由，必须包含扣分/加分依据 |
| score | integer | 是 | 0-100之间的整数 |
| deduction_items | array | 是 | 扣分明细列表，无扣分时为空数组 |
| bonus_items | array | 是 | 加分明细列表，无加分时为空数组 |

### 扣分项新增字段说明

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| item_name | string | 是 | 扣分项简要名称，便于报告展示 |
| original_text_location | string | 是 | 原文定位（页码/段落/行号），必须可查对 |
| legal_basis | string | 是 | 法条依据，如涉及法律适用问题 |
| suggestion | string | 是 | 修复建议，提供具体可操作的改进方向 |
| a_code | string | 是 | A系列分类编号，映射到A1-A8 |
| f_code | string | 条件 | F编号，仅事实认定维度必填（F-01至F-26） |
| beneficiary | string | 是 | 获益方，根据程序阶段使用对应术语 |
| confidence | string | 是 | 置信度，0.0-1.0 |
| severity | string | 是 | 严重度：疑似/可能/高度可能/确定 |
| q1_alternative | string | 是 | 对抗校验Q1：是否存在合理解释 |
| q2_subjective_intent | string | 是 | 对抗校验Q2：是否存在主观恶意证据 |
| q3_contradictory_evidence | string | 是 | 对抗校验Q3：是否存在反向证据 |
| conclusion | string | 是 | 对抗校验结论：成立/存疑/不成立 |
| reverse_anomaly | string | 否 | 反向异常点描述 |
| net_anomaly | string | 是 | 净异常判定：成立/存疑/不成立 |
| stage_scope | string | 是 | 审级归属：一审/二审/再审/仲裁/行政/未知 |
| stage_unclear | boolean | 是 | 是否无法区分审级归属，默认false |

### 加分项新增字段说明

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| item_name | string | 是 | 加分项简要名称 |
| original_text_location | string | 是 | 原文定位 |
| legal_basis | string | 否 | 法条依据 |
| detail | string | 否 | 详细说明 |

## 格式约束

1. **score 必须为整数**：不接受小数、字符串或其他类型
2. **score 范围 [0, 100]**：超出范围的分数将被自动校准
3. **quote 必须有原文依据**：不得凭空编造或概括性描述
4. **deduction_items 和 bonus_items 不可同时为空**：至少有一项
5. **同一问题不重复扣分**：就高扣分原则
6. **加分后总分不超过100分**
7. **底线尊重原则**：只要存在一项对弱势方有利的正确认定，总分不低于40分
8. **A系列分类必填**：每个扣分项必须映射到A1-A8
9. **对抗校验必填**：每个扣分项必须完成Q1/Q2/Q3三问校验
10. **净异常判定必填**：扣除反向异常后，判定该异常是否仍然成立

## ⚠️ 说理充分性硬约束（零容忍）

> 检测他人文书的异常，自己的说理却稀里糊涂、找不到根据，这是绝对不允许的。
> 以下字段为**必填且禁止空值**，违反任何一条将导致该扣分项无效：

| 字段 | 硬约束要求 | 禁止示例 | 正确示例 |
|:---|:---|:---|:---|
| original_text_location | 必须定位到具体段落/页码/行号 | "—"、"全文"、"多处" | "第3页第2段'关于加班工资的认定'" |
| legal_basis | 必须引用具体法条编号+条文要点 | "劳动合同法"、"相关法律" | "《劳动合同法》第30条第1款：用人单位应当按照劳动合同约定和国家规定，向劳动者及时足额支付劳动报酬" |
| suggestion | 必须给出具体可操作的修复建议 | "加强说理"、"完善论证"、"注意规范" | "在证据采信部分补充说明为何采信考勤记录而排除证人证言，参照《民事诉讼证据规定》第85条" |
| q1_alternative | 必须分析是否存在合理解释+说明理由 | "存在"、"不存在" | "存在——用人单位可能因考勤系统故障导致记录不完整，但被上诉人未提供系统故障证据" |
| q2_subjective_intent | 必须分析是否有主观偏向证据 | "无"、"未见" | "未见——判决书对双方证据均逐一回应，未发现选择性忽略" |
| q3_contradictory_evidence | 必须说明是否存在反向证据及其内容 | "无" | "存在——被上诉人提交的工资条显示已支付加班费，但该工资条未经质证" |
| conclusion | 必须基于Q1/Q2/Q3给出明确结论+一句话理由 | "成立"、"存疑" | "存疑——举证责任分配虽有争议，但存在合理解释空间" |
| net_anomaly | 必须附理由 | "成立"、"不成立" | "存疑——扣除反向异常后，核心举证责任分配问题仍未充分说理" |

## 耦合分析输出格式

当多个维度存在关联异常时，输出耦合分析：

```json
{
    "coupled_dimensions": ["evidence", "fact_finding", "law_application"],
    "coupling_type": "证据-事实-法律链条断裂",
    "coupling_strength": "强/中/弱",
    "coupling_description": "描述多个维度异常如何相互关联",
    "overall_risk": "critical/high/medium/low",
    "beneficiary_analysis": "耦合异常整体使哪方获益"
}
```

## 五理说理评估输出格式

说理充分透彻维度（thorough_reasoning）的评分中，需额外输出五理分析：

```json
{
    "five_reasoning": {
        "事理": {"score": 80, "analysis": "事实叙述的完整性和逻辑性"},
        "法理": {"score": 75, "analysis": "法律适用的论证深度"},
        "学理": {"score": 70, "analysis": "学术理论的引用和运用"},
        "情理": {"score": 65, "analysis": "人情事理的考量"},
        "文理": {"score": 85, "analysis": "文书结构和语言表达"}
    }
}
```

## 四元结构分析输出格式

事实清楚维度（clear_facts）的评分中，需额外输出四元结构分析：

```json
{
    "four_element": {
        "界定民事主体": {"score": 85, "analysis": "当事人主体资格和诉讼地位的认定"},
        "判断法律行为": {"score": 80, "analysis": "法律行为性质和效力的认定"},
        "保障民事权利": {"score": 75, "analysis": "权利归属和范围的认定"},
        "划分民事责任": {"score": 70, "analysis": "责任构成和分担的认定"}
    }
}
```

## 负面清单（一票否决项）

以下情形一旦确认，该维度评分直接降为0分，并在报告中标注⚠️：

| 编号 | 否决情形 | 适用维度 |
|:---|:---|:---|
| V1 | 裁判主文与说理部分结论直接矛盾 | thorough_reasoning, logic |
| V2 | 对关键证据只字不提且无任何解释 | sufficient_evidence, fact_finding |
| V3 | 引用的法条与案件类型完全不相关 | correct_law_application |
| V4 | 判决结果超出当事人诉讼请求范围 | substantive_resolution |
| V5 | 剥夺当事人法定程序权利且无合法理由 | formal_specification |

## 锚定示例引用

当 Agent 调用 `render_dimension_prompt` 时，如果 `include_anchors=true`，输出中会包含该维度的锚定示例。Agent 应将锚定示例作为 LLM 推理的参照系，帮助 LLM 校准评分尺度。
