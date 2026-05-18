---
name: auxiliary_detection
title: Phase 3 — 辅助检测
type: phase
order: 3
description: 使用辅助检测工具进行时间线分析、证据追踪和规避模式检测
---

{{_system}}

# Phase 3 — 辅助检测

## 阶段目标

在质量评估和异常联动之外，使用三个辅助检测工具对文书进行深度分析，发现可能被维度评分遗漏的结构性和语义级异常。

## 工作流程

### Step 3.1：时间线一致性检测

调用 `extract_timeline(document_text)` 提取文书中的时间节点，检测以下异常：

| 异常类型 | 严重程度 | 说明 |
|:---|:---|:---|
| `temporal_inversion` | high | 时间倒置：文书中事件叙述顺序与时间线不一致 |
| `temporal_gap` | medium | 时间缺口：时间线跨度过大但中间年份无事件覆盖 |

**检测原理**：
1. 使用正则表达式提取文书中所有日期（YYYY年MM月DD日、YYYY-MM-DD等格式）
2. 按文书出现顺序排列，检测相邻事件是否存在时间倒置
3. 按时间排序后，检测年份缺口

**与anomaly-mcp联动**：anomaly-mcp的`temporal`维度可提供更深入的语义级时间一致性检测。

### Step 3.2：证据引用追踪

调用 `trace_evidence_references(document_text)` 追踪文书中的证据引用情况，检测以下异常：

| 异常类型 | 严重程度 | 说明 |
|:---|:---|:---|
| `unaddressed_evidence` | medium | 未被回应：当事人提交的证据在说理部分未被分析 |
| `missing_adoption_reason` | high | 缺乏采信理由：证据被采信或排除但未说明理由 |
| `incomplete_reasoning` | medium | 推理不完整：证据与事实认定之间的推理链断裂 |

**检测原理**：
1. 从"上述事实"等证据列举段落提取证据项
2. 在"本院认为"说理部分搜索每项证据的回应情况
3. 检测采信/排除是否附有理由

**与anomaly-mcp联动**：anomaly-mcp的`evidence`维度可提供更深入的证据双标检测。

### Step 3.3：规避责任写作模式检测

调用 `detect_evasive_patterns(document_text)` 检测以下规避模式：

| 模式ID | 严重程度 | 检测内容 | 正则模式示例 |
|:---|:---|:---|:---|
| `vague_subject` | medium | 主体模糊 | "相关单位/人员"等模糊表述 |
| `evasive_timing` | low | 时间模糊 | "此后/随后"等模糊时间 |
| `selective_citation` | high | 选择性引用 | "仅依据单方证据" |
| `template_language` | medium | 模板化说理 | "并无不当/于法有据"等套话 |
| `missing_response` | high | 回避回应 | "不予回应/无需审查" |

**风险等级判定**：

| 条件 | 风险等级 |
|:---|:---|
| high ≥ 2 | critical |
| high ≥ 1 或 medium ≥ 3 | high |
| medium ≥ 1 或 low ≥ 3 | medium |
| 其他 | low |

**与anomaly-mcp联动**：anomaly-mcp的`rhetoric_trick`维度可提供更深入的语义级规避模式检测。

## 输出

Phase 3 的输出包含三个检测工具的结果：

```json
{
    "timeline": {
        "events": [...],
        "anomalies": [...],
        "coverage": { "total_events": 8, "anomaly_count": 2, "completeness": "high" }
    },
    "evidence_trace": {
        "evidence_items": [...],
        "unaddressed": [...],
        "missing_reasoning": [...],
        "trace_summary": { ... }
    },
    "evasive_patterns": {
        "detected_patterns": [...],
        "risk_level": "medium",
        "recommendation": "..."
    }
}
```

## 与后续Phase的衔接

Phase 3 的辅助检测结果供 Phase 4（报告生成）使用：
- 时间线异常纳入报告"时间线分析"章节
- 证据追踪结果纳入报告"证据引用追踪"章节
- 规避模式检测结果纳入报告"规避模式检测"章节
- 各检测结果的综合风险等级纳入报告摘要
