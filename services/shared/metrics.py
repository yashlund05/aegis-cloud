import time
from fastapi import Request
from prometheus_client import Histogram, Counter, Gauge

request_duration = Histogram(
    "request_duration_seconds", 
    "Duration of HTTP requests in seconds",
    ["method", "endpoint"]
)

request_count = Counter(
    "request_count_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"]
)

active_requests = Gauge(
    "active_requests",
    "Number of active HTTP requests"
)

errors_count = Counter(
    "errors_count_total",
    "Total number of errors",
    ["type"]
)

async def metrics_middleware(request: Request, call_next):
    method = request.method
    endpoint = request.url.path
    
    active_requests.inc()
    start_time = time.time()
    
    try:
        response = await call_next(request)
        status_code = response.status_code
        request_count.labels(method=method, endpoint=endpoint, status_code=status_code).inc()
        return response
    except Exception as e:
        errors_count.labels(type=type(e).__name__).inc()
        request_count.labels(method=method, endpoint=endpoint, status_code=500).inc()
        raise e
    finally:
        duration = time.time() - start_time
        request_duration.labels(method=method, endpoint=endpoint).observe(duration)
        active_requests.dec()
