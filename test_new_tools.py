"""Quick verification test for new tools added based on LLM review suggestions."""

import json
from judicial_quality_mcp.server import (
    query_anomaly_mcp,
    extract_timeline,
    trace_evidence_references,
    detect_evasive_patterns,
    render_dimension_prompt_batch,
    pipeline_progress,
    extract_document_sections,
)

SAMPLE_DOC = """北京市朝阳区人民法院
民事判决书
（2023）京0105民初12345号

原告张某诉称：2023年3月15日，原告与被告签订房屋买卖合同，约定被告将位于朝阳区某小区的房屋出售给原告，价格为500万元。原告依约支付了定金50万元，但被告拒绝履行合同。请求法院判令被告继续履行合同并支付违约金。

被告李某辩称：双方确实签订了合同，但原告未按约定时间支付首付款，被告有权解除合同。相关单位已对此事进行了调解，但未成功。

经审理查明：2023年3月15日，原被告签订房屋买卖合同。2023年4月1日，原告向被告支付定金50万元。此后，双方就首付款支付时间产生争议。2023年5月10日，原告向法院提起诉讼。

上述事实，有原告提交的房屋买卖合同、转账凭证、微信聊天记录等证据在案佐证。被告提交了相关单位的调解记录。

本院认为，原被告签订的房屋买卖合同系双方真实意思表示，不违反法律强制性规定，合法有效。被告辩称原告未按约定支付首付款，但未提交充分证据予以证明。依照《中华人民共和国民法典》第五百零九条、第五百七十七条之规定，判决如下：

一、被告李某继续履行与原告张某于2023年3月15日签订的房屋买卖合同；
二、被告李某于本判决生效之日起十日内向原告张某支付违约金50万元；
三、驳回原告张某的其他诉讼请求。

审判员 王某
2023年8月20日
"""

COMPLEX_ANOMALY_DOC = """北京市海淀区人民法院
民事判决书
（2022）京0108民初67890号

原告王某诉称：原告于2021年6月1日入职被告A公司，担任技术总监。2022年3月15日，被告A公司无故解除劳动合同。原告实际工作至2022年4月10日。此后，原告发现工资由B公司发放，社保由C公司缴纳，但实际管理均由A公司负责。2022年5月20日，原告向劳动仲裁委员会申请仲裁。原告提交了入职通知书、工资流水、社保缴纳记录、与A公司法定代表人的微信聊天记录等证据。请求法院确认原告与A公司存在劳动关系，并支付违法解除劳动合同赔偿金。

被告A公司辩称：A公司与原告不存在劳动关系，原告系B公司员工，相关单位负责原告的日常管理。A公司与B公司系独立法人，不存在混同。原告主张的关联关系缺乏依据，无需审查。

经审理查明：2022年4月10日，原告离开A公司办公场所。2021年6月1日，原告入职B公司。2022年3月15日，A公司向原告发送解除通知。随后，原告向相关机构投诉。期间，原告提交了多份证据。2022年5月20日，原告申请劳动仲裁。2021年9月，原告参加了A公司的年会。2022年1月，A公司法定代表人通过微信向原告布置工作。

上述事实，有原告提交的入职通知书、工资流水等证据在案佐证。

本院认为，原告主张与A公司存在劳动关系，但仅依据原告单方陈述，不足以认定。原告提交的微信聊天记录、社保缴纳记录等证据，本院不予采信。A公司辩称原告系B公司员工，具有事实依据。依照《中华人民共和国劳动合同法》之规定，判决如下：

一、驳回原告王某的全部诉讼请求；
二、案件受理费由原告负担。

审判员 赵某
2022年9月15日
"""


def test_query_anomaly_mcp():
    print("=== Test 1: query_anomaly_mcp ===")
    r = json.loads(query_anomaly_mcp(SAMPLE_DOC))
    assert r["success"]
    assert r["available"] is False
    assert len(r["anomaly_results"]) == 0
    assert r["fallback_mode"] == "blank"
    print(f"  available={r['available']}, fallback={r['fallback_mode']}")
    print(f"  message: {r['message'][:60]}...")
    print("  PASSED")


def test_extract_timeline():
    print("\n=== Test 2: extract_timeline ===")
    r = json.loads(extract_timeline(SAMPLE_DOC))
    assert r["success"]
    assert r["coverage"]["total_events"] >= 3
    print(f"  events={r['coverage']['total_events']}, anomalies={r['coverage']['anomaly_count']}, completeness={r['coverage']['completeness']}")
    for ev in r["events"][:3]:
        print(f"    {ev['date']}: {ev['context'][:50]}...")
    print("  PASSED")


def test_trace_evidence_references():
    print("\n=== Test 3: trace_evidence_references ===")
    r = json.loads(trace_evidence_references(SAMPLE_DOC))
    assert r["success"]
    print(f"  total_evidence={r['trace_summary']['total_evidence']}, unaddressed={r['trace_summary']['unaddressed_count']}, missing_reasoning={r['trace_summary']['missing_reasoning_count']}")
    print("  PASSED")


def test_detect_evasive_patterns():
    print("\n=== Test 4: detect_evasive_patterns ===")
    r = json.loads(detect_evasive_patterns(SAMPLE_DOC))
    assert r["success"]
    assert "risk_level" in r
    print(f"  risk_level={r['risk_level']}, detected={r['summary']['total_patterns']}")
    for d in r["detected_patterns"][:3]:
        print(f"    {d['pattern_id']}: {d['message'][:50]}...")
    print("  PASSED")


