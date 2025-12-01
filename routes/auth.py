# routes/auth.py
from fastapi import APIRouter, HTTPException, status, Depends
from server import db, hash_password, verify_password, create_access_token
from server import UserSignup, UserLogin, AuthResponse
from datetime import datetime


router = APIRouter()

@router.post("/signup", status_code=201, response_model=AuthResponse)
async def signup(user: UserSignup):
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
    "created_at": datetime.utcnow(),   #
    "points": 0,
    "streak": 0,
    "topics_completed": 0,
    "problems_solved": 0,
}


    res = await db.users.insert_one(doc)
    user_doc = await db.users.find_one({"_id": res.inserted_id})

    token = create_access_token({"sub": str(user_doc["_id"])})

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
    if not user or not verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

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
