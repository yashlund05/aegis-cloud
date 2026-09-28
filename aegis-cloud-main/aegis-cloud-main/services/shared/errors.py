from fastapi import Request
from fastapi.responses import JSONResponse

class AegisError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class PredictionError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 500)

class DecisionError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 500)

class ExecutionError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 502)

class TelemetryError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 503)

class ValidationError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 400)

class StaleDataError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 409)

class SolverTimeoutError(AegisError):
    def __init__(self, message: str):
        super().__init__(message, 408)

async def aegis_exception_handler(request: Request, exc: AegisError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.__class__.__name__, "message": exc.message}
    )
