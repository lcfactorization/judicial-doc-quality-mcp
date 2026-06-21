"""Anomaly MCP bridge v0.2.0 — integration with judicial-doc-anomaly-mcp.

Extracts the anomaly detection bridge logic from server.py into a standalone
module. Handles auto-detection, prompt generation, response parsing, and
session management for the anomaly-mcp integration.

Bridge Architecture: NO LLM calls. Only bridges to anomaly-mcp's own bridge.
"""

import importlib
import json
import logging
import re
import threading

logger = logging.getLogger(__name__)

# ── Thread-safe anomaly session state ──────────────────────────
_session_lock = threading.Lock()
_anomaly_session: dict = {
    "dimensions": [],
    "collected_results": {},
    "total_dimensions": 0,
    "document_text": "",
}


# ── Auto-detection ─────────────────────────────────────────────

def detect_anomaly_mcp() -> bool:
    """Auto-detect whether judicial-doc-anomaly-mcp is installed and importable."""
    try:
        mod = importlib.import_module("judicial_lint_mcp")
        has_server = hasattr(mod, "server") or importlib.util.find_spec("judicial_lint_mcp.server") is not None
        if has_server:
            logger.info("detect_anomaly_mcp: judicial-lint-mcp detected and importable")
            return True
        logger.info("detect_anomaly_mcp: judicial-lint-mcp found but server module missing")
        return False
    except ImportError:
        logger.info("detect_anomaly_mcp: judicial-lint-mcp not installed")
        return False
    except Exception as e:
        logger.warning("detect_anomaly_mcp: detection error: %s", e)
        return False


# ── Dimension mapping ──────────────────────────────────────────

DIM_TO_SKILL = {
    "procedure": "dimensions/01_procedure",
    "evidence": "dimensions/02_evidence",
    "fact_finding": "dimensions/03_fact_finding",
    "focus_drift": "dimensions/04_focus_drift",
    "law_application": "dimensions/05_law_application",
    "discretion": "dimensions/06_discretion",
    "rhetoric_trick": "dimensions/07_rhetoric_trick",
    "logic": "dimensions/08_logic",
    "temporal": "dimensions/09_temporal",
    "trial_process": "dimensions/10_trial_process",
    "external_interference": "dimensions/11_external_interference",
    "execution": "dimensions/12_execution",
    "negative_space": "dimensions/13_negative_space",
    "semantic_drift": "dimensions/14_semantic_drift",
    "case_deviation": "dimensions/15_case_deviation",
    "coupling": "dimensions/16_coupling",
}

SUPPORTED_DIMENSIONS = list(DIM_TO_SKILL.keys())


# ── Query anomaly MCP ──────────────────────────────────────────

