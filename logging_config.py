import json
import logging
import os
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

# Attributes every stdlib LogRecord carries. Anything else on a record came from
# our own `extra={...}` calls and should be surfaced as a JSON field.
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

_logger_provider: LoggerProvider | None = None


# Attaches the active span's trace_id/span_id to each log record, correlating a
# log line back to the OTel trace that produced it.
class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            record.trace_id = format(span_context.trace_id, "032x")
            record.span_id = format(span_context.span_id, "016x")
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    global _logger_provider

    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JSONFormatter())
    stdout_handler.addFilter(TraceContextFilter())
    handlers = [stdout_handler]

    # In compose (OTEL_EXPORTER_OTLP_ENDPOINT set), also ship every log record to the
    # Collector via OTLP — same env-var toggle otel_setup.py uses for traces/metrics.
    # The OTel LoggingHandler attaches trace_id/span_id natively (its own mechanism,
    # separate from TraceContextFilter above, which only serves the stdout JSON path).
    # Native dev keeps the stdout-only behavior unchanged.
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        resource = Resource.create({"service.name": "simpleapp"})
        _logger_provider = LoggerProvider(resource=resource)
        _logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        handlers.append(LoggingHandler(logger_provider=_logger_provider))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers

    # Uvicorn's own loggers default to their own formatters; route them through
    # ours too so every log line in the process is consistently JSON (and, in
    # compose, also shipped via OTLP like every other logger).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = handlers
        uvicorn_logger.propagate = False

    # Our own request middleware already logs every request with more detail
    # (duration_ms, path) than uvicorn.access's plain text line — avoid duplicates.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# Flushes any buffered log records before the process exits.
def shutdown_logging() -> None:
    if _logger_provider is not None:
        _logger_provider.shutdown()
