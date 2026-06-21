"""Prompt builder v0.2.0 — trial stage inference + system prompt construction.

Consolidates `_infer_trial_stage` (from server.py) and `build_system_prompt`
(from skill_runner.py) into a single cohesive module.

Bridge Architecture: NO LLM calls.
"""

import logging
import re

logger = logging.getLogger(__name__)


# ── Trial stage inference ──────────────────────────────────────

# Mapping from trial stage to party terminology
STAGE_TERMS: dict[str, dict[str, str]] = {
    "一审": {"plaintiff": "原告", "defendant": "被告", "parties": "原告/被告"},
    "二审": {"plaintiff": "上诉人", "defendant": "被上诉人", "parties": "上诉人/被上诉人"},
    "再审": {"plaintiff": "申诉人", "defendant": "被申诉人", "parties": "申诉人/被申诉人"},
    "仲裁": {"plaintiff": "申请人", "defendant": "被申请人", "parties": "申请人/被申请人"},
    "行政": {"plaintiff": "投诉人", "defendant": "被投诉人", "parties": "投诉人/被投诉人"},
    "未知": {"plaintiff": "当事人", "defendant": "对方当事人", "parties": "当事人"},
}

# Stage responsibility descriptions for reports
STAGE_RESPONSIBILITY: dict[str, str] = {
    "一审": "一审法院对事实认定和法律适用负全部责任",
    "二审": "二审法院对一审判决的审查和自身裁判负责，不承担一审责任",
    "再审": "再审法院对原审生效判决的审查和再审裁判负责",
    "仲裁": "仲裁庭对仲裁裁决的事实认定和法律适用负责",
    "行政": "行政机关对行政决定的合法性和合理性负责",
}


def infer_trial_stage(case_name: str, document_text: str = "") -> str:
    """Infer trial stage from case number and/or document content.

    Uses regex patterns on case number first, falls back to document text
    scanning for party terminology.

    Args:
        case_name: Case number string (e.g. "(2024)苏06民终6271号").
        document_text: Full document text for fallback inference.

    Returns:
        One of: "一审", "二审", "再审", "仲裁", "行政", "未知"
    """
    if not case_name and not document_text:
        return "未知"

    search_text = case_name or document_text[:500]

    # ── Case number pattern matching ───────────────────────────
    if re.search(r"民终|行终|刑终|终字|终\d+号", search_text):
        return "二审"
    if re.search(r"民再|行再|刑再|再字|再\d+号", search_text):
        return "再审"
    if re.search(r"民初|行初|刑初|初字|初\d+号", search_text):
        return "一审"
    if re.search(r"劳仲|仲字|仲\d+号", search_text):
        return "仲裁"
    if re.search(r"行罚|行决|罚字", search_text):
        return "行政"

    # ── Fallback: party terminology in document text ────────────
    if document_text:
        if re.search(r"上诉人|被上诉人", document_text[:2000]):
            return "二审"
        if re.search(r"申诉人|被申诉人", document_text[:2000]):
            return "再审"
        if re.search(r"原告|被告", document_text[:2000]) and not re.search(r"上诉人|被上诉人", document_text[:2000]):
            return "一审"

    return "未知"


def get_stage_terms(trial_stage: str) -> dict[str, str]:
    """Get party terminology for a given trial stage."""
    return STAGE_TERMS.get(trial_stage, STAGE_TERMS["未知"])


# ── System prompt construction ─────────────────────────────────

# A-code anomaly classification
A_CODE_MAP = {
    "A1": "关键证据未回应",
    "A2": "事实认定跳跃",
    "A3": "法律适用未解释",
    "A4": "同类证据双重标准",
    "A5": "程序时间线异常",
    "A6": "回避核心争点",
    "A7": "机械复制模板化论证",
    "A8": "举证责任倒置异常",
}