def query_anomaly_mcp(
    document_text: str,
    dimensions: list[str] | None = None,
    anomaly_mcp_available: bool = False,
    anomaly_mcp_auto_detected: bool = False,
    server_name: str = "judicial-lint",
) -> dict:
    """Query anomaly-mcp for detection prompts.

    Args:
        document_text: Full document text.
        dimensions: Dimensions to check (default: all 16).
        anomaly_mcp_available: Whether anomaly-mcp is available.
        anomaly_mcp_auto_detected: Whether auto-detected.
        server_name: MCP server name.

    Returns:
        Result dict with prompts, availability info, etc.
    """
    if dimensions is None:
        dimensions = SUPPORTED_DIMENSIONS

    if not anomaly_mcp_available:
        return {
            "success": True,
            "available": False,
            "auto_detected": False,
            "anomaly_results": [],
            "prompts": [],
            "dimensions": dimensions,
            "fallback_mode": "blank",
            "message": (
                "judicial-doc-anomaly-mcp 当前不可用（未检测到安装）。"
                "异常扣分项将留空白，质量评估流程不受影响。"
            ),
            "suggestion": (
                "如需启用异常检测联动，请安装：pip install judicial-lint-mcp "
                "或参考 https://github.com/lcfactorization/judicial-doc-anomaly-mcp"
            ),
        }

    try:
        from judicial_lint_mcp.server import render_skill, list_skills
    except ImportError:
        logger.warning("query_anomaly_mcp: anomaly-mcp import failed, falling back")
        return {
            "success": True,
            "available": False,
            "auto_detected": False,
            "anomaly_results": [],
            "prompts": [],
            "dimensions": dimensions,
            "fallback_mode": "import_failed",
            "message": "judicial-doc-anomaly-mcp 导入失败，已自动降级为不可用模式。",
            "suggestion": "请检查 judicial-lint-mcp 安装是否完整。",
        }

    prompts = []
    for idx, dim in enumerate(dimensions):
        try:
            skill_name = DIM_TO_SKILL.get(dim, f"dimensions/{idx+1:02d}_{dim}")
            prompt_json = render_skill(
                skill_name=skill_name,
                variables={"materials": document_text},
            )
            prompt_data = json.loads(prompt_json)
            prompts.append({
                "dimension": dim,
                "dimension_index": idx,
                "system_prompt": prompt_data.get("system_prompt", ""),
                "user_prompt": prompt_data.get("user_prompt", ""),
                "estimated_tokens": prompt_data.get("estimated_tokens", 0),
            })
        except Exception as e:
            logger.warning("query_anomaly_mcp: failed to generate prompt for dim=%s: %s", dim, e)
            prompts.append({
                "dimension": dim,
                "dimension_index": idx,
                "error": str(e),
            })

    # Update session state (thread-safe)
    with _session_lock:
        _anomaly_session["dimensions"] = dimensions
        _anomaly_session["collected_results"] = {}
        _anomaly_session["total_dimensions"] = len(dimensions)
        _anomaly_session["document_text"] = document_text

    return {
        "success": True,
        "available": True,
        "auto_detected": anomaly_mcp_auto_detected,
        "anomaly_results": [],
        "prompts": prompts,
        "dimensions": dimensions,
        "total_prompts": len(prompts),
        "message": (
            f"已自动检测到 judicial-doc-anomaly-mcp 并生成 {len(prompts)} 个维度的检测 Prompt。"
            "请将每个 Prompt 的 system_prompt + user_prompt 发送给 LLM，"
            "再将 LLM 响应通过 submit_anomaly_response 提交解析。"
        ),
        "next_step": (
            "对每个 prompt 调用 submit_anomaly_response(dimension, llm_response, dimension_index)，"
            "全部完成后调用 finalize_anomaly_detection() 获取汇总结果。"
        ),
    }


# ── Submit anomaly response ────────────────────────────────────

