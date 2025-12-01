# routes/auth.py
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import EmailStr
from server import db, hash_password, verify_password, create_access_token
from server import UserSignup, UserLogin, Token, ProfileOut, AuthResponse
from typing import Any
from datetime import timedelta

router = APIRouter()

@router.post("/signup", status_code=201, response_model=AuthResponse)
async def signup(user: UserSignup):
    # check existing
    existing = await db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = hash_password(user.password)
    doc = {
        "name": user.name,
        "email": user.email,
        "password": hashed,
        "skill_level": user.skill_level,
        "batch": user.batch,
        "gender": user.gender,
        "created_at": None,
    }
    res = await db.users.insert_one(doc)
    user_doc = await db.users.find_one({"_id": res.inserted_id})
    # create token and return same shape as login so frontend can proceed to dashboard
    token = create_access_token({"sub": str(user_doc.get("_id"))})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "name": user_doc.get("name"),
            "email": user_doc.get("email"),
            "skillLevel": user_doc.get("skill_level"),
            "batch": user_doc.get("batch"),
            "gender": user_doc.get("gender"),
        },
    }

@router.post("/login", response_model=AuthResponse)
async def login(payload: UserLogin):
    user = await db.users.find_one({"email": payload.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    # create token with subject = user id
    token = create_access_token({"sub": str(user["_id"])})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "name": user.get("name"),
            "email": user.get("email"),
            "skillLevel": user.get("skill_level"),
            "batch": user.get("batch"),
            "gender": user.get("gender"),
        },
    }

@router.get("/profile", response_model=ProfileOut)
async def profile(current_user=Depends(lambda: None)):
    # This route will be handled in profile.py with real dependency, but keep a simple check
    raise HTTPException(status_code=501, detail="Use /api/profile (GET) in profile router")
