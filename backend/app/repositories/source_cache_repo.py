from datetime import datetime, timedelta

from app.database import research_cache_collection
from app.repositories.base import MongoRepository


class SourceCacheRepository(MongoRepository):
    """Small TTL cache of collector output, keyed by (source, key)."""

    async def get(self, source: str, key: str) -> dict | None:
        doc = await self.find_one({"source": source, "key": key})
        if not doc or doc["expires_at"] <= datetime.utcnow():
            return None
        return doc["payload"]

    async def put(self, source: str, key: str, payload: dict, ttl_seconds: int) -> None:
        now = datetime.utcnow()
        await self.update_one(
            {"source": source, "key": key},
            {
                "$set": {
                    "payload": payload,
                    "fetched_at": now,
                    "expires_at": now + timedelta(seconds=ttl_seconds),
                }
            },
            upsert=True,
        )


source_cache_repo = SourceCacheRepository(research_cache_collection)
