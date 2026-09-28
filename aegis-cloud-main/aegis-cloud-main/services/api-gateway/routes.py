from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from services.api_gateway.service import AuthService
import httpx

router = APIRouter()
auth_service = AuthService()

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    role: str = "operator"

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await auth_service.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Simplified token for now
    token = f"{user['username']}:{user['role']}:token"
    return TokenResponse(access_token=token, token_type="bearer")

@router.post("/auth/register")
async def register(req: RegisterRequest):
    success = await auth_service.register(req.username, req.password, req.role)
    if not success:
        raise HTTPException(status_code=400, detail="User already exists")
    return {"status": "User registered successfully"}

# Proxy route example for predictor
@router.post("/api/v1/predict")
async def proxy_predict(payload: dict):
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post("http://predictor:8000/v1/predict", json=payload)
            return resp.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Failed to connect to predictor: {exc}")
