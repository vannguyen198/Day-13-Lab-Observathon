"""Helpers to wire the Day 13 telemetry toolkit around the opaque agent.
Import these from wrapper.py. The agent emits NOTHING, so whatever you record here
is the only telemetry you will have to diagnose the faults.
"""
import time
import logging

try:
    from telemetry.logger import logger, new_correlation_id, set_correlation_id
    from telemetry.cost import cost_from_usage
    from telemetry.redact import redact
except Exception:
    logger = logging.getLogger("instrument")
    logging.basicConfig(level=logging.INFO)

    def cost_from_usage(model, usage):
        return 0.0

    def redact(s):
        return (s, 0)

def observed_call(call_next, question, config, context):
    """Wrap agent call with observability: latency, cost, PII, tools, errors."""
    t0 = time.time()
    try:
        res = call_next(question, config)
    except Exception as e:
        logger.error("AGENT_ERROR qid=%s error=%s", context.get("qid"), str(e))
        raise

    wall_ms = int((time.time() - t0) * 1000)
    meta = res.get("meta", {})
    usage = meta.get("usage", {})

    logger.info({
        "event": "AGENT_CALL",
        "qid": context.get("qid"),
        "status": res.get("status"),
        "reported_latency_ms": meta.get("latency_ms"),
        "wall_ms": wall_ms,
        "tokens": usage,
        "cost_usd": cost_from_usage(meta.get("model", ""), usage),
        "pii_in_answer": redact(res.get("answer") or "")[1] > 0,
        "tools_used": meta.get("tools_used", []),
        "tool_count": len(meta.get("tools_used", [])),
    })
    return res