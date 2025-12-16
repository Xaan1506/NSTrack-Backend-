# routes/notifications.py
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from server import db, get_current_user

router = APIRouter()

# Get all unread notifications
@router.get("/unread")
async def unread_notifications(
    current_user: dict = Depends(get_current_user)
):
    cursor = db.notifications.find(
        {"to": current_user["email"], "read": False}
    )

    out = []
    async for d in cursor:
        out.append({
            "id": str(d.get("_id")),
            "from": d.get("from"),
            "type": d.get("type"),
            "created_at": d.get("created_at"),
        })

    return {"notifications": out}


# Mark notification as read (single or all)
@router.post("/mark-read")
async def mark_read(
    payload: dict,
    current_user: dict = Depends(get_current_user)
):
    nid = payload.get("id")

    if nid:
        # mark single notification
        try:
            oid = ObjectId(nid)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid notification id")

        await db.notifications.update_one(
            {"_id": oid, "to": current_user["email"]},
            {"$set": {"read": True}}
        )
    else:
        # mark all notifications
        await db.notifications.update_many(
            {"to": current_user["email"]},
            {"$set": {"read": True}}
        )

    return {"detail": "ok"}
