# Graph Report - judicial-doc-quality-mcp  (2026-05-19)

## Corpus Check
- 20 files · ~33,859 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 197 nodes · 581 edges · 14 communities detected
- Extraction: 41% EXTRACTED · 59% INFERRED · 0% AMBIGUOUS · INFERRED: 343 edges (avg confidence: 0.55)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]

## God Nodes (most connected - your core abstractions)
1. `SkillLoader` - 67 edges
2. `ResponseParser` - 66 edges
3. `TemplateRenderer` - 61 edges
4. `ErrorCode` - 57 edges
5. `StructuredError` - 57 edges
6. `_make_error()` - 27 edges
7. `process_document()` - 18 edges
8. `main()` - 16 edges
9. `judicial-doc-quality-mcp v0.1.0 — Bridge Architecture for Judicial Document Qual` - 15 edges
10. `test_full_pipeline_dryrun()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `批量检测5份模拟判决书，生成独立报告和综合比对报告。  工作流程： 1. 逐份读取判决书 2. 运行完整检测流程（时间线、规避模式、证据追踪、法律法规、类案判例` --uses--> `ResponseParser`  [INFERRED]
  batch_assess.py → src\judicial_quality_mcp\response_parser.py
- `test_extract_sections_with_rule_engine()` --calls--> `extract_document_sections()`  [INFERRED]
  test_new_tools.py → src\judicial_quality_mcp\server.py
- `test_complex_anomaly_doc_sections()` --calls--> `extract_document_sections()`  [INFERRED]
  test_new_tools.py → src\judicial_quality_mcp\server.py
- `process_document()` --calls--> `extract_timeline()`  [INFERRED]
  batch_assess.py → src\judicial_quality_mcp\server.py
- `process_document()` --calls--> `detect_evasive_patterns()`  [INFERRED]
  batch_assess.py → src\judicial_quality_mcp\server.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.1
Nodes (34): apply_anomaly_deduction(), apply_innovation_bonus(), calculate_weighted_score(), cross_check_consistency(), estimate_token_budget(), _estimate_tokens(), extract_document_sections(), generate_report() (+26 more)

### Community 1 - "Community 1"
Cohesion: 0.18
Nodes (29): ErrorCode, StructuredError, 生成结构化 Markdown 评分报告。纯规则函数，零 Token 消耗。      Agent 收集所有评分结果后，调用此工具生成最终报告。     支, 汇总所有已提交的异常检测结果，生成最终异常数据。      在 Agent 完成所有维度的 submit_anomaly_response 后调用此工具，, 从裁判文书全文中提取各核心段落，供后续评分使用。      基于正则表达式提取：原告诉称、被告辩称、本院查明、证据分析、     本院认为、法律依据、判决, 自动检测并调用 judicial-doc-anomaly-mcp 进行异常检测。      启动时自动检测 anomaly-mcp 是否已安装且可导入：, 从裁判文书中提取时间线事件，检测影响裁判质量的实质时序异常。      检测范围聚焦于可能影响裁判公正性和文书质量的时序问题：     1. 程序时序倒置, 提交 LLM 对某个异常检测维度的响应，自动解析为结构化异常数据。      当 query_anomaly_mcp 返回 prompts 后，Agent (+21 more)

### Community 2 - "Community 2"
Cohesion: 0.13
Nodes (19): BaseModel, Enum, AppConfig, _detect_anomaly_mcp(), Configuration management for judicial-doc-quality-mcp v0.1.0, Auto-detect whether judicial-doc-anomaly-mcp is installed and importable., judicial-doc-quality-mcp v0.1.0 — Bridge Architecture for Judicial Document Qual, BonusItem (+11 more)

### Community 3 - "Community 3"
Cohesion: 0.12
Nodes (21): extract_version_label(), generate_comparison_report(), generate_mock_anomalies(), main(), process_document(), 批量检测5份模拟判决书，生成独立报告和综合比对报告。  工作流程： 1. 逐份读取判决书 2. 运行完整检测流程（时间线、规避模式、证据追踪、法律法规、类案判例, score_document_quality(), analyze_legal_difficulty() (+13 more)

### Community 4 - "Community 4"
Cohesion: 0.12
Nodes (18): Quick verification test for new tools added based on LLM review suggestions., test_complex_anomaly_doc_evasive(), test_complex_anomaly_doc_evidence(), test_complex_anomaly_doc_sections(), test_complex_anomaly_doc_timeline(), test_detect_evasive_patterns(), test_extract_sections_with_rule_engine(), test_extract_timeline() (+10 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (9): test_query_anomaly_mcp(), test_render_dimension_prompt_batch(), from_env(), query_anomaly_mcp(), 自动检测并调用 judicial-doc-anomaly-mcp 进行异常检测。      启动时自动检测 anomaly-mcp 是否已安装且可导入：, 批量渲染多个维度的评分 Prompt，减少 Agent 调用次数。      借鉴 Gemini 3.1 Pro 建议的"动态批处理"：     当文书较, render_dimension_prompt_batch(), SkillMeta (+1 more)

### Community 6 - "Community 6"
Cohesion: 0.18
Nodes (9): 自动检测并调用 judicial-doc-anomaly-mcp 进行异常检测。      启动时自动检测 anomaly-mcp 是否已安装且可导入：, 提交 LLM 对某个异常检测维度的响应，自动解析为结构化异常数据。      当 query_anomaly_mcp 返回 prompts 后，Agent, 检查 judicial-doc-anomaly-mcp 的安装和运行状态。      返回 JSON 字符串，包含：     - installed: 是, 追踪文书中的证据引用情况，检测证据采信缺失。      借鉴 ChatGPT 5.5 建议的"证据引用追踪"：     自动追踪证据回应情况、采信理由、推, 计算加权总分并确定等级。纯规则函数，零 Token 消耗。      Agent 收集所有维度的评分后，调用此工具计算加权总分。     支持异常扣分（与, 检查各维度评分间的逻辑一致性，返回冲突列表和建议。      纯规则引擎，零 Token 消耗。Agent 在收集所有维度评分后应调用此工具。, Load and parse Skill .md files from the skills/ directory., SkillLoader (+1 more)

### Community 7 - "Community 7"
Cohesion: 0.29
Nodes (5): Parse LLM/Agent responses into structured score results., ResponseParser, 检查 judicial-doc-anomaly-mcp 的安装和运行状态。      返回 JSON 字符串，包含：     - installed: 是, 查询类案判例数据库，检测类案冲突和偏离。      基于案件类型和关键事实，检索类案判例，分析裁判倾向和偏离点。     支持指导性案例、公报案例、参考案, 检测文书中的"规避责任写作模式"。      借鉴 ChatGPT 5.5 建议的"对抗式检测"：     检测刻意模糊主体、回避关键时间、选择性采信、模

### Community 8 - "Community 8"
Cohesion: 1.0
Nodes (1): 评估脚本：对（2025）苏06民终6271号判决书进行七维质量评估

### Community 9 - "Community 9"
Cohesion: 1.0
Nodes (1): 演示补充说明文档提交与报告引用流程。  本脚本演示： 1. 提交多份不同类型的补充文档 2. 在报告中引用并展示这些文档 3. 验证扩展检测功能的完整协作流程

### Community 10 - "Community 10"
Cohesion: 1.0
Nodes (2): 针对特定案例提交补充说明文件，可在报告中引用作为说明基础。      支持的文档类型：     - law_analysis: 法律适用分析说明, submit_supplementary_doc()

### Community 11 - "Community 11"
Cohesion: 1.0
Nodes (2): Rule Engine 初筛：基于正则模式检测文书中的结构性异常。          借鉴 ChatGPT 5.5 建议的 Rule Engine + LL, _run_rule_engine()

### Community 12 - "Community 12"
Cohesion: 1.0
Nodes (2): query_case_precedent(), 查询类案判例数据库，检测类案冲突和偏离。      基于案件类型和关键事实，检索类案判例，分析裁判倾向和偏离点。     支持指导性案例、公报案例、参考案

### Community 13 - "Community 13"
Cohesion: 1.0
Nodes (2): get_dimension_standards(), 获取指定维度的扣分项清单和加分项清单（不含文书段落，仅评分标准）。      可用于 Agent 快速了解某维度的评分标准，无需渲染完整 Prompt。

## Knowledge Gaps
- **12 isolated node(s):** `评估脚本：对（2025）苏06民终6271号判决书进行七维质量评估`, `演示补充说明文档提交与报告引用流程。  本脚本演示： 1. 提交多份不同类型的补充文档 2. 在报告中引用并展示这些文档 3. 验证扩展检测功能的完整协作流程`, `Quick verification test for new tools added based on LLM review suggestions.`, `Configuration management for judicial-doc-quality-mcp v0.1.0`, `Auto-detect whether judicial-doc-anomaly-mcp is installed and importable.` (+7 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 8`** (2 nodes): `assess_doc.py`, `评估脚本：对（2025）苏06民终6271号判决书进行七维质量评估`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 9`** (2 nodes): `demo_supplementary_doc.py`, `演示补充说明文档提交与报告引用流程。  本脚本演示： 1. 提交多份不同类型的补充文档 2. 在报告中引用并展示这些文档 3. 验证扩展检测功能的完整协作流程`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 10`** (2 nodes): `针对特定案例提交补充说明文件，可在报告中引用作为说明基础。      支持的文档类型：     - law_analysis: 法律适用分析说明`, `submit_supplementary_doc()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 11`** (2 nodes): `Rule Engine 初筛：基于正则模式检测文书中的结构性异常。          借鉴 ChatGPT 5.5 建议的 Rule Engine + LL`, `_run_rule_engine()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 12`** (2 nodes): `query_case_precedent()`, `查询类案判例数据库，检测类案冲突和偏离。      基于案件类型和关键事实，检索类案判例，分析裁判倾向和偏离点。     支持指导性案例、公报案例、参考案`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 13`** (2 nodes): `get_dimension_standards()`, `获取指定维度的扣分项清单和加分项清单（不含文书段落，仅评分标准）。      可用于 Agent 快速了解某维度的评分标准，无需渲染完整 Prompt。`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ResponseParser` connect `Community 7` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 10`, `Community 11`, `Community 12`, `Community 13`?**
  _High betweenness centrality (0.174) - this node is a cross-community bridge._
- **Why does `SkillLoader` connect `Community 6` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 10`, `Community 11`, `Community 12`, `Community 13`?**
  _High betweenness centrality (0.157) - this node is a cross-community bridge._