def test_render_dimension_prompt_batch():
    print("\n=== Test 5: render_dimension_prompt_batch ===")
    r = json.loads(render_dimension_prompt_batch(
        ["formal_specification", "clear_facts"],
        include_anchors=True,
        anchor_count=1,
    ))
    assert r["success"]
    assert r["batch_size"] == 2
    print(f"  batch_size={r['batch_size']}, total_tokens={r['total_token_estimate']}")
    for res in r["results"]:
        if "error" in res:
            print(f"    {res['dimension']}: ERROR {res['error']}")
        else:
            print(f"    {res['dimension']}: title={res['dimension_title']}, tokens={res['token_estimate']}")
    print("  PASSED")


def test_pipeline_progress():
    print("\n=== Test 6: pipeline_progress ===")
    r = json.loads(pipeline_progress("test-session-new", action="start"))
    assert r["success"]
    print(f"  session_id={r['session_id']}, total={r['total_count']}")

    r = json.loads(pipeline_progress(
        "test-session-new",
        action="complete",
        dimension_name="formal_specification",
        result_summary="score=85",
    ))
    assert r["success"]
    print(f"  completed={r['completed_count']}, progress={r['progress_pct']}%")

    r = json.loads(pipeline_progress("test-session-new", action="resume"))
    assert r["success"]
    assert "remaining_dimensions" in r
    print(f"  remaining={r['remaining_dimensions']}")
    print("  PASSED")


def test_extract_sections_with_rule_engine():
    print("\n=== Test 7: extract_document_sections (with rule engine) ===")
    r = json.loads(extract_document_sections(SAMPLE_DOC))
    assert r["success"]
    flags = r.get("rule_engine_flags", [])
    print(f"  confidence={r['extraction_confidence']}, rule_engine_flags={len(flags)}")
    for f in flags[:3]:
        print(f"    {f['rule_id']}: {f['message']} (severity={f['severity']})")
    print("  PASSED")


def test_complex_anomaly_doc_timeline():
    print("\n=== Test 8: extract_timeline (complex anomaly doc) ===")
    r = json.loads(extract_timeline(COMPLEX_ANOMALY_DOC))
    assert r["success"]
    print(f"  events={r['coverage']['total_events']}, anomalies={r['coverage']['anomaly_count']}, completeness={r['coverage']['completeness']}")
    for ev in r["events"]:
        print(f"    {ev['date']}: {ev['context'][:60]}...")
    if r["anomalies"]:
        print("  Timeline anomalies detected:")
        for a in r["anomalies"]:
            print(f"    [{a['severity']}] {a['type']}: {a['message'][:80]}...")
            if a.get("evidence"):
                for e in a["evidence"][:2]:
                    print(f"      evidence: {e[:60]}...")
    else:
        print("  No timeline anomalies detected (expected temporal inversion)")
    assert r["coverage"]["total_events"] >= 5, f"Expected >=5 events, got {r['coverage']['total_events']}"
    print("  PASSED")


def test_complex_anomaly_doc_evasive():
    print("\n=== Test 9: detect_evasive_patterns (complex anomaly doc) ===")
    r = json.loads(detect_evasive_patterns(COMPLEX_ANOMALY_DOC))
    assert r["success"]
    print(f"  risk_level={r['risk_level']}, detected={r['summary']['total_patterns']}")
    print(f"  summary: high={r['summary']['high_severity']}, medium={r['summary']['medium_severity']}, low={r['summary']['low_severity']}")
    for d in r["detected_patterns"]:
        print(f"    [{d['severity']}] {d['pattern_id']}: {d['message'][:60]}...")
        print(f"      match_count={d['match_count']}, sample: {d['sample_contexts'][0][:50] if d['sample_contexts'] else 'N/A'}...")
    assert r["summary"]["total_patterns"] >= 2, f"Expected >=2 evasive patterns, got {r['summary']['total_patterns']}"
    assert r["risk_level"] in ("medium", "high", "critical"), f"Expected risk >= medium, got {r['risk_level']}"
    print("  PASSED")


def test_complex_anomaly_doc_evidence():
    print("\n=== Test 10: trace_evidence_references (complex anomaly doc) ===")
    r = json.loads(trace_evidence_references(COMPLEX_ANOMALY_DOC))
    assert r["success"]
    print(f"  total_evidence={r['trace_summary']['total_evidence']}, unaddressed={r['trace_summary']['unaddressed_count']}, missing_reasoning={r['trace_summary']['missing_reasoning_count']}")
    if r["unaddressed"]:
        print("  Unaddressed evidence:")
        for u in r["unaddressed"][:3]:
            print(f"    [{u['severity']}] {u['message'][:70]}...")
    if r["missing_reasoning"]:
        print("  Missing reasoning:")
        for m in r["missing_reasoning"][:3]:
            print(f"    [{m['severity']}] {m['message'][:70]}...")
    print("  PASSED")


def test_complex_anomaly_doc_sections():
    print("\n=== Test 11: extract_document_sections (complex anomaly doc with rule engine) ===")
    r = json.loads(extract_document_sections(COMPLEX_ANOMALY_DOC))
    assert r["success"]
    flags = r.get("rule_engine_flags", [])
    print(f"  confidence={r['extraction_confidence']}, rule_engine_flags={len(flags)}")
    for f in flags:
        print(f"    [{f['severity']}] {f['rule_id']}: {f['message']}")
    print("  PASSED")


if __name__ == "__main__":
    test_query_anomaly_mcp()
    test_extract_timeline()
    test_trace_evidence_references()
    test_detect_evasive_patterns()
    test_render_dimension_prompt_batch()
    test_pipeline_progress()
    test_extract_sections_with_rule_engine()
    test_complex_anomaly_doc_timeline()
    test_complex_anomaly_doc_evasive()
    test_complex_anomaly_doc_evidence()
    test_complex_anomaly_doc_sections()
    print("\n" + "=" * 60)
    print("All tests passed! (11/11)")
    print("=" * 60)
