# judicial-doc-quality-mcp v0.1.0

> MCP Server for Judicial Document Quality Assessment — Bridge Architecture, Zero LLM Calls

English | [中文](./README.md)

## Overview

`judicial-doc-quality-mcp` is a judicial document quality assessment server built on the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It adopts a **Bridge Architecture** — the server itself makes no LLM calls. Instead, it provides structured scoring prompts, a rule engine, anomaly detection integration, and report generation tools, leaving all AI inference to the Agent (e.g., Claude, GPT).

**Core Value**: Encapsulates professional knowledge of judicial document quality assessment (7-dimension scoring system, deduction/bonus rules, cross-consistency checks, etc.) into MCP tools, enabling any MCP-compatible AI Agent to perform systematic, standardized quality assessments of judicial documents.

## Features

- **Bridge Architecture**: Zero LLM calls from the server. All AI inference is handled by the Agent, giving full control over token consumption.
- **7-Dimension Scoring System**: Formal Specification (3%), Clear Facts (12%), Sufficient Evidence (12%), Correct Law Application (18%), Thorough Reasoning (22%), Substantive Resolution (25%), Concise Language (8%).
- **Rule Engine + LLM Hybrid**: Structural anomalies are pre-screened by a regex rule engine; semantic anomalies are analyzed by the Agent.
- **Anomaly Detection Integration**: Optional integration with [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp) for 16-dimension anomaly detection and linked scoring deductions.
- **Evasive Pattern Detection**: Automatically identifies vague subjects, evasive timing, and missing responses — patterns used to evade responsibility in legal writing.
- **Timeline Extraction & Anomaly Detection**: Extracts timeline events from documents and detects temporal inversions.
- **Evidence Reference Tracing**: Tracks evidence citations in documents and detects missing evidence reasoning.
- **Law Database**: Built-in national laws, judicial interpretations, and local regulations. Supports legal priority ranking (special law over general law, new law over old law, higher law over lower law), conflict detection, and retroactivity analysis.
- **Case Precedent Database**: Retrieves case precedents based on case type and key facts. Analyzes adjudication tendencies, deviation points, and conflict points. Supports multi-level precedent retrieval (guiding cases, gazette cases, etc.).
- **Supplementary Document Submission**: Supports 7 types of supplementary documents (legal analysis, academic opinions, precedent comparison, legal maxim, ethics/morality, frontier issues, innovation arguments) that can be referenced in reports.
- **Legal Difficulty Analysis**: Identifies legal gray areas and frontier issues. Cites legal maxims and principles (e.g., "no one should profit from wrongdoing"). Analyzes social ethics and public order considerations. Provides innovation space without violating existing legal provisions.
- **Civil & Commercial Specialized Standards**: Built-in legal basis for civil/commercial judicial documents, mandatory hearing procedure items, and legal citation format standards.
- **Cross-Consistency Check**: Automatically detects logical conflicts between dimension scores (e.g., high "Clear Facts" but low "Sufficient Evidence").
- **Token Budget Estimation**: Estimates token consumption before rendering prompts, preventing context overflow.
- **Batch Rendering**: Supports batch rendering of multi-dimension prompts to reduce Agent call overhead.

## Installation

### Prerequisites

- Python >= 3.11
- An MCP-compatible AI client (e.g., Claude Desktop, Trae IDE)

### Install from Source

```bash
# Clone the repository
git clone https://github.com/CSlawyer1985/judicial-doc-quality-mcp.git
cd judicial-doc-quality-mcp

# Install dependencies (virtual environment recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .

# Optional: install anomaly detection integration
pip install -e ".[anomaly]"

# Optional: install development dependencies
pip install -e ".[dev]"
```

### Configuration

```bash
# Copy the environment variable template
cp .env.example .env

# Edit .env file as needed
# Key configuration items:
#   ANOMALY_MCP_AVAILABLE=false    # Enable anomaly detection integration
#   RULE_ENGINE_ENABLED=true       # Enable rule engine
#   EVASIVE_DETECTION_ENABLED=true # Enable evasive pattern detection
```

