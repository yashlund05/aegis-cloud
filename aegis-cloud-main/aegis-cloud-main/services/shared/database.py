import asyncpg
from services.shared.config import config
from services.shared.logging import setup_logging

logger = setup_logging("database")

class DatabaseManager:
    def __init__(self):
        self.pool = None

    async def get_pool(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(
                user=config.postgres_user,
                password=config.postgres_password,
                database=config.postgres_db,
                host=config.postgres_host,
                port=config.postgres_port
            )
            logger.info("Database connection pool created")
        return self.pool

    async def close_pool(self):
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")

    async def execute_query(self, query: str, *args):
        pool = await self.get_pool()
        async with pool.acquire() as connection:
            return await connection.fetch(query, *args)

db = DatabaseManager()
