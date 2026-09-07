# Aegis API Gateway

Responsibility: JWT auth, routing, rate limiting, API versioning.

## Endpoints
- `POST /auth/login`
- `POST /auth/register` (admin only)
- `GET /v1/health`
- Proxy routes to other services (TODO)

## Config
See `config.py`

## Running Locally
```bash
uvicorn main:app --reload
```
