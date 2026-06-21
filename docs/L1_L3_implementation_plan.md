# L1 & L3 优化方案实施步骤与工时预估

> 版本：v1.0 · 日期：2026-06-04

---

## L1：requires_absent 上下文级检查

### 目标

将 `requires_absent` 的搜索范围从全文档（document 级）缩小到匹配点附近的上下文窗口（context 级），减少因远距离文本导致的误抑制。

### 当前问题

```python
# rule_engine.py 当前实现
for absent_pattern in requires_absent:
    if re.search(absent_pattern, document_text):  # 全文档搜索
        absent_ok = False
        break
```

问题：当文档其他位置存在 `requires_absent` 匹配时，即使与当前检测点无关，也会抑制该检测，导致漏报。

### 实施步骤

| 步骤 | 任务 | 涉及文件 | 预估工时 |
|:---:|:---|:---|:---:|
| L1-1 | **扩展 DetectionRule 数据类**：新增 `requires_absent_scope`（"document"/"context"）和 `requires_absent_window`（默认 200 字符）字段 | `rule_engine.py` | 0.5h |
| L1-2 | **修改 `detect_evasive_patterns()`**：当 `scope == "context"` 时，提取匹配点前后 `window` 字符范围作为搜索文本 | `rule_engine.py` | 1h |
| L1-3 | **修改 `run_rule_engine()`**：对 `RULE_ENGINE_PATTERNS` 中的 presence 规则同样支持 context 级检查 | `rule_engine.py` | 0.5h |
| L1-4 | **更新 EVASIVE_PATTERNS 规则定义**：为现有 5 条规则添加 `requires_absent_scope` 和 `requires_absent_window` 字段 | `rule_engine.py` | 0.5h |
| L1-5 | **编写单元测试**：覆盖 context 级 vs document 级行为差异、边界窗口、窗口不足等场景 | `tests/test_v020_modules.py` | 2h |
| L1-6 | **集成测试**：使用真实判决书文本验证 L1 优化后的检测结果变化 | `tests/` | 1h |
| L1-7 | **文档更新**：更新 rule_engine.py docstring 和 README | `rule_engine.py`, `README.md` | 0.5h |

**L1 总计：6h**

### 技术细节

```python
# L1-2 核心修改
for match in matches:
    matched_text = match.group(0)
    scope = pattern_def.get("requires_absent_scope", "document")
    window = pattern_def.get("requires_absent_window", 200)

    if scope == "context":
        ctx_start = max(0, match.start() - window)
        ctx_end = min(len(document_text), match.end() + window)
        search_text = document_text[ctx_start:ctx_end]
    else:
        search_text = document_text

    for absent_pattern in requires_absent:
        if re.search(absent_pattern, search_text):
            absent_ok = False
            break
```

---

## L3：扩展规避模式库

### 目标

新增 5 条规避模式规则，覆盖当前未检测到的常见司法文书规避手法，提升异常检测覆盖率。

### 当前覆盖

| 规则 ID | 检测内容 | 严重度 |
|:---|:---|:---:|
| vague_subject | 主体模糊 | medium |
| evasive_timing | 时间模糊 | low |
| selective_citation | 选择性引用 | high |
| template_language | 模板化说理 | medium |
| missing_response | 回避回应 | high |

### 新增规则

| 规则 ID | 检测内容 | 模式 | 严重度 | requires_absent_scope |
|:---|:---|:---|:---:|:---:|
| burden_shift | 举证责任转移 | 原告/被告.*应.*举证/证明 | high | context |
| selective_law | 选择性适用法律 | 仅适用.*条.*未提及.*条 | high | document |
| vague_ruling | 判决主文模糊 | 相关事宜.*另行处理/协商解决 | medium | context |
| circular_reasoning | 循环论证 | 因.*故.*因.*故（同义反复） | medium | context |
| implicit_conclusion | 隐含结论 | 综上所述.*应予支持（无前置论证） | medium | context |

### 实施步骤

| 步骤 | 任务 | 涉及文件 | 预估工时 |
|:---:|:---|:---|:---:|
| L3-1 | **设计 5 条新规则的正则模式**：基于真实判决书样本调优，确保误报率 < 10% | `rule_engine.py` | 2h |
| L3-2 | **添加新规则到 EVASIVE_PATTERNS**：包含 pattern/rule_type/severity/message/exceptions/requires_absent | `rule_engine.py` | 1h |
| L3-3 | **编写单规则测试**：每条规则至少 3 个正向用例 + 2 个反向用例 + 1 个边界用例 | `tests/test_v020_modules.py` | 3h |
| L3-4 | **集成测试**：使用 (2025)苏06民终6271号 判决书验证新规则触发情况 | `tests/` | 1h |
| L3-5 | **调优与迭代**：根据集成测试结果调整正则模式和阈值 | `rule_engine.py` | 2h |
| L3-6 | **文档更新**：更新规则说明和示例 | `rule_engine.py` | 0.5h |

**L3 总计：9.5h**

---

## 工时汇总

| 优化方案 | 步骤数 | 预估工时 | 优先级 |
|:---|:---:|:---:|:---:|
| L1 - requires_absent 上下文检查 | 7 | 6h | 高 |
| L3 - 扩展规避模式库 | 6 | 9.5h | 中 |
| **合计** | **13** | **15.5h** | - |

### 建议执行顺序

1. **L1 优先**：L1 是 L3 的前置依赖（L3 新规则依赖 context 级检查）
2. **L3 在 L1 完成后启动**：新规则的 `requires_absent_scope` 默认使用 "context"

---

## 待优化后续任务清单

| 编号 | 任务 | 优先级 | 预估工时 | 依赖 |
|:---:|:---|:---:|:---:|:---:|
| P1 | L1: requires_absent 上下文级检查 | 高 | 6h | 无 |
| P2 | L3: 扩展规避模式库（5条新规则） | 中 | 9.5h | P1 |
| P3 | L2: LLM 辅助确认机制（规则引擎初筛 → LLM 二次确认） | 中 | 16h | P1 |
| P4 | PDF 报告输出支持 | 低 | 8h | 无 |
| P5 | 增量评估能力（仅重新计算变更部分） | 低 | 12h | 无 |
| P6 | 规则热加载（运行时添加/修改规则无需重启） | 低 | 4h | 无 |
| P7 | 多文书批量评估与对比报告 | 低 | 10h | 无 |
| P8 | 评估结果持久化与历史趋势分析 | 低 | 8h | P7 |
| P9 | 规避模式库持续扩充（目标 20+ 条规则） | 中 | 持续 | P2 |
| P10 | 国际化支持（英文/日文文书评估） | 低 | 20h | 无 |

**总计待优化工时：约 93.5h（不含 P9 持续任务）**

---

*本文档由 judicial-doc-quality-mcp 项目维护团队生成 · 2026-06-04*
