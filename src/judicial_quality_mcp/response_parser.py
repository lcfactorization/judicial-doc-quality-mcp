"""Response parser v0.2.0 — extract structured score results from LLM/Agent responses.

Bridge Architecture: NO LLM calls.
Pure text parsing and validation logic.
"""

import json
import logging
import re

from .config import (
    ANOMALY_DEDUCTION,
    ANOMALY_TOTAL_MAX_DEDUCTION,
    DIMENSION_TITLES,
    INNOVATION_BONUS,
    INNOVATION_TOTAL_MAX_BONUS,
    QUALITY_GRADES,
    QUALITY_WEIGHTS,
)

logger = logging.getLogger(__name__)

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

MINIMUM_SCORE = 40


class ResponseParser:
    """Parse LLM/Agent responses into structured score results."""

    def parse_score_result(self, dimension: str, response: str) -> dict:
        logger.info("parse_score_result: dimension=%s, response_len=%d", dimension, len(response))

        result = {
            "dimension": dimension,
            "dimension_title": DIMENSION_TITLES.get(dimension, dimension),
            "weight": QUALITY_WEIGHTS.get(dimension, 0.0),
            "parsed": {},
            "validation": {
                "format_valid": False,
                "score_in_bounds": False,
                "required_fields_present": False,
                "warnings": [],
            },
            "raw_response": response,
        }

        json_obj = self._extract_json(response)
        if json_obj is None:
            result["validation"]["warnings"].append("无法从响应中提取JSON对象")
            logger.warning("parse_score_result: JSON extraction failed for dimension=%s", dimension)
            return result

        result["parsed"] = json_obj
        result["validation"]["format_valid"] = True

        score = json_obj.get("score")
        if score is not None:
            try:
                score = int(score)
                if 0 <= score <= 100:
                    result["validation"]["score_in_bounds"] = True
                    json_obj["score"] = score
                else:
                    original = score
                    score = max(0, min(100, score))
                    json_obj["score"] = score
                    result["validation"]["score_in_bounds"] = True
                    result["validation"]["warnings"].append(
                        f"分数越界已校准: 原始值={original}, 校准后={score}"
                    )
                    logger.warning(
                        "parse_score_result: score out of bounds, dimension=%s, original=%d, calibrated=%d",
                        dimension, original, score,
                    )
            except (ValueError, TypeError):
                result["validation"]["warnings"].append(f"score字段非整数: {score}")
                json_obj["score"] = 0
                logger.warning("parse_score_result: score not integer, dimension=%s, value=%s", dimension, score)

        required = ["quote", "reasoning", "score"]
        present = all(k in json_obj for k in required)
        result["validation"]["required_fields_present"] = present
        if not present:
            missing = [k for k in required if k not in json_obj]
            result["validation"]["warnings"].append(f"缺少必填字段: {missing}")

        if "deduction_items" not in json_obj:
            json_obj["deduction_items"] = []
            result["validation"]["warnings"].append("缺少deduction_items字段，已设为空数组")

        if "bonus_items" not in json_obj:
            json_obj["bonus_items"] = []

        self._validate_deduction_items(json_obj.get("deduction_items", []), result["validation"], dimension)
        self._validate_bonus_items(json_obj.get("bonus_items", []), result["validation"])

        if "five_reasoning" in json_obj:
            result["five_reasoning"] = json_obj["five_reasoning"]
        if "four_element" in json_obj:
            result["four_element"] = json_obj["four_element"]

        if dimension == "substantive_resolution" and "data_completeness" not in json_obj:
            json_obj["data_completeness"] = "partial"
            result["validation"]["warnings"].append("实质解纷维度缺少data_completeness字段，已设为partial")

        logger.info(
            "parse_score_result: dimension=%s, score=%s, valid=%s, warnings=%d",
            dimension, json_obj.get("score"), result["validation"]["format_valid"],
            len(result["validation"]["warnings"]),
        )

        return result

    def _extract_json(self, text: str) -> dict | None:
        cleaned = text.strip()

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
            logger.debug("_extract_json: extracted from markdown fence, len=%d", len(cleaned))

        brace_count = 0
        start_idx = -1
        for i, ch in enumerate(cleaned):
            if ch == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx >= 0:
                    candidate = cleaned[start_idx:i + 1]
                    parsed = self._try_parse_json(candidate)
                    if parsed is not None:
                        return parsed

        logger.debug("_extract_json: balanced brace search failed, falling back to regex")
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            parsed = self._try_parse_json(json_match.group())
            if parsed is not None:
                return parsed

        return None

    def _try_parse_json(self, text: str) -> dict | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        try:
            fixed = re.sub(r",\s*}", "}", text)
            fixed = re.sub(r",\s*]", "]", fixed)
            fixed = re.sub(r"'", '"', fixed)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        try:
            fixed = re.sub(r",\s*}", "}", text)
            fixed = re.sub(r",\s*]", "]", fixed)
            fixed = re.sub(r"[\x00-\x1f\x7f]", " ", fixed)
            fixed = re.sub(r"'", '"', fixed)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        try:
            fixed = re.sub(r",\s*}", "}", text)
            fixed = re.sub(r",\s*]", "]", fixed)
            fixed = re.sub(r"[\x00-\x1f\x7f]", " ", fixed)
            fixed = re.sub(r"'", '"', fixed)
            fixed = re.sub(r"(\w+)\s*:", r'"\1":', fixed)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        logger.debug("_try_parse_json: all parse attempts failed for text len=%d", len(text))
        return None

    def _validate_deduction_items(self, items: list, validation: dict, dimension: str = ""):
        if not isinstance(items, list):
            validation["warnings"].append("deduction_items不是数组")
            return
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                validation["warnings"].append(f"deduction_items[{i}]不是对象")
                continue
            if "item" not in item:
                validation["warnings"].append(f"deduction_items[{i}]缺少item字段")
            if "deduction" not in item:
                validation["warnings"].append(f"deduction_items[{i}]缺少deduction字段")
            elif not isinstance(item["deduction"], (int, float)):
                validation["warnings"].append(f"deduction_items[{i}].deduction非数值")
            if "evidence" not in item and "quote" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少evidence/quote字段（可解释性要求：扣分项需有原文引用支撑）"
                )
            if "reasoning" not in item and "basis" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少reasoning/basis字段（可解释性要求：扣分项需有说理依据）"
                )
            if "a_code" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少a_code字段（A系列分类编号必填）"
                )
            elif item.get("a_code") not in A_CODE_MAP:
                validation["warnings"].append(
                    f"deduction_items[{i}].a_code={item.get('a_code')}不在A1-A8范围内"
                )
            if dimension == "clear_facts" and "f_code" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少f_code字段（事实认定维度F编号必填）"
                )
            if "beneficiary" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少beneficiary字段（获益方标注必填）"
                )
            if "conclusion" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少conclusion字段（对抗校验结论必填）"
                )
            if "net_anomaly" not in item:
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少net_anomaly字段（净异常判定必填）"
                )
            if "stage_scope" not in item:
                item["stage_scope"] = ""
                validation["warnings"].append(
                    f"deduction_items[{i}]缺少stage_scope字段（审级归属必填），已设为空"
                )
            if "stage_unclear" not in item:
                item["stage_unclear"] = False

    def _validate_bonus_items(self, items: list, validation: dict):
        if not isinstance(items, list):
            validation["warnings"].append("bonus_items不是数组")
            return
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                validation["warnings"].append(f"bonus_items[{i}]不是对象")
                continue
            if "item" not in item:
                validation["warnings"].append(f"bonus_items[{i}]缺少item字段")
            if "bonus" not in item:
                validation["warnings"].append(f"bonus_items[{i}]缺少bonus字段")
            elif not isinstance(item["bonus"], (int, float)):
                validation["warnings"].append(f"bonus_items[{i}].bonus非数值")
            if "evidence" not in item and "quote" not in item:
                validation["warnings"].append(
                    f"bonus_items[{i}]缺少evidence/quote字段（可解释性要求：加分项需有原文引用支撑）"
                )
            if "reasoning" not in item and "reason" not in item:
                validation["warnings"].append(
                    f"bonus_items[{i}]缺少reasoning/reason字段（可解释性要求：加分项需有加分理由）"
                )

    def calculate_weighted_score(
        self,
        dimension_scores: dict[str, int],
        anomaly_items: list[dict] | None = None,
        innovation_items: list[dict] | None = None,
        has_favorable_finding: bool = True,
    ) -> dict:
        logger.info(
            "calculate_weighted_score: starting calculation with scores=%s, anomaly_count=%d, innovation_count=%d, has_favorable=%s",
            dimension_scores,
            len(anomaly_items) if anomaly_items else 0,
            len(innovation_items) if innovation_items else 0,
            has_favorable_finding,
        )

        total = 0.0
        details = []
        for dim, score in dimension_scores.items():
            weight = QUALITY_WEIGHTS.get(dim, 0.0)
            weighted = score * weight
            total += weighted
            details.append({
                "dimension": dim,
                "dimension_title": DIMENSION_TITLES.get(dim, dim),
                "score": score,
                "weight": weight,
                "weighted_score": round(weighted, 2),
            })
            logger.debug(
                "calculate_weighted_score: dimension=%s, score=%d, weight=%.2f, weighted=%.2f, running_total=%.2f",
                dim, score, weight, weighted, total,
            )

        base_total = round(total, 1)
        logger.info("calculate_weighted_score: base_weighted_total=%.1f (before adjustments)", base_total)

        anomaly_deduction = 0
        anomaly_details = []
        if anomaly_items:
            type_deductions: dict[str, float] = {}
            for item in anomaly_items:
                anomaly_type = item.get("type", "unknown")
                severity = item.get("severity", "medium")
                desc = item.get("description", "")

                rule = ANOMALY_DEDUCTION.get(anomaly_type)
                if rule:
                    deduction = rule["severity_map"].get(severity, rule["per_item_deduction"])
                    type_deductions[anomaly_type] = type_deductions.get(anomaly_type, 0) + deduction
                    anomaly_details.append({
                        "type": anomaly_type,
                        "label": rule["label"],
                        "severity": severity,
                        "deduction": deduction,
                        "description": desc,
                        "evidence": item.get("evidence", item.get("quote", "")),
                        "reasoning": item.get("reasoning", item.get("basis", "")),
                        "item_name": item.get("item_name", item.get("item", desc[:30] if desc else "")),
                        "original_text_location": item.get("original_text_location", item.get("location", item.get("quote", ""))),
                        "evidence_reference": item.get("evidence_reference", item.get("evidence", "")),
                        "legal_analysis": item.get("legal_analysis", item.get("background", "")),
                        "beneficiary": item.get("beneficiary", item.get("target", "")),
                        "confidence": item.get("confidence", ""),
                        "brief": item.get("brief", desc[:50] if desc else ""),
                        "q1_alternative": item.get("q1_alternative", item.get("alternative_explanation", "")),
                        "q2_subjective_intent": item.get("q2_subjective_intent", ""),
                        "q3_contradictory_evidence": item.get("q3_contradictory_evidence", ""),
                        "conclusion": item.get("conclusion", ""),
                        "suggestion": item.get("suggestion", item.get("fix", "")),
                        "a_code": item.get("a_code", ""),
                        "a_code_desc": A_CODE_MAP.get(item.get("a_code", ""), ""),
                        "f_code": item.get("f_code", ""),
                        "f_code_desc": F_CODE_MAP.get(item.get("f_code", ""), ""),
                        "reverse_anomaly": item.get("reverse_anomaly", ""),
                        "net_anomaly": item.get("net_anomaly", ""),
                        "stage_scope": item.get("stage_scope", ""),
                        "stage_unclear": item.get("stage_unclear", False),
                    })
                    logger.debug(
                        "calculate_weighted_score: anomaly type=%s, severity=%s, deduction=%d, desc=%s",
                        anomaly_type, severity, deduction, desc[:50],
                    )
                else:
                    logger.warning("calculate_weighted_score: unknown anomaly type=%s", anomaly_type)

            for anomaly_type, type_total in type_deductions.items():
                rule = ANOMALY_DEDUCTION.get(anomaly_type)
                if rule and type_total > rule["max_deduction"]:
                    capped = rule["max_deduction"]
                    logger.info(
                        "calculate_weighted_score: capping anomaly type=%s, raw=%.0f, capped=%d",
                        anomaly_type, type_total, capped,
                    )
                    type_deductions[anomaly_type] = capped

            anomaly_deduction = min(sum(type_deductions.values()), ANOMALY_TOTAL_MAX_DEDUCTION)
            logger.info(
                "calculate_weighted_score: total_anomaly_deduction=%.0f (capped at %d)",
                anomaly_deduction, ANOMALY_TOTAL_MAX_DEDUCTION,
            )

        innovation_bonus = 0
        innovation_details = []
        if innovation_items:
            for item in innovation_items:
                bonus_type = item.get("type", "")
                desc = item.get("description", "")
                bonus_value = item.get("bonus", 0)

                rule = INNOVATION_BONUS.get(bonus_type)
                if rule:
                    min_b, max_b = rule["bonus_range"]
                    actual_bonus = max(min_b, min(max_b, bonus_value)) if bonus_value > 0 else 0
                    innovation_bonus += actual_bonus
                    innovation_details.append({
                        "type": bonus_type,
                        "label": rule["label"],
                        "bonus": actual_bonus,
                        "description": desc,
                        "evidence": item.get("evidence", item.get("quote", "")),
                        "reasoning": item.get("reasoning", item.get("reason", "")),
                        "legal_basis": item.get("legal_basis", ""),
                        "detail": item.get("detail", item.get("analysis", "")),
                    })
                    logger.debug(
                        "calculate_weighted_score: innovation type=%s, requested=%d, actual=%d, desc=%s",
                        bonus_type, bonus_value, actual_bonus, desc[:50],
                    )
                else:
                    logger.warning("calculate_weighted_score: unknown innovation type=%s", bonus_type)

            innovation_bonus = min(innovation_bonus, INNOVATION_TOTAL_MAX_BONUS)
            logger.info(
                "calculate_weighted_score: total_innovation_bonus=%d (capped at %d)",
                innovation_bonus, INNOVATION_TOTAL_MAX_BONUS,
            )

        adjusted_total = base_total - anomaly_deduction + innovation_bonus
        adjusted_total = max(0, min(100, round(adjusted_total, 1)))

        if has_favorable_finding and adjusted_total < MINIMUM_SCORE:
            logger.info(
                "calculate_weighted_score: applying minimum score floor (%d) due to favorable finding",
                MINIMUM_SCORE,
            )
            adjusted_total = MINIMUM_SCORE

        grade, grade_desc = self._determine_grade(adjusted_total)

        logger.info(
            "calculate_weighted_score: final total=%.1f (base=%.1f - anomaly=%.0f + innovation=%d), grade=%s, grade_desc=%s",
            adjusted_total, base_total, anomaly_deduction, innovation_bonus, grade, grade_desc,
        )

        return {
            "weighted_total": adjusted_total,
            "base_weighted_total": base_total,
            "anomaly_deduction": anomaly_deduction,
            "innovation_bonus": innovation_bonus,
            "grade": grade,
            "grade_description": grade_desc,
            "dimension_details": details,
            "anomaly_details": anomaly_details,
            "innovation_details": innovation_details,
            "minimum_score_applied": has_favorable_finding and (base_total - anomaly_deduction + innovation_bonus) < MINIMUM_SCORE,
        }

    @staticmethod
    def _determine_grade(total: float) -> tuple[str, str]:
        for grade_key, (lo, hi, desc) in QUALITY_GRADES.items():
            if lo <= total <= hi:
                return grade_key, desc
        return "F", "不及格"

    @staticmethod
    def compute_beneficiary_distribution(anomaly_details: list[dict]) -> dict:
        dist = {}
        for item in anomaly_details:
            b = item.get("beneficiary", "未标注")
            dist[b] = dist.get(b, 0) + 1
        return dist

    @staticmethod
    def compute_coupling_analysis(anomaly_details: list[dict]) -> list[dict]:
        dim_groups: dict[str, list[dict]] = {}
        for item in anomaly_details:
            dim = item.get("type", "unknown")
            if dim not in dim_groups:
                dim_groups[dim] = []
            dim_groups[dim].append(item)

        coupled = []
        dims_with_anomalies = [d for d, items in dim_groups.items() if len(items) > 0]
        if len(dims_with_anomalies) >= 2:
            for i in range(len(dims_with_anomalies)):
                for j in range(i + 1, len(dims_with_anomalies)):
                    d1, d2 = dims_with_anomalies[i], dims_with_anomalies[j]
                    items1, items2 = dim_groups[d1], dim_groups[d2]
                    shared_beneficiary = set()
                    for it1 in items1:
                        for it2 in items2:
                            b1 = it1.get("beneficiary", "")
                            b2 = it2.get("beneficiary", "")
                            if b1 and b2 and b1 == b2:
                                shared_beneficiary.add(b1)
                    if shared_beneficiary:
                        coupled.append({
                            "coupled_dimensions": [d1, d2],
                            "coupling_type": f"{d1}-{d2}异常耦合",
                            "coupling_strength": "中",
                            "coupling_description": f"维度{d1}和{d2}的异常均指向同一获益方：{'、'.join(shared_beneficiary)}",
                            "overall_risk": "medium",
                            "beneficiary_analysis": list(shared_beneficiary),
                        })
        return coupled