- **Why does `TemplateRenderer` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 10`, `Community 11`, `Community 12`, `Community 13`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 58 inferred relationships involving `SkillLoader` (e.g. with `MCP Server v0.1.0 — Bridge Architecture for Judicial Document Quality Assessment` and `Rule Engine 初筛：基于正则模式检测文书中的结构性异常。          借鉴 ChatGPT 5.5 建议的 Rule Engine + LL`) actually correct?**
  _`SkillLoader` has 58 INFERRED edges - model-reasoned connections that need verification._
- **Are the 58 inferred relationships involving `ResponseParser` (e.g. with `批量检测5份模拟判决书，生成独立报告和综合比对报告。  工作流程： 1. 逐份读取判决书 2. 运行完整检测流程（时间线、规避模式、证据追踪、法律法规、类案判例` and `MCP Server v0.1.0 — Bridge Architecture for Judicial Document Quality Assessment`) actually correct?**
  _`ResponseParser` has 58 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `TemplateRenderer` (e.g. with `MCP Server v0.1.0 — Bridge Architecture for Judicial Document Quality Assessment` and `Rule Engine 初筛：基于正则模式检测文书中的结构性异常。          借鉴 ChatGPT 5.5 建议的 Rule Engine + LL`) actually correct?**
  _`TemplateRenderer` has 56 INFERRED edges - model-reasoned connections that need verification._
- **Are the 54 inferred relationships involving `ErrorCode` (e.g. with `MCP Server v0.1.0 — Bridge Architecture for Judicial Document Quality Assessment` and `Rule Engine 初筛：基于正则模式检测文书中的结构性异常。          借鉴 ChatGPT 5.5 建议的 Rule Engine + LL`) actually correct?**
  _`ErrorCode` has 54 INFERRED edges - model-reasoned connections that need verification._