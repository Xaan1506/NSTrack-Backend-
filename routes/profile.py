# routes/profile.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr
from typing import Any
from server import db, get_current_user, ProfileOut

router = APIRouter()

@router.get("/auth/profile", response_model=ProfileOut)
async def get_profile(current_user=Depends(get_current_user)):
    # current_user is the raw document from db
    return {
        "name": current_user.get("name"),
        "email": current_user.get("email"),
        "skillLevel": current_user.get("skill_level"),
        "batch": current_user.get("batch"),
        "gender": current_user.get("gender"),
    }
