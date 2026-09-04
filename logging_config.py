import json
import logging
import os
import sys

from opentelemetry import trace

# Attributes every stdlib LogRecord carries. Anything else on a record came from
# our own `extra={...}` calls and should be surfaced as a JSON field.
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


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
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(TraceContextFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]

    # Uvicorn's own loggers default to their own formatters; route them through
    # ours too so every log line in the process is consistently JSON.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = [handler]
        uvicorn_logger.propagate = False

    # Our own request middleware already logs every request with more detail
    # (duration_ms, path) than uvicorn.access's plain text line — avoid duplicates.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
