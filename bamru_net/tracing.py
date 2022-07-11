from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

def _django_response_hook(span, request, response):
    if span and span.is_recording():
        # Do this on response because the instrumentation middleware may run
        # before the user attribute is set on request.
        if hasattr(request, "user"):
            span.set_attribute("username", str(request.user))

def setup_tracing():
    provider = TracerProvider()
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    LoggingInstrumentor().instrument()
    DjangoInstrumentor().instrument(response_hook=_django_response_hook)
    # Skip dep checks because we use psycopg2-binary.
    Psycopg2Instrumentor().instrument(skip_dep_check=True)
    URLLib3Instrumentor().instrument()
