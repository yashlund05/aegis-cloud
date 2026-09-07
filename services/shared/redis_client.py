import redis.asyncio as redis
import json
from services.shared.config import config
from services.shared.logging import setup_logging

logger = setup_logging("redis_client")

class RedisManager:
    def __init__(self):
        self.client = None

    async def get_redis(self):
        if not self.client:
            self.client = redis.Redis(
                host=config.redis_host,
                port=config.redis_port,
                db=config.redis_db,
                decode_responses=True
            )
            logger.info("Redis connection established")
        return self.client

    async def close_redis(self):
        if self.client:
            await self.client.aclose()
            logger.info("Redis connection closed")

    async def get_features(self, key: str):
        client = await self.get_redis()
        data = await client.get(key)
        return json.loads(data) if data else None

    async def set_features(self, key: str, value: dict, expire: int = 3600):
        client = await self.get_redis()
        await client.set(key, json.dumps(value), ex=expire)

    async def publish(self, channel: str, message: dict):
        client = await self.get_redis()
        await client.publish(channel, json.dumps(message))

    async def subscribe(self, channel: str):
        client = await self.get_redis()
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

redis_client = RedisManager()