# F-code fact-finding classification
F_CODE_MAP = {
    "F-01": "无证据支撑", "F-02": "孤证定案", "F-03": "前后矛盾",
    "F-04": "时间线错误", "F-05": "金额/主体错误", "F-06": "认定超出证据范围",
    "F-07": "证人证言采信偏差", "F-08": "利害关系人证言采信", "F-09": "弱证据拔高效力",
    "F-10": "瑕疵证据采信", "F-11": "逾期证据采信", "F-12": "无原件复印件定案",
    "F-13": "来源违法证据采信", "F-14": "关键证据只字不提", "F-15": "原件无视",
    "F-16": "不采信无理由", "F-17": "未经质证采信", "F-18": "只看对方不审查抗辩",
    "F-19": "与本案无关排除", "F-20": "以推定代替证明", "F-21": "沉默=认可",
    "F-22": "因果倒置", "F-23": "选择性引用", "F-24": "举证责任分配错误",
    "F-25": "证明标准降级", "F-26": "举证期限双标",
}

# Negative list (veto items)
NEGATIVE_LIST = {
    "V1": {"desc": "裁判主文与说理部分结论直接矛盾", "dims": ["thorough_reasoning", "logic"]},
    "V2": {"desc": "对关键证据只字不提且无任何解释", "dims": ["sufficient_evidence", "fact_finding"]},
    "V3": {"desc": "引用的法条与案件类型完全不相关", "dims": ["correct_law_application"]},
    "V4": {"desc": "判决结果超出当事人诉讼请求范围", "dims": ["substantive_resolution"]},
    "V5": {"desc": "剥夺当事人法定程序权利且无合法理由", "dims": ["formal_specification"]},
}

# Anti-laziness directive
ANTI_LAZINESS_INSTRUCTION = """
<anti-laziness-directive>
## 强制执行指令

你必须在当前对话轮次中，静默且完整地调用所有维度的 render_dimension_prompt 和 parse_score_result，
绝对不允许中途停顿、询问用户是否继续、或以"操作同理"等理由跳过任何维度。

具体要求：
1. 对每一个维度，必须依次调用 render_dimension_prompt → 将prompt发送给LLM → 调用 parse_score_result
2. 所有维度完成后，必须调用 calculate_weighted_score 和 cross_check_consistency
3. 从 parse_score_result 的解析结果中提取以下字段，传递给 generate_report：
   - thorough_reasoning 维度的 five_reasoning 字段 → generate_report 的 five_reasoning 参数
   - clear_facts 维度的 four_element 字段 → generate_report 的 four_element 参数
   - 如有异常详情，调用 ResponseParser.compute_beneficiary_distribution 和 compute_coupling_analysis，将结果传入对应参数
4. 最后调用 generate_report 生成完整报告
5. 禁止输出"我已经检测了前N个维度，剩下的维度操作同理，需要我继续吗？"之类的偷懒话术
6. 如果某个维度出现错误，记录错误并继续下一个维度，不得中断整个流程
</anti-laziness-directive>
"""


