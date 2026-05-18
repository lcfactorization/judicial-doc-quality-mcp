"""Skill Loader & Template Renderer v0.1.0 — loads Skill .md files, renders templates.

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

    SYSTEM_SKILLS = ["_system", "_output_format"]

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


def build_system_prompt(meta: SkillMeta) -> str:
    """Build system prompt from SkillMeta and system skills."""
    parts = []
    parts.append(f"# 裁判文书质量评审专家 — {meta.title}维度")
    parts.append("")
    parts.append(f"你是一位资深的中国司法文书质量评审专家，正在评估裁判文书的【{meta.title}】维度。")
    parts.append(f"本维度权重：{meta.weight*100:.0f}%，满分：{meta.full_score}分。")
    parts.append("")
    parts.append("请严格按照评分标准中的扣分项和加分项逐项检查，确保：")
    parts.append("1. 每个扣分项/加分项都有文书原文引用")
    parts.append("2. 评分理由清晰、具体、可验证")
    parts.append("3. 输出格式为严格的JSON对象")
    parts.append("4. score为0-100之间的整数")
    return "\n".join(parts)
