from dotenv import load_dotenv
load_dotenv()
import os
import logging
from typing import Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext

# ---------------------------
# Load ENV variables
# ---------------------------
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME", "nstrack")
JWT_SECRET = os.getenv("JWT_SECRET")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

if not MONGO_URL:
    raise RuntimeError("MONGO_URL not set")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET not set")

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------
# FastAPI App + Router
# ---------------------------
app = FastAPI()
api = APIRouter(prefix="/api")

# ---------------------------
# CORS
# ---------------------------
origins = [
    "http://localhost:3000",
    "https://nstrack-frontend.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# MongoDB
# ---------------------------
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
users_collection = db["users"]
notifications_collection = db["notifications"]

# ---------------------------
# Security & Password Hashing
# ---------------------------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    return pwd_context.hash(password)

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

# ---------------------------
# JWT Helpers
# ---------------------------
def create_access_token(data: dict, expires_minutes=60):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)

# ---------------------------
# Pydantic Models
# ---------------------------
class UserSignup(BaseModel):
    name: str
    email: EmailStr
    password: str
    skill_level: str
    batch: Optional[str] = None
    gender: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ------------------------------------------------------------
# ROUTES UNDER /api/auth
# ------------------------------------------------------------

@api.post("/auth/signup")
async def signup(user: UserSignup):
    # Check existing user
    existing = await users_collection.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_pw = hash_password(user.password)

    user_data = {
        "name": user.name,
        "email": user.email,
        "password": hashed_pw,
        "skill_level": user.skill_level,
        "batch": user.batch,
        "gender": user.gender,
        "points": 10,
        "created_at": datetime.utcnow(),
    }

    await users_collection.insert_one(user_data)

    token = create_access_token({"email": user.email})

    return {
        "message": "Signup success",
        "access_token": token,
        "user": {
            "name": user.name,
            "email": user.email,
            "points": 10,
        }
    }


@api.post("/auth/login")
async def login(user: UserLogin):
    found = await users_collection.find_one({"email": user.email})
    if not found:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(user.password, found["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"email": user.email})

    return {
        "message": "Login successful",
        "access_token": token,
        "user": {
            "name": found["name"],
            "email": found["email"],
            "points": found.get("points", 0)
        }
    }


# ------------------------------------------------------------
# NOTIFICATIONS ROUTES
# ------------------------------------------------------------
@api.get("/notifications/unread")
async def get_unread_notifications():
    notifications = await notifications_collection.find({"read": False}).to_list(100)
    return notifications


# ------------------------------------------------------------
# HEALTH CHECK
# ------------------------------------------------------------
@api.get("/health")
async def health():
    return {"status": "ok"}


# ------------------------------------------------------------
# Include Router
# ------------------------------------------------------------
app.include_router(api)

# ------------------------------------------------------------
# Shutdown Hook
# ------------------------------------------------------------
@app.on_event("shutdown")
def shutdown():
    client.close()
    logger.info("MongoDB client closed.")
