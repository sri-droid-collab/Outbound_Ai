from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings

settings = get_settings()

client = AsyncIOMotorClient(settings.mongo_uri)
db = client[settings.mongo_db_name]

contacts_collection = db["contacts"]
call_logs_collection = db["call_logs"]
clients_collection = db["clients"]
projects_collection = db["projects"]
users_collection = db["users"]
twilio_numbers_collection = db["twilio_numbers"]
lead_research_collection = db["lead_research"]
research_cache_collection = db["research_cache"]


async def ensure_indexes():
    """Create indexes for the new collections. Called once on app startup."""
    # Unique: one research document per contact. The repository's atomic
    # claim() relies on this to stop two clicks starting two runs.
    await lead_research_collection.create_index("contact_id", unique=True)
    await lead_research_collection.create_index("status")
    # Per-source cache for rate-limited public sources (news, Wikidata). Mongo deletes a document
    # once expires_at passes; the repository also checks it, since that sweep runs only about
    # once a minute.
    await research_cache_collection.create_index([("source", 1), ("key", 1)], unique=True)
    await research_cache_collection.create_index("expires_at", expireAfterSeconds=0)
    await clients_collection.create_index("phone")
    await clients_collection.create_index("domain")
    await clients_collection.create_index("contact_id")
    await clients_collection.create_index([("created_at", -1)])
    await projects_collection.create_index("processing_status")
    await projects_collection.create_index("metadata.domain")
    await projects_collection.create_index([("created_at", -1)])
    await users_collection.create_index("email", unique=True)
    await users_collection.create_index("assigned_number_ids")
    await twilio_numbers_collection.create_index("phone_number", unique=True)
