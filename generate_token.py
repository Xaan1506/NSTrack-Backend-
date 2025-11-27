import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

# Load env vars
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

async def generate_token():
    mongo_url = os.environ.get('MONGO_URL')
    if not mongo_url:
        print("MONGO_URL not found")
        return

    client = AsyncIOMotorClient(mongo_url)
    db_name = os.environ.get('DB_NAME', 'nstrack')
    db = client[db_name]
    
    email = "e25b070726@adypu.edu.in" # Lowercase
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    reset_token = {
        "email": email,
        "token": token,
        "type": "reset",
        "expires_at": expires_at
    }
    
    await db.password_resets.insert_one(reset_token)
    print(f"GENERATED TOKEN: {token}")

if __name__ == "__main__":
    asyncio.run(generate_token())
