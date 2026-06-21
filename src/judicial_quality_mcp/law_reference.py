"""Law reference module — 法律法规数据库、类案判例、法律适用难点分析。

从 server.py 迁移的独立模块，包含：
- 法律法规数据库查询与冲突检测
- 类案判例查询与偏离检测
- 补充文档管理
- 法律适用难点分析
"""

import json
import logging
import re
import threading

from .config import ErrorCode

logger = logging.getLogger("judicial-quality")

# ── 法律法规数据库 ──────────────────────────────────────────────

LAW_DATABASE: dict[str, dict] = {
    "民法典": {
        "full_name": "中华人民共和国民法典",
        "effective_date": "2021-01-01",
        "hierarchy": "法律",
        "scope": "general",
        "predecessor": ["民法通则", "合同法", "物权法", "侵权责任法", "婚姻法", "继承法"],
        "key_provisions": {
            "总则编": "民事活动基本原则、民事主体、民事权利、民事法律行为",
            "物权编": "所有权、用益物权、担保物权",
            "合同编": "合同的订立、效力、履行、变更转让、权利义务终止、违约责任",
            "人格权编": "生命权、身体权、健康权、姓名权、肖像权、名誉权、隐私权",
            "婚姻家庭编": "结婚、家庭关系、离婚、收养",
            "继承编": "法定继承、遗嘱继承和遗赠、遗产的处理",
            "侵权责任编": "损害赔偿、责任构成和方式、不承担责任和减轻责任",
        },
    },
    "劳动合同法": {
        "full_name": "中华人民共和国劳动合同法",
        "effective_date": "2008-01-01",
        "hierarchy": "法律",
        "scope": "special",
        "superior_law": "民法典",
        "key_provisions": {
            "第7条": "劳动关系自用工之日起建立",
            "第10条": "建立劳动关系应订立书面劳动合同",
            "第14条": "无固定期限劳动合同的订立条件",
            "第26条": "劳动合同无效的情形",
            "第30条": "用人单位支付劳动报酬的义务",
            "第82条": "未订立书面劳动合同的二倍工资",
            "第85条": "未支付劳动报酬的加付赔偿金",
            "第87条": "违法解除劳动合同的赔偿金",
        },
    },
    "劳动争议调解仲裁法": {
        "full_name": "中华人民共和国劳动争议调解仲裁法",
        "effective_date": "2008-05-01",
        "hierarchy": "法律",
        "scope": "special",
        "superior_law": "劳动合同法",
        "key_provisions": {
            "第2条": "劳动争议范围",
            "第5条": "劳动争议处理程序",
            "第27条": "仲裁时效（一年）",
            "第47条": "终局裁决情形",
            "第48条": "劳动者对终局裁决的起诉权",
        },
    },
    "民事诉讼法": {
        "full_name": "中华人民共和国民事诉讼法",
        "effective_date": "2022-01-01",
        "hierarchy": "法律",
        "scope": "general",
        "amendment_history": ["1991", "2007", "2012", "2017", "2021", "2023"],
        "key_provisions": {
            "第119条": "起诉条件",
            "第164条": "上诉期限",
            "第170条": "二审审理范围",
            "第175条": "二审裁判方式",
        },
    },
    "公司法": {
        "full_name": "中华人民共和国公司法",
        "effective_date": "2024-07-01",
        "hierarchy": "法律",
        "scope": "special",
        "superior_law": "民法典",
        "amendment_history": ["1993", "1999", "2004", "2005", "2013", "2018", "2023"],
        "key_provisions": {
            "第20条": "公司人格否认（刺破公司面纱）",
            "第21条": "关联交易规制",
            "第63条": "一人公司举证责任倒置",
        },
    },
    "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）": {
        "full_name": "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）",
        "effective_date": "2021-01-01",
        "hierarchy": "司法解释",
        "scope": "special",
        "superior_law": "劳动合同法",
        "key_provisions": {
            "第1条": "劳动争议范围界定",
            "第34条": "未签订书面劳动合同的处理",
            "第43条": "加班工资举证责任",
        },
    },
    "江苏省工资支付条例": {
        "full_name": "江苏省工资支付条例",
        "effective_date": "2005-01-01",
        "hierarchy": "地方性法规",
        "scope": "special",
        "superior_law": "劳动合同法",
        "region": "江苏省",
        "key_provisions": {
            "第31条": "停工停产期间工资支付标准",
            "第32条": "用人单位克扣、无故拖欠工资的责任",
        },
    },
}