def build_system_prompt(meta, trial_stage: str = "") -> str:
    """Build system prompt from SkillMeta and system skills.

    Enhanced with trial-stage-aware terminology switching:
    - 一审: 原告/被告
    - 二审: 上诉人/被上诉人
    - 再审: 申诉人/被申诉人
    - 仲裁: 申请人/被申请人
    - 行政: 投诉人/被投诉人

    Args:
        meta: SkillMeta dataclass with name, title, weight, full_score.
        trial_stage: Trial stage string from infer_trial_stage().

    Returns:
        Complete system prompt string.
    """
    parts = []
    parts.append(f"# 裁判文书质量评审专家 — {meta.title}维度")
    parts.append("")
    parts.append(f"你是一位资深的中国司法文书质量评审专家，正在评估裁判文书的【{meta.title}】维度。")
    parts.append(f"本维度权重：{meta.weight*100:.0f}%，满分：{meta.full_score}分。")

    if trial_stage:
        terms = get_stage_terms(trial_stage)
        parts.append(f"当前文书审级：{trial_stage}")
        parts.append(f"获益方标注必须使用：{terms['parties']}，禁止使用其他审级术语。")
        parts.append(f"评估范围：仅评{trial_stage}法院的裁判行为，不评判其他审级。")
        parts.append(f"每个扣分项/加分项必须标注 stage_scope=\"{trial_stage}\"。")

    parts.append("")
    parts.append("请严格按照评分标准中的扣分项和加分项逐项检查，确保：")
    parts.append("1. 每个扣分项/加分项都有文书原文引用（original_text_location字段），禁止用'全文'、'多处'等模糊表述")
    parts.append("2. 评分理由清晰、具体、可验证，包含法理依据（legal_basis字段），必须引用具体法条编号及条文要点")
    parts.append("3. 输出格式为严格的JSON对象")
    parts.append("4. score为0-100之间的整数")

    # ── Hard constraints ────────────────────────────────────────
    parts.append("")
    parts.append("## ⚠️ 说理充分性硬约束（零容忍）")
    parts.append("")
    parts.append("检测他人文书的异常，自己的说理却稀里糊涂、找不到根据，这是绝对不允许的。")
    parts.append("以下字段为**必填且禁止空值**，违反任何一条将导致该扣分项无效：")
    parts.append("")
    parts.append("- **original_text_location**：必须定位到文书的具体段落/页码/行号，禁止用'—'、'全文'、'多处'敷衍")
    parts.append("- **legal_basis**：必须引用具体法条编号和条文要点（如'《劳动合同法》第30条第1款：用人单位应当按照劳动合同约定和国家规定，向劳动者及时足额支付劳动报酬'），禁止只写法条名不写条文")
    parts.append("- **suggestion**：必须给出具体可操作的修复建议（如'在证据采信部分补充说明为何采信考勤记录而排除证人证言，参照《民事诉讼证据规定》第85条'），禁止用'加强说理'、'完善论证'等空话")
    parts.append("- **q1_alternative**：必须分析是否存在合理解释，并说明理由（如'存在——用人单位可能因考勤系统故障导致记录不完整，但被上诉人未提供系统故障证据'），禁止只写'存在'或'不存在'")
    parts.append("- **q2_subjective_intent**：必须分析是否有主观偏向证据（如'未见——判决书对双方证据均逐一回应，未发现选择性忽略'），禁止只写'无'")
    parts.append("- **q3_contradictory_evidence**：必须说明是否存在反向证据及其内容（如'存在——被上诉人提交的工资条显示已支付加班费，但该工资条未经质证'），禁止只写'无'")
    parts.append("- **conclusion**：必须基于Q1/Q2/Q3给出明确结论（成立/存疑/不成立），并附一句话理由")
    parts.append("- **net_anomaly**：扣除反向异常后判定该异常是否仍然成立，必须附理由")
    parts.append("")
    parts.append("5. 每个扣分项必须包含：")
    parts.append("   - item_name（简要名称）、original_text_location（原文定位）、legal_basis（法理依据）、suggestion（改进建议）")
    parts.append("   - a_code（A系列分类编号，映射到A1-A8）")
    parts.append("   - beneficiary（获益方，根据程序阶段使用对应术语）")
    parts.append("   - confidence（置信度0.0-1.0）、severity（严重度：疑似/可能/高度可能/确定）")
    parts.append("   - 对抗校验：q1_alternative（替代解释）、q2_subjective_intent（排除主观故意）、q3_contradictory_evidence（相反证据）、conclusion（校验结论：成立/存疑/不成立）")
    parts.append("   - reverse_anomaly（反向异常点描述，如存在）、net_anomaly（净异常判定：成立/存疑/不成立）")
    parts.append("6. 每个加分项必须包含：item_name、original_text_location、legal_basis、detail")

    # ── A-code classification ───────────────────────────────────
    parts.append("")
    parts.append("## A系列异常分类体系")
    parts.append("每个扣分项必须映射到以下A系列分类之一：")
    for code, desc in A_CODE_MAP.items():
        parts.append(f"- {code}：{desc}")
    parts.append("")

    # ── Dimension-specific sections ─────────────────────────────
    if meta.name == "clear_facts":
        parts.append("## F编号体系（事实认定维度专用）")
        parts.append("本维度扣分项必须额外标注F编号：")
        for code, desc in F_CODE_MAP.items():
            parts.append(f"- {code}：{desc}")
        parts.append("")
        parts.append("## 四元结构分析法")
        parts.append("本维度评分中，需额外输出四元结构分析（four_element字段）：")
        parts.append("- 界定民事主体：当事人主体资格和诉讼地位的认定")
        parts.append("- 判断法律行为：法律行为性质和效力的认定")
        parts.append("- 保障民事权利：权利归属和范围的认定")
        parts.append("- 划分民事责任：责任构成和分担的认定")
        parts.append("")

    if meta.name == "thorough_reasoning":
        parts.append("## 五理说理评估")
        parts.append("本维度评分中，需额外输出五理分析（five_reasoning字段）：")
        parts.append("- 事理：事实叙述的完整性和逻辑性")
        parts.append("- 法理：法律适用的论证深度")
        parts.append("- 学理：学术理论的引用和运用")
        parts.append("- 情理：人情事理的考量")
        parts.append("- 文理：文书结构和语言表达")
        parts.append("")

    # ── Negative list ───────────────────────────────────────────
    parts.append("## 负面清单（一票否决项）")
    parts.append("以下情形一旦确认，该维度评分直接降为0分：")
    for vcode, vinfo in NEGATIVE_LIST.items():
        if meta.name in vinfo["dims"]:
            parts.append(f"- ⚠️ {vcode}：{vinfo['desc']}")
    parts.append("")

    # ── Minimum score principle ─────────────────────────────────
    parts.append("## 底线尊重原则")
    parts.append("只要判决中至少存在一项对弱势方有利的正确认定，总分不得低于40分（D级下限）。")
    parts.append("")

    # ── Output enrichment rules ─────────────────────────────────
    parts.append("## 输出充实规则（Anti-Dryness Directive）")
    parts.append("")
    parts.append("### 规则1：论证义务（Argumentation Duty）")
    parts.append("每个维度——包括\"无扣分\"维度——必须展开充分论证，论证义务不因检测结果为\"满分\"而免除。")
    parts.append("- 满分维度：(1) 检测过程说明 (2) 审查标准说明 (3) 达标论证 (4) 保持建议")
    parts.append("- 有扣分维度：(1) 扣分项定位（原文段落/行号） (2) 扣分性质分析 (3) 扣分合理性论证 (4) 改写建议 (5) 法条参照")
    parts.append("- 多项扣分维度：(1) 逐项定位 (2) 逐项分析 (3) 扣分间关联分析 (4) 详细改写建议 (5) 法条参照 (6) 改进路径建议")
    parts.append("")
    parts.append("### 规则2：Callout语义化（Obsidian Callouts）")
    parts.append("报告Markdown必须使用Obsidian Callouts（首字母大写格式），禁止使用GitHub Alerts全大写格式。")
    parts.append("类型映射：`[!Note]`检测过程 | `[!Abstract]`章节摘要 | `[!Info]`法理补充 | `[!Tip]`改写建议 | `[!Success]`检测通过 | `[!Question]`方法论反思 | `[!Warning]`风险提示 | `[!Failure]`检测未通过 | `[!Danger]`高危风险 | `[!Bug]`低风险异常 | `[!Example]`典型对照 | `[!Todo]`待办事项")
    parts.append("")
    parts.append("### 规则3：论证深度（Argumentation Depth）")
    parts.append("论证必须达到\"独立可验证\"的深度——读者无需查阅原始判决书即可理解论证过程和结论。")
    parts.append("- 事实陈述：必须标注证据来源（如\"见证据7.2\"）")
    parts.append("- 法律适用：必须引用完整法条内容，非仅法条编号")
    parts.append("- 逻辑推理：必须展示\"证据→事实→法律→结论\"推理链")
    parts.append("- 风险评估：必须说明风险等级的判定依据")
    parts.append("- 改写建议：必须提供具体替代表述，非仅\"建议修改\"")
    parts.append("")
    parts.append("### 规则4：质量自检（Quality Self-Check）")
    parts.append("报告生成后必须自检：每个维度至少1个深度论证callout；\"满分\"维度有检测过程说明；Callout类型≥6种；模板套话占比<10%。")
    parts.append("")
    parts.append("### 规则5：Callout结构规范（No Nested Blockquotes）")
    parts.append("Callout必须是顶层引用块，禁止在blockquote内嵌套Callout。即：`> [!Tag]` 是正确的，`> > [!Tag]` 是禁止的。Callout内容中也不得再嵌套另一个Callout。嵌套blockquote会导致HTML转换失败。")
    parts.append("")

    return "\n".join(parts)


