---
name: quality_assessment
title: Phase 1 — 七维质量评估
type: phase
order: 1
description: 对文书进行7个维度的质量评分，这是核心评估阶段
---

{{_system}}

{{_output_format}}

# Phase 1 — 七维质量评估

## 阶段目标

对裁判文书进行7个维度的逐一质量评估，每个维度独立评分（0-100分），最终加权汇总。这是整个评估体系的核心阶段。

## 评估维度

| 序号 | 维度名称 | 维度标识 | 权重 | 评估重点 |
|:---|:---|:---|:---|:---|
| 1 | 形式规范 | `formal_specification` | 3% | 首部完整性、尾部规范性、格式统一性 |
| 2 | 事实清楚 | `clear_facts` | 12% | 诉辩归纳、事实认定逻辑、证据链条 |
| 3 | 证据确实充分 | `sufficient_evidence` | 12% | 证据采信理由、质证认证、证明力判断 |
| 4 | 法律适用正确 | `correct_law_application` | 18% | 法条引用、法律解释、适用准确性 |
| 5 | 说理充分透彻 | `thorough_reasoning` | 22% | 五理说理、逻辑推导、争议焦点回应 |
| 6 | 实质解纷效果 | `substantive_resolution` | 25% | 服判息诉、矛盾化解、可执行性 |
| 7 | 语言精练流畅 | `concise_language` | 8% | 法言法语、表述规范、逻辑清晰 |

> [!NOTE]
> 权重设计遵循"重实质轻形式"原则：实质解纷效果(25%) > 说理充分透彻(22%) > 法律适用正确(18%) > 事实清楚(12%) = 证据确实充分(12%) > 语言精练流畅(8%) > 形式规范(3%)。

## 工作流程

### Step 1.1：逐一维度评估

对每个维度，Agent 必须依次执行以下三步：

1. **渲染Prompt**：调用 `render_dimension_prompt(dimension, sections, include_anchors=True)`
   - 获取该维度的评分标准Prompt
   - `include_anchors=True` 时包含锚定示例，帮助LLM校准评分尺度
   - Prompt中已嵌入该维度的扣分项和加分项清单

2. **发送给LLM**：Agent 将渲染后的Prompt发送给自己的LLM
   - 必须设置 `temperature=0`，确保评分稳定性和可重复性
   - LLM返回严格的JSON格式评分结果

3. **解析结果**：调用 `parse_score_result(dimension, llm_response)`
   - 自动校准超范围分数
   - 验证必填字段完整性
   - 提取扣分项和加分项

### Step 1.2：批量渲染优化（可选）

如果Token预算允许，可使用 `render_dimension_prompt_batch` 批量渲染多个维度的Prompt，减少调用次数：

```
render_dimension_prompt_batch(
    dimensions=["formal_specification", "clear_facts", "sufficient_evidence"],
    include_anchors=True,
    anchor_count=2
)
```

### Step 1.3：记录进度

每完成一个维度的评估，调用 `pipeline_progress(action="complete", dimension_name="xxx")` 记录进度，支持断点续传。

## Anti-Laziness 强制执行指令

> [!IMPORTANT]
> Agent 必须在当前对话轮次中，静默且完整地调用所有7个维度的评估，绝对不允许中途停顿、询问用户是否继续、或以"操作同理"等理由跳过任何维度。

具体要求：
1. 对每一个维度，必须依次调用 render_dimension_prompt → 发送给LLM → 调用 parse_score_result
2. 如果某个维度出现错误，记录错误并继续下一个维度，不得中断整个流程
3. 禁止输出"我已经检测了前N个维度，剩下的维度操作同理"之类的偷懒话术

## 评分等级

| 等级 | 分数范围 | 含义 |
|:---|:---|:---|
| A | 90-100 | 优秀 |
| B | 75-89 | 良好 |
| C | 60-74 | 合格 |
| D | 40-59 | 不合格 |
| F | 0-39 | 严重缺陷 |

## 输出

Phase 1 的输出为7个维度的评分结果列表，每个结果包含：

```json
{
    "dimension": "thorough_reasoning",
    "title": "说理充分透彻",
    "score": 78,
    "quote": "...",
    "reasoning": "...",
    "deduction_items": [...],
    "bonus_items": [...]
}
```

## 与后续Phase的衔接

Phase 1 的7个维度评分结果将供 Phase 2（一致性校验）和 Phase 4（报告生成）使用：
- 7个维度评分传入 `calculate_weighted_score` 计算加权总分
- 7个维度评分传入 `cross_check_consistency` 进行一致性校验
- 各维度的扣分项和加分项将纳入最终报告
