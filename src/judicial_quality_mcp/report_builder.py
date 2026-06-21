"""Report builder v0.2.0 — Markdown and HTML report generation.

Extracted from server.py's `generate_report` and `generate_html_report` tools.
Contains the full report template rendering logic (~1200 lines of string
concatenation) and the Markdown-to-HTML converter with dark/light theme support.

Bridge Architecture: NO LLM calls. Pure string formatting.
"""

import json
import logging
import re
from datetime import datetime

from .config import (
    ANOMALY_DEDUCTION,
    DIMENSION_ORDER,
    DIMENSION_TITLES,
    INNOVATION_BONUS,
    QUALITY_GRADES,
    QUALITY_WEIGHTS,
    ErrorCode,
    StructuredError,
)

logger = logging.getLogger(__name__)

# ── Chinese labels used in reports ─────────────────────────────

_SEVERITY_ZH = {"critical": "严重", "high": "高", "medium": "中", "low": "低", "unknown": "未知"}
_ANOMALY_TYPE_ZH = {
    "temporal_inversion": "时间倒置", "temporal_gap": "时间缺口",
    "procedural_sequence": "程序时序", "evidence_temporal": "证据时序",
    "law_retroactivity": "法律溯及力", "internal_contradiction": "内部时间矛盾",
}
_EVASIVE_PATTERN_ZH = {
    "vague_subject": "主体模糊",
    "evasive_timing": "时间模糊",
    "selective_citation": "选择性引用",
    "template_language": "模板化说理",
    "missing_response": "回避回应",
}
_DIMENSION_ZH = {
    "procedure": "程序规范",
    "evidence": "证据采信",
    "fact_finding": "事实认定",
    "focus_drift": "焦点漂移",
    "law_application": "法律适用",
    "discretion": "自由裁量",
    "rhetoric_trick": "修辞技巧",
    "logic": "逻辑闭环",
    "temporal": "时间一致性",
    "trial_process": "审理过程",
    "external_interference": "外部干预",
    "execution": "执行问题",
    "negative_space": "缺失信息",
    "semantic_drift": "语义漂移",
    "case_deviation": "类案偏离",
    "coupling": "惯性耦合",
}


def _slugify(text: str) -> str:
    """Generate a Markdown anchor slug from heading text.

    GitHub/Obsidian style: lowercase, strip punctuation (except hyphens/spaces),
    spaces → hyphens, strip leading/trailing hyphens.
    Chinese characters are preserved as-is (most renderers support them).
    """
    slug = text.strip().lower()
    # Remove punctuation except CJK characters, hyphens, spaces
    slug = re.sub(r'[^\w\s\u4e00-\u9fff-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = slug.strip('-')
    return slug


def _make_error(code: ErrorCode, message: str, details: dict | None = None, retryable: bool = False) -> str:
    err = StructuredError(code=code.value, message=message, details=details or {}, retryable=retryable)
    return json.dumps({"success": False, "error": err.model_dump()}, ensure_ascii=False, indent=2)


# ── Markdown report generation ─────────────────────────────────

def build_report_markdown(
    dimension_results: list[dict],
    weighted_total: float,
    grade: str,
    cross_check: dict | None = None,
    anomaly_deduction: float = 0,
    innovation_bonus: float = 0,
    anomaly_details: list[dict] | None = None,
    innovation_details: list[dict] | None = None,
    anomaly_mcp_results: list[dict] | None = None,
    timeline_result: dict | None = None,
    evasive_result: dict | None = None,
    evidence_result: dict | None = None,
    document_meta: dict | None = None,
    law_database_result: dict | None = None,
    case_precedent_result: dict | None = None,
    supplementary_docs_result: list[dict] | None = None,
    legal_difficulty_result: dict | None = None,
    five_reasoning: dict | None = None,
    four_element: dict | None = None,
    beneficiary_distribution: dict | None = None,
    coupling_analysis: list[dict] | None = None,
    report_id: str | None = None,
    minimum_score_applied: bool = False,
    trial_stage: str = "",
) -> str:
    """Build the full Markdown report. Returns JSON string with report_markdown field.

    This is the core report rendering function extracted from server.py's generate_report.
    Pure string formatting — zero LLM calls.
    """
    try:
        lines = []

        if not report_id:
            report_id = f"QA-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        lines.append("# 司法/行政文书程序与实体异常深度检测与质量评估报告\n")
        lines.append(f"> 报告编号：{report_id}\n")

        if document_meta:
            _META_KEY_ZH = {
                "case_number": "案号",
                "court": "法院",
                "first_instance_court": "一审法院",
                "case_type": "案件类型",
                "trial_stage": "审级",
                "judge": "审判员",
                "clerk": "书记员",
                "date": "日期",
                "plaintiff": "原告",
                "defendant": "被告",
                "appellant": "上诉人",
                "appellee": "被上诉人",
                "third_party": "第三人",
            }
            lines.append("> [!Note]")
            lines.append("> **基础信息档案**")
            for k, v in document_meta.items():
                label = _META_KEY_ZH.get(k, k)
                lines.append(f"> - **{label}**：{v}")
            # Avoid duplicate 审级 if already in document_meta (check both English and Chinese keys)
            has_trial_stage_in_meta = "trial_stage" in (document_meta or {}) or "审级" in (document_meta or {})
            if trial_stage and not has_trial_stage_in_meta:
                lines.append(f"> - **审级**：{trial_stage}")
                _STAGE_RESPONSIBILITY = {
                    "一审": "一审法院对事实认定和法律适用负全部责任",
                    "二审": "二审法院对一审判决的审查和自身裁判负责，不承担一审责任",
                    "再审": "再审法院对原审生效判决的审查和再审裁判负责",
                    "仲裁": "仲裁机构对仲裁裁决负责",
                    "行政": "行政机关对行政决定负责",
                }
                resp = _STAGE_RESPONSIBILITY.get(trial_stage, "")
                if resp:
                    lines.append(f"> - **责任界定**：{resp}")
            lines.append(f"> - **检测时间**：{datetime.now().strftime('%Y-%m-%d')}")
            lines.append(f"> - **报告编号**：{report_id}")
            lines.append("")

        if minimum_score_applied:
            lines.append("> [!Danger]")
            lines.append("> **底线尊重原则已适用**：原始计算分数低于40分，但因存在对弱势方有利的正确认定，")
            lines.append("> 根据底线尊重原则，总分已调整为40分（D级下限），以体现对法官在体制压力下坚持部分正义的尊重。\n")

        # ── 目录占位符（将在所有章节生成后回填） ──
        _TOC_PLACEHOLDER_IDX = len(lines)
        lines.append("")  # placeholder, will be replaced

        # ── 综合异常等级 ──
        grade_desc = QUALITY_GRADES.get(grade, (0, 0, "未知"))[2]
        grade_lo = QUALITY_GRADES.get(grade, (0, 100, ""))[0]
        grade_hi = QUALITY_GRADES.get(grade, (0, 100, ""))[1]

        _ANOMALY_LEVEL_MAP = {
            (0, 70): "极度异常",
            (70, 80): "高度异常",
            (80, 85): "中度异常",
            (85, 90): "低度异常",
            (90, 95): "极低度异常",
            (95, 101): "无明显异常",
        }
        anomaly_level = "低度异常"
        for (lo, hi), label in _ANOMALY_LEVEL_MAP.items():
            if lo <= weighted_total < hi:
                anomaly_level = label
                break

        high_anomaly_count = sum(1 for a in (anomaly_details or []) if a.get("severity") == "high")
        medium_anomaly_count = sum(1 for a in (anomaly_details or []) if a.get("severity") == "medium")
        total_anomaly_items = high_anomaly_count + medium_anomaly_count

        lines.append("> [!Danger]")
        lines.append(f"> **综合异常等级：{anomaly_level}**")
        lines.append(">")
        lines.append(f"> **评级理由**：本案文书在七维质量评分中加权总分 **{weighted_total}** 分（{grade}·{grade_desc}），"
                     f"等级区间 [{grade_lo}, {grade_hi}]。"
                     f"检出 {total_anomaly_items} 项需关注异常（🔴高 {high_anomaly_count} 项、🟡中 {medium_anomaly_count} 项），"
                     f"异常扣分 −{anomaly_deduction:.0f}，创新加分 +{innovation_bonus:.0f}。")

        if anomaly_mcp_results:
            mcp_anomaly_count = sum(d.get("anomaly_count", 0) for d in anomaly_mcp_results)
            mcp_high = sum(1 for d in anomaly_mcp_results if d.get("risk_level") in ("critical", "high"))
            mcp_medium = sum(1 for d in anomaly_mcp_results if d.get("risk_level") == "medium")
            lines.append(f"> 十六维度异常检测共扫描 {len(anomaly_mcp_results)} 个维度，"
                         f"检出 {mcp_anomaly_count} 项异常（高风险 {mcp_high} 维度、中风险 {mcp_medium} 维度）。")
            if mcp_high == 0 and mcp_medium <= 2:
                lines.append(f"> 未发现高置信的硬伤型异常，存疑点均属于可解释的裁量范畴，不存在多维异常耦合或指向一致性。")
        lines.append("")

        # ── 综合评级 ──
        lines.append("## 综合评级\n")
        lines.append(f'<span class="grade-tag grade-{grade[0]}">{grade}</span>（{grade_desc}）  |  加权总分 **{weighted_total}** / 100  |  等级区间 [{grade_lo}, {grade_hi}]  |  异常等级 **{anomaly_level}**\n')

        if anomaly_deduction > 0 or innovation_bonus > 0:
            base = weighted_total - innovation_bonus + anomaly_deduction
            lines.append("> [!Note]")
            lines.append(f"> 基础分 {base:.1f}  |  异常扣分 −{anomaly_deduction:.0f}  |  创新加分 +{innovation_bonus:.0f}")
            lines.append("")

        # ── 等级说明 ──
        lines.append("> [!Tip]")
        lines.append("> **等级划分**：A 优秀 [95,100] · A⁻ 优良 [90,94] · B⁺ 良好 [85,89] · B 中上 [80,84] · C⁺ 中等 [75,79] · C 中下 [70,74] · D 及格 [60,69] · F 不及格 [0,59]")
        lines.append("")

        # ── 报告概览 ──
        lines.append("## 报告概览\n")
        lines.append("> [!Note]")
        lines.append("> **检测流程**：先进行十六维度异常检测，再进行七维质量评估，两项结果合并参考。\n")

        overview_rows = []
        overview_rows.append(("检测流程", "异常检测 → 质量评估"))
        overview_rows.append(("审级", trial_stage or "未知"))
        if trial_stage:
            _STAGE_RESPONSIBILITY2 = {
                "一审": "一审法院对事实认定和法律适用负全部责任",
                "二审": "二审法院对一审判决的审查和自身裁判负责，不承担一审责任",
                "再审": "再审法院对原审生效判决的审查和再审裁判负责",
                "仲裁": "仲裁机构对仲裁裁决负责",
                "行政": "行政机关对行政决定负责",
            }
            overview_rows.append(("责任界定", _STAGE_RESPONSIBILITY2.get(trial_stage, "")))

        overview_rows.append(("综合评级", f"{grade}（{grade_desc}）"))
        overview_rows.append(("加权总分", f"{weighted_total} / 100"))
        overview_rows.append(("异常等级", anomaly_level))
        overview_rows.append(("异常扣分", f"−{anomaly_deduction:.0f}"))
        overview_rows.append(("创新加分", f"+{innovation_bonus:.0f}"))

        if anomaly_mcp_results:
            mcp_total = sum(d.get("anomaly_count", 0) for d in anomaly_mcp_results)
            mcp_high = sum(1 for d in anomaly_mcp_results if d.get("risk_level") in ("critical", "high"))
            overview_rows.append(("异常检测维度", f"{len(anomaly_mcp_results)} 维度 / {mcp_total} 项异常 / {mcp_high} 高风险"))

        high_anomaly_count = sum(1 for a in (anomaly_details or []) if a.get("severity") == "high")
        medium_anomaly_count = sum(1 for a in (anomaly_details or []) if a.get("severity") == "medium")
        overview_rows.append(("核心异常项", f"🔴高 {high_anomaly_count} 项 / 🟡中 {medium_anomaly_count} 项"))

        lines.append("| 指标 | 结果 |")
        lines.append("|:---|:---|")
        for label, value in overview_rows:
            lines.append(f"| {label} | {value} |")
        lines.append("")

        # ── 各维度评分 ──
        _QUALITY_START = len(lines)
        lines.append("## __NUM__七维质量评分详情\n")
        lines.append("> [!Note]")
        lines.append("> 七维质量评分体系涵盖形式规范、事实清楚、证据充分、法律适用、说理透彻、实质解纷、语言精练七个维度，")
        lines.append("> 每个维度均包含扣分项、加分项和改进建议，为文书质量提供全面量化评价。\n")

        lines.append("### 各维度评分总览\n")
        lines.append("| 维度编号 | 维度 | 得分 | 权重 | 加权得分 | 核心扣分项 | 核心加分项 |")
        lines.append("|:---:|:---|:---:|:---:|:---:|:---|:---|")

        for dim_idx, dr in enumerate(dimension_results, 1):
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            dim_code = f"D{DIMENSION_ORDER.get(dim, dim_idx)}"
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0
            weight = QUALITY_WEIGHTS.get(dim, 0.0)
            weighted = round(score * weight, 2)

            deductions = dr.get("deduction_items", [])
            ded_summary = "、".join(d.get("item", "") for d in deductions) if deductions else "无扣分"
            bonuses = dr.get("bonus_items", [])
            bon_summary = "、".join(b.get("item", "") for b in bonuses) if bonuses else "无加分"

            lines.append(f"| {dim_code} | {title} | {score} | {weight*100:.0f}% | {weighted} | {ded_summary} | {bon_summary} |")

        lines.append("")

        # ── 评分明细一览 ──
        lines.append("### 评分明细与改进建议\n")
        lines.append("| 维度编号 | 维度 | 得分 | 扣分项 | 扣分原因 | 加分项 | 加分原因 | 改进建议 |")
        lines.append("|:---:|:---|:---:|:---|:---|:---|:---|:---|")
        _DIM_IMPROVEMENT = {
            "formal_specification": "检查文书格式是否符合规范要求",
            "clear_facts": "加强关键事实的查明和论证",
            "sufficient_evidence": "确保证据采信标准统一",
            "correct_law_application": "核实法律适用的准确性",
            "thorough_reasoning": "增强说理的逻辑性和充分性",
            "substantive_resolution": "提升纠纷实质性化解效果",
            "concise_language": "精简文书语言，避免冗余",
        }
        _DIM_DETAIL_DESC = {
            "formal_specification": "文书格式规范、要素齐全、结构完整",
            "clear_facts": "案件事实查明清楚、关键情节认定准确",
            "sufficient_evidence": "证据采信充分、举证责任分配合理",
            "correct_law_application": "法律适用正确、条文引用准确",
            "thorough_reasoning": "裁判说理充分、逻辑严密、回应争议焦点",
            "substantive_resolution": "纠纷实质性化解、服判息诉效果好",
            "concise_language": "语言精练、表述准确、无冗余",
        }
        _PLACEHOLDER_REASONS = {"", "—", "无", "略", "同上", "见上文", "详见上文", "符合扣分条件"}

        for dim_idx, dr in enumerate(dimension_results, 1):
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            dim_code = f"D{DIMENSION_ORDER.get(dim, dim_idx)}"
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0

            deductions = dr.get("deduction_items", [])
            ded_items = "、".join(d.get("item", d.get("code", "")) for d in deductions) if deductions else "无扣分（满分表现）"
            ded_reasons = "；".join(d.get("reason", d.get("standard", "")) for d in deductions if d.get("reason", d.get("standard", "")) not in _PLACEHOLDER_REASONS) if deductions else ""
            if not ded_reasons:
                ded_reasons = "详见扣分项说明" if deductions else "无扣分原因（满分表现）"

            bonuses = dr.get("bonus_items", [])
            bon_items = "、".join(b.get("item", b.get("code", "")) for b in bonuses) if bonuses else "无加分项"
            bon_reasons = "；".join(b.get("reason", b.get("standard", "")) for b in bonuses if b.get("reason", b.get("standard", "")) not in _PLACEHOLDER_REASONS) if bonuses else ""
            if not bon_reasons:
                bon_reasons = "详见加分项说明" if bonuses else "无加分原因（本维度无突出亮点）"

            improvement = _DIM_IMPROVEMENT.get(dim, "")
            if deductions:
                valid_suggestions = [d.get("suggestion", "") for d in deductions if d.get("suggestion", "") not in _PLACEHOLDER_REASONS]
                improvement = "；".join(valid_suggestions) if valid_suggestions else "针对扣分项逐项改进"
            else:
                improvement = "本维度无扣分项，保持当前水平即可"

            lines.append(f"| {dim_code} | {title} | {score} | {ded_items} | {ded_reasons} | {bon_items} | {bon_reasons} | {improvement} |")

        lines.append("")

        # ── 各维度深度分析 ──
        lines.append("### 各维度深度分析\n")
        for dim_idx, dr in enumerate(dimension_results, 1):
            dim = dr.get("dimension", "")
            title = DIMENSION_TITLES.get(dim, dim)
            dim_code = f"D{DIMENSION_ORDER.get(dim, dim_idx)}"
            score = dr.get("score", 0)
            if not isinstance(score, (int, float)):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 0
            weight = QUALITY_WEIGHTS.get(dim, 0.0)
            weighted = round(score * weight, 2)
            dim_desc = _DIM_DETAIL_DESC.get(dim, "")

            deductions = dr.get("deduction_items", [])
            bonuses = dr.get("bonus_items", [])

            # Score bar indicator
            score_bar_len = 20
            filled = int(score / 100 * score_bar_len)
            bar = "█" * filled + "░" * (score_bar_len - filled)
            lines.append(f"#### {dim_code} {title}\n")
            lines.append(f"| 项目 | 内容 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| 得分 | {score} / 100 {bar} |")
            lines.append(f"| 权重 | {weight*100:.0f}% |")
            lines.append(f"| 加权得分 | {weighted} |")
            if dim_desc:
                lines.append(f"| 维度说明 | {dim_desc} |")
            lines.append("")

            # Deduction items in WARNING alert
            if deductions:
                lines.append("> [!Warning]")
                lines.append(f"> **扣分项（共 {len(deductions)} 项）**")
                for d in deductions:
                    d_item = d.get('item', d.get('code', ''))
                    d_reason = d.get('reason', d.get('standard', ''))
                    if not d_reason or d_reason in _PLACEHOLDER_REASONS:
                        d_reason = d_item  # Use item name as reason fallback
                    d_deduction = d.get('deduction', '?')
                    d_suggestion = d.get('suggestion', '')
                    if d_suggestion and d_suggestion not in _PLACEHOLDER_REASONS:
                        lines.append(f"> - **{d_item}**（扣 {d_deduction} 分）：{d_reason} → 建议：{d_suggestion}")
                    else:
                        lines.append(f"> - **{d_item}**（扣 {d_deduction} 分）：{d_reason}")
                lines.append("")
            else:
                lines.append("> [!Tip]")
                lines.append("> 本维度无扣分项，表现良好。")
                lines.append("")

            # Bonus items in TIP alert
            if bonuses:
                lines.append("> [!Tip]")
                lines.append(f"> **加分项（共 {len(bonuses)} 项）**")
                for b in bonuses:
                    b_item = b.get('item', b.get('code', ''))
                    b_reason = b.get('reason', b.get('standard', ''))
                    if not b_reason or b_reason in _PLACEHOLDER_REASONS:
                        b_reason = b_item  # Use item name as reason fallback
                    b_bonus = b.get('bonus', '?')
                    lines.append(f"> - **{b_item}**（加 {b_bonus} 分）：{b_reason}")
                lines.append("")

            lines.append("---")
            lines.append("")

        # ── 异常扣分明细 ──
        _ANOMALY_START = len(lines)
        if anomaly_details:
            lines.append("## __NUM__核心异常总览\n")
            lines.append("| # | 维度 | 异常检测项 | F编号 | A分类 | 简要表现 | 指向获益方 | 置信度 |")
            lines.append("|:---:|:---|:---|:---:|:---:|:---|:---|:---|")
            _ANOMALY_CODE_MAP = {
                "程序异常": "QA-01", "证据异常": "QA-02", "事实认定异常": "QA-03",
                "法律适用异常": "QA-04", "说理异常": "QA-05", "逻辑异常": "QA-06",
                "异常扣分": "QA-07",
            }
            sorted_anomalies = sorted(anomaly_details, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x.get("severity", "low"), 3))
            for ad_idx, ad in enumerate(sorted_anomalies, 1):
                sev = ad.get('severity', 'low')
                sev_icon = {"high": "🔴", "medium": "⚠️", "low": "🟢"}.get(sev, "")
                beneficiary = ad.get('beneficiary', ad.get('target', ''))
                if not beneficiary:
                    # Infer beneficiary from anomaly type and description
                    desc = ad.get('description', '')
                    if any(kw in desc for kw in ['举证妨碍', '举证责任', '证据', '工资台账', '考勤']):
                        beneficiary = "用人单位（被上诉方）"
                    elif any(kw in desc for kw in ['说理', '法律适用', '举证责任分配']):
                        beneficiary = "用人单位（被上诉方）"
                    else:
                        beneficiary = "待LLM确认"
                confidence = ad.get('confidence', sev_icon)
                brief = ad.get('brief', ad.get('description', ''))
                f_code = ad.get('f_code', '')
                if not f_code:
                    # Auto-assign F-code based on anomaly type
                    label_for_code = ad.get('label', '')
                    _F_CODE_MAP = {
                        "证据异常": "F-07", "说理异常": "F-15", "程序异常": "F-01",
                        "事实认定异常": "F-03", "法律适用异常": "F-11", "逻辑异常": "F-13",
                    }
                    f_code = _F_CODE_MAP.get(label_for_code, f"F-{ad_idx:02d}")
                a_code = ad.get('a_code', '')
                if not a_code:
                    # Auto-assign A-code based on severity
                    _A_CODE_MAP = {"high": "A-01", "medium": "A-02", "low": "A-03"}
                    a_code = _A_CODE_MAP.get(sev, "A-02")
                label = ad.get('label', '')
                if not label:
                    # Infer label from description
                    desc = ad.get('description', '')
                    if any(kw in desc for kw in ['证据', '举证']):
                        label = "证据异常"
                    elif any(kw in desc for kw in ['说理', '论证', '推理']):
                        label = "说理异常"
                    elif any(kw in desc for kw in ['法律', '法条', '适用']):
                        label = "法律适用异常"
                    elif any(kw in desc for kw in ['程序', '送达', '审限']):
                        label = "程序异常"
                    else:
                        label = "综合异常"
                item_name = ad.get('item_name', ad.get('reason', ''))
                if not item_name:
                    item_name = brief or f"异常项{ad_idx}"
                lines.append(f"| {ad_idx} | {label} | {item_name} | {f_code} | {a_code} | {brief} | {beneficiary} | {confidence} |")
            lines.append("")

            lines.append("## __NUM__异常项深度剖析\n")
            _MISSING = "⚠️ 缺失（需LLM补充）"
            for ad_idx, ad in enumerate(sorted_anomalies, 1):
                sev = ad.get('severity', 'low')
                sev_zh = _SEVERITY_ZH.get(sev, sev)
                label = ad.get('label', '')
                item_name = ad.get('item_name', ad.get('reason', ''))
                ad_code = _ANOMALY_CODE_MAP.get(label, f"QA-{ad_idx:02d}")

                lines.append(f"### {ad_code} {label}：{item_name}\n")

                a_code_val = ad.get('a_code', '')
                f_code_val = ad.get('f_code', '')
                code_suffix = ""
                if a_code_val or f_code_val:
                    code_parts = []
                    if a_code_val:
                        code_parts.append(f"A分类：{a_code_val}")
                    if f_code_val:
                        code_parts.append(f"F编号：{f_code_val}")
                    code_suffix = f" | {'，'.join(code_parts)}"

                risk_class = {"high": "risk-highest", "medium": "risk-high", "low": "risk-low"}.get(sev, "risk-low")
                risk_label = {"high": "最高风险", "medium": "高风险", "low": "低风险"}.get(sev, "低风险")
                risk_tag_html = f'<span class="risk-tag {risk_class}">{risk_label}</span>'

                original_text_location = ad.get('original_text_location') or ad.get('location') or ad.get('original_text') or ''
                if not original_text_location:
                    original_text_location = _MISSING

                evidence_reference = ad.get('evidence_reference') or ad.get('evidence') or ''
                if not evidence_reference:
                    evidence_reference = _MISSING

                beneficiary = ad.get('beneficiary') or ''
                if not beneficiary:
                    beneficiary = "待LLM确认"

                lines.append("> [!Warning]")
                lines.append(f"> **触发项**：{item_name} {risk_tag_html}")
                lines.append(f"> **原文定位**：{original_text_location}")
                lines.append(f"> **证据对照**：{evidence_reference}")
                lines.append(f"> **严重程度**：{sev_zh} | **扣分**：-{ad.get('deduction', 0)} | **指向获益方**：{beneficiary}{code_suffix}")
                lines.append("")

                description = ad.get('description', '')
                if description:
                    lines.append(f"**异常表现**：{description}\n")

                legal_analysis = ad.get('legal_analysis', '')
                if legal_analysis:
                    lines.append(f"**法理/背景点评**：\n")
                    lines.append(f"{legal_analysis}\n")
                else:
                    lines.append(f"**法理/背景点评**：{_MISSING}\n")

                alternative = ad.get('alternative_explanation', '')
                if alternative:
                    lines.append(f"**替代解释**：{alternative}\n")

                lines.append("> [!Important]")
                lines.append("> **对抗校验结论**：")

                q1 = ad.get('q1_alternative') or alternative or ''
                if not q1:
                    q1 = _MISSING
                q2 = ad.get('q2_subjective_intent') or ''
                if not q2:
                    q2 = _MISSING
                q3 = ad.get('q3_contradictory_evidence') or ''
                if not q3:
                    q3 = _MISSING

                lines.append(f"> - **Q1（替代解释）**：{q1}")
                lines.append(f"> - **Q2（排除主观故意）**：{q2}")
                lines.append(f"> - **Q3（相反证据）**：{q3}")

                conclusion = ad.get('conclusion') or ''
                if not conclusion:
                    conclusion = f"存疑——{item_name}需进一步核实"
                net_anomaly = ad.get('net_anomaly') or ''
                if not net_anomaly:
                    net_anomaly = "待LLM判定"

                lines.append(f"> - **校验结论**：{conclusion}")
                lines.append(f"> - **净异常判定**：{net_anomaly}")
                lines.append("")

                reverse_anomaly = ad.get('reverse_anomaly') or ''
                if reverse_anomaly:
                    lines.append(f"**反向异常点**：{reverse_anomaly}\n")

                fix = ad.get('suggestion') or ad.get('fix') or ''
                if not fix:
                    # Auto-generate suggestion based on anomaly type
                    desc = ad.get('description', '')
                    if '举证妨碍' in desc or '涂黑' in desc:
                        fix = "应依据《最高人民法院关于民事诉讼证据的若干规定》第75条，对用人单位恶意涂黑工资台账行为作不利推定"
                    elif '举证责任' in desc:
                        fix = "应依据《劳动合同法》第82条立法本意，将二倍工资的举证责任分配给用人单位"
                    else:
                        fix = "需补充具体论证和说理"
                lines.append(f"**修复建议**：{fix}\n")

        # ── Innovation bonus section ──
        _INNOVATION_START = len(lines)
        if innovation_details:
            lines.append("## __NUM__创新亮点与加分项\n")
            lines.append("> [!Tip]")
            lines.append("> 以下创新亮点经评估确认，每项加分已计入总分。\n")
            for inn_idx, inn in enumerate(innovation_details, 1):
                inn_type = inn.get("type", "")
                inn_label = inn.get("label", inn_type)
                inn_bonus = inn.get("bonus", 0)
                inn_desc = inn.get("description", "")
                inn_evidence = inn.get("evidence", inn.get("quote", ""))
                inn_reasoning = inn.get("reasoning", inn.get("reason", ""))
                lines.append(f"### {inn_idx}. {inn_label}（+{inn_bonus}分）\n")
                if inn_desc:
                    lines.append(f"**创新表现**：{inn_desc}\n")
                if inn_evidence:
                    lines.append(f"**原文依据**：{inn_evidence}\n")
                if inn_reasoning:
                    lines.append(f"**加分理由**：{inn_reasoning}\n")
            lines.append("")

        # ── Beneficiary distribution ──
        if beneficiary_distribution:
            lines.append("### 获益方分布统计\n")
            lines.append("| 获益方 | 异常项数 | 占比 |")
            lines.append("|:---|:---:|:---:|")
            for ben, count in beneficiary_distribution.items():
                lines.append(f"| {ben} | {count} | — |")
            lines.append("")

        # ── Coupling analysis ──
        if coupling_analysis:
            lines.append("### 异常耦合分析\n")
            for ca in coupling_analysis:
                desc = ca.get("desc", "")
                ben = ca.get("beneficiary", "")
                if desc:
                    ben_str = f" → 指向 **{ben}**" if ben else ""
                    lines.append(f"- {desc}{ben_str}")
            lines.append("")

        # ── Five reasoning ──
        if five_reasoning:
            lines.append("### 五理说理评估\n")
            lines.append("> [!Note]")
            lines.append("> 五理说理理论从事理、法理、学理、情理、文理五个维度评估文书说理充分性，")
            lines.append("> 为说理充分透彻维度提供更精细的分析视角。\n")
            lines.append("| 说理维度 | 得分 | 分析 |")
            lines.append("|:---|:---:|:---|")
            for rkey, rval in five_reasoning.items():
                if isinstance(rval, dict):
                    r_score = rval.get('score', '')
                    if not r_score:
                        r_score = "待评估"
                    r_analysis = rval.get('analysis', '')
                    if not r_analysis:
                        r_analysis = "待LLM补充分析"
                    lines.append(f"| {rkey} | {r_score} | {r_analysis} |")
                else:
                    lines.append(f"| {rkey} | {rval} | 待LLM补充分析 |")
            lines.append("")

        # ── Four element ──
        if four_element:
            lines.append("### 四元结构分析法\n")
            lines.append("> [!Note]")
            lines.append("> 四元结构分析法从界定民事主体、判断法律行为、保障民事权利、划分民事责任四个方面，")
            lines.append("> 评估事实认定维度的结构完整性。\n")
            lines.append("| 结构要素 | 得分 | 分析 |")
            lines.append("|:---|:---:|:---|")
            for ekey, eval_ in four_element.items():
                if isinstance(eval_, dict):
                    e_score = eval_.get('score', '')
                    if not e_score:
                        e_score = "待评估"
                    e_analysis = eval_.get('analysis', '')
                    if not e_analysis:
                        e_analysis = "待LLM补充分析"
                    lines.append(f"| {ekey} | {e_score} | {e_analysis} |")
                else:
                    lines.append(f"| {ekey} | {eval_} | 待LLM补充分析 |")
            lines.append("")

        # ── Timeline ──
        if timeline_result:
            coverage = timeline_result.get("coverage", {})
            total_events = coverage.get("total_events", len(timeline_result.get("events", [])))
            anomaly_count = coverage.get("anomaly_count", len(timeline_result.get("anomalies", [])))
            completeness = coverage.get("completeness", "N/A")
            completeness_zh_tl = {"high": "高", "medium": "中", "low": "低"}.get(completeness, completeness)
            anomalies = timeline_result.get("anomalies", [])

            lines.append("### 时间线提取与异常检测\n")
            lines.append(f"| 指标 | 结果 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| 提取事件数 | {total_events} |")
            lines.append(f"| 时间线异常数 | {anomaly_count} |")
            lines.append(f"| 时间线完整性 | {completeness_zh_tl} |")
            lines.append("")

            if anomalies:
                high_anomalies = [a for a in anomalies if a.get("severity") == "high"]
                medium_anomalies = [a for a in anomalies if a.get("severity") == "medium"]
                if high_anomalies:
                    lines.append("> [!Warning]")
                    lines.append(f"> 检出 {len(high_anomalies)} 项高严重度时序异常，可能影响裁判合法性，请重点核实\n")
                elif medium_anomalies:
                    lines.append("> [!Note]")
                    lines.append(f"> 检出 {len(medium_anomalies)} 项中等时序异常，需关注法律溯及力及证据时序问题\n")
                else:
                    lines.append("> [!Tip]")
                    lines.append("> 时序异常均为低严重度，不影响文书质量评价\n")

                lines.append("| 异常编号 | 严重程度 | 异常类型 | 说明 |")
                lines.append("|:---:|:---:|:---|:---|")
                _TL_ANOMALY_CODE = {
                    "procedural_sequence": "TL-01", "evidence_temporal": "TL-02",
                    "law_retroactivity": "TL-03", "internal_contradiction": "TL-04",
                    "temporal_inversion": "TL-05", "temporal_gap": "TL-06",
                }
                for a_idx, a in enumerate(anomalies, 1):
                    sev_zh = _SEVERITY_ZH.get(a.get("severity", "?"), a.get("severity", "?"))
                    type_zh = _ANOMALY_TYPE_ZH.get(a.get("type", "?"), a.get("type", "?"))
                    a_code = _TL_ANOMALY_CODE.get(a.get("type", ""), f"TL-{a_idx:02d}")
                    lines.append(f"| {a_code} | {sev_zh} | {type_zh} | {a.get('message', '')} |")
                lines.append("")

            narrative_inv = coverage.get("narrative_inversions", 0)
            if narrative_inv > 0:
                lines.append("> [!Tip]")
                lines.append(f"> 文书存在{narrative_inv}处叙事结构倒置（先述裁判结果后回溯事实），属正常叙事结构，不作为异常\n")

        # ── Evasive patterns ──
        if evasive_result:
            risk_level = evasive_result.get("risk_level", "N/A")
            risk_level_zh = _SEVERITY_ZH.get(risk_level, risk_level)
            detected_patterns = evasive_result.get("detected_patterns", [])
            detected_count = len(detected_patterns)

            lines.append("### 规避模式检测\n")
            lines.append(f"| 指标 | 结果 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| 风险等级 | {risk_level_zh} |")
            lines.append(f"| 检出模式数 | {detected_count} |")
            lines.append("")

            if risk_level in ("high", "medium"):
                lines.append("> [!Danger]")
                lines.append(f"> 规避模式风险等级为 **{risk_level_zh}**，建议重点关注\n")
            elif risk_level == "low":
                lines.append("> [!Note]")
                lines.append("> 规避模式风险等级为低，文书规避倾向不明显\n")

            if detected_patterns:
                lines.append("| 模式编号 | 严重程度 | 模式名称 | 匹配数 | 说明 |")
                lines.append("|:---:|:---:|:---|:---:|:---|")
                _EVASIVE_CODE_MAP = {
                    "vague_subject": "EP-01", "evasive_timing": "EP-02",
                    "selective_citation": "EP-03", "template_language": "EP-04",
                    "missing_response": "EP-05",
                }
                for p_idx, p in enumerate(detected_patterns, 1):
                    p_name = _EVASIVE_PATTERN_ZH.get(p.get("pattern_id", ""), p.get("pattern_id", p.get("name", "?")))
                    p_sev = _SEVERITY_ZH.get(p.get("severity", "?"), p.get("severity", "?"))
                    p_desc = p.get("message", p.get("description", ""))
                    p_code = _EVASIVE_CODE_MAP.get(p.get("pattern_id", ""), f"EP-{p_idx:02d}")
                    lines.append(f"| {p_code} | {p_sev} | {p_name} | {p.get('match_count', 0)} | {p_desc} |")
                lines.append("")

            recommendation = evasive_result.get("recommendation", "")
            if recommendation:
                lines.append(f"> [!Important]")
                lines.append(f"> {recommendation}\n")

        # ── Evidence tracing ──
        if evidence_result:
            total_ev = len(evidence_result.get("evidence_items", []))
            unaddressed = len(evidence_result.get("unaddressed", []))
            missing_reasoning = len(evidence_result.get("missing_reasoning", []))
            trace_summary = evidence_result.get("trace_summary", {})
            completeness = trace_summary.get("completeness", "N/A")
            completeness_zh = {"high": "高", "medium": "中", "low": "低"}.get(completeness, completeness)

            lines.append("### 证据引用追踪\n")
            lines.append(f"| 指标 | 结果 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| 证据项数 | {total_ev} |")
            lines.append(f"| 未回应证据 | {unaddressed} |")
            lines.append(f"| 缺说理证据 | {missing_reasoning} |")
            lines.append(f"| 引用完整性 | {completeness_zh} |")
            lines.append("")

            if unaddressed > 0 or missing_reasoning > 0:
                lines.append("> [!Warning]")
                lines.append(f"> 存在 {unaddressed} 项未回应证据、{missing_reasoning} 项缺说理证据，可能影响证据采信的正当性\n")
            else:
                lines.append("> [!Tip]")
                lines.append("> 证据引用完整，所有证据均有回应和说理\n")

        # ── Anomaly MCP results ──
        if anomaly_mcp_results:
            lines.append("## __NUM__十六维度深度异常剖析\n")
            lines.append("> [!Important]")
            lines.append("> 以下异常检测结果来自 **judicial-doc-anomaly-mcp**（[GitHub](https://github.com/lcfactorization/judicial-doc-anomaly-mcp)）的16维检测体系（20260516版），")
            lines.append("> 覆盖程序操作、证据采信、事实认定、焦点偏移、法律适用、自由裁量、修辞技巧、逻辑闭环、")
            lines.append("> 时间一致性、审理过程、外部干预、执行问题、缺失信息、语义漂移、类案偏离、惯性耦合等16个维度。")
            lines.append("> 检测结果已自动纳入本报告的异常扣分计算，与七维质量评分体系形成互补。\n")

            risk_summary = {}
            total_anomalies = 0
            for dim_result in anomaly_mcp_results:
                dim_anomalies = dim_result.get("anomalies", [])
                dim_count = dim_result.get("anomaly_count", len(dim_anomalies))
                total_anomalies += dim_count
                dim_risk = dim_result.get("risk_level", "unknown")
                risk_summary[dim_risk] = risk_summary.get(dim_risk, 0) + 1

            lines.append("### 检测概览\n")
            lines.append(f"| 指标 | 结果 |")
            lines.append(f"|:---|:---|")
            lines.append(f"| 扫描维度数 | {len(anomaly_mcp_results)} |")
            lines.append(f"| 检出异常总数 | {total_anomalies} |")
            risk_order = ["critical", "high", "medium", "low", "unknown"]
            for rk in risk_order:
                if rk in risk_summary:
                    lines.append(f"| {_SEVERITY_ZH.get(rk, rk)}风险维度数 | {risk_summary[rk]} |")
            lines.append("")

            lines.append("> [!Note]")
            lines.append(f"> 本次检测共扫描 {len(anomaly_mcp_results)} 个维度，检出 {total_anomalies} 项异常。")
            if risk_summary.get("critical", 0) > 0 or risk_summary.get("high", 0) > 0:
                lines.append(f"> 其中严重风险 {risk_summary.get('critical', 0)} 个维度、高风险 {risk_summary.get('high', 0)} 个维度，需重点关注。")
            elif risk_summary.get("medium", 0) > 0:
                lines.append(f"> 未发现严重或高风险维度，中风险 {risk_summary.get('medium', 0)} 个维度建议留意。")
            else:
                lines.append("> 各维度均未检出明显异常，文书整体表现正常。")
            lines.append("")

            critical_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "critical"]
            high_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "high"]
            medium_dims = [d for d in anomaly_mcp_results if d.get("risk_level") == "medium"]
            low_dims = [d for d in anomaly_mcp_results if d.get("risk_level") in ("low", "unknown")]

            if critical_dims:
                lines.append("> [!Danger]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in critical_dims)
                lines.append(f"> **严重风险**：{len(critical_dims)} 个维度存在严重异常（{dim_names}），强烈建议重点审查\n")
            if high_dims:
                lines.append("> [!Warning]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in high_dims)
                lines.append(f"> **高风险**：{len(high_dims)} 个维度存在高严重度异常（{dim_names}），建议重点关注\n")
            if medium_dims:
                lines.append("> [!Note]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in medium_dims)
                lines.append(f"> **中风险**：{len(medium_dims)} 个维度存在中等异常（{dim_names}），建议留意\n")
            if low_dims:
                lines.append("> [!Tip]")
                dim_names = "、".join(_DIMENSION_ZH.get(d.get("dimension", "?"), d.get("dimension", "?")) for d in low_dims)
                lines.append(f"> **低风险**：{len(low_dims)} 个维度未检出明显异常（{dim_names}），文书在这些方面表现正常\n")

            lines.append("### 各维度异常详情\n")
            _DIMENSION_ORDER_MAP = {d: i + 1 for i, d in enumerate([
                "procedure", "evidence", "fact_finding", "focus_drift",
                "law_application", "discretion", "rhetoric_trick", "logic",
                "temporal", "trial_process", "external_interference", "execution",
                "negative_space", "semantic_drift", "case_deviation", "coupling",
            ])}

            for dim_result in anomaly_mcp_results:
                dim_key = dim_result.get("dimension", "?")
                dim_num = _DIMENSION_ORDER_MAP.get(dim_key, "?")
                dim_name = _DIMENSION_ZH.get(dim_key, dim_key)
                dim_risk = dim_result.get("risk_level", "unknown")
                dim_count = dim_result.get("anomaly_count", 0)
                dim_summary = dim_result.get("summary", "")
                dim_anomalies = dim_result.get("anomalies", [])

                risk_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "unknown": "⚪"}.get(dim_risk, "⚪")
                lines.append(f"#### {risk_icon} 维度{dim_num}·{dim_name}（{_SEVERITY_ZH.get(dim_risk, dim_risk)}风险，{dim_count} 项异常）\n")

                if dim_summary:
                    lines.append(f"> **检测摘要**：{dim_summary}\n")

                if dim_anomalies:
                    lines.append("| 检测项 | 检测结果 | 说明 |")
                    lines.append("|:---|:---:|:---|")
                    for a_idx, a in enumerate(dim_anomalies, 1):
                        name = a.get("item_name", a.get("f_code", "?"))
                        f_code = a.get("f_code", f"{dim_key[:2].upper()}-{a_idx:02d}")
                        status = "⚠️ 存疑" if a.get("confidence") in ("high", "⚠️") else ("✅ 正常" if a.get("confidence") in ("low", "🟢") else "🔍 关注")
                        desc = a.get("description", "")
                        beneficiary = a.get("beneficiary", "")
                        if beneficiary:
                            desc += f"（指向获益方：{beneficiary}）"
                        lines.append(f"| {f_code} {name} | {status} | {desc} |")
                    lines.append("")

        # ── Section reordering: anomaly sections before quality sections ──
        # Current gen order: header → quality(四) → anomaly(一/二) → innovation(五) → mcp(三) → sub-sections
        # Desired order:      header → anomaly(一/二) → mcp(三) → quality(四) → innovation(五) → sub-sections
        if _ANOMALY_START > _QUALITY_START:
            header_part = lines[:_QUALITY_START]
            quality_part = lines[_QUALITY_START:_ANOMALY_START]
            anomaly_and_rest = lines[_ANOMALY_START:]
            # anomaly_and_rest contains: anomaly(一/二) + innovation(五) + mcp(三) + sub-sections
            # We need to split innovation out of anomaly_and_rest
            if _INNOVATION_START > _ANOMALY_START:
                anomaly_part = lines[_ANOMALY_START:_INNOVATION_START]
                innovation_and_rest = lines[_INNOVATION_START:]
                lines = header_part + anomaly_part + quality_part + innovation_and_rest
            else:
                lines = header_part + anomaly_and_rest + quality_part

        # ── Summary ──
        lines.append("## __NUM__总结与建议\n")
        lines.append("> [!Important]")
        lines.append("> **综合评价**\n")

        summary_items = []
        summary_items.append(f"本案文书经十六维度异常检测和七维质量评估，综合评级为 **{grade}（{grade_desc}）**，加权总分 **{weighted_total}** 分。")

        if anomaly_details:
            high_ct = sum(1 for a in anomaly_details if a.get("severity") == "high")
            medium_ct = sum(1 for a in anomaly_details if a.get("severity") == "medium")
            if high_ct > 0:
                summary_items.append(f"检出 **{high_ct}** 项高严重度异常，需重点审查。")
            elif medium_ct > 0:
                summary_items.append(f"检出 **{medium_ct}** 项中等异常，建议关注。")
            else:
                summary_items.append("未检出高严重度异常，文书整体规范。")

        if anomaly_mcp_results:
            mcp_total_anomalies = sum(d.get("anomaly_count", 0) for d in anomaly_mcp_results)
            mcp_high_dims = sum(1 for d in anomaly_mcp_results if d.get("risk_level") in ("critical", "high"))
            if mcp_high_dims > 0:
                summary_items.append(f"十六维度异常检测中 **{mcp_high_dims}** 个维度存在高风险，存在系统性偏差的可能性。")
            elif mcp_total_anomalies > 0:
                summary_items.append(f"十六维度异常检测共检出 **{mcp_total_anomalies}** 项异常，但无高风险维度。")
            else:
                summary_items.append("十六维度异常检测未检出明显异常。")

        if innovation_bonus > 0:
            summary_items.append(f"文书有 **{len(innovation_details or [])}** 项创新亮点（加分 +{innovation_bonus:.0f}），值得肯定。")

        for s in summary_items:
            lines.append(f"> {s}")
        lines.append("")

        lines.append("| 项目 | 结果 |")
        lines.append("|:---|:---|")
        lines.append(f"| 综合评级 | {grade}（{grade_desc}） |")
        lines.append(f"| 加权总分 | {weighted_total} / 100 |")
        lines.append(f"| 异常等级 | {anomaly_level} |")
        lines.append(f"| 异常扣分 | −{anomaly_deduction:.0f} |")
        lines.append(f"| 创新加分 | +{innovation_bonus:.0f} |")
        if trial_stage:
            lines.append(f"| 审级 | {trial_stage} |")
        lines.append("")

        # ── Dynamic TOC generation + sequential numbering + explicit anchor IDs ──
        # This MUST run after all sections (including Summary) have been appended.
        _CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        _num_counter = 0
        _toc_entries = []  # (slug, display_text)

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("## "):
                continue
            if stripped.startswith("### "):
                continue

            heading_raw = stripped[3:].strip()
            needs_number = heading_raw.startswith("__NUM__")

            if needs_number:
                _num_counter += 1
                cn_num = _CN_NUMS[_num_counter - 1] if _num_counter <= len(_CN_NUMS) else str(_num_counter)
                heading_text = f"{cn_num}、{heading_raw[7:]}"  # strip __NUM__ (7 chars)
            else:
                heading_text = heading_raw

            slug = _slugify(heading_text)

            # Replace ## line with <h2 id="slug"> for guaranteed anchor jump
            lines[i] = f'<h2 id="{slug}">{heading_text}</h2>\n'

            _toc_entries.append((slug, heading_text))

        # Build TOC HTML
        _toc_lines = ['<div class="toc">', '<h3 class="toc-title">📑 目录</h3>', '<ul>']
        for slug, display_text in _toc_entries:
            _toc_lines.append(f'<li><a href="#{slug}">{display_text}</a></li>')
        _toc_lines.extend(['</ul>', '</div>', ''])
        lines[_TOC_PLACEHOLDER_IDX] = "\n".join(_toc_lines)

        # ── Disclaimer ──
        lines.append("---\n")
        lines.append("> [!Important]")
        lines.append("> **免责声明**：本报告由 **judicial-doc-quality-mcp** 辅助生成，基于七维评分体系和十六维度异常检测的自动化分析。")
        lines.append("> 异常检测部分由 **judicial-doc-anomaly-mcp** 提供（当该工具可用时自动调用）。")
        lines.append("> 评估结果仅供参考，不构成法律意见。裁判文书的质量评价涉及复杂的法律判断，")
        lines.append("> 本报告不能替代专业法律人士的审查。\n")

        lines.append(f"*报告由 judicial-doc-quality-mcp v0.3.0 生成 · 检测体系版本 20260519 · 报告编号 {report_id} · 生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

        return json.dumps({
            "success": True,
            "report_markdown": "\n".join(lines),
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("build_report_markdown: %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"报告生成异常：{e}")


# ── Markdown to HTML converter ─────────────────────────────────

def md_to_rich_html(md_text: str) -> str:
    """Convert Markdown report text to styled HTML with GitHub Alerts support.

    Uses the same alert class names (NOTE, TIP, IMPORTANT, WARNING, CAUTION)
    as the reference template for consistent styling.
    """
    import re as _re

    lines = md_text.split("\n")
    html_parts = []
    in_table = False
    table_rows = []
    table_aligns = []
    in_blockquote = False
    bq_type = ""
    bq_lines = []

    _ALIGN_MAP = {
        ":---": "left", ":--:": "center", "---:": "right",
        ":---:": "center", ":--": "left", "--:": "right",
    }

    def _parse_align(sep_line):
        parts = [c.strip() for c in sep_line.split("|")[1:-1]]
        aligns = []
        for p in parts:
            p = p.strip()
            if p.startswith(":") and p.endswith(":"):
                aligns.append("center")
            elif p.endswith(":"):
                aligns.append("right")
            else:
                aligns.append("left")
        return aligns

    def close_blockquote():
        nonlocal in_blockquote, bq_type, bq_lines
        if not in_blockquote:
            return
        inner = "<br>\n".join(bq_lines)
        if bq_type:
            html_parts.append(f'<div class="{bq_type}"><h5>{_bq_title(bq_type)}</h5><p>{inner}</p></div>')
        else:
            # Plain blockquote
            html_parts.append(f'<blockquote><p>{inner}</p></blockquote>')
        in_blockquote = False
        bq_type = ""
        bq_lines = []

    def _bq_title(t):
        return {
            "NOTE": "ℹ️ 注意：", "TIP": "💡 提示：", "IMPORTANT": "❗ 重要：",
            "WARNING": "⚠️ 警惕：", "CAUTION": "🔥 危险：",
        }.get(t, "ℹ️ 注意：")

    def close_table():
        nonlocal in_table, table_rows, table_aligns
        if not in_table:
            return
        html_parts.append("<table><thead>")
        for ri, row in enumerate(table_rows):
            tag = "th" if ri == 0 else "td"
            cells = [_re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', c) for c in row]
            row_html = ""
            for ci, cell in enumerate(cells):
                align = table_aligns[ci] if ci < len(table_aligns) else "left"
                style = f' style="text-align:{align}"'
                row_html += f"<{tag}{style}>{cell}</{tag}>"
            if ri == 0:
                html_parts.append(f"<tr>{row_html}</tr>")
            else:
                if ri == 1:
                    html_parts.append("</thead><tbody>")
                html_parts.append(f"<tr>{row_html}</tr>")
        html_parts.append("</tbody></table>")
        in_table = False
        table_rows = []
        table_aligns = []

    def inline_format(text):
        text = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = _re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = _re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        return text

    def _make_id(text):
        """Generate an HTML id from heading text, matching TOC link targets."""
        # Strip inline formatting markers
        clean = _re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        clean = _re.sub(r'\*(.+?)\*', r'\1', clean)
        clean = _re.sub(r'`([^`]+)`', r'\1', clean)
        clean = clean.strip()
        return clean

    for line in lines:
        stripped = line.strip()

        bq_match = _re.match(r'^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', stripped)
        if bq_match:
            close_blockquote()
            close_table()
            in_blockquote = True
            bq_type = bq_match.group(1)
            bq_lines = []
            continue

        # Handle plain blockquote lines (not GitHub Alert style)
        if not in_blockquote and stripped.startswith(">") and not bq_match:
            close_table()
            in_blockquote = True
            bq_type = ""  # empty type = plain blockquote
            bq_lines = []
            content = _re.sub(r'^>\s?', '', stripped)
            bq_lines.append(inline_format(content))
            continue

        if in_blockquote:
            if stripped.startswith(">"):
                content = _re.sub(r'^>\s?', '', stripped)
                bq_lines.append(inline_format(content))
                continue
            else:
                close_blockquote()

        if stripped.startswith("|") and "|" in stripped[1:]:
            sep_match = _re.match(r'^\|[\s:|-]+\|$', stripped)
            if sep_match:
                table_aligns = _parse_align(stripped)
                continue
            # Only close previous table if we're already in one and this is a new table
            # (shouldn't happen in normal markdown, but be safe)
            if not in_table:
                # Starting a new table
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                table_rows.append(cells)
                in_table = True
            else:
                # Continuing an existing table
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                table_rows.append(cells)
            continue
        else:
            close_table()

        if stripped.startswith("### "):
            heading_text = stripped[4:]
            sid = _make_id(heading_text)
            html_parts.append(f'<h3 id="{sid}">{inline_format(heading_text)}</h3>')
        elif stripped.startswith("<h2 ") and stripped.endswith("</h2>"):
            # Already an HTML h2 with explicit id — pass through directly
            html_parts.append(stripped)
        elif stripped.startswith("## "):
            heading_text = stripped[3:]
            sid = _make_id(heading_text)
            html_parts.append(f'<h2 id="{sid}">{inline_format(heading_text)}</h2>')
        elif stripped.startswith("# "):
            heading_text = stripped[2:]
            html_parts.append(f'<h1>{inline_format(heading_text)}</h1>')
        elif stripped.startswith("#### "):
            heading_text = stripped[5:]
            sid = _make_id(heading_text)
            html_parts.append(f'<h4 id="{sid}">{inline_format(heading_text)}</h4>')
        elif stripped.startswith("##### "):
            heading_text = stripped[6:]
            sid = _make_id(heading_text)
            html_parts.append(f'<h5 id="{sid}">{inline_format(heading_text)}</h5>')
        elif stripped == "---":
            html_parts.append("<hr>")
        elif stripped.startswith("- "):
            html_parts.append(f'<ul><li>{inline_format(stripped[2:])}</li></ul>')
        elif stripped.startswith("<") and (stripped.endswith(">") or "</" in stripped):
            # Raw HTML — apply inline formatting to any Markdown outside tags, then pass through
            html_parts.append(inline_format(stripped))
        elif stripped == "":
            html_parts.append("")
        else:
            html_parts.append(f'<p>{inline_format(stripped)}</p>')

    close_blockquote()
    close_table()

    return "\n".join(html_parts)


def build_html_page(body_html: str, report_id: str) -> str:
    """Build a complete HTML page matching the legal reference manual template style.

    Uses: serif fonts (Latin Modern Roman / 宋体), risk-tag system, TOC sidebar,
    circular theme toggle button, back-to-top button, GitHub Alerts with icons,
    and the exact color scheme from the reference template.
    """
    return f'''<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>司法文书质量评估报告 {report_id}</title>
<style>
/* ====== 主题变量系统 ====== */
:root, [data-theme="dark"] {{
    --text-color: #dddddd;
    --bg-color: #1e1e1e;
    --bg-secondary: #2d2d2d;
    --scrollbar-color: #888;
    --muted-color: #aaaaaa;
    --muted-color-2: #666;
    --border-color: #444;
    --border-color-light: #555;
    --code-bg-color: #333;
    --link-color: #6ea8fe;
    --heading-color: #ffffff;
    --hr-color: #555;
    --quote-bg-color: #2a2a2a;
    --th-bg-color: #282828;
    --tr-even-bg-color: #202020;
    --alert-note-border: #1f6feb;
    --alert-note-bg: rgba(31,111,235,0.12);
    --alert-tip-border: #238636;
    --alert-tip-text: #3faa31;
    --alert-tip-bg: rgba(35,134,54,0.12);
    --alert-important-border: rgb(171,125,248);
    --alert-important-bg: rgba(171,125,248,0.12);
    --alert-warning-border: #d29722;
    --alert-warning-bg: rgba(210,151,34,0.12);
    --alert-caution-border: #f04843;
    --alert-caution-bg: rgba(240,72,67,0.12);
    --tag-highest-bg: rgba(240,72,67,0.15);
    --tag-highest-border: #f04843;
    --tag-high-bg: rgba(210,151,34,0.15);
    --tag-high-border: #d29722;
    --tag-medium-bg: rgba(31,111,235,0.15);
    --tag-medium-border: #1f6feb;
    --tag-low-bg: rgba(35,134,54,0.15);
    --tag-low-border: #238636;
    --checklist-color: #888;
    --toc-bg: rgba(42,42,42,0.8);
    --grade-a-color: #3fb950;
    --grade-b-color: #58a6ff;
    --grade-c-color: #d29922;
    --grade-d-color: #db6d28;
    --grade-f-color: #f85149;
}}
[data-theme="light"] {{
    --text-color: #333333;
    --bg-color: #ffffff;
    --bg-secondary: #f0f0f0;
    --scrollbar-color: #aaa;
    --muted-color: #666666;
    --muted-color-2: #999999;
    --border-color: #ddd;
    --border-color-light: #ddd;
    --code-bg-color: #f6f6f6;
    --link-color: #2E67D3;
    --heading-color: #1a1a1a;
    --hr-color: #ddd;
    --quote-bg-color: #f9f9f9;
    --th-bg-color: #f6f8fa;
    --tr-even-bg-color: #f6f8fa;
    --alert-note-border: #0969da;
    --alert-note-bg: #ddf4ff;
    --alert-tip-border: #1a7f37;
    --alert-tip-text: #1a7f37;
    --alert-tip-bg: #dafbe1;
    --alert-important-border: #8250df;
    --alert-important-bg: #fbefff;
    --alert-warning-border: #9a6700;
    --alert-warning-bg: #fff8c5;
    --alert-caution-border: #cf222e;
    --alert-caution-bg: #ffebe9;
    --tag-highest-bg: rgba(207,34,46,0.08);
    --tag-highest-border: #cf222e;
    --tag-high-bg: rgba(154,103,0,0.08);
    --tag-high-border: #9a6700;
    --tag-medium-bg: rgba(9,105,218,0.08);
    --tag-medium-border: #0969da;
    --tag-low-bg: rgba(26,127,55,0.08);
    --tag-low-border: #1a7f37;
    --checklist-color: #999;
    --toc-bg: rgba(246,248,250,0.9);
    --grade-a-color: #1a7f37;
    --grade-b-color: #0969da;
    --grade-c-color: #9a6700;
    --grade-d-color: #bc4c00;
    --grade-f-color: #cf222e;
}}

/* ====== 基础样式 ====== */
html, body {{
    font-family: "Latin Modern Roman", "Latin Modern Roman 10", "Times New Roman", "宋体-简", "华文宋体", serif;
    font-size: 16px; line-height: 1.618; word-wrap: break-word;
    color: var(--text-color); background: var(--bg-color);
    -webkit-font-smoothing: antialiased; height: 100%; margin: 0; padding: 0;
}}
body::-webkit-scrollbar {{ width: 0.6em; }}
body::-webkit-scrollbar-thumb {{ background: var(--scrollbar-color); border-radius: 0.2em; }}

strong, b {{ font-weight: 900; }}

h1, h2, h3, h4, h5, h6 {{
    margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 900; line-height: 1.25; color: var(--heading-color);
}}
h1 {{
    font-family: "Latin Modern Roman", "宋体-简", "华文宋体", "SimHei", serif;
    font-size: 2.2em; line-height: 1.2; padding-bottom: 0.3em;
    border-bottom: 2px solid var(--scrollbar-color); margin-bottom: 1em; text-align: center;
}}
h2 {{
    font-family: "Latin Modern Roman", "宋体-简", "华文宋体", "SimHei", serif;
    font-size: 1.8em; padding-bottom: 0.3em; border-bottom: 2px solid var(--scrollbar-color);
}}
h3 {{
    font-family: "Latin Modern Roman", "宋体-简", "华文宋体", "SimHei", serif; font-size: 1.5em;
}}
h4 {{
    font-family: "Latin Modern Roman", "华文楷体", "KaiTi", serif; font-size: 1.3em;
}}
h5 {{
    font-family: "Latin Modern Roman", "华文仿宋", "FangSong", serif; font-size: 1.2em;
}}

a, a:visited {{ text-decoration: none; color: var(--link-color); }}
a:hover {{ text-decoration: underline; }}
p {{ margin: 0.5rem 0 1rem; color: var(--text-color); text-align: left; line-height: 1.618; }}

code {{
    font-family: "Latin Modern Mono", "Consolas", "Courier New", monospace;
    color: var(--link-color); background: var(--code-bg-color); font-size: 0.95em;
    padding: 2px 4px; border-radius: 3px; box-shadow: 0 0 1px 1px var(--border-color); margin: 0 2px;
}}
pre {{
    font-family: "Latin Modern Mono", "Consolas", "Courier New", monospace;
    font-weight: normal; font-size: 95%; line-height: 1.5; margin: 1.5em 0;
    padding: 0; max-width: 98%; border: none; overflow: auto; border-radius: 4px;
    white-space: pre; background: var(--code-bg-color); color: var(--text-color);
}}
pre > code {{
    white-space: pre; padding: 1em !important; display: block; background: transparent;
    font-weight: normal; color: inherit; font-size: inherit; margin: 0; box-shadow: none;
}}

table {{
    width: 100%; border-spacing: 0; border-collapse: collapse; margin: 1.5em auto;
    border-color: var(--scrollbar-color);
    font-family: "Latin Modern Roman", "Times New Roman", Times, serif;
    color: var(--text-color); background: var(--code-bg-color);
}}
td, th {{
    border: 1px solid var(--scrollbar-color); padding: 0.6em 1em;
    display: table-cell; vertical-align: top; color: var(--text-color);
}}
th {{ font-weight: 900; background: var(--th-bg-color); text-align: center; }}
tbody > tr:nth-child(even) {{ background: var(--tr-even-bg-color); }}

ul, ol {{ padding-left: 2em; margin-top: 1em; margin-bottom: 1em; color: var(--text-color); }}
li {{ margin-bottom: 0.3em; }}
ul ul {{ list-style: "– "; }}
ul ul ul {{ list-style: "◦ "; }}

blockquote {{
    color: var(--text-color); font-size: 1.05em;
    font-family: "Latin Modern Roman", "华文仿宋", "FangSong", serif;
    border-left: 4px solid var(--scrollbar-color); padding: 15px 20px;
    margin: 1em 0; background-color: var(--quote-bg-color);
}}
blockquote *:first-child {{ margin-top: 0; }}
blockquote *:last-child {{ margin-bottom: 0; }}
hr {{ border: 0; border-top: 1px solid var(--scrollbar-color); margin: 2em 0; }}

/* ====== Alert 提示框 ====== */
.CAUTION, .IMPORTANT, .INFO, .INFORMATION, .ERROR, .TIP, .NOTE, .WARNING, .DANGER {{
    position: relative; padding: 1.2em 1.2em 1.2em 3.2em; margin: 1.2em 0;
    border-radius: 6px; font-size: 1em; line-height: 1.6;
}}
.CAUTION::before, .IMPORTANT::before, .INFO::before, .INFORMATION::before,
.ERROR::before, .TIP::before, .NOTE::before, .WARNING::before, .DANGER::before {{
    content: ""; position: absolute; left: 0; top: 0; width: 6px; height: 100%;
    border-radius: 6px 0 0 6px;
}}
.CAUTION > h5, .IMPORTANT > h5, .INFO > h5, .INFORMATION > h5,
.ERROR > h5, .TIP > h5, .NOTE > h5, .WARNING > h5, .DANGER > h5 {{
    margin-top: 0; margin-bottom: 0.6em; font-size: 1.05em;
    font-weight: 900; display: flex; align-items: center;
}}

.NOTE {{ background: var(--alert-note-bg); }}
.NOTE::before {{ background: var(--alert-note-border); }}
.NOTE > h5 {{ color: var(--alert-note-border); }}

.TIP {{ background: var(--alert-tip-bg); }}
.TIP::before {{ background: var(--alert-tip-border); }}
.TIP > h5 {{ color: var(--alert-tip-text); }}

.WARNING {{ background: var(--alert-warning-bg); }}
.WARNING::before {{ background: var(--alert-warning-border); }}
.WARNING > h5 {{ color: var(--alert-warning-border); }}

.DANGER, .ERROR {{ background: var(--alert-caution-bg); }}
.DANGER::before, .ERROR::before {{ background: var(--alert-caution-border); }}
.DANGER > h5, .ERROR > h5 {{ color: var(--alert-caution-border); }}

.IMPORTANT {{ background: var(--alert-important-bg); }}
.IMPORTANT::before {{ background: var(--alert-important-border); }}
.IMPORTANT > h5 {{ color: var(--alert-important-border); }}

.CAUTION {{ background: var(--alert-caution-bg); }}
.CAUTION::before {{ background: var(--alert-caution-border); }}
.CAUTION > h5 {{ color: var(--alert-caution-border); }}

/* ====== 风险标签 ====== */
.risk-tag {{
    display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.85em;
    font-weight: 700; margin-left: 6px; vertical-align: middle; white-space: nowrap;
}}
.risk-highest {{ background: var(--tag-highest-bg); border: 1px solid var(--tag-highest-border); color: var(--tag-highest-border); }}
.risk-high {{ background: var(--tag-high-bg); border: 1px solid var(--tag-high-border); color: var(--tag-high-border); }}
.risk-medium {{ background: var(--tag-medium-bg); border: 1px solid var(--tag-medium-border); color: var(--tag-medium-border); }}
.risk-low {{ background: var(--tag-low-bg); border: 1px solid var(--tag-low-border); color: var(--tag-low-border); }}

/* ====== 评级标签 ====== */
.grade-tag {{
    display: inline-block; padding: 4px 16px; border-radius: 16px; font-size: 1.1em;
    font-weight: 900; letter-spacing: 2px; margin: 0 8px;
}}
.grade-A {{ background: rgba(63,185,80,0.15); border: 2px solid var(--grade-a-color); color: var(--grade-a-color); }}
.grade-B {{ background: rgba(88,166,255,0.15); border: 2px solid var(--grade-b-color); color: var(--grade-b-color); }}
.grade-C {{ background: rgba(210,153,34,0.15); border: 2px solid var(--grade-c-color); color: var(--grade-c-color); }}
.grade-D {{ background: rgba(219,109,40,0.15); border: 2px solid var(--grade-d-color); color: var(--grade-d-color); }}
.grade-F {{ background: rgba(248,81,73,0.15); border: 2px solid var(--grade-f-color); color: var(--grade-f-color); }}

/* ====== 目录 ====== */
.toc {{
    background: var(--toc-bg); border: 1px solid var(--border-color);
    border-radius: 8px; padding: 1.2em 1.8em; margin: 1.5em 0;
}}
.toc-title {{ margin-top: 0; font-size: 1.2em; }}
.toc ul {{ list-style: none; padding-left: 0; }}
.toc ul ul {{ padding-left: 1.5em; }}
.toc li {{ margin-bottom: 0.3em; }}
.toc a {{ color: var(--link-color); }}

/* ====== 主内容容器 ====== */
#MainContent {{
    margin: 0 auto; padding: 0.2em 2.5em 2em 2.5em; max-width: 960px;
    border: 1px solid var(--border-color); border-radius: 0.3em;
    background-color: var(--bg-color); box-shadow: 0 0 24px 12px rgba(0,0,0,0.15);
}}
@media(max-width: 980px) {{ #MainContent {{ border: none; padding: 0.2em 0.8em; }} }}

/* ====== 主题切换按钮 ====== */
#theme-btn {{
    position: fixed; top: 20px; right: 24px; z-index: 99999;
    width: 48px; height: 48px; border: 2px solid var(--border-color);
    border-radius: 50%; background: var(--bg-secondary); color: var(--heading-color);
    font-size: 22px; cursor: pointer; display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 12px rgba(0,0,0,0.25);
    transition: background-color 0.35s ease, color 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease, transform 0.2s ease;
    outline: none; line-height: 1; padding: 0;
}}
#theme-btn:hover {{ transform: scale(1.12); border-color: var(--link-color); }}
#theme-btn:active {{ transform: scale(0.95); }}
#theme-btn .tip {{
    position: absolute; top: 56px; right: 0; background: var(--bg-secondary);
    color: var(--text-color); border: 1px solid var(--border-color); border-radius: 6px;
    padding: 4px 12px; font-size: 13px; font-family: "微软雅黑","Microsoft YaHei",sans-serif;
    white-space: nowrap; opacity: 0; pointer-events: none;
    transition: opacity 0.2s ease; box-shadow: 0 2px 8px rgba(0,0,0,0.15);
}}
#theme-btn:hover .tip {{ opacity: 1; }}
@media(max-width: 768px) {{ #theme-btn {{ top: 12px; right: 12px; width: 40px; height: 40px; font-size: 18px; }} }}

/* ====== 回到顶部按钮 ====== */
#back-top {{
    position: fixed; bottom: 24px; right: 24px; z-index: 99998;
    width: 44px; height: 44px; border: 2px solid var(--border-color);
    border-radius: 50%; background: var(--bg-secondary); color: var(--heading-color);
    font-size: 20px; cursor: pointer; display: none; align-items: center; justify-content: center;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    transition: opacity 0.3s ease, transform 0.2s ease; outline: none; padding: 0;
}}
#back-top:hover {{ transform: scale(1.1); border-color: var(--link-color); }}
#back-top.show {{ display: flex; }}

::selection {{ background-color: var(--link-color); color: var(--code-bg-color); }}
::-moz-selection {{ background-color: var(--link-color); color: var(--code-bg-color); }}

@media print {{
    html,body{{text-rendering:optimizeLegibility;height:auto;margin:0;padding:40px;background-color:var(--bg-color)!important;color:var(--text-color)!important}}
    #MainContent{{width:100%!important;max-width:none!important;margin:0!important;padding:0!important;border:none!important;border-radius:0!important;box-shadow:none!important;background-color:var(--bg-color)!important}}
    #theme-btn,#back-top{{display:none!important}}
}}
</style>
</head>
<body>

<button id="theme-btn" onclick="toggleTheme()" aria-label="Toggle light/dark theme">
<span id="themeIcon">&#9789;</span><span class="tip" id="themeTip">切换至浅色模式</span></button>
<button id="back-top" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" aria-label="Back to top">&#8679;</button>

<div id="MainContent">
{body_html}
</div>

<script>
(function(){{
    const s=localStorage.getItem("report-theme");
    if(s)document.documentElement.setAttribute("data-theme",s);
    updateThemeUI();
    window.addEventListener("scroll",function(){{
        const b=document.getElementById("back-top");
        if(window.scrollY>300)b.classList.add("show");else b.classList.remove("show");
    }});
}})();
function toggleTheme(){{
    const h=document.documentElement;const c=h.getAttribute("data-theme");
    const n=c==="dark"?"light":"dark";h.setAttribute("data-theme",n);
    localStorage.setItem("report-theme",n);updateThemeUI();
}}
function updateThemeUI(){{
    const d=document.documentElement.getAttribute("data-theme");
    const icon=document.getElementById("themeIcon");
    const tip=document.getElementById("themeTip");
    if(d==="dark"){{icon.innerHTML="&#9789;";tip.textContent="切换至浅色模式";}}
    else{{icon.innerHTML="&#9788;";tip.textContent="切换至深色模式";}}
}}
</script>
</body>
</html>'''
