from typing import Optional, Dict

class AuthService:
    async def authenticate(self, username: str, password: str) -> Optional[Dict]:
        # TODO: Implement proper database lookup for users and password hashing verification
        if username == "admin" and password == "admin":
            return {"id": "1", "role": "admin"}
        if username == "operator" and password == "operator":
            return {"id": "2", "role": "operator"}
        return None
