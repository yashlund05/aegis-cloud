from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from services.shared.auth import create_token, get_current_user, TokenPayload, require_role
from services.api_gateway.service import AuthService

router = APIRouter()
auth_service = AuthService()

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await auth_service.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token(user_id=user["id"], role=user["role"])
    return TokenResponse(access_token=token)

@router.post("/auth/register", dependencies=[Depends(require_role(["admin"]))])
async def register(req: LoginRequest):
    # TODO: Implement user registration
    return {"status": "ok", "message": "User registered"}

# TODO: Proxy routes to other services
