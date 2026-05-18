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

## 文书元信息（如有）
## 综合评级
  > [!TIP] 等级划分说明
  > [!NOTE] 基础分/异常扣分/创新加分

## 各维度评分（表格）

## 异常扣分明细
  > [!CAUTION] 异常扣分汇总

## 创新性加分明细
  > [!TIP] 创新亮点汇总

## 辅助检测结果
  ### 时间线提取与异常检测
    > [!WARNING] 高严重度时间线异常
    > [!NOTE] 低严重度时间线异常
  ### 规避模式检测
    > [!CAUTION] 高风险规避模式
    > [!IMPORTANT] 规避模式建议
  ### 证据引用追踪
    > [!WARNING] 未回应/缺说理证据
    > [!TIP] 证据引用完整

## 异常检测MCP联动结果（anomaly-mcp 已安装时）
  > [!IMPORTANT] 检测来源说明
  ### 检测概览（表格）
  ### 各维度异常详情
    > [!CAUTION] 严重风险维度
    > [!WARNING] 高风险维度
    > [!NOTE] 中风险维度
    每维度：异常项表格（异常项/受益方/置信度/简述）
  > [!TIP] 异常检测与质量评估互补说明

## 异常检测MCP联动（anomaly-mcp 未安装时）
  > [!NOTE] 未安装提示 + 安装方式

## 一致性审查
  > [!WARNING] 检出矛盾
  > [!TIP] 逻辑一致

## 免责声明
  > [!IMPORTANT] 免责声明
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
  ├── check_anomaly_mcp_status → 检查anomaly-mcp状态（自动检测）
  ├── query_anomaly_mcp → 获取检测Prompt列表（自动调用render_skill）
  │   └── 如不可用：返回空白，跳过异常检测
  ├── for each prompt:
  │   ├── [Agent sends to LLM] → LLM异常检测
  │   └── submit_anomaly_response → 提交并解析响应
  ├── finalize_anomaly_detection → 汇总异常检测结果
  ├── apply_anomaly_deduction → 计算异常扣分
  ├── apply_innovation_bonus → 计算创新加分
  ├── calculate_weighted_score → 计算加权总分
  └── cross_check_consistency → 一致性校验

Phase 3 (辅助检测)
  ├── extract_timeline → 时间线分析
  ├── trace_evidence_references → 证据追踪
  └── detect_evasive_patterns → 规避模式检测

Phase 4 (报告生成)
  ├── generate_report → 生成合并报告（含异常MCP联动结果）
  └── pipeline_progress(complete_all) → 完成流水线
```

> [!IMPORTANT]
> anomaly-mcp 的检测和调用为全自动：
> - 已安装：自动生成 Prompt、自动解析响应、自动合并到报告
> - 未安装：静默跳过，不影响质量评估流程
> - 无需手动配置 `ANOMALY_MCP_AVAILABLE` 环境变量
