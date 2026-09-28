import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from services.shared.config import config

security = HTTPBearer()

class TokenPayload(BaseModel):
    user_id: str
    role: str
    exp: datetime

def create_token(user_id: str, role: str) -> str:
    expires_delta = timedelta(hours=24)
    expire = datetime.utcnow() + expires_delta
    to_encode = {"user_id": user_id, "role": role, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, config.jwt_secret, algorithm=config.jwt_algorithm)
    return encoded_jwt

def verify_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> TokenPayload:
    return verify_token(credentials.credentials)

def require_role(allowed_roles: list[str]):
    def role_checker(user: TokenPayload = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return user
    return role_checker
