# routes/friends.py
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from datetime import datetime
from server import db, get_current_user

router = APIRouter()

# send friend request
@router.post("/request")
async def send_friend_request(payload: dict, current_user=Depends(get_current_user)):
    """
    payload should contain: { "to_email": "friend@example.com" }
    """
    to_email = payload.get("to_email")
    if not to_email:
        raise HTTPException(status_code=400, detail="to_email required")
    to_user = await db.users.find_one({"email": to_email})
    if not to_user:
        raise HTTPException(status_code=404, detail="Target user not found")
    # don't duplicate
    exists = await db.friends.find_one({
        "from": current_user["email"],
        "to": to_email,
        "status": {"$in": ["pending", "accepted"]}
    })
    if exists:
        raise HTTPException(status_code=400, detail="Request already exists")
    doc = {
        "from": current_user["email"],
        "to": to_email,
        "status": "pending",
        "created_at": datetime.utcnow()
    }
    await db.friends.insert_one(doc)
    # create a notification
    await db.notifications.insert_one({
        "to": to_email,
        "from": current_user["email"],
        "type": "friend_request",
        "read": False,
        "created_at": datetime.utcnow()
    })
    return {"detail": "request sent"}

# accept request
@router.post("/accept")
async def accept_request(payload: dict, current_user=Depends(get_current_user)):
    """
    payload: { "from_email": "sender@example.com" }
    """
    from_email = payload.get("from_email")
    if not from_email:
        raise HTTPException(status_code=400, detail="from_email required")
    res = await db.friends.find_one_and_update(
        {"from": from_email, "to": current_user["email"], "status": "pending"},
        {"$set": {"status": "accepted", "updated_at": datetime.utcnow()}},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Friend request not found")
    return {"detail": "accepted"}

# reject request
@router.post("/reject")
async def reject_request(payload: dict, current_user=Depends(get_current_user)):
    from_email = payload.get("from_email")
    if not from_email:
        raise HTTPException(status_code=400, detail="from_email required")
    res = await db.friends.find_one_and_update(
        {"from": from_email, "to": current_user["email"], "status": "pending"},
        {"$set": {"status": "rejected", "updated_at": datetime.utcnow()}},
    )
    if not res:
        raise HTTPException(status_code=404, detail="Friend request not found")
    return {"detail": "rejected"}

# list all accepted friends for current user
@router.get("/list")
async def list_friends(current_user=Depends(get_current_user)):
    email = current_user["email"]
    # outgoing accepted
    out = db.friends.find({"from": email, "status": "accepted"})
    in_ = db.friends.find({"to": email, "status": "accepted"})
    friends = set()
    async for doc in out:
        friends.add(doc["to"])
    async for doc in in_:
        friends.add(doc["from"])
    return {"friends": list(friends)}

# incoming/outgoing pending lists
@router.get("/requests/incoming")
async def incoming_requests(current_user=Depends(get_current_user)):
    cursor = db.friends.find({"to": current_user["email"], "status": "pending"})
    arr = []
    async for d in cursor:
        arr.append({"from": d["from"], "created_at": d["created_at"]})
    return {"incoming": arr}

@router.get("/requests/outgoing")
async def outgoing_requests(current_user=Depends(get_current_user)):
    cursor = db.friends.find({"from": current_user["email"], "status": "pending"})
    arr = []
    async for d in cursor:
        arr.append({"to": d["to"], "created_at": d["created_at"]})
    return {"outgoing": arr}