### MCP Client Configuration

Add to your MCP client (e.g., Claude Desktop) configuration:

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

For anomaly detection integration, also configure:

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

## Usage

### Tool List (21 MCP Tools)

| Tool | Description | Token Cost |
|:---|:---|:---|
| `list_dimensions` | List all scoring dimensions and metadata | Zero |
| `extract_document_sections` | Extract core sections from document text | Zero |
| `render_dimension_prompt` | Render scoring prompt for a single dimension | Zero (output for Agent) |
| `render_dimension_prompt_batch` | Batch render prompts for multiple dimensions | Zero |
| `parse_score_result` | Parse Agent-returned scoring results | Zero |
| `calculate_weighted_score` | Calculate weighted total score | Zero |
| `cross_check_consistency` | Cross-consistency check across dimensions | Zero |
| `apply_anomaly_deduction` | Calculate anomaly deductions | Zero |
| `apply_innovation_bonus` | Calculate innovation bonuses | Zero |
| `get_dimension_standards` | Get dimension scoring standards | Zero |
| `estimate_token_budget` | Estimate token consumption | Zero |
| `generate_report` | Generate quality assessment report | Zero |
| `query_anomaly_mcp` | Integrate with anomaly detection MCP | Zero (bridge call) |
| `extract_timeline` | Extract timeline and detect anomalies | Zero |
| `trace_evidence_references` | Trace evidence citations | Zero |
| `detect_evasive_patterns` | Detect evasive writing patterns | Zero |
| `pipeline_progress` | Query assessment pipeline progress | Zero |
| `query_law_database` | Query law database, detect priority, conflicts, retroactivity | Zero |
| `query_case_precedent` | Query case precedent database, detect conflicts and deviations | Zero |
| `submit_supplementary_doc` | Submit supplementary documents for report referencing | Zero |
| `analyze_legal_difficulty` | Analyze legal difficulty, legal maxims, public order, innovation space | Zero |

### Typical Assessment Workflow

```
1. extract_document_sections  → Extract document sections
2. estimate_token_budget      → Estimate token consumption
3. render_dimension_prompt    → Render per-dimension scoring prompts
4. [Agent calls LLM]          → Agent performs LLM inference
5. parse_score_result         → Parse scoring results
6. cross_check_consistency    → Cross-consistency check
7. detect_evasive_patterns    → Detect evasive patterns
8. extract_timeline           → Extract timeline
9. trace_evidence_references  → Trace evidence references
10. query_law_database        → Query law database (priority, conflicts, retroactivity)
11. query_case_precedent      → Query case precedents (conflicts, deviations, innovation)
12. submit_supplementary_doc  → Submit supplementary documents (optional)
13. analyze_legal_difficulty  → Analyze legal difficulty (maxims, public order, frontier)
14. calculate_weighted_score  → Calculate weighted total
15. generate_report           → Generate assessment report
```

### 7-Dimension Scoring System

| Dimension | Weight | Core Assessment |
|:---|:---|:---|
| Formal Specification | 3% | Case number, party info, hearing procedure, citation format |
| Clear Facts | 12% | Issue framing, fact-finding completeness, timeline clarity |
| Sufficient Evidence | 12% | Evidence admissibility, burden of proof, reasoning for admission/rejection |
| Correct Law Application | 18% | Accurate legal citations, interpretation methods, subsumption process |
| Thorough Reasoning | 22% | Integration of facts/law/equity, response to arguments, logical rigor |
| Substantive Resolution | 25% | Acceptance rate, judgment clarity, enforceability |
| Concise Language | 8% | Language norms, legal terminology accuracy, redundancy |

## Project Structure