# ── Render dimension prompt ────────────────────────────────────

def render_dimension_prompt(
    dimension: str,
    sections: dict | None = None,
    include_anchors: bool = True,
    anchor_count: int = 3,
    loader=None,
    renderer=None,
) -> dict:
    """Render the scoring Prompt template for a specified dimension.

    Migrated from server.py inline implementation. Returns a dict
    (not a JSON string) for the server.py thin proxy to serialize.

    Args:
        dimension: Dimension identifier (e.g. 'thorough_reasoning').
        sections: Pre-processed document section dict from extract_document_sections.
        include_anchors: Whether to include anchor examples (default True).
        anchor_count: Number of anchor examples to include (default 3).
        loader: SkillLoader instance (injected by server.py).
        renderer: TemplateRenderer instance (injected by server.py).

    Returns:
        Dict with dimension, dimension_title, weight, full_score,
        system_prompt, user_prompt, anchor_examples, output_schema,
        token_estimate.
    """
    from .token_estimator import estimate_tokens

    skill_name = f"dimensions/{dimension}"
    logger.info("render_dimension_prompt: dimension=%s", dimension)

    meta, body = loader.load(skill_name)
    logger.info("render_dimension_prompt: loaded skill=%s, title=%s, body_len=%d", meta.name, meta.title, len(body))

    template_vars = {}
    if sections:
        for key, value in sections.items():
            template_vars[key] = str(value) if value else ""

    rendered = renderer.render(body, template_vars)
    logger.info("render_dimension_prompt: rendered_len=%d", len(rendered))

    system_prompt = build_system_prompt(meta) + "\n\n" + ANTI_LAZINESS_INSTRUCTION

    anchors = []
    if include_anchors:
        anchors = loader.load_anchors(dimension)[:anchor_count]

    total_chars = len(system_prompt) + len(rendered)
    if anchors:
        import json as _json
        total_chars += len(_json.dumps(anchors, ensure_ascii=False))

    output_schema = {
        "type": "object",
        "properties": {
            "quote": {"type": "string", "description": "原文摘录"},
            "reasoning": {"type": "string", "description": "评分理由"},
            "score": {"type": "integer", "minimum": 0, "maximum": 100, "description": "得分"},
            "deduction_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "deduction": {"type": "integer"},
                        "quote": {"type": "string"},
                        "basis": {"type": "string"},
                    },
                },
            },
            "bonus_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "bonus": {"type": "integer"},
                        "quote": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
        },
        "required": ["quote", "reasoning", "score"],
    }

    if dimension == "substantive_resolution":
        output_schema["properties"]["data_completeness"] = {
            "type": "string",
            "enum": ["complete", "partial", "insufficient"],
            "description": "数据完整性",
        }
        output_schema["properties"]["sub_scores"] = {
            "type": "object",
            "description": "五个子项得分",
        }

    if dimension == "thorough_reasoning":
        output_schema["properties"]["five_reasoning"] = {
            "type": "object",
            "description": "五理说理评估",
            "properties": {
                "事理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "法理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "学理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "情理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "文理": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
            },
        }

    if dimension == "clear_facts":
        output_schema["properties"]["four_element"] = {
            "type": "object",
            "description": "四元结构分析",
            "properties": {
                "界定民事主体": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "判断法律行为": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "保障民事权利": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
                "划分民事责任": {"type": "object", "properties": {"score": {"type": "integer"}, "analysis": {"type": "string"}}},
            },
        }

    return {
        "dimension": meta.name,
        "dimension_title": meta.title,
        "weight": meta.weight,
        "full_score": meta.full_score,
        "system_prompt": system_prompt,
        "user_prompt": rendered,
        "anchor_examples": anchors,
        "output_schema": output_schema,
        "token_estimate": estimate_tokens(" " * total_chars),
    }
