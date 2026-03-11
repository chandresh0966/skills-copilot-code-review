"""Announcement endpoints for the High School Management System API."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementInput(BaseModel):
    """Input model for creating or updating an announcement."""

    message: str = Field(min_length=1, max_length=500)
    expiration_date: str
    start_date: Optional[str] = None


def parse_iso_datetime(value: str, field_name: str) -> datetime:
    """Parse an ISO datetime and raise a 400 if invalid."""
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}. Use ISO-8601 datetime format."
        ) from exc


def ensure_authenticated_user(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Validate that a signed in teacher exists."""
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def serialize_announcement(announcement: Dict[str, Any]) -> Dict[str, Any]:
    """Convert database object to API response shape."""
    return {
        "id": str(announcement["_id"]),
        "message": announcement["message"],
        "start_date": announcement.get("start_date"),
        "expiration_date": announcement["expiration_date"],
        "created_by": announcement.get("created_by")
    }


@router.get("", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get currently active announcements visible to all users."""
    now = datetime.utcnow()
    active_announcements: List[Dict[str, Any]] = []

    for item in announcements_collection.find({}):
        expiration_date = parse_iso_datetime(item["expiration_date"], "expiration_date")
        if expiration_date < now:
            continue

        start_date_raw = item.get("start_date")
        if start_date_raw:
            start_date = parse_iso_datetime(start_date_raw, "start_date")
            if start_date > now:
                continue

        active_announcements.append(serialize_announcement(item))

    active_announcements.sort(key=lambda row: row["expiration_date"])
    return active_announcements


@router.get("/all", response_model=List[Dict[str, Any]])
def get_all_announcements(
    teacher_username: Optional[str] = Query(None)
) -> List[Dict[str, Any]]:
    """Get all announcements, including expired or future ones, for signed in users."""
    ensure_authenticated_user(teacher_username)

    announcements: List[Dict[str, Any]] = []
    for item in announcements_collection.find({}).sort("expiration_date", 1):
        announcements.append(serialize_announcement(item))

    return announcements


@router.post("", response_model=Dict[str, Any])
def create_announcement(
    payload: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement. Only signed in users can do this."""
    teacher = ensure_authenticated_user(teacher_username)

    expiration_date = parse_iso_datetime(payload.expiration_date, "expiration_date")
    if payload.start_date:
        start_date = parse_iso_datetime(payload.start_date, "start_date")
        if start_date > expiration_date:
            raise HTTPException(
                status_code=400,
                detail="start_date must be before or equal to expiration_date"
            )

    new_announcement = {
        "message": payload.message.strip(),
        "start_date": payload.start_date,
        "expiration_date": payload.expiration_date,
        "created_by": teacher["_id"]
    }

    result = announcements_collection.insert_one(new_announcement)
    inserted_announcement = {**new_announcement, "_id": result.inserted_id}
    return serialize_announcement(inserted_announcement)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    payload: AnnouncementInput,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement. Only signed in users can do this."""
    ensure_authenticated_user(teacher_username)

    expiration_date = parse_iso_datetime(payload.expiration_date, "expiration_date")
    if payload.start_date:
        start_date = parse_iso_datetime(payload.start_date, "start_date")
        if start_date > expiration_date:
            raise HTTPException(
                status_code=400,
                detail="start_date must be before or equal to expiration_date"
            )

    if not ObjectId.is_valid(announcement_id):
        raise HTTPException(status_code=404, detail="Announcement not found")

    result = announcements_collection.update_one(
        {"_id": ObjectId(announcement_id)},
        {
            "$set": {
                "message": payload.message.strip(),
                "start_date": payload.start_date,
                "expiration_date": payload.expiration_date
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": ObjectId(announcement_id)})
    return serialize_announcement(updated)


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an existing announcement. Only signed in users can do this."""
    ensure_authenticated_user(teacher_username)

    if not ObjectId.is_valid(announcement_id):
        raise HTTPException(status_code=404, detail="Announcement not found")

    result = announcements_collection.delete_one({"_id": ObjectId(announcement_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
