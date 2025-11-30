import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
env_path = ROOT_DIR / '.env'
if env_path.exists():
    load_dotenv(env_path)

async def debug_db():
    mongo_url = os.environ.get('MONGO_URL')
    if not mongo_url:
        print("MONGO_URL not found. Set it in the environment or .env file.")
        return

    client = AsyncIOMotorClient(mongo_url)
    db_name = os.environ.get('DB_NAME', 'nstrack')
    db = client[db_name]
    
    print("\n--- USERS ---")
    async for user in db.users.find({}, {"email": 1, "name": 1}):
        print(f"User: {user.get('name')} | Email: {user.get('email')}")
        
    print("\n--- PASSWORD RESET TOKENS ---")
    async for token in db.password_resets.find({}):
        print(f"Token for: {token.get('email')} | Code: {token.get('token')} | Expires: {token.get('expires_at')}")

if __name__ == "__main__":
    asyncio.run(debug_db())

ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get('ACCESS_TOKEN_EXPIRE_MINUTES', '30'))
