---
name: report_generation
title: Phase 4 — 报告生成
type: phase
order: 4
description: 汇总所有评估和检测结果，生成结构化质量评估报告
---

{{_system}}

# Phase 4 — 报告生成

## 阶段目标

汇总Phase 0-3的所有评估和检测结果，调用 `generate_report` 工具生成结构化的裁判文书质量评估报告。

## 工作流程

### Step 4.1：汇总输入数据

收集以下数据作为 `generate_report` 的输入：

| 输入项 | 来源 | 说明 |
|:---|:---|:---|
| `dimension_results` | Phase 1 | 7个维度的评分结果列表 |
| `weighted_score_result` | Phase 2 | 加权总分计算结果 |
| `anomaly_deduction_result` | Phase 2 | 异常扣分明细 |
| `innovation_bonus_result` | Phase 2 | 创新加分明细 |
| `cross_check_result` | Phase 2 | 一致性校验结果 |
| `timeline_result` | Phase 3 | 时间线分析结果（可选） |
| `evidence_trace_result` | Phase 3 | 证据追踪结果（可选） |
| `evasive_patterns_result` | Phase 3 | 规避模式检测结果（可选） |

### Step 4.2：生成报告

调用 `generate_report(dimension_results, weighted_score_result, ...)` 生成报告。

报告结构如下：

```
# 裁判文书质量评估报告

## 评估摘要
- 文书基本信息
- 加权总分与等级
- 异常扣分与加分汇总
- 综合风险等级

## 维度评分明细
### 1. 形式规范 (3%)
### 2. 事实清楚 (12%)
### 3. 证据确实充分 (12%)
### 4. 法律适用正确 (18%)
### 5. 说理充分透彻 (22%)
### 6. 实质解纷效果 (25%)
### 7. 语言精练流畅 (8%)

## 异常扣分明细（联动 judicial-doc-anomaly-mcp）
## 创新加分明细
## 一致性审查
## 时间线分析
## 证据引用追踪
## 规避模式检测
## 关联工具
```

### Step 4.3：报告格式规范

报告遵循以下格式规范：

1. **表格优先**：评分明细、扣分项、加分项等使用表格呈现
2. **GitHub Alerts**：使用 `> [!NOTE]`、`> [!WARNING]`、`> [!IMPORTANT]` 等标注
3. **原文引用**：每个扣分项和加分项必须附原文引用
4. **说理依据**：每个异常项必须附说理依据（evidence + reasoning）

### Step 4.4：完成流水线

调用 `pipeline_progress(action="complete_all")` 标记评估流程全部完成。

## 报告尾部信息

报告末尾包含：

1. **版本信息**：`*报告由 judicial-doc-quality-mcp v0.1.0 生成*`
2. **关联工具**：说明与 [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp) 的联动关系

## 输出

Phase 4 的输出为完整的Markdown格式质量评估报告。

## 完整评估流程回顾

```
Phase 0 (预检)
  ├── extract_document_sections → 段落提取 + 规则引擎初筛
  ├── estimate_token_budget → Token预算预估
  └── pipeline_progress(start) → 初始化流水线

Phase 1 (七维评估)
  ├── for each dimension:
  │   ├── render_dimension_prompt → 渲染评分Prompt
  │   ├── [Agent sends to LLM] → LLM评分
  │   ├── parse_score_result → 解析评分结果
  │   └── pipeline_progress(complete) → 记录进度
  └── (可选) render_dimension_prompt_batch → 批量渲染

Phase 2 (异常联动)
  ├── query_anomaly_mcp → 获取异常检测结果
  ├── apply_anomaly_deduction → 计算异常扣分
  ├── apply_innovation_bonus → 计算创新加分
  ├── calculate_weighted_score → 计算加权总分
  └── cross_check_consistency → 一致性校验

Phase 3 (辅助检测)
  ├── extract_timeline → 时间线分析
  ├── trace_evidence_references → 证据追踪
  └── detect_evasive_patterns → 规避模式检测

Phase 4 (报告生成)
  ├── generate_report → 生成报告
  └── pipeline_progress(complete_all) → 完成流水线
```
