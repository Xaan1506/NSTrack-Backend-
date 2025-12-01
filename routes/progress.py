# routes/progress.py
from fastapi import APIRouter, Depends
from typing import List
from server import db, get_current_user
from datetime import datetime

router = APIRouter()

@router.get("/")
async def get_progress(current_user=Depends(get_current_user)):
    cursor = db.progress.find({"email": current_user["email"]})
    arr = []
    async for d in cursor:
        arr.append(d)
    return {"progress": arr}

@router.post("/")
async def post_progress(payload: dict, current_user=Depends(get_current_user)):
    # payload example: {"chapter": "Arrays", "completed": True, "score": 90}
    doc = {
        "email": current_user["email"],
        "payload": payload,
        "created_at": datetime.utcnow()
    }
    await db.progress.insert_one(doc)
    return {"detail": "saved"}