```
judicial-doc-quality-mcp/
├── src/judicial_quality_mcp/   # Core source code
│   ├── server.py               # MCP server (21 tools)
│   ├── config.py               # Configuration management
│   ├── models.py               # Data models
│   ├── response_parser.py      # Response parser
│   └── skill_runner.py         # Skill loader & renderer
├── skills/                     # Scoring standards (Skill files)
│   ├── dimensions/             # 7-dimension scoring standards
│   │   ├── 01_formal_specification.md
│   │   ├── 02_clear_facts.md
│   │   ├── 03_sufficient_evidence.md
│   │   ├── 04_correct_law_application.md
│   │   ├── 05_reasoning.md
│   │   ├── 06_substantive_resolution.md
│   │   └── 07_concise_language.md
│   ├── phases/                 # Assessment workflow phases
│   │   ├── 00_precheck.md
│   │   ├── 01_quality_assessment.md
│   │   ├── 02_anomaly_integration.md
│   │   ├── 03_auxiliary_detection.md
│   │   └── 04_report_generation.md
│   ├── _system.md              # System-level instructions
│   └── _output_format.md       # Output format specification
├── anchors/                    # Anchor examples (per-dimension scoring samples)
├── tests/                      # Unit tests
├── .env.example                # Environment variable template
├── pyproject.toml              # Project configuration
└── test_new_tools.py           # Integration tests
```

## Limitations

1. **No Direct LLM Calls**: The server uses a bridge architecture. All AI inference is performed by the Agent. The server cannot independently generate assessment conclusions and must be used with an MCP-compatible AI client.
2. **Rule Engine Limitations**: The regex-based rule engine can only detect structured, pattern-based anomalies. It cannot understand complex semantic issues (e.g., legal application errors, reasoning logic defects).
3. **Subjectivity of Scoring Standards**: The deduction/bonus rules in the 7-dimension scoring system are based on legal practice experience and academic research, but judicial document quality assessment inherently involves subjectivity. Different evaluators may reach different conclusions.
4. **Civil/Commercial Focus**: The current scoring standards are primarily designed for civil and commercial judicial documents. Adaptability for criminal and administrative documents is limited.
5. **Anomaly Detection Dependency**: The `query_anomaly_mcp` tool requires separate deployment of [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp). When not configured, the tool returns blank results (basic assessment workflow is unaffected).
6. **Token Estimation is Approximate**: `estimate_token_budget` estimates token consumption based on character count. Actual consumption depends on the specific LLM tokenizer and may have 10-20% deviation.
7. **Timeline Extraction Depends on Date Format**: The `extract_timeline` tool extracts dates via regex matching. Recognition of non-standard date formats (e.g., "recently", "thereafter") is limited.
8. **Evidence Tracing Limitations**: `trace_evidence_references` is based on keyword matching and cannot understand the substantive content or probative value of evidence.

## Disclaimer

This project is intended for **academic research and legal technology exploration only** and does **not constitute legal advice or professional legal opinion**.

1. **Unofficial Tool**: This project is not affiliated with any judicial or arbitral institution and does not represent any official position. Assessment results are for reference only and should not be used in any formal legal proceedings or decision-making.
2. **Assessment Limitations**: Assessment results are based on preset scoring standards and rules and may not fully reflect the actual quality of a judicial document. Evaluating judicial documents involves complex legal judgments that this tool cannot replace with professional legal review.
3. **Data Security**: When processing judicial documents with this tool, please protect party privacy and case-sensitive information. Running in a local environment is recommended to avoid transmitting document content to uncontrolled third-party services.
4. **Intellectual Property**: The scoring standards, legal basis, and case citations used in this project are derived from publicly available laws, judicial interpretations, and academic literature, and are for academic research purposes only. Please contact us for removal if any infringement is found.
5. **Applicable Law**: The scoring standards are based on the current legal system of the People's Republic of China and are not applicable to judicial documents from other jurisdictions.
6. **No Warranty**: This project is provided "as is" without any express or implied warranties, including but not limited to merchantability, fitness for a particular purpose, and non-infringement.

## License

MIT License

## Acknowledgments

- Scoring standards reference: *Research on Standards for Excellent Civil and Commercial Judicial Documents* (Supreme People's Court research project)
- Anomaly detection integration: [judicial-doc-anomaly-mcp](https://github.com/lcfactorization/judicial-doc-anomaly-mcp)
- MCP Protocol: [Model Context Protocol](https://modelcontextprotocol.io/)
