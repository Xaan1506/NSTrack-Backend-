# routes/profile.py
from fastapi import APIRouter, Depends
from server import get_current_user

router = APIRouter()

@router.get("/profile")
async def get_profile(current_user = Depends(get_current_user)):
    created = current_user.get("created_at")

    # Convert datetime to ISO string if needed
    if created:
        try:
            created = created.isoformat()
        except:
            pass

    return {
        "name": current_user.get("name"),
        "email": current_user.get("email"),
        "skillLevel": current_user.get("skill_level"),
        "batch": current_user.get("batch"),
        "gender": current_user.get("gender"),

        # FIXED: Member Since date
        "createdAt": created,

        # FIXED: default values so UI shows correctly
        "points": current_user.get("points", 0),
        "streak": current_user.get("streak", 0),
        "topicsCompleted": current_user.get("topics_completed", 0),
        "problemsSolved": current_user.get("problems_solved", 0),
    }
