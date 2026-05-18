---
name: precheck
title: Phase 0 — 预检与结构提取
type: phase
order: 0
description: 对文书进行结构提取和规则引擎初筛，为后续评估提供基础数据
---

{{_system}}

# Phase 0 — 预检与结构提取

## 阶段目标

在正式质量评估之前，对文书进行预处理和结构化提取，识别明显的结构性缺陷，为后续各维度评估提供段落级输入材料。

## 工作流程

### Step 0.1：文书段落提取

调用 `extract_document_sections` 工具，从文书全文中提取以下核心段落：

| 段落标识 | 内容 | 用途 |
|:---|:---|:---|
| `header_text` | 首部（法院名称、案号、当事人信息） | 形式规范评估输入 |
| `plaintiff_claim_text` | 原告诉称 | 事实认定、说理评估输入 |
| `defendant_defense_text` | 被告辩称 | 事实认定、说理评估输入 |
| `court_finding_text` | 经审理查明 | 事实认定评估输入 |
| `evidence_analysis_text` | 证据分析部分 | 证据评估输入 |
| `reasoning_text` | 本院认为 | 说理评估输入 |
| `judgment_main_text` | 判决主文 | 实质解纷评估输入 |
| `footer_text` | 尾部（上诉权告知、署名） | 形式规范评估输入 |

### Step 0.2：规则引擎初筛

`extract_document_sections` 内置规则引擎（`_run_rule_engine`），自动检测以下结构性异常：

| 规则ID | 检测内容 | 严重程度 |
|:---|:---|:---|
| `missing_court_name` | 首部缺少法院名称 | high |
| `missing_case_number` | 首部缺少案号或案号格式错误 | high |
| `missing_judgment_main` | 缺少判决主文 | high |
| `missing_reasoning` | 缺少"本院认为"说理部分 | high |
| `missing_law_basis` | 缺少法律依据引用 | medium |
| `missing_evidence_section` | 缺少证据分析部分 | medium |

规则引擎结果存入 `rule_engine_flags` 字段，供后续维度评估参考。

### Step 0.3：Token预算预估

调用 `estimate_token_budget` 工具，预估各维度Prompt的Token消耗，帮助Agent规划调用策略：

- 评估是否需要使用 `render_dimension_prompt_batch` 批量渲染
- 评估是否需要分批处理以避免Token溢出
- 确定最优的维度评估顺序

### Step 0.4：初始化流水线进度

调用 `pipeline_progress` 工具（action=start），初始化评估会话，记录：

- `session_id`：评估会话唯一标识
- `total_count`：待评估维度总数（7）
- `remaining_dimensions`：剩余维度列表

## 输出

Phase 0 的输出为结构化JSON，包含：

```json
{
    "sections": { ... },
    "rule_engine_flags": [ ... ],
    "token_budget": { ... },
    "pipeline_session_id": "xxx"
}
```

## 与后续Phase的衔接

Phase 0 的输出直接供 Phase 1 使用：
- `sections` 中的各段落作为 `render_dimension_prompt` 的变量输入
- `rule_engine_flags` 作为各维度评估的参考信息
- `token_budget` 指导 Phase 1 的调用策略
- `pipeline_session_id` 跟踪整个评估流程进度

## 异常处理

- 如果 `extract_document_sections` 的 `extraction_confidence < 0.5`，说明文书结构异常严重，建议Agent先确认文书完整性
- 如果规则引擎检测到 high 级别缺陷 ≥ 3 个，可在报告中标注"文书存在严重结构性缺陷"
