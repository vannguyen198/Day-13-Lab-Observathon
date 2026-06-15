"""Send traces to Langfuse (Track 4, real backend) -- activates only with keys.

Uses the CURRENT Langfuse Python SDK v4 (2026), which is OpenTelemetry-based.
Requires `pip install langfuse` and env LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
"""
from __future__ import annotations
import os
from typing import Any
from telemetry.backends.base import Backend

class LangfuseBackend(Backend):
    def __init__(self):
        if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
            raise RuntimeError("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set")
        try:
            from langfuse import Langfuse
        except ImportError as exc:
            raise RuntimeError("langfuse not installed (pip install langfuse)") from exc
        self._client: Any = Langfuse()
    
    def _create_and_end_span_recursive(self, parent_lf_object, span_dict: dict):
        """Recursively creates Langfuse spans and ends them."""
        lf_span = parent_lf_object.span(
            name=span_dict["name"],
            input=span_dict.get("attributes", {}),
            output={"status": span_dict["status"], "duration_ms": span_dict["duration_ms"]}
        )
        for child_dict in span_dict.get("children", []):
            self._create_and_end_span_recursive(lf_span, child_dict)
        lf_span.end()

    def export_trace(self, trace_data: dict) -> None:
        # The 'trace' dict here represents the root span of the telemetry system.
        # We map it to a Langfuse trace.
        trace_id = trace_data.get("attributes", {}).get("correlation_id", trace_data["span_id"])
        lf_trace = self._client.trace(
            id=trace_id,
            name=trace_data["name"],
            input=trace_data.get("attributes", {}),
            output={"status": trace_data["status"], "duration_ms": trace_data["duration_ms"]}
        )
        for child_dict in trace_data.get("children", []):
            self._create_and_end_span_recursive(lf_trace, child_dict)
        self._client.flush()