from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
# TODO: Import proper rate limiting library

def setup_middlewares(app: FastAPI):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # TODO: Add rate limiting middleware using Redis and config.rate_limit_per_minute
