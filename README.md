# judicial-doc-quality-mcp v0.1.0

> 司法裁判文书质量评估 MCP 服务器 — 桥接架构，零 LLM 调用

[English](./README_EN.md) | 中文

## 概述

`judicial-doc-quality-mcp` 是一个基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 的裁判文书质量评估服务器，采用**桥接架构（Bridge Architecture）**设计——服务器本身不调用任何 LLM，而是提供结构化的评分 Prompt、规则引擎、异常检测联动和报告生成工具，由 Agent（如 Claude、GPT 等）负责实际的 LLM 推理调用。

本项目的核心价值：将裁判文书质量评估的专业知识（七维评分体系、扣分/加分规则、交叉一致性检查等）封装为 MCP 工具，使任何支持 MCP 的 AI Agent 都能对裁判文书进行系统化、标准化的质量评估。

## 特点

- **桥接架构**：服务器零 LLM 调用，所有 AI 推理由 Agent 完成，Token 消耗完全可控
- **七维评分体系**：形式规范(3%)、事实清楚(12%)、证据确实充分(12%)、法律适用正确(18%)、说理充分透彻(22%)、实质解纷效果(25%)、语言精练流畅(8%)
- **规则引擎 + LLM 混合架构**：结构化异常由正则规则引擎初筛，语义异常由 Agent 深度分析
- **异常检测联动**：可选集成 [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp)，实现16维度异常检测与质量评估的联动扣分
- **规避模式检测**：自动识别文书中的模糊主体、时间模糊、回避回应等规避责任写作模式
- **时间线提取与异常检测**：从文书中提取时间线事件，检测时间倒置等异常
- **证据引用追踪**：追踪文书中的证据引用情况，检测证据采信缺失
- **法律法规数据库**：内置国家法律、司法解释、地方法规，支持法律适用优先级排序（特别法优于一般法、新法优于旧法、上位法优于下位法）、冲突检测和溯及力分析
- **类案判例数据库**：基于案件类型和关键事实检索类案判例，分析裁判倾向、偏离点和冲突点，支持指导性案例、公报案例等多层级检索
- **补充说明文档提交**：支持针对特定案例提交法律适用分析、学术观点、类案对比、法谚说明、伦理道德、前沿问题、创新论证等7种类型的补充文档，可在报告中引用
- **法律适用难点分析**：识别法律模糊地带和前沿问题，引用法谚和法律原则（如"任何人不得从违法行为中获利"），分析社会伦理道德和公序良俗考量，在不突破法律明文规定的前提下提供突破性创新空间
- **民商事专项标准**：内置民商事裁判文书专项法律依据、审理经过必须交代事项、法条引用格式规范等
- **交叉一致性检查**：自动检测各维度评分间的逻辑冲突（如事实清楚高分但证据充分低分）
- **Token 预算估算**：在渲染 Prompt 前预估 Token 消耗，避免上下文溢出
- **批处理渲染**：支持多维度 Prompt 批量渲染，减少 Agent 调用次数

## 安装

### 前置条件

- Python >= 3.11
- 支持 MCP 的 AI 客户端（如 Claude Desktop、Trae IDE 等）

### 从源码安装

```bash
# 克隆仓库
git clone https://github.com/CSlawyer1985/judicial-doc-quality-mcp.git
cd judicial-doc-quality-mcp

# 安装依赖（推荐使用虚拟环境）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .

# 可选：安装异常检测联动依赖
pip install -e ".[anomaly]"

# 可选：安装开发依赖
pip install -e ".[dev]"
```