LEGAL_PRINCIPLES: dict[str, dict] = {
    "任何人不得从违法行为中获利": {
        "origin": "罗马法法谚",
        "latin": "Nullus commodum capere potest de injuria sua propria",
        "scope": "民法基本原则",
        "application": "用人单位违法待岗不得因此降低工资标准；违法解除不得因此免除支付义务",
        "constraint": "不突破法律明文规定，仅作为法律解释和漏洞填补的指导原则",
    },
    "诚实信用原则": {
        "origin": "民法典第7条",
        "latin": "Bona fides",
        "scope": "民法基本原则（帝王条款）",
        "application": "用人单位不得以自身违约行为对抗劳动者权利主张",
        "constraint": "仅在法律无明文规定时作为补充解释依据",
    },
    "公平原则": {
        "origin": "民法典第6条",
        "scope": "民法基本原则",
        "application": "合理确定各方权利义务，防止利益严重失衡",
        "constraint": "不突破法律明文规定",
    },
    "公序良俗": {
        "origin": "民法典第8条、第153条",
        "scope": "民法基本原则",
        "application": "违反公序良俗的法律行为无效；社会公共利益优先于个体利益",
        "constraint": "仅在法律行为效力判断时适用，不直接作为裁判依据",
    },
    "举轻以明重": {
        "origin": "罗马法法谚",
        "latin": "A maiore ad minus",
        "scope": "法律解释方法",
        "application": "轻行为尚且禁止，重行为更应禁止",
        "constraint": "仅用于法律解释，不创设新的法律规范",
    },
    "特别法优于一般法": {
        "origin": "立法法第92条",
        "scope": "法律适用规则",
        "application": "同一事项特别规定与一般规定不一致时适用特别规定",
        "constraint": "仅在同一机关制定的法律之间适用",
    },
    "新法优于旧法": {
        "origin": "立法法第92条",
        "scope": "法律适用规则",
        "application": "同一事项新规定与旧规定不一致时适用新规定",
        "constraint": "需注意溯及力问题，新法一般不溯及既往",
    },
    "上位法优于下位法": {
        "origin": "立法法第88条",
        "scope": "法律适用规则",
        "application": "下位法不得抵触上位法，抵触时适用上位法",
        "constraint": "法律 > 行政法规 > 地方性法规 > 规章",
    },
}

# ── 类案判例数据库 ──────────────────────────────────────────────

CASE_TYPE_PRECEDENTS: dict[str, dict] = {
    "劳动争议": {
        "guiding_cases": [
            {
                "id": "指导案例18号",
                "title": "中兴通讯诉王鹏劳动合同纠纷案",
                "court": "最高人民法院",
                "key_ruling": "劳动者在用人单位等级考核中居于末位等次，不等同于'不能胜任工作'",
                "relevance": "绩效考核与不能胜任的区分",
            },
            {
                "id": "指导案例94号",
                "title": "重庆市涪陵志大物业诉何某某劳动争议案",
                "court": "最高人民法院",
                "key_ruling": "见义勇为受伤应视同工伤",
                "relevance": "工伤认定标准",
            },
        ],
        "common_issues": [
            {"issue": "未签书面劳动合同的二倍工资", "tendency": "支持，但高管兼人事负责人除外", "rate": "约85%支持"},
            {"issue": "违法待岗期间的工资标准", "tendency": "分歧较大，部分按最低工资、部分按原工资", "rate": "约55%按原工资"},
            {"issue": "混同用工的连带责任", "tendency": "支持关联企业承担连带责任", "rate": "约78%支持"},
            {"issue": "加班工资的举证责任", "tendency": "劳动者主张加班事实需初步举证", "rate": "约70%要求劳动者举证"},
        ],
    },
}

# ── 补充文档存储 ────────────────────────────────────────────────

_supplementary_docs: dict[str, list[dict]] = {}
_docs_lock = threading.Lock()

_VALID_DOC_TYPES = {
    "law_analysis": "法律适用分析说明",
    "academic_opinion": "学术论文或观点",
    "precedent_comparison": "类案对比分析",
    "legal_maxim": "法谚或法律原则适用说明",
    "ethics_morality": "社会伦理道德和公序良俗规则适用说明",
    "frontier_issue": "法律适用前沿问题分析",
    "innovation_argument": "突破性创新论证",
}