def submit_anomaly_response(
    dimension: str,
    llm_response: str,
    dimension_index: int = 0,
) -> dict:
    """Submit and parse LLM response for an anomaly detection dimension.

    Args:
        dimension: Dimension identifier.
        llm_response: Raw LLM response text.
        dimension_index: Dimension index (0-15).

    Returns:
        Result dict with anomaly_count, risk_level, progress.
    """
    try:
        from judicial_lint_mcp.server import parse_response as anomaly_parse
    except ImportError:
        return {
            "success": False,
            "error": "judicial-doc-anomaly-mcp 不可用，无法解析响应。",
            "dimension": dimension,
        }

    parsed_data = None

    # Try extracting JSON from markdown fence
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)```", llm_response, re.DOTALL)
    if json_match:
        try:
            parsed_data = json.loads(json_match.group(1).strip())
            if not isinstance(parsed_data, dict) or "dimension" not in parsed_data:
                parsed_data = None
        except (json.JSONDecodeError, ValueError):
            parsed_data = None

    # Try direct JSON parse
    if parsed_data is None:
        try:
            candidate = llm_response.strip()
            if candidate.startswith("{"):
                parsed_data = json.loads(candidate)
                if not isinstance(parsed_data, dict) or "dimension" not in parsed_data:
                    parsed_data = None
        except (json.JSONDecodeError, ValueError):
            parsed_data = None

    # Fallback to anomaly-mcp's parser
    if parsed_data is None:
        parsed_json = anomaly_parse(
            dimension=dimension,
            response=llm_response,
            dimension_index=dimension_index,
        )
        parsed_data = json.loads(parsed_json)

    # Store result (thread-safe)
    with _session_lock:
        if "error" in parsed_data:
            _anomaly_session["collected_results"][dimension] = {
                "dimension": dimension,
                "anomaly_count": 0,
                "risk_level": "unknown",
                "anomalies": [],
                "summary": f"解析失败：{parsed_data['error']}",
            }
        else:
            _anomaly_session["collected_results"][dimension] = parsed_data

        collected = len(_anomaly_session["collected_results"])
        total = _anomaly_session["total_dimensions"]

    return {
        "success": True,
        "dimension": dimension,
        "anomaly_count": parsed_data.get("anomaly_count", 0),
        "risk_level": parsed_data.get("risk_level", "unknown"),
        "progress": f"{collected}/{total}",
        "is_complete": collected >= total,
        "next_step": (
            "继续提交剩余维度的响应，或如果全部完成则调用 finalize_anomaly_detection()"
            if collected < total
            else "所有维度已收集完毕，请调用 finalize_anomaly_detection() 获取汇总结果"
        ),
    }


# ── Finalize anomaly detection ─────────────────────────────────

def finalize_anomaly_detection() -> dict:
    """Aggregate all submitted anomaly detection results.

    Returns:
        Result dict with anomaly_results, total_anomalies, risk_summary.
    """
    with _session_lock:
        collected = dict(_anomaly_session["collected_results"])
        total_dims = _anomaly_session["total_dimensions"]
        all_dimensions = list(_anomaly_session["dimensions"])

    anomaly_results = []
    total_anomalies = 0
    risk_summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}

    for dim_key in all_dimensions:
        dim_data = collected.get(dim_key)
        if dim_data is None:
            continue
        anomaly_results.append(dim_data)
        count = dim_data.get("anomaly_count", 0)
        total_anomalies += count
        risk = dim_data.get("risk_level", "unknown")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1

    missing = [d for d in all_dimensions if d not in collected]

    return {
        "success": True,
        "anomaly_results": anomaly_results,
        "total_anomalies": total_anomalies,
        "risk_summary": risk_summary,
        "dimensions_scanned": list(collected.keys()),
        "dimensions_missing": missing,
        "total_dimensions": total_dims,
        "completed": len(missing) == 0,
        "message": (
            f"异常检测汇总完成：共扫描 {len(collected)}/{total_dims} 个维度，"
            f"检出 {total_anomalies} 项异常。"
            + ("所有维度已完成。" if not missing else f"未完成维度：{', '.join(missing)}")
        ),
        "next_step": (
            "将 anomaly_results 传入 apply_anomaly_deduction 计算扣分，"
            "再传入 generate_report 的 anomaly_mcp_results 参数生成合并报告。"
        ),
    }


# ── Check anomaly MCP status ───────────────────────────────────

def check_anomaly_mcp_status(
    auto_detected: bool = False,
    server_name: str = "judicial-lint",
    supported_dimensions: list[str] | None = None,
) -> dict:
    """Check installation and runtime status of anomaly-mcp.

    Args:
        auto_detected: Whether auto-detection found it.
        server_name: MCP server name.
        supported_dimensions: List of supported dimensions.

    Returns:
        Status dict.
    """
    if supported_dimensions is None:
        supported_dimensions = SUPPORTED_DIMENSIONS

    importable = False
    version = None
    try:
        import judicial_lint_mcp
        importable = True
        version = getattr(judicial_lint_mcp, "__version__", None)
    except ImportError:
        pass

    return {
        "success": True,
        "installed": auto_detected or importable,
        "auto_detected": auto_detected,
        "importable": importable,
        "server_name": server_name,
        "supported_dimensions": supported_dimensions,
        "version": version,
        "message": (
            f"judicial-doc-anomaly-mcp 状态：{'已安装可导入' if importable else '未安装或不可导入'}"
            + (f"（v{version}）" if version else "")
            + f"，自动检测：{'通过' if auto_detected else '未通过'}"
        ),
    }


# ── Apply anomaly deduction ────────────────────────────────────

def apply_anomaly_deduction(anomaly_results: list[dict]) -> dict:
    """Calculate anomaly deduction based on anomaly-mcp detection results.

    Migrated from server.py inline implementation.

    Args:
        anomaly_results: List of anomaly items from anomaly-mcp, each containing:
            - type: anomaly type (procedural_anomaly/evidence_anomaly/fact_anomaly/
                    law_application_anomaly/reasoning_anomaly/logic_anomaly)
            - severity: severity level (low/medium/high)
            - description: anomaly description
            - evidence: supporting evidence (optional)
            - reasoning: reasoning (optional)

    Returns:
        Dict with total_deduction, capped, items, type_summaries, suggestion.
    """
    from .config import ANOMALY_DEDUCTION, ANOMALY_TOTAL_MAX_DEDUCTION

    logger.info("apply_anomaly_deduction: input_count=%d", len(anomaly_results))

    total_deduction = 0
    items = []
    type_totals: dict[str, float] = {}

    for anomaly in anomaly_results:
        anomaly_type = anomaly.get("type", "unknown")
        severity = anomaly.get("severity", "medium")
        desc = anomaly.get("description", "")
        evidence = anomaly.get("evidence", "")
        reasoning = anomaly.get("reasoning", "")

        rule = ANOMALY_DEDUCTION.get(anomaly_type)
        if not rule:
            logger.warning("apply_anomaly_deduction: unknown type=%s, skipping", anomaly_type)
            continue

        deduction = rule["severity_map"].get(severity, rule["per_item_deduction"])
        type_totals[anomaly_type] = type_totals.get(anomaly_type, 0) + deduction

        items.append({
            "type": anomaly_type,
            "label": rule["label"],
            "severity": severity,
            "deduction": deduction,
            "description": desc,
            "evidence": evidence,
            "reasoning": reasoning,
        })
        logger.debug(
            "apply_anomaly_deduction: type=%s, severity=%s, deduction=%d",
            anomaly_type, severity, deduction,
        )

    capped_items = []
    for anomaly_type, type_total in type_totals.items():
        rule = ANOMALY_DEDUCTION.get(anomaly_type)
        cap = rule["max_deduction"] if rule else type_total
        capped_val = min(type_total, cap)
        if type_total > cap:
            logger.info(
                "apply_anomaly_deduction: capping type=%s, raw=%.0f, cap=%d",
                anomaly_type, type_total, cap,
            )
        capped_items.append({
            "type": anomaly_type,
            "label": rule["label"] if rule else anomaly_type,
            "raw_deduction": type_total,
            "capped_deduction": capped_val,
            "cap": cap,
        })

    total_deduction = min(sum(c["capped_deduction"] for c in capped_items), ANOMALY_TOTAL_MAX_DEDUCTION)
    is_capped = total_deduction >= ANOMALY_TOTAL_MAX_DEDUCTION

    logger.info(
        "apply_anomaly_deduction: total=%d, capped=%s, items=%d",
        total_deduction, is_capped, len(items),
    )

    return {
        "total_deduction": total_deduction,
        "capped": is_capped,
        "max_deduction": ANOMALY_TOTAL_MAX_DEDUCTION,
        "items": items,
        "type_summaries": capped_items,
        "suggestion": (
            f"异常扣分合计{total_deduction}分。"
            "请将此结果传入 calculate_weighted_score 的 anomaly_items 参数。"
            if not is_capped
            else f"异常扣分已触及上限{ANOMALY_TOTAL_MAX_DEDUCTION}分。"
            "文书存在严重系统性异常，建议重点关注。"
        ),
    }
