# 输出格式规范

## 通用输出格式

所有维度的评分结果必须输出为严格的 JSON 对象，包含以下核心字段：

```json
{
    "quote": "从文书中摘录一处最能体现该维度质量（好或差）的原文段落，不超过200字",
    "reasoning": "一句话概括评分理由，包含主要扣分项或加分项",
    "score": 78,
    "deduction_items": [
        {
            "item": "扣分项名称（对应编号）",
            "deduction": 15,
            "quote": "原文引用",
            "basis": "判定依据"
        }
    ],
    "bonus_items": [
        {
            "item": "加分项名称（对应编号）",
            "bonus": 5,
            "quote": "原文引用",
            "reason": "加分理由"
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

## 格式约束

1. **score 必须为整数**：不接受小数、字符串或其他类型
2. **score 范围 [0, 100]**：超出范围的分数将被自动校准
3. **quote 必须有原文依据**：不得凭空编造或概括性描述
4. **deduction_items 和 bonus_items 不可同时为空**：至少有一项
5. **同一问题不重复扣分**：就高扣分原则
6. **加分后总分不超过100分**

## 锚定示例引用

当 Agent 调用 `render_dimension_prompt` 时，如果 `include_anchors=true`，输出中会包含该维度的锚定示例。Agent 应将锚定示例作为 LLM 推理的参照系，帮助 LLM 校准评分尺度。
