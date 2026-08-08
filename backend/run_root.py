import asyncio
from app.core.database import Database
from app.core.config import settings
from app.services.identity_tree import current_root

async def main():
    await Database.connect(settings.MONGO_URL, settings.MONGODB_DB_NAME)
    root = await current_root()
    print(root)
    await Database.close()

if __name__ == "__main__":
    asyncio.run(main())
