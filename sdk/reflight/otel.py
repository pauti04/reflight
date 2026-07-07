"""Export recorded runs as OpenTelemetry spans (GenAI semantic conventions).

Composability, not competition: recorded runs land in whatever observability
stack you already have (Langfuse, Datadog, Jaeger, Grafana...) via OTLP.

    reflight otel <run_id> --endpoint http://localhost:4318/v1/traces

Timestamps are honest about what a recording knows: events carry the moment
they were emitted (call completion), so each span runs from the previous
event's timestamp to its own — durations are between-event gaps, exact for
the run as a whole.

Requires the `otel` extra: pip install reflight[otel].
"""

from __future__ import annotations

from typing import Any

GEN_AI_SYSTEM_DEFAULT = "anthropic"  # events only carry `provider` for openai


def _ns(ts: float | None) -> int | None:
    return int(ts * 1e9) if ts is not None else None


def _llm_attributes(event: dict) -> dict:
    response = event["response"]
    usage = response.get("usage") or {}
    attrs = {
        "gen_ai.operation.name": "chat",
        "gen_ai.system": event.get("provider", GEN_AI_SYSTEM_DEFAULT),
        "gen_ai.request.model": event["request"].get("model", ""),
        "gen_ai.response.model": response.get("model", ""),
        "reflight.request_hash": event["request_hash"],
        "reflight.seq": event["seq"],
    }
    # anthropic usage vs openai usage field names
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = input_tokens
    if output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = output_tokens
    stop = response.get("stop_reason") or next(
        (c.get("finish_reason") for c in response.get("choices", []) if c.get("finish_reason")),
        None,
    )
    if stop:
        attrs["gen_ai.response.finish_reasons"] = [stop]
    from .pricing import cost_usd

    cost = cost_usd(response.get("model"), usage)
    if cost is not None:
        attrs["reflight.cost_usd"] = cost
    return attrs


def export_run(run_id: str, events: list[dict], tracer: Any) -> int:
    """Emit one root span + one child span per llm/tool event. Returns span count."""
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    start = next((e for e in events if e["type"] == "run_start"), None)
    end = next((e for e in events if e["type"] == "run_end"), None)
    first_ts = events[0]["ts"] if events else None
    last_ts = events[-1]["ts"] if events else None

    root = tracer.start_span(f"agent_run {run_id}", start_time=_ns(first_ts))
    root.set_attribute("reflight.run_id", run_id)
    if start:
        root.set_attribute("reflight.task", start.get("task") or "")
        if start.get("agent"):
            root.set_attribute("reflight.agent", start["agent"])
    if end:
        root.set_attribute("reflight.status", end.get("status") or "")
        root.set_attribute("gen_ai.usage.input_tokens", end.get("input_tokens") or 0)
        root.set_attribute("gen_ai.usage.output_tokens", end.get("output_tokens") or 0)
        if end.get("status") not in ("completed", None):
            root.set_status(Status(StatusCode.ERROR, end.get("status")))

    context = trace.set_span_in_context(root)
    count = 1
    previous_ts = first_ts
    for event in events:
        event_type = event["type"]
        if event_type == "llm_call":
            model = event["request"].get("model", "?")
            span = tracer.start_span(
                f"chat {model}", context=context, start_time=_ns(previous_ts)
            )
            for key, value in _llm_attributes(event).items():
                span.set_attribute(key, value)
            span.end(end_time=_ns(event["ts"]))
            count += 1
        elif event_type == "tool_call":
            span = tracer.start_span(
                f"execute_tool {event['name']}", context=context, start_time=_ns(previous_ts)
            )
            span.set_attribute("gen_ai.operation.name", "execute_tool")
            span.set_attribute("gen_ai.tool.name", event["name"])
            span.set_attribute("gen_ai.tool.call.id", event["tool_use_id"])
            span.set_attribute("reflight.seq", event["seq"])
            if event.get("cached"):
                span.set_attribute("reflight.cached", True)
            if event["is_error"]:
                span.set_status(Status(StatusCode.ERROR, str(event["result"])[:200]))
            span.end(end_time=_ns(event["ts"]))
            count += 1
        elif event_type == "error":
            root.add_event(
                "error",
                {"error.type": event["error_type"], "error.message": event["message"]},
                timestamp=_ns(event["ts"]),
            )
        previous_ts = event["ts"]

    root.end(end_time=_ns(last_ts))
    return count


def export_to_otlp(run_id: str, events: list[dict], endpoint: str | None = None) -> int:
    """Ship one run's spans to an OTLP HTTP collector. Returns span count."""
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "OpenTelemetry packages missing — install with: pip install 'reflight[otel]'"
        ) from exc

    provider = TracerProvider(resource=Resource.create({"service.name": "reflight"}))
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    count = export_run(run_id, events, provider.get_tracer("reflight"))
    provider.force_flush()
    provider.shutdown()
    return count