_VALID_AUTHORITY_LEVELS = ["binding", "authoritative", "reference", "persuasive"]


# ── Helper ─────────────────────────────────────────────────────

def _make_error(code: ErrorCode, message: str) -> str:
    return json.dumps({"success": False, "error": {"code": code.value, "message": message}}, ensure_ascii=False)


# ── Public API ─────────────────────────────────────────────────

def query_law_database(
    law_names: list[str] | None = None,
    case_context: str = "",
    check_conflicts: bool = True,
) -> str:
    """查询法律法规数据库，检测法律适用优先级、冲突和溯及力问题。"""
    logger.info("query_law_database: >>> ENTER | law_names=%s, check_conflicts=%s", law_names, check_conflicts)
    try:
        matched = []
        search_names = law_names or []
        if case_context:
            for key, info in LAW_DATABASE.items():
                if any(kw in case_context for kw in [key, info.get("full_name", "")]):
                    if key not in search_names:
                        search_names.append(key)
            if not search_names:
                for key in LAW_DATABASE:
                    if any(kw in case_context for kw in ["劳动", "合同", "工资", "用工"]):
                        if key in ["劳动合同法", "劳动争议调解仲裁法", "民法典"]:
                            if key not in search_names:
                                search_names.append(key)

        for name in search_names:
            if name in LAW_DATABASE:
                matched.append({"name": name, **LAW_DATABASE[name]})

        priority_order = sorted(
            matched,
            key=lambda x: {"法律": 0, "司法解释": 1, "地方性法规": 2}.get(x.get("hierarchy", ""), 3),
        )

        conflicts = []
        retroactivity_issues = []
        if check_conflicts and len(matched) >= 2:
            for i in range(len(matched)):
                for j in range(i + 1, len(matched)):
                    a, b = matched[i], matched[j]
                    if a.get("scope") == "special" and b.get("scope") == "general":
                        conflicts.append({
                            "type": "特别法与一般法",
                            "special": a["name"],
                            "general": b["name"],
                            "rule": "特别法优于一般法，优先适用" + a["name"],
                            "exception": "特别法无规定时适用一般法",
                        })
                    if a.get("region") and not b.get("region"):
                        conflicts.append({
                            "type": "地方性法规与上位法",
                            "local": a["name"],
                            "national": b["name"],
                            "rule": "地方性法规不得抵触上位法",
                        })

        if check_conflicts:
            for law in matched:
                eff_date = law.get("effective_date", "")
                if eff_date and case_context:
                    eff_year = int(eff_date.split("-")[0])
                    year_matches = re.findall(r"(\d{4})年", case_context)
                    if year_matches:
                        earliest = min(int(y) for y in year_matches if int(y) >= 2000)
                        if eff_year > earliest:
                            retroactivity_issues.append({
                                "law": law["name"],
                                "effective_date": eff_date,
                                "case_earliest_fact": f"{earliest}年",
                                "issue": f"《{law['name']}》{eff_date}生效，但案件事实始于{earliest}年",
                                "resolution": "需核实是否适用溯及力条款或过渡期规定",
                                "retroactivity_clause": law.get("full_name") + "关于时间效力的规定",
                            })

        result = {
            "success": True,
            "matched_laws": matched,
            "priority_order": [{"rank": i+1, "name": l["name"], "hierarchy": l.get("hierarchy", "")}
                               for i, l in enumerate(priority_order)],
            "conflicts": conflicts,
            "retroactivity_issues": retroactivity_issues,
            "applicable_principles": [],
        }

        if case_context:
            for pname, pinfo in LEGAL_PRINCIPLES.items():
                if any(kw in case_context for kw in ["违法获利", "违法", "获利", "诚实", "信用",
                                                      "公平", "公序良俗", "道德"]):
                    result["applicable_principles"].append({"name": pname, **pinfo})

        logger.info("query_law_database: <<< EXIT | matched=%d, conflicts=%d, retro=%d",
                     len(matched), len(conflicts), len(retroactivity_issues))
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("query_law_database: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"法律法规查询异常：{e}")


def query_case_precedent(
    case_type: str,
    key_facts: list[str],
    court_level: str = "",
) -> str:
    """查询类案判例数据库，检测类案冲突和偏离。"""
    logger.info("query_case_precedent: >>> ENTER | case_type=%s, facts=%d", case_type, len(key_facts))
    try:
        precedents = []
        conflict_points = []
        deviation_points = []

        type_data = CASE_TYPE_PRECEDENTS.get(case_type, {})
        if type_data:
            for gc in type_data.get("guiding_cases", []):
                precedents.append({"level": "指导性案例", **gc})

            for ci in type_data.get("common_issues", []):
                if any(kw in ci["issue"] for kw in key_facts):
                    if "分歧" in ci.get("tendency", ""):
                        conflict_points.append({
                            "issue": ci["issue"],
                            "tendency": ci["tendency"],
                            "support_rate": ci.get("rate", ""),
                            "significance": "类案裁判存在分歧，需注意法律适用一致性",
                        })
                    deviation_points.append({
                        "issue": ci["issue"],
                        "mainstream_tendency": ci["tendency"],
                        "support_rate": ci.get("rate", ""),
                    })

        result = {
            "success": True,
            "case_type": case_type,
            "precedents": precedents,
            "deviation_points": deviation_points,
            "conflict_points": conflict_points,
            "innovation_space": [],
        }

        if conflict_points:
            result["innovation_space"] = [{
                "area": c["issue"],
                "current_status": c["tendency"],
                "innovation_direction": "存在突破类案裁判分歧、创设新裁判规则的空间",
                "constraint": "突破类案需充分说理，不得违反法律明文规定",
            } for c in conflict_points]

        logger.info("query_case_precedent: <<< EXIT | precedents=%d, conflicts=%d, deviations=%d",
                     len(precedents), len(conflict_points), len(deviation_points))
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("query_case_precedent: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"类案查询异常：{e}")


def submit_supplementary_doc(
    case_id: str,
    doc_type: str,
    doc_content: str,
    doc_title: str = "",
    authority_level: str = "reference",
) -> str:
    """提交补充说明文件，可在报告中引用作为说明基础。"""
    logger.info("submit_supplementary_doc: >>> ENTER | case_id=%s, doc_type=%s, authority=%s",
                 case_id, doc_type, authority_level)
    try:
        if doc_type not in _VALID_DOC_TYPES:
            return _make_error(
                ErrorCode.INVALID_INPUT,
                f"不支持的文档类型：{doc_type}，可选：{list(_VALID_DOC_TYPES.keys())}",
            )
        if authority_level not in _VALID_AUTHORITY_LEVELS:
            authority_level = "reference"

        with _docs_lock:
            if case_id not in _supplementary_docs:
                _supplementary_docs[case_id] = []

            doc_index = len(_supplementary_docs[case_id]) + 1
            doc_entry = {
                "index": doc_index,
                "doc_type": doc_type,
                "doc_type_zh": _VALID_DOC_TYPES[doc_type],
                "title": doc_title or f"补充文档-{doc_index}",
                "content": doc_content,
                "authority_level": authority_level,
                "authority_level_zh": {"binding": "约束性", "authoritative": "权威性",
                                       "reference": "参考性", "persuasive": "说服性"}[authority_level],
            }
            _supplementary_docs[case_id].append(doc_entry)
            total = len(_supplementary_docs[case_id])

        result = {
            "success": True,
            "case_id": case_id,
            "doc_index": doc_index,
            "doc_type_zh": doc_entry["doc_type_zh"],
            "title": doc_entry["title"],
            "authority_level_zh": doc_entry["authority_level_zh"],
            "total_docs_for_case": total,
            "message": f"补充文档已提交：{doc_entry['title']}（{doc_entry['doc_type_zh']}，{doc_entry['authority_level_zh']}）",
        }

        logger.info("submit_supplementary_doc: <<< EXIT | index=%d, total=%d",
                     doc_index, total)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("submit_supplementary_doc: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"补充文档提交异常：{e}")


def analyze_legal_difficulty(
    case_context: str,
    legal_issues: list[str],
    allow_innovation: bool = False,
) -> str:
    """分析法律适用难点和前沿问题，允许在疑难案件中突破性创新。"""
    logger.info("analyze_legal_difficulty: >>> ENTER | issues=%d, innovation=%s",
                 len(legal_issues), allow_innovation)
    try:
        difficulties = []
        for issue in legal_issues:
            diff_entry = {
                "issue": issue,
                "difficulty_level": "high",
                "current_legal_status": "法律适用存在模糊地带",
                "relevant_provisions": [],
                "analysis": "",
            }
            for law_name, law_info in LAW_DATABASE.items():
                for prov_name, prov_desc in law_info.get("key_provisions", {}).items():
                    if any(kw in issue for kw in prov_desc.split("、")):
                        diff_entry["relevant_provisions"].append(
                            f"《{law_info.get('full_name', law_name)}》{prov_name}：{prov_desc}"
                        )
            if not diff_entry["relevant_provisions"]:
                diff_entry["difficulty_level"] = "frontier"
                diff_entry["current_legal_status"] = "法律尚无明确规定，属于前沿问题"
            difficulties.append(diff_entry)

        applicable_principles = []
        principle_keywords = {
            "违法": ["任何人不得从违法行为中获利", "诚实信用原则"],
            "获利": ["任何人不得从违法行为中获利"],
            "待岗": ["任何人不得从违法行为中获利", "公平原则"],
            "混同": ["诚实信用原则", "公序良俗"],
            "人格": ["公序良俗", "诚实信用原则"],
            "工资": ["公平原则", "任何人不得从违法行为中获利"],
            "加班": ["公平原则"],
        }
        seen = set()
        for issue in legal_issues:
            for kw, principles in principle_keywords.items():
                if kw in issue or kw in case_context:
                    for p in principles:
                        if p not in seen and p in LEGAL_PRINCIPLES:
                            seen.add(p)
                            applicable_principles.append({
                                "name": p,
                                **LEGAL_PRINCIPLES[p],
                                "applicable_to": issue,
                            })

        ethics_considerations = []
        if any(kw in case_context for kw in ["违法", "待岗", "拒绝", "剥夺"]):
            ethics_considerations.append({
                "principle": "任何人不得从违法行为中获利",
                "application": "用人单位违法拒绝提供劳动条件，不得因此降低工资标准；违法在先者不得因自身违法行为获益",
                "constraint": "此原则不创设新的法律规范，仅在法律解释存在模糊时作为补充依据",
                "source": "罗马法法谚，已被中国司法实践广泛采纳",
            })
        if any(kw in case_context for kw in ["混同", "关联", "人格"]):
            ethics_considerations.append({
                "principle": "诚实信用原则（帝王条款）",
                "application": "关联企业不得利用人格混同规避法律义务",
                "constraint": "仅在法律无明文规定时作为补充解释依据",
                "source": "民法典第7条",
            })

        frontier_analysis = []
        for diff in difficulties:
            if diff["difficulty_level"] == "frontier":
                frontier_analysis.append({
                    "issue": diff["issue"],
                    "current_status": diff["current_legal_status"],
                    "academic_views": "学界存在不同观点，需结合具体案情判断",
                    "practical_significance": "该问题的裁判规则尚在发展中，具有创设指导案例的潜力",
                })

        innovation_space = []
        if allow_innovation:
            for diff in difficulties:
                if diff["difficulty_level"] in ("high", "frontier"):
                    innovation_space.append({
                        "issue": diff["issue"],
                        "current_limitation": diff["current_legal_status"],
                        "innovation_direction": "存在突破现有裁判惯例、创设新裁判规则的空间",
                        "legal_basis": "在法律框架内，通过法律解释和类推适用填补法律漏洞",
                        "constraint": "不得违反法律明文规定，需充分说理，确保裁判公正",
                        "precedent_potential": "若裁判理由充分，具有成为指导性案例的潜力",
                    })

        result = {
            "success": True,
            "difficulties": difficulties,
            "applicable_principles": applicable_principles,
            "ethics_considerations": ethics_considerations,
            "frontier_analysis": frontier_analysis,
            "innovation_space": innovation_space,
            "constraint_notice": "所有分析均不得突破现有法律法规的明确规定，法谚和法律原则仅在法律解释存在模糊时作为补充依据",
        }

        logger.info("analyze_legal_difficulty: <<< EXIT | difficulties=%d, principles=%d, ethics=%d, innovation=%d",
                     len(difficulties), len(applicable_principles), len(ethics_considerations), len(innovation_space))
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("analyze_legal_difficulty: <<< EXIT (ERROR) | %s", e, exc_info=True)
        return _make_error(ErrorCode.INTERNAL_ERROR, f"法律适用难点分析异常：{e}")
