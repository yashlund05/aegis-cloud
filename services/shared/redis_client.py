import json
from services.shared.config import config
from services.shared.logging import setup_logging

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

logger = setup_logging("redis_client")


class RedisManager:
    def __init__(self):
        self.client = None
        self._in_memory_cache = {}

    async def get_redis(self):
        if redis is None:
            return None
        if not self.client:
            try:
                self.client = redis.Redis(
                    host=config.redis_host,
                    port=config.redis_port,
                    db=config.redis_db,
                    decode_responses=True,
                )
                logger.info("Redis connection established")
            except Exception as e:
                logger.debug(f"Redis connection creation deferred: {e}")
                return None
        return self.client

    async def close_redis(self):
        if self.client:
            try:
                await self.client.aclose()
                logger.info("Redis connection closed")
            except Exception:
                pass

    async def get_features(self, key: str):
        client = await self.get_redis()
        if client:
            try:
                data = await client.get(key)
                return json.loads(data) if data else None
            except Exception:
                pass
        return self._in_memory_cache.get(key)

    async def set_features(self, key: str, value: dict, expire: int = 3600):
        self._in_memory_cache[key] = value
        client = await self.get_redis()
        if client:
            try:
                await client.set(key, json.dumps(value), ex=expire)
            except Exception:
                pass

    async def publish(self, channel: str, message: dict):
        client = await self.get_redis()
        if client:
            try:
                await client.publish(channel, json.dumps(message))
            except Exception:
                pass

    async def subscribe(self, channel: str):
        client = await self.get_redis()
        if client:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            return pubsub
        return None


redis_client = RedisManager()