### 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，按需修改配置
# 主要配置项：
#   ANOMALY_MCP_AVAILABLE=false   # 是否启用异常检测联动
#   RULE_ENGINE_ENABLED=true      # 是否启用规则引擎
#   EVASIVE_DETECTION_ENABLED=true # 是否启用规避模式检测
```

### MCP 客户端配置

在 MCP 客户端（如 Claude Desktop）的配置文件中添加：

```json
{
  "mcpServers": {
    "judicial-quality": {
      "command": "python",
      "args": ["-m", "judicial_quality_mcp.server"],
      "cwd": "/path/to/judicial-doc-quality-mcp"
    }
  }
}
```

如需联动异常检测 MCP，同时配置：

```json
{
  "mcpServers": {
    "judicial-quality": {
      "command": "python",
      "args": ["-m", "judicial_quality_mcp.server"],
      "cwd": "/path/to/judicial-doc-quality-mcp"
    },
    "judicial-anomaly": {
      "command": "python",
      "args": ["-m", "judicial_doc_anomaly.server"],
      "cwd": "/path/to/judicial-doc-anomaly-mcp"
    }
  }
}
```

## 使用

### 工具列表（21个 MCP 工具）

| 工具名称 | 功能 | Token 消耗 |
|:---|:---|:---|
| `list_dimensions` | 列出所有评分维度及元数据 | 零 |
| `extract_document_sections` | 从文书全文提取核心段落 | 零 |
| `render_dimension_prompt` | 渲染单个维度的评分 Prompt | 零（输出供 Agent 使用） |
| `render_dimension_prompt_batch` | 批量渲染多个维度的评分 Prompt | 零 |
| `parse_score_result` | 解析 Agent 返回的评分结果 | 零 |
| `calculate_weighted_score` | 计算加权总分 | 零 |
| `cross_check_consistency` | 交叉一致性检查 | 零 |
| `apply_anomaly_deduction` | 计算异常扣分 | 零 |
| `apply_innovation_bonus` | 计算创新性加分 | 零 |
| `get_dimension_standards` | 获取维度评分标准 | 零 |
| `estimate_token_budget` | 预估 Token 消耗 | 零 |
| `generate_report` | 生成质量评估报告 | 零 |
| `query_anomaly_mcp` | 联动异常检测 MCP | 零（桥接调用） |
| `extract_timeline` | 提取时间线并检测异常 | 零 |
| `trace_evidence_references` | 追踪证据引用情况 | 零 |
| `detect_evasive_patterns` | 检测规避责任写作模式 | 零 |
| `pipeline_progress` | 查询评估流水线进度 | 零 |
| `query_law_database` | 查询法律法规数据库，检测法律适用优先级、冲突和溯及力问题 | 零 |
| `query_case_precedent` | 查询类案判例数据库，检测类案冲突和偏离 | 零 |
| `submit_supplementary_doc` | 提交补充说明文件，可在报告中引用 | 零 |
| `analyze_legal_difficulty` | 分析法律适用难点和前沿问题，支持法谚、公序良俗、突破性创新 | 零 |

### 典型评估流程

```
1. extract_document_sections  → 提取文书段落
2. estimate_token_budget      → 预估 Token 消耗
3. render_dimension_prompt    → 逐维度渲染评分 Prompt
4. [Agent 调用 LLM 评分]      → Agent 自行调用 LLM
5. parse_score_result         → 解析评分结果
6. cross_check_consistency    → 交叉一致性检查
7. detect_evasive_patterns    → 检测规避模式
8. extract_timeline           → 提取时间线
9. trace_evidence_references  → 追踪证据引用
10. query_law_database        → 查询法律法规数据库（优先级、冲突、溯及力）
11. query_case_precedent      → 查询类案判例（冲突、偏离、创新空间）
12. submit_supplementary_doc  → 提交补充说明文档（可选）
13. analyze_legal_difficulty  → 分析法律适用难点（法谚、公序良俗、前沿问题）
14. calculate_weighted_score  → 计算加权总分
15. generate_report           → 生成评估报告
```

### 七维评分体系

| 维度 | 权重 | 核心评估内容 |
|:---|:---|:---|
| 形式规范 | 3% | 案号、当事人信息、审理经过、法条引用格式 |
| 事实清楚 | 12% | 争议焦点归纳、事实认定完整性、时间线清晰度 |
| 证据确实充分 | 12% | 证据三性审查、举证责任分配、采信理由说明 |
| 法律适用正确 | 18% | 法条引用准确性、法律解释方法、涵摄过程 |
| 说理充分透彻 | 22% | 事理法理情理融合、对辩驳回应、逻辑严密性 |
| 实质解纷效果 | 25% | 服判息诉效果、裁判主文明确性、可执行性 |
| 语言精练流畅 | 8% | 语言规范性、法言法语准确性、冗余度 |

## 项目结构

```
judicial-doc-quality-mcp/
├── src/judicial_quality_mcp/   # 核心源码
│   ├── server.py               # MCP 服务器（21个工具）
│   ├── config.py               # 配置管理
│   ├── models.py               # 数据模型
│   ├── response_parser.py      # 响应解析器
│   └── skill_runner.py         # Skill 加载与渲染
├── skills/                     # 评分标准（Skill 文件）
│   ├── dimensions/             # 七维评分标准
│   │   ├── 01_formal_specification.md
│   │   ├── 02_clear_facts.md
│   │   ├── 03_sufficient_evidence.md
│   │   ├── 04_correct_law_application.md
│   │   ├── 05_reasoning.md
│   │   ├── 06_substantive_resolution.md
│   │   └── 07_concise_language.md
│   ├── phases/                 # 评估流程阶段
│   │   ├── 00_precheck.md
│   │   ├── 01_quality_assessment.md
│   │   ├── 02_anomaly_integration.md
│   │   ├── 03_auxiliary_detection.md
│   │   └── 04_report_generation.md
│   ├── _system.md              # 系统级指令
│   └── _output_format.md       # 输出格式规范
├── anchors/                    # 锚定示例（各维度评分范例）
├── tests/                      # 单元测试
├── .env.example                # 环境变量模板
├── pyproject.toml              # 项目配置
└── test_new_tools.py           # 集成测试
```

## 局限性

1. **不直接调用 LLM**：本服务器采用桥接架构，所有 AI 推理由 Agent 完成。服务器本身无法独立生成评估结论，必须配合支持 MCP 的 AI 客户端使用。
2. **规则引擎的局限性**：基于正则表达式的规则引擎只能检测结构化、模式化的异常，无法理解语义层面的复杂问题（如法律适用错误、说理逻辑缺陷等）。
3. **评分标准的主观性**：七维评分体系中的扣分/加分规则基于法律实务经验和学术研究，但裁判文书质量评估本身具有一定主观性，不同评估者可能得出不同结论。
4. **民商事侧重**：当前评分标准主要针对民商事裁判文书设计，对刑事、行政裁判文书的适配性有限。
5. **异常检测联动依赖**：`query_anomaly_mcp` 工具需要单独部署 [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp)，未配置时该工具返回空白结果（不影响基本评估流程）。
6. **Token 消耗估算为近似值**：`estimate_token_budget` 基于字符数估算 Token 消耗，实际消耗取决于具体 LLM 的分词器，可能存在 10-20% 的偏差。
7. **时间线提取依赖日期格式**：`extract_timeline` 工具基于正则匹配提取日期，对非标准日期格式（如"近日""此后"）的识别能力有限。
8. **证据引用追踪的局限**：`trace_evidence_references` 基于关键词匹配，无法理解证据的实质内容和证明力。

## 免责声明

本项目仅供学术研究和法律技术探索使用，**不构成法律意见或专业法律建议**。

1. **非官方工具**：本项目与任何司法机关、仲裁机构均无关联，不代表任何官方立场。评估结果仅供参考，不应用于任何正式的法律程序或决策。
2. **评估结果的局限性**：本工具的评估结果基于预设的评分标准和规则，可能无法全面反映裁判文书的实际质量。裁判文书的评价涉及复杂的法律判断，本工具不能替代专业法律人士的审查。
3. **数据安全**：使用本工具处理裁判文书时，请注意保护当事人隐私和案件敏感信息。建议在本地环境运行，避免将文书内容传输至不可控的第三方服务。
4. **知识产权**：本项目使用的评分标准、法律依据和案例引用均来自公开的法律法规、司法解释和学术文献，仅供学术研究使用。如有侵权，请联系删除。
5. **适用法律**：本项目的评分标准基于中华人民共和国现行法律体系，对其他法域的裁判文书不适用。
6. **无担保**：本项目按"原样"提供，不作任何明示或暗示的担保，包括但不限于适销性、特定用途的适用性和非侵权性。

## 许可证

MIT License

## 致谢

- 评分标准参考：《优秀民商事裁判文书标准研究》（最高法院课题成果）
- 异常检测联动：[judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp)
- MCP 协议：[Model Context Protocol](https://modelcontextprotocol.io/)
