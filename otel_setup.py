import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import Histogram, MeterProvider
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

_RESOURCE = Resource.create({"service.name": "simpleapp"})

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


# Real OTLP export (to the Collector, in compose) when OTEL_EXPORTER_OTLP_ENDPOINT is
# set; otherwise falls back to console exporters, unchanged, for native `uvicorn
# --reload` dev where no Collector is running. BatchSpanProcessor for the OTLP path
# (batching is worth it once spans leave the process); SimpleSpanProcessor (synchronous,
# no batching win for a trivial local app) stays for the console path.
def configure_telemetry() -> None:
    global _tracer_provider, _meter_provider

    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    _tracer_provider = TracerProvider(resource=_RESOURCE)
    if otlp_endpoint:
        _tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    else:
        _tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_tracer_provider)

    # 5s export interval (default is 60s) so metrics show up quickly during local testing.
    if otlp_endpoint:
        # The Elasticsearch exporter (in the Collector) only accepts delta-temporality
        # histograms, not the SDK's cumulative default — without this, every histogram
        # metric (http.server.duration, request/response size) is silently dropped.
        metric_exporter = OTLPMetricExporter(preferred_temporality={Histogram: AggregationTemporality.DELTA})
    else:
        metric_exporter = ConsoleMetricExporter()
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=5000)
    _meter_provider = MeterProvider(resource=_RESOURCE, metric_readers=[metric_reader])
    metrics.set_meter_provider(_meter_provider)


def instrument_app(app) -> None:
    FastAPIInstrumentor.instrument_app(app)


def instrument_engine(engine) -> None:
    SQLAlchemyInstrumentor().instrument(engine=engine)


# Flushes any buffered spans/metrics before the process exits.
def shutdown_telemetry() -> None:
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
    if _meter_provider is not None:
        _meter_provider.shutdown()
