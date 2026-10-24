from datetime import datetime, timedelta

from app.repositories.source_cache_repo import SourceCacheRepository


class FakeCollection:
    """The slice of a Motor collection the cache repository uses."""

    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}

    async def find_one(self, filter_, **kwargs):
        return self.docs.get((filter_["source"], filter_["key"]))

    async def update_one(self, filter_, update, upsert=False, **kwargs):
        key = (filter_["source"], filter_["key"])
        if key not in self.docs and not upsert:
            return
        self.docs.setdefault(key, {"source": key[0], "key": key[1]}).update(update["$set"])


async def test_stored_payload_is_returned_until_it_expires():
    repo = SourceCacheRepository(FakeCollection())

    await repo.put("news", "acme", {"items": [1]}, ttl_seconds=3600)

    assert await repo.get("news", "acme") == {"items": [1]}


async def test_expired_entries_are_ignored_even_before_mongo_sweeps_them():
    collection = FakeCollection()
    repo = SourceCacheRepository(collection)
    await repo.put("news", "acme", {"items": [1]}, ttl_seconds=3600)
    collection.docs[("news", "acme")]["expires_at"] = datetime.utcnow() - timedelta(seconds=1)

    assert await repo.get("news", "acme") is None


async def test_missing_entries_return_none_and_sources_do_not_collide():
    repo = SourceCacheRepository(FakeCollection())
    await repo.put("news", "acme", {"a": 1}, 60)

    assert await repo.get("news", "other") is None
    assert await repo.get("wikidata", "acme") is None


async def test_putting_again_replaces_the_payload_and_extends_the_expiry():
    collection = FakeCollection()
    repo = SourceCacheRepository(collection)
    await repo.put("news", "acme", {"v": 1}, ttl_seconds=60)
    first_expiry = collection.docs[("news", "acme")]["expires_at"]

    await repo.put("news", "acme", {"v": 2}, ttl_seconds=7200)

    assert await repo.get("news", "acme") == {"v": 2}
    assert collection.docs[("news", "acme")]["expires_at"] > first_expiry
    assert len(collection.docs) == 1
