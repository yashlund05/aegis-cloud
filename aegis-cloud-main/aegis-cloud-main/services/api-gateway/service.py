from typing import Optional, Dict
import hashlib
import sqlite3
import os

class AuthService:
    def __init__(self):
        self.db_path = "users.db"
        self._init_db()
        
    def _init_db(self):
        if not os.path.exists(self.db_path):
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE users (username text, password_hash text, role text)''')
            # Insert default admin
            admin_hash = hashlib.sha256("admin".encode()).hexdigest()
            op_hash = hashlib.sha256("operator".encode()).hexdigest()
            c.execute("INSERT INTO users VALUES ('admin', ?, 'admin')", (admin_hash,))
            c.execute("INSERT INTO users VALUES ('operator', ?, 'operator')", (op_hash,))
            conn.commit()
            conn.close()

    async def authenticate(self, username: str, password: str) -> Optional[Dict]:
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE username=? AND password_hash=?", (username, pwd_hash))
        row = c.fetchone()
        conn.close()
        
        if row:
            return {"username": username, "role": row[0]}
        return None
        
    async def register(self, username: str, password: str, role: str) -> bool:
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT 1 FROM users WHERE username=?", (username,))
            if c.fetchone():
                return False
            c.execute("INSERT INTO users VALUES (?, ?, ?)", (username, pwd_hash, role))
            conn.commit()
            return True
        finally:
            conn.close()
