# routes/notifications.py
from fastapi import APIRouter, Depends
from server import db, get_current_user

router = APIRouter()

@router.get("/unread")
async def unread_notifications(current_user=Depends(get_current_user)):
    cursor = db.notifications.find({"to": current_user["email"], "read": False})
    out = []
    async for d in cursor:
        out.append({
            "from": d.get("from"),
            "type": d.get("type"),
            "created_at": d.get("created_at"),
            "id": str(d.get("_id")),
        })
    return {"notifications": out}

@router.post("/mark-read")
async def mark_read(payload: dict, current_user=Depends(get_current_user)):
    # payload: { "id": "<notification_id>" } or mark all
    nid = payload.get("id")
    if nid:
        await db.notifications.update_one({"_id": nid, "to": current_user["email"]}, {"$set": {"read": True}})
    else:
        await db.notifications.update_many({"to": current_user["email"]}, {"$set": {"read": True}})
    return {"detail": "ok"}
