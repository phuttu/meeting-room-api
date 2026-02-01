from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List, Final
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path, status
from pydantic import BaseModel, Field
from zoneinfo import ZoneInfo
import threading
from threading import Lock


APP_TZ = ZoneInfo("Europe/Helsinki")
BUSINESS_START = time(8, 0)
BUSINESS_END = time(16, 0)
MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(hours=8)

ROOMS: Final[set[str]] = {"A", "B"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_room(room_id: str) -> str:
    room_id = room_id.upper()
    if room_id not in ROOMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found. Allowed rooms: {sorted(ROOMS)}",
        )
    return room_id


def parse_iso_to_utc(iso_str: str) -> datetime:
    """
    Accepts ISO 8601 string. If naive (no offset), treat as Europe/Helsinki local time.
    Returns timezone-aware datetime in UTC.
    """
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid ISO 8601 datetime: '{iso_str}'")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)

    # Convert to UTC for normalized storage/comparison
    return dt.astimezone(timezone.utc)


def to_helsinki(dt_utc: datetime) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(APP_TZ)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    # Half-open intervals [start, end)
    return a_start < b_end and b_start < a_end


def validate_business_rules(start_utc: datetime, end_utc: datetime) -> None:
    if start_utc >= end_utc:
        raise HTTPException(status_code=400, detail="Start time must be before end time.")

    now = now_utc()
    now_floor_to_minute = now.replace(second=0, microsecond=0)
    if start_utc < now_floor_to_minute:
        raise HTTPException(status_code=400, detail="Reservation start time cannot be in the past.")
    
    # Convert to Helsinki local time for local rules (also used for business-hour checks)
    start_local = to_helsinki(start_utc)
    end_local = to_helsinki(end_utc)
    
    # Allow reservations only in 30-minute blocks in Helsinki local time (xx:00 or xx:30)
    if start_local.minute % 30 != 0 or end_local.minute % 30 != 0:
        raise HTTPException(
            status_code=400,
            detail="Reservations must start and end at 30-minute intervals (xx:00 or xx:30)."
        )
    
    duration = end_utc - start_utc
    if duration < MIN_DURATION:
        raise HTTPException(status_code=400, detail="Reservation duration must be at least 30 minutes.")
    if duration > MAX_DURATION:
        raise HTTPException(status_code=400, detail="Reservation duration must be at most 8 hours.")

    # Enforce that reservation stays within a single local day (practical for office hours)
    if start_local.date() != end_local.date():
        raise HTTPException(status_code=400, detail="Reservation must be within a single local day (Europe/Helsinki).")

    if not (BUSINESS_START <= start_local.timetz().replace(tzinfo=None) <= BUSINESS_END):
        raise HTTPException(status_code=400, detail="Reservation start must be within office hours 08:00–16:00.")

    if not (BUSINESS_START <= end_local.timetz().replace(tzinfo=None) <= BUSINESS_END):
        raise HTTPException(status_code=400, detail="Reservation end must be within office hours 08:00–16:00.")

    if start_local.time() == BUSINESS_END:
        raise HTTPException(status_code=400, detail="Reservation cannot start at 16:00 (office closes).")


class CreateReservationRequest(BaseModel):
    start: str = Field(..., description="ISO 8601 datetime (local Europe/Helsinki if no offset)")
    end: str = Field(..., description="ISO 8601 datetime (local Europe/Helsinki if no offset)")


class ReservationResponse(BaseModel):
    id: str
    room: str
    start: str  # ISO 8601 in Europe/Helsinki
    end: str    # ISO 8601 in Europe/Helsinki


@dataclass(frozen=True)
class Reservation:
    id: str
    room: str
    start_utc: datetime
    end_utc: datetime


class InMemoryStore:
    def __init__(self) -> None:
        self._lock: Lock = Lock()
        self._by_room: Dict[str, List[Reservation]] = {room: [] for room in ROOMS}

    def list_room(self, room: str) -> List[Reservation]:
        with self._lock:
            return sorted(self._by_room[room], key=lambda r: r.start_utc)

    def create(self, room: str, start_utc: datetime, end_utc: datetime) -> Reservation:
        validate_business_rules(start_utc, end_utc)

        with self._lock:
            existing = self._by_room[room]
            for r in existing:
                if overlaps(start_utc, end_utc, r.start_utc, r.end_utc):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Reservation overlaps with an existing reservation in the same room.",
                    )

            new_res = Reservation(id=str(uuid4()), room=room, start_utc=start_utc, end_utc=end_utc)
            existing.append(new_res)
            return new_res

    def delete(self, room: str, reservation_id: str) -> None:
        with self._lock:
            reservations = self._by_room[room]
            for i, r in enumerate(reservations):
                if r.id == reservation_id:
                    reservations.pop(i)
                    return
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found.")


store = InMemoryStore()
app = FastAPI(title="Meeting Room Booking API", version="1.0.0")


def to_response(r: Reservation) -> ReservationResponse:
    start_local = to_helsinki(r.start_utc).isoformat()
    end_local = to_helsinki(r.end_utc).isoformat()
    return ReservationResponse(id=r.id, room=r.room, start=start_local, end=end_local)


@app.post(
    "/rooms/{room_id}/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)

def create_reservation(
    room_id: str = Path(..., description="Room id (A or B)"),
    body: CreateReservationRequest = ...,
) -> ReservationResponse:
    room = ensure_room(room_id)
    start_utc = parse_iso_to_utc(body.start)
    end_utc = parse_iso_to_utc(body.end)
    created = store.create(room, start_utc, end_utc)
    return to_response(created)


@app.get(
    "/rooms/{room_id}/reservations",
    response_model=list[ReservationResponse],
)

def list_reservations(
    room_id: str = Path(..., description="Room id (A or B)")
) -> list[ReservationResponse]:
    room = ensure_room(room_id)
    reservations = store.list_room(room)
    return [to_response(r) for r in reservations]

@app.delete(
    "/rooms/{room_id}/reservations/{reservation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reservation(
    room_id: str = Path(..., description="Room id (A or B)"),
    reservation_id: str = Path(..., description="Reservation id (UUID)"),
) -> None:
    room = ensure_room(room_id)
    store.delete(room, reservation_id)
    return None