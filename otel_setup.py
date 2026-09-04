from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

_RESOURCE = Resource.create({"service.name": "simpleapp"})

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


# SimpleSpanProcessor (synchronous per-span export) not BatchSpanProcessor: this
# app's traffic is trivial, so there's no batching win — a production-grade version
# would batch to cut exporter overhead under real load. Console exporters are this
# step's deliberate scope; a real OTLP endpoint arrives in Step D.
def configure_telemetry() -> None:
    global _tracer_provider, _meter_provider

    _tracer_provider = TracerProvider(resource=_RESOURCE)
    _tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_tracer_provider)

    # 5s export interval (default is 60s) so metrics show up quickly during local testing.
    metric_reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=5000)
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
