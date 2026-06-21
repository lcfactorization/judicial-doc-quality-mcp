# Phase 1 重构详细修改清单

> 生成时间：2026-06-04
> 目标：将 server.py 中的内联大函数迁移到对应模块，server.py 仅保留薄代理

---

## 一、server.py 修改（10处）

### 1.1 extract_document_sections（第222-315行，约94行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- def extract_document_sections(document_full_text: str) -> str:
-     """从裁判文书全文中提取各核心段落..."""
-     try:
-         sections = {}
-         plaintiff = re.search(...)
-         sections["plaintiff_claim"] = ...
-         # ... 90+ 行正则提取逻辑
-         return json.dumps({"success": True, **sections}, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ def extract_document_sections(document_full_text: str) -> str:
+     """从裁判文书全文中提取各核心段落，供后续评分使用。"""
+     try:
+         from .section_extractor import extract_document_sections as _extract
+         from .rule_engine import run_rule_engine
+         result = _extract(document_full_text, run_rule_engine=True, rule_engine_fn=run_rule_engine)
+         return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("extract_document_sections: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"提取异常：{e}", retryable=True)
```

### 1.2 render_dimension_prompt（第316-465行，约150行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def render_dimension_prompt(dimension, sections=None, include_anchors=True, anchor_count=3):
-     """渲染指定维度的评分 Prompt 模板..."""
-     try:
-         skill_name = f"dimensions/{dimension}"
-         meta, body = _loader.load(skill_name)
-         # ... 140+ 行模板渲染、锚定加载、output_schema构建逻辑
-         return json.dumps(result, ensure_ascii=False, indent=2)
-     except FileNotFoundError as e:
-         return _make_error(...)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def render_dimension_prompt(
+     dimension: str,
+     sections: dict | None = None,
+     include_anchors: bool = True,
+     anchor_count: int = 3,
+ ) -> str:
+     """渲染指定维度的评分 Prompt 模板，供 AI Agent 发送给自己的 LLM 进行评分。"""
+     try:
+         from .prompt_builder import render_dimension_prompt as _render
+         result = _render(
+             dimension=dimension,
+             sections=sections,
+             include_anchors=include_anchors,
+             anchor_count=anchor_count,
+             loader=_loader,
+             renderer=_renderer,
+         )
+         return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
+     except FileNotFoundError as e:
+         logger.error("render_dimension_prompt: Skill not found: %s", e)
+         return _make_error(ErrorCode.SKILL_NOT_FOUND, f"维度不存在：{e}", details={"dimension": dimension})
+     except Exception as e:
+         logger.error("render_dimension_prompt: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"渲染异常：{e}", retryable=True)
```

### 1.3 parse_score_result（第466-502行，约37行）

**操作**：已经是薄代理（调用 `_parser.parse_score_result`），**无需修改**

### 1.4 cross_check_consistency（第550-633行，约84行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def cross_check_consistency(scores: dict) -> str:
-     """检查各维度评分间的逻辑一致性..."""
-     try:
-         int_scores = {}
-         for k, v in scores.items():
-             # ... 80+ 行规则检查逻辑
-         return json.dumps(result, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def cross_check_consistency(scores: dict) -> str:
+     """检查各维度评分间的逻辑一致性，返回冲突列表和建议。"""
+     try:
+         from .rule_engine import cross_check_consistency as _cross_check
+         int_scores = {}
+         for k, v in scores.items():
+             try:
+                 int_scores[k] = int(v)
+             except (ValueError, TypeError):
+                 int_scores[k] = 0
+         result = _cross_check(int_scores)
+         return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("cross_check_consistency: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"一致性检查异常：{e}", retryable=True)
```

### 1.5 apply_anomaly_deduction（第634-738行，约105行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def apply_anomaly_deduction(anomaly_results: list[dict]) -> str:
-     """根据judicial-doc-anomaly-mcp的检测结果，计算异常扣分。"""
-     try:
-         # ... 100+ 行扣分计算逻辑
-         return json.dumps({...}, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def apply_anomaly_deduction(anomaly_results: list[dict]) -> str:
+     """根据judicial-doc-anomaly-mcp的检测结果，计算异常扣分。"""
+     try:
+         from .anomaly_bridge import apply_anomaly_deduction as _apply_deduction
+         result = _apply_deduction(anomaly_results)
+         return json.dumps({"success": True, **result}, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("apply_anomaly_deduction: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"异常扣分计算异常：{e}", retryable=True)
```

### 1.6 apply_innovation_bonus（第739-822行，约84行）

**操作**：**保留不动**（纯计算+配置引用，无独立模块归属，且仅84行）

### 1.7 query_anomaly_mcp（第1169-1349行，约180行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def query_anomaly_mcp(document_text, dimensions=None) -> str:
-     """自动检测并调用 judicial-doc-anomaly-mcp..."""
-     try:
-         # ... 170+ 行检测和Prompt生成逻辑
-         return json.dumps(result, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def query_anomaly_mcp(document_text: str, dimensions: list[str] | None = None) -> str:
+     """自动检测并调用 judicial-doc-anomaly-mcp 进行异常检测。"""
+     try:
+         from .anomaly_bridge import query_anomaly_mcp as _query
+         result = _query(
+             document_text=document_text,
+             dimensions=dimensions,
+             anomaly_mcp_available=ANOMALY_MCP_CONFIG["available"],
+             anomaly_mcp_auto_detected=ANOMALY_MCP_CONFIG.get("auto_detected", False),
+             server_name=ANOMALY_MCP_CONFIG["server_name"],
+         )
+         return json.dumps(result, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("query_anomaly_mcp: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"异常MCP查询异常：{e}", retryable=True)
```

### 1.8 submit_anomaly_response（第1350-1457行，约108行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def submit_anomaly_response(dimension, llm_response, dimension_index=0) -> str:
-     """提交 LLM 对某个异常检测维度的响应..."""
-     try:
-         # ... 100+ 行解析和暂存逻辑
-         return json.dumps(result, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def submit_anomaly_response(dimension: str, llm_response: str, dimension_index: int = 0) -> str:
+     """提交 LLM 对某个异常检测维度的响应，自动解析为结构化异常数据。"""
+     try:
+         from .anomaly_bridge import submit_anomaly_response as _submit
+         result = _submit(dimension=dimension, llm_response=llm_response, dimension_index=dimension_index)
+         return json.dumps(result, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("submit_anomaly_response: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"提交异常响应失败：{e}", retryable=True)
```

### 1.9 _anomaly_session 全局变量（第1350行附近，5行）

**操作**：**删除**（已在 anomaly_bridge.py 中管理）

### 1.10 finalize_anomaly_detection（第1457-1540行，约83行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def finalize_anomaly_detection() -> str:
-     """汇总所有已提交的异常检测结果..."""
-     try:
-         # ... 80+ 行汇总逻辑
-         return json.dumps(result, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def finalize_anomaly_detection() -> str:
+     """汇总所有已提交的异常检测结果，生成最终异常数据。"""
+     try:
+         from .anomaly_bridge import finalize_anomaly_detection as _finalize
+         result = _finalize()
+         return json.dumps(result, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("finalize_anomaly_detection: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"汇总异常检测失败：{e}", retryable=True)
```

### 1.11 detect_evasive_patterns（第1967-2222行，约256行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def detect_evasive_patterns(document_text: str) -> str:
-     """检测文书中的"规避责任写作模式"..."""
-     try:
-         # ... 250+ 行检测逻辑
-         return json.dumps({...}, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def detect_evasive_patterns(document_text: str) -> str:
+     """检测文书中的"规避责任写作模式"。"""
+     try:
+         from .rule_engine import detect_evasive_patterns as _detect
+         from .rule_engine import EVASIVE_PATTERNS
+         detections = _detect(document_text)
+         # 风险等级计算
+         high_count = sum(1 for d in detections if d["severity"] == "high")
+         medium_count = sum(1 for d in detections if d["severity"] == "medium")
+         low_count = sum(1 for d in detections if d["severity"] == "low")
+         if high_count >= 2:
+             risk_level = "critical"
+         elif high_count >= 1 or medium_count >= 3:
+             risk_level = "high"
+         elif medium_count >= 1 or low_count >= 3:
+             risk_level = "medium"
+         else:
+             risk_level = "low"
+         recommendation = {
+             "critical": "文书存在严重的规避责任写作嫌疑...",
+             "high": "文书存在较明显的规避模式...",
+             "medium": "文书存在部分规避模式...",
+             "low": "未检测到明显规避模式...",
+         }.get(risk_level, "建议进一步审查")
+         return json.dumps({
+             "success": True,
+             "detected_patterns": detections,
+             "risk_level": risk_level,
+             "recommendation": recommendation,
+             "summary": {
+                 "total_patterns": len(detections),
+                 "high_severity": high_count,
+                 "medium_severity": medium_count,
+                 "low_severity": low_count,
+             },
+         }, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("detect_evasive_patterns: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"规避模式检测异常：{e}", retryable=True)
```

### 1.12 check_anomaly_mcp_status（第1541-1590行，约50行）

**操作**：删除内联实现，替换为薄代理调用

```diff
- @mcp.tool()
- def check_anomaly_mcp_status() -> str:
-     """检查 judicial-doc-anomaly-mcp 的安装和运行状态。"""
-     try:
-         # ... 50行状态检查逻辑
-         return json.dumps(result, ensure_ascii=False, indent=2)
-     except Exception as e:
-         return _make_error(...)

+ @mcp.tool()
+ def check_anomaly_mcp_status() -> str:
+     """检查 judicial-doc-anomaly-mcp 的安装和运行状态。"""
+     try:
+         from .anomaly_bridge import check_anomaly_mcp_status as _check
+         result = _check(
+             auto_detected=ANOMALY_MCP_CONFIG.get("auto_detected", False),
+             server_name=ANOMALY_MCP_CONFIG["server_name"],
+             supported_dimensions=ANOMALY_MCP_CONFIG["supported_dimensions"],
+         )
+         return json.dumps(result, ensure_ascii=False, indent=2)
+     except Exception as e:
+         logger.error("check_anomaly_mcp_status: %s", e, exc_info=True)
+         return _make_error(ErrorCode.INTERNAL_ERROR, f"状态检查异常：{e}")
```

---

## 二、rule_engine.py 新增（1个函数）

### 2.1 cross_check_consistency(scores: dict) -> dict

从 server.py 第550-633行迁移，返回 dict（不再返回 JSON 字符串）。
依赖：从 config 导入 CROSS_CHECK_RULES, DIMENSION_TITLES, QUALITY_WEIGHTS

---

## 三、anomaly_bridge.py 新增（1个函数）

### 3.1 apply_anomaly_deduction(anomaly_results: list[dict]) -> dict

从 server.py 第634-738行迁移，返回 dict（不再返回 JSON 字符串）。
依赖：从 config 导入 ANOMALY_DEDUCTION, ANOMALY_TOTAL_MAX_DEDUCTION

---

## 四、prompt_builder.py 新增（1个函数）

### 4.1 render_dimension_prompt(dimension, sections, include_anchors, anchor_count, loader, renderer) -> dict

从 server.py 第316-465行迁移，返回 dict（不再返回 JSON 字符串）。
依赖：从 skill_runner 导入 SkillLoader, TemplateRenderer
依赖：从 prompt_builder 导入 build_system_prompt, ANTI_LAZINESS_INSTRUCTION
依赖：从 token_estimator 导入 estimate_tokens

---

## 五、test_phase1.py 修复（1处）

### 5.1 第699行断言修复

```diff
- assert "裁判文书质量评估报告" in report
+ assert "司法/行政文书程序与实体异常深度检测与质量评估报告" in report
```

---

## 六、风险评估

| 风险项 | 级别 | 说明 |
|:-------|:-----|:-----|
| 业务逻辑变更 | **无** | 所有迁移均为纯搬迁，不修改任何业务逻辑 |
| MCP工具注册 | **无影响** | @mcp.tool() 装饰器保留在 server.py |
| 循环依赖 | **无** | 依赖方向：server.py → 各子模块（单向） |
| 接口兼容性 | **无影响** | 所有MCP工具的输入/输出签名不变 |
| 测试兼容性 | **需修复** | test_phase1.py 第699行标题断言需更新 |

---

## 七、预期效果

- server.py：从约 2904 行降至约 1970 行（减少约 930 行）
- 新增代码：rule_engine.py +80行，anomaly_bridge.py +100行，prompt_builder.py +150行
- 净减少：约 600 行重复代码
