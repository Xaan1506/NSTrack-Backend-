# server.py
import os
import asyncio
from typing import Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field
from passlib.context import CryptContext
from jose import JWTError, jwt
from dotenv import load_dotenv

# load .env
load_dotenv()

MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME", "nstrack")
JWT_SECRET = os.getenv("JWT_SECRET", "change_this")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

if not MONGO_URL:
    raise RuntimeError("MONGO_URL not set in .env")

# DB client
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

app = FastAPI(title="NSTrack Backend (FastAPI)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for dev; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# helpers
def hash_password(password: str) -> str:
    # bcrypt / passlib handles up to 72 bytes; truncate safely if needed
    if isinstance(password, str):
        pw = password
    else:
        pw = str(password)
    if len(pw.encode("utf-8")) > 72:
        pw = pw.encode("utf-8")[:72].decode("utf-8", errors="ignore")
    return pwd_context.hash(pw)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded

async def get_user_by_email(email: str):
    return await db.users.find_one({"email": email})

async def get_user_by_id(user_id: str):
    return await db.users.find_one({"_id": user_id})

# Pydantic models (allow camelCase from frontend)
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: ProfileOut

class UserSignup(BaseModel):
    name: str
    email: EmailStr
    password: str
    skill_level: Optional[str] = Field(None, alias="skillLevel")
    batch: Optional[str] = None
    gender: Optional[str] = None

    class Config:
        allow_population_by_field_name = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class ProfileOut(BaseModel):
    name: str
    email: EmailStr
    skill_level: Optional[str] = Field(None, alias="skillLevel")
    batch: Optional[str] = None
    gender: Optional[str] = None

    class Config:
        orm_mode = True
        allow_population_by_field_name = True

# auth utils
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise credentials_exception
    return user

# include routers (these files will import app/db/pwd_context via from server import db, create_access_token, ...)
# to avoid circular import we'll import them late
from routes import auth, friends, notifications, profile, progress  # type: ignore

app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(friends.router, prefix="/api/friends", tags=["Friends"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(profile.router, prefix="/api", tags=["Profile"])
app.include_router(progress.router, prefix="/api/progress", tags=["Progress"])


@app.on_event("shutdown")
def shutdown_db_client():
    client.close()
