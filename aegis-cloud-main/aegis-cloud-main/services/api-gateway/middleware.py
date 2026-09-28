import time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from .config import config

class RateLimiter:
    def __init__(self, limit: int = 100):
        self.limit = limit
        self.requests = {}
        
    async def __call__(self, request: Request, call_next):
        client_ip = request.client.host
        current_time = time.time()
        
        if client_ip not in self.requests:
            self.requests[client_ip] = []
            
        # Clean up old requests (older than 1 minute)
        self.requests[client_ip] = [t for t in self.requests[client_ip] if current_time - t < 60]
        
        if len(self.requests[client_ip]) >= self.limit:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
            
        self.requests[client_ip].append(current_time)
        return await call_next(request)

def setup_middleware(app):
    limiter = RateLimiter(config.rate_limit_per_minute)
    app.middleware("http")(limiter)
