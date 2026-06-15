"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}

PROMPT ROUTING: you can override the agent's system prompt PER REQUEST by setting it in
the config you pass to call_next, e.g.:
    conf = dict(config); conf["system_prompt"] = my_better_prompt
    result = call_next(question, conf)
(Or just edit solution/prompt.txt for a single static prompt used on every request.)
"""
from __future__ import annotations
import sys
import os

from telemetry.logger import logger, set_correlation_id, new_correlation_id
from telemetry.cost import cost_from_usage
from telemetry.redact import redact
from telemetry.tracing import Tracer
import time

tracer = Tracer()

def mitigate(call_next, question, config, context):
    key = (question, str(config))

    # --- CACHE CHECK ---
    with context["cache_lock"]:
        if key in context["cache"]:
            cached = context["cache"][key]
            logger.info({"qid": context["qid"], "session": context["session_id"],
                         "status": "cache_hit"})
            return cached

    # --- TRACING & INSTRUMENTATION ---
    # Track 1: Correlation ID connects logs and traces
    cid = new_correlation_id()
    set_correlation_id(cid)

    # Track 3: Start a root span for the request
    with tracer.start_span("agent_request", correlation_id=cid, qid=context["qid"]) as span:
        start = time.time()
        
        # --- CALL AGENT WITH RETRY ---
        result = call_next(question, config)
        if result["status"] == "error":
            logger.warning({"qid": context["qid"], "session": context["session_id"], "status": "retrying"})
            result = call_next(question, config)

        latency_ms = int((time.time() - start) * 1000)
        usage = result["meta"].get("usage", {})
        model = result["meta"].get("model", "")

        # --- GUARDRAILS / SANITIZATION ---
        # Track 1: Redact PII at origin
        answer = redact(result.get("answer") or "")[0]
        result["answer"] = answer

        # Attach metadata to the trace span
        span.set(
            model=model,
            tokens=usage.get("total_tokens", 0),
            cost_usd=cost_from_usage(model, usage),
            status=result["status"]
        )

    # --- TRACK 1: STRUCTURED LOGGING ---
    log_entry = {
        "qid": context["qid"],
        "session": context["session_id"],
        "turn": context["turn_index"],
        "latency_ms": latency_ms,
        "tokens": usage.get("total_tokens", 0),
        "cost": cost_from_usage(result["meta"].get("model", ""), usage),
        "status": result["status"],
        "question": redact(question)[0],
        "answer": redact(result.get("answer") or "")[0],
    }
    logger.info(log_entry)

    # --- CACHE STORE ---
    with context["cache_lock"]:
        context["cache"][key] = result

    return result