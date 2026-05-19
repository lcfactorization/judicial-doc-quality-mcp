"""Skill Loader & Template Renderer v0.2.0 — loads Skill .md files, renders templates.

Bridge Architecture: NO LLM calls.
This module only provides SkillLoader (file I/O) and TemplateRenderer (variable substitution).
LLM calling is the Agent's responsibility.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import (
    ANCHORS_DIR,
    DIMENSION_ORDER,
    DIMENSION_TITLES,
    QUALITY_WEIGHTS,
    SKILLS_DIR,
)

logger = logging.getLogger(__name__)


@dataclass
class SkillMeta:
    name: str = ""
    title: str = ""
    type: str = ""
    layer: str = ""
    order: int = 0
    weight: float = 0.0
    full_score: int = 100
    output_format: str = ""


class SkillLoader:
    """Load and parse Skill .md files from the skills/ directory."""

    SYSTEM_SKILLS = ["_system", "_output_format", "_taxonomy", "_neutrality"]

    def __init__(self, skills_dir: Path | str | None = None, anchors_dir: Path | str | None = None):
        self.skills_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
        self.anchors_dir = Path(anchors_dir) if anchors_dir else ANCHORS_DIR
        self._cache: dict[str, tuple[SkillMeta, str]] = {}

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        fm = {}
        body = content
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if m:
            for line in m.group(1).strip().split("\n"):
                if ":" in line:
                    key, _, val = line.partition(":")
                    val = val.strip().strip('"').strip("'")
                    if val.startswith("[") and val.endswith("]"):
                        val = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
                    fm[key.strip()] = val
            body = m.group(2)
        return fm, body

    def load(self, skill_name: str) -> tuple[SkillMeta, str]:
        if skill_name in self._cache:
            return self._cache[skill_name]

        parts = skill_name.split("/")
        skill_path = self.skills_dir / Path(*parts)

        if skill_path.is_dir():
            skill_path = skill_path / "skill.md"
        if not skill_path.suffix:
            skill_path = skill_path.with_suffix(".md")

        if not skill_path.exists():
            alt = self._find_by_name(skill_name)
            if alt:
                skill_path = alt
            else:
                raise FileNotFoundError(f"Skill not found: {skill_name} (looked at {skill_path})")

        logger.info("load: skill=%s, path=%s", skill_name, skill_path)
        content = skill_path.read_text(encoding="utf-8")
        fm, body = self._parse_frontmatter(content)

        dim_name = fm.get("name", skill_name)
        meta = SkillMeta(
            name=dim_name,
            title=fm.get("title", DIMENSION_TITLES.get(dim_name, "")),
            type=fm.get("type", ""),
            layer=fm.get("layer", ""),
            order=int(fm.get("order", DIMENSION_ORDER.get(dim_name, 0))),
            weight=float(fm.get("weight", QUALITY_WEIGHTS.get(dim_name, 0.0))),
            full_score=int(fm.get("full_score", 100)),
            output_format=fm.get("output_format", ""),
        )

        self._cache[skill_name] = (meta, body)
        return meta, body

    def _find_by_name(self, skill_name: str) -> Path | None:
        base_name = skill_name.split("/")[-1]
        parent_parts = skill_name.split("/")[:-1]
        search_dir = self.skills_dir
        for p in parent_parts:
            search_dir = search_dir / p
        if not search_dir.is_dir():
            return None
        for md_file in search_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_frontmatter(content)
                if fm.get("name") == base_name:
                    logger.info("_find_by_name: matched %s -> %s", skill_name, md_file)
                    return md_file
            except Exception:
                continue
        return None

    def load_system_skill(self, name: str) -> str:
        if not name.startswith("_"):
            name = f"_{name}"
        path = self.skills_dir / f"{name}.md"
        if not path.exists():
            logger.warning("load_system_skill: not found name=%s", name)
            return ""
        _, body = self._parse_frontmatter(path.read_text(encoding="utf-8"))
        return body

    def load_anchors(self, dimension: str) -> list[dict]:
        anchor_file = self.anchors_dir / f"{dimension}_examples.json"
        if not anchor_file.exists():
            short = dimension.replace("thorough_", "").replace("substantive_", "")
            alt_file = self.anchors_dir / f"{short}_examples.json"
            if alt_file.exists():
                anchor_file = alt_file
            else:
                for f in self.anchors_dir.glob("*_examples.json"):
                    stem = f.stem.replace("_examples", "")
                    if stem in dimension or dimension in stem:
                        anchor_file = f
                        break
                else:
                    logger.warning("load_anchors: not found dimension=%s", dimension)
                    return []
        try:
            content = anchor_file.read_text(encoding="utf-8")
            return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
            logger.error("load_anchors: parse error dimension=%s, error=%s", dimension, e)
            return []

    def list_dimensions(self) -> list[dict]:
        results = []
        dims_dir = self.skills_dir / "dimensions"
        if not dims_dir.exists():
            return results
        for md_file in sorted(dims_dir.glob("*.md")):
            skill_name = f"dimensions/{md_file.stem}"
            try:
                meta, _ = self.load(skill_name)
                results.append({
                    "name": meta.name,
                    "title": meta.title,
                    "type": meta.type,
                    "layer": meta.layer,
                    "order": meta.order,
                    "weight": meta.weight,
                    "full_score": meta.full_score,
                    "output_format": meta.output_format,
                })
            except Exception as e:
                logger.warning("list_dimensions: failed %s: %s", skill_name, e)
        return results


class TemplateRenderer:
    """Render {{variable}} templates in Skill .md content."""

    def __init__(self, loader: SkillLoader):
        self.loader = loader
        self._system_cache: dict[str, str] = {}

    def _get_system_content(self, name: str) -> str:
        if name not in self._system_cache:
            self._system_cache[name] = self.loader.load_system_skill(name)
        return self._system_cache[name]

    def render(self, template: str, variables: dict | None = None) -> str:
        variables = variables or {}

        for sys_name in SkillLoader.SYSTEM_SKILLS:
            placeholder = "{{" + sys_name + "}}"
            if placeholder in template:
                content = self._get_system_content(sys_name)
                template = template.replace(placeholder, content)

        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            template = template.replace(placeholder, str(value))

        cleaned = re.findall(r"\{\{([_a-zA-Z][_a-zA-Z0-9]*)\}\}", template)
        if cleaned:
            logger.warning("render: unresolved placeholders: %s", cleaned)
        template = re.sub(r"\{\{[_a-zA-Z][_a-zA-Z0-9]*\}\}", "", template)

        return template.strip()


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

NEGATIVE_LIST = {
    "V1": {"desc": "裁判主文与说理部分结论直接矛盾", "dims": ["thorough_reasoning", "logic"]},
    "V2": {"desc": "对关键证据只字不提且无任何解释", "dims": ["sufficient_evidence", "fact_finding"]},
    "V3": {"desc": "引用的法条与案件类型完全不相关", "dims": ["correct_law_application"]},
    "V4": {"desc": "判决结果超出当事人诉讼请求范围", "dims": ["substantive_resolution"]},
    "V5": {"desc": "剥夺当事人法定程序权利且无合法理由", "dims": ["formal_specification"]},
}


def build_system_prompt(meta: SkillMeta) -> str:
    """Build system prompt from SkillMeta and system skills."""
    parts = []
    parts.append(f"# 裁判文书质量评审专家 — {meta.title}维度")
    parts.append("")
    parts.append(f"你是一位资深的中国司法文书质量评审专家，正在评估裁判文书的【{meta.title}】维度。")
    parts.append(f"本维度权重：{meta.weight*100:.0f}%，满分：{meta.full_score}分。")
    parts.append("")
    parts.append("请严格按照评分标准中的扣分项和加分项逐项检查，确保：")
    parts.append("1. 每个扣分项/加分项都有文书原文引用（original_text_location字段），禁止用'全文'、'多处'等模糊表述")
    parts.append("2. 评分理由清晰、具体、可验证，包含法理依据（legal_basis字段），必须引用具体法条编号及条文要点")
    parts.append("3. 输出格式为严格的JSON对象")
    parts.append("4. score为0-100之间的整数")
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
    parts.append("")
    parts.append("## A系列异常分类体系")
    parts.append("每个扣分项必须映射到以下A系列分类之一：")
    for code, desc in A_CODE_MAP.items():
        parts.append(f"- {code}：{desc}")
    parts.append("")

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

    parts.append("## 负面清单（一票否决项）")
    parts.append("以下情形一旦确认，该维度评分直接降为0分：")
    for vcode, vinfo in NEGATIVE_LIST.items():
        if meta.name in vinfo["dims"]:
            parts.append(f"- ⚠️ {vcode}：{vinfo['desc']}")
    parts.append("")

    parts.append("## 底线尊重原则")
    parts.append("只要判决中至少存在一项对弱势方有利的正确认定，总分不得低于40分（D级下限）。")
    parts.append("")

    return "\n".join(parts)
