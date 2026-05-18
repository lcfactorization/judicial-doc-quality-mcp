---
name: anomaly_integration
title: Phase 2 — 异常检测联动与一致性校验
type: phase
order: 2
description: 联动judicial-doc-anomaly-mcp进行异常检测，计算异常扣分和创新加分，校验维度间一致性
---

{{_system}}

# Phase 2 — 异常检测联动与一致性校验

## 阶段目标

在Phase 1七维质量评估的基础上，进行三个关键步骤：
1. 联动异常检测MCP获取文书异常项
2. 计算异常扣分和创新加分
3. 校验各维度评分间的逻辑一致性

## 工作流程

### Step 2.1：异常检测联动

系统启动时自动检测 judicial-doc-anomaly-mcp 是否已安装：
- **已安装**：`query_anomaly_mcp` 自动调用 anomaly-mcp 的 `render_skill` 生成各维度检测 Prompt
- **未安装**：返回空白结果，质量评估流程不受影响

> [!TIP]
> judicial-doc-anomaly-mcp 的安装检测为全自动，无需手动配置。
> 安装方式：`pip install judicial-lint-mcp`
> 安装后系统将自动检测并启用联动。

#### 自动检测与调用流程

1. 调用 `check_anomaly_mcp_status()` 确认 anomaly-mcp 状态
2. 调用 `query_anomaly_mcp(document_text)` 获取检测 Prompt 列表
3. 对每个 Prompt，将 `system_prompt` + `user_prompt` 发送给 LLM
4. 将 LLM 响应通过 `submit_anomaly_response(dimension, llm_response, dimension_index)` 提交解析
5. 全部维度完成后调用 `finalize_anomaly_detection()` 获取汇总结果
6. 将汇总结果传入 `apply_anomaly_deduction` 计算扣分

> [!NOTE]
> 如果 judicial-doc-anomaly-mcp 不可用（`available=False`），异常检测结果为空，不影响质量评估流程。Agent可继续执行后续步骤，在 `apply_anomaly_deduction` 中 `anomaly_items` 参数传空即可。

> [!IMPORTANT]
> anomaly-mcp 是 Bridge Architecture，不直接调用 LLM。它生成 Prompt 供 Agent 发送给自己的 LLM，
> 再通过 `submit_anomaly_response` 提交 LLM 响应进行解析。这种设计确保 Agent 对 LLM 调用有完全控制权。

anomaly-mcp 提供16维异常检测能力：

| 维度标识 | 中文名称 | 说明 |
|:---|:---|:---|
| procedure | 程序异常 | 程序操作违规、程序缺失 |
| evidence | 证据异常 | 证据采信双标、证据不当排除 |
| fact_finding | 事实认定异常 | 事实认定偏差、关键情节遗漏 |
| focus_drift | 焦点漂移 | 争议焦点偏移或遗漏 |
| law_application | 法律适用异常 | 法条引用错误、适用不当 |
| discretion | 自由裁量权滥用 | 裁量明显不当 |
| rhetoric_trick | 修辞技巧异常 | 规避责任写作模式 |
| logic | 逻辑异常 | 逻辑闭环断裂、自相矛盾 |
| temporal | 时间一致性异常 | 时间倒置、时间缺口 |
| trial_process | 审理过程异常 | 审理程序违规 |
| external_interference | 外部干预 | 地方保护、行政干预迹象 |
| execution | 执行异常 | 判决可执行性问题 |
| negative_space | 负空间异常 | 缺失信息、应说未说 |
| semantic_drift | 语义漂移 | 关键概念含义变化 |
| case_deviation | 类案偏离 | 与同类案件裁判结果显著偏离 |
| coupling | 惯性耦合 | 多维度异常相互关联 |

### Step 2.2：异常扣分计算

调用 `apply_anomaly_deduction(anomaly_results)` 计算异常扣分：

| 异常类型 | 单项扣分 | 最大扣分 | 严重程度映射 |
|:---|:---|:---|:---|
| 程序异常 | 5 | 25 | low:3, medium:5, high:10 |
| 证据异常 | 6 | 30 | low:4, medium:6, high:12 |
| 事实认定异常 | 7 | 35 | low:5, medium:7, high:15 |
| 法律适用异常 | 8 | 40 | low:5, medium:8, high:18 |
| 说理异常 | 6 | 30 | low:4, medium:6, high:12 |
| 逻辑异常 | 7 | 35 | low:5, medium:7, high:15 |

**异常扣分上限**：50分（`ANOMALY_MAX_DEDUCTION`）

### Step 2.3：创新加分计算

调用 `apply_innovation_bonus(innovation_items)` 计算创新加分：

| 创新类型 | 加分范围 | 说明 |
|:---|:---|:---|
| 调解成功/促成和解 | 5-10 | 实质性化解矛盾，案结事了 |
| 法律漏洞填补 | 8-12 | 通过法律解释方法填补漏洞 |
| 创造性突破既有框架 | 10-15 | 打破陈规，推动司法进步 |
| 体现司法底层逻辑 | 5-8 | 公平正义、权利保障而非机械适用 |
| 复杂纠纷一揽子解决 | 5-10 | 避免程序空转 |

**创新加分上限**：30分（`INNOVATION_MAX_BONUS`）

### Step 2.4：加权总分计算

调用 `calculate_weighted_score(scores, anomaly_items, innovation_items)` 计算最终加权总分：

```
最终得分 = 加权质量分 - 异常扣分 + 创新加分
最低分 = max(0, 最终得分)
```

### Step 2.5：一致性校验

调用 `cross_check_consistency(scores)` 检查各维度评分间的逻辑一致性：

| 规则ID | 检测内容 | 矛盾说明 |
|:---|:---|:---|
| R1 | 说理高但法律适用低 | 说理充分却法律适用错误 |
| R2 | 证据高但事实低 | 证据充分却事实不清 |
| R3 | 说理高但事实或证据很低 | 无事实基础的说理是空中楼阁 |
| R4 | 语言满分但形式低 | 语言精练却格式不规范 |
| R5 | 事实与证据分差过大 | 两者评分依据可能不一致 |
| R6 | 实质解纷高但说理低 | 结果正确但论证不足 |
| R7 | 法律适用满分但说理极低 | 法条引用正确却完全未说理 |
| R8 | 所有实质维度均低但形式高 | 金玉其外败絮其中 |
| R9 | 实质解纷极低但法律适用不低 | 法律适用正确但裁判方式不当 |
| R10 | 创新性加分与低分矛盾 | 需核实创新是否真正成立 |

## 输出

Phase 2 的输出包含：

```json
{
    "weighted_score": { "weighted_total": 72.5, "grade": "C", ... },
    "anomaly_deduction": { "total_deduction": 15, "items": [...] },
    "innovation_bonus": { "total_bonus": 8, "items": [...] },
    "cross_check": { "conflict_detected": true, "conflicts": [...] }
}
```

## 与后续Phase的衔接

Phase 2 的输出供 Phase 4（报告生成）使用：
- 加权总分、异常扣分、创新加分纳入报告摘要
- 一致性校验冲突纳入报告"一致性审查"章节
