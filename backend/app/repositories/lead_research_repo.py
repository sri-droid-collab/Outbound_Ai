from datetime import datetime

from pymongo.errors import DuplicateKeyError

from app.database import lead_research_collection
from app.repositories.base import MongoRepository

ACTIVE_STATUSES = ["queued", "running"]


class LeadResearchRepository(MongoRepository):
    """One document per contact, keyed by `contact_id` (unique index)."""

    async def get(self, contact_id: str) -> dict | None:
        return await self.find_one({"contact_id": contact_id})

    async def claim(self, contact_id: str, fields: dict) -> bool:
        """Atomically start a run: create the document, or reset it if it
        isn't already queued/running. Returns False when another run holds it.

        The filter only matches a non-active document; for an active one the
        upsert tries to insert, hits the unique index, and we report the loss.
        """
        try:
            await self.update_one(
                {"contact_id": contact_id, "status": {"$nin": ACTIVE_STATUSES}},
                {"$set": fields, "$setOnInsert": {"created_at": datetime.utcnow()}},
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return True

    async def save(self, contact_id: str, fields: dict) -> None:
        await self.update_one(
            {"contact_id": contact_id}, {"$set": {**fields, "updated_at": datetime.utcnow()}}
        )

    async def set_step(self, contact_id: str, name: str, status: str) -> None:
        await self.update_one(
            {"contact_id": contact_id, "steps.name": name},
            {"$set": {"steps.$.status": status, "updated_at": datetime.utcnow()}},
        )

    async def list_statuses(self, limit: int = 1000) -> list[dict]:
        projection = {"contact_id": 1, "status": 1, "updated_at": 1, "completed_at": 1}
        return await self.find({}, projection=projection).limit(limit).to_list(limit)

    async def fail_interrupted(self, error: str) -> int:
        """Mark runs left queued/running by a previous process as failed."""
        result = await self.update_many(
            {"status": {"$in": ACTIVE_STATUSES}},
            {"$set": {"status": "failed", "error": error, "updated_at": datetime.utcnow()}},
        )
        return result.modified_count


lead_research_repo = LeadResearchRepository(lead_research_collection)
