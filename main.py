from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from threading import Lock
from typing import Dict, Final, List
from uuid import uuid4

from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Path, status
from pydantic import BaseModel, Field

APP_TZ = ZoneInfo("Europe/Helsinki")

BUSINESS_START = time(8, 0)
BUSINESS_END = time(16, 0)

MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(hours=8)

ROOMS: Final[set[str]] = {"A", "B"}


def now_utc() -> datetime:
    """
    Returns the current timestamp in UTC.

    Returns
    -------
    now: datetime
        Current time as timezone-aware datetime in UTC.
    """
    return datetime.now(timezone.utc)


def ensure_room(room_id: str) -> str:
    """
    Normalizes and validates the room identifier.

    The room id is normalized to uppercase and checked against the allowed rooms.
    Raises an HTTP 404 error if the room is not supported.

    Parameters
    ----------
    room_id: str
        Room identifier from the request path (case-insensitive).

    Returns
    -------
    room_id: str
        Normalized room identifier (uppercase), guaranteed to be in ROOMS.

    Raises
    ------
    HTTPException
        If the room id is not found among the allowed rooms.
    """
    room_id = room_id.upper()
    if room_id not in ROOMS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Room '{room_id}' not found. Allowed rooms: {sorted(ROOMS)}",
        )
    return room_id


def parse_iso_to_utc(iso_str: str) -> datetime:
    """
    Parses an ISO 8601 timestamp into a timezone-aware UTC datetime.

    If the input timestamp is naive (no timezone offset), it is interpreted as
    Europe/Helsinki local time. The returned datetime is always normalized to UTC.

    Parameters
    ----------
    iso_str: str
        Timestamp in ISO 8601 format. Naive timestamps are treated as Europe/Helsinki.

    Returns
    -------
    dt_utc: datetime
        Timezone-aware datetime in UTC.

    Raises
    ------
    HTTPException
        If the input is not a valid ISO 8601 timestamp.
    """
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid ISO 8601 datetime: '{iso_str}'")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    return dt.astimezone(timezone.utc)


def to_helsinki(dt_utc: datetime) -> datetime:
    """
    Converts a UTC datetime to Europe/Helsinki local time.

    If the given datetime is naive (no timezone information), it is assumed
    to be in UTC before conversion.

    Parameters
    ----------
    dt_utc: datetime
        Datetime in UTC or naive datetime assumed to be UTC.

    Returns
    -------
    dt_local: datetime
        Timezone-aware datetime converted to Europe/Helsinki local time.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(APP_TZ)


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """
    Checks whether two time intervals overlap.

    The intervals are treated as half-open intervals: [start, end),
    meaning the start time is inclusive and the end time is exclusive.

    Parameters
    ----------
    a_start: datetime
        Start time of the first interval.
    a_end: datetime
        End time of the first interval.
    b_start: datetime
        Start time of the second interval.
    b_end: datetime
        End time of the second interval.

    Returns
    -------
    overlaps: bool
        True if the intervals overlap, False otherwise.
    """
    return a_start < b_end and b_start < a_end


def validate_time_order(start_utc: datetime, end_utc: datetime) -> None:
    """
    Validates that the reservation start time is before the end time.

    Parameters
    ----------
    start_utc: datetime
        Reservation start time in UTC.
    end_utc: datetime
        Reservation end time in UTC.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If start time is not before end time.
    """
    if start_utc >= end_utc:
        raise HTTPException(status_code=400, detail="Start time must be before end time.")


def validate_not_in_past(start_utc: datetime) -> None:
    """
    Validates that the reservation start time is not in the past.

    The current time is floored to the minute to allow a reservation
    starting at the current minute.

    Parameters
    ----------
    start_utc: datetime
        Reservation start time in UTC.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If the reservation start time is in the past.
    """
    now = now_utc()
    now_floor_to_minute = now.replace(second=0, microsecond=0)
    if start_utc < now_floor_to_minute:
        raise HTTPException(status_code=400, detail="Reservation start time cannot be in the past.")


def validate_30_min_blocks_local(start_local: datetime, end_local: datetime) -> None:
    """
    Validates that reservation start and end times align to 30-minute blocks
    in Europe/Helsinki local time.

    Parameters
    ----------
    start_local: datetime
        Reservation start time in Europe/Helsinki local time.
    end_local: datetime
        Reservation end time in Europe/Helsinki local time.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If start or end time is not at xx:00 or xx:30 local time.
    """
    if start_local.minute % 30 != 0 or end_local.minute % 30 != 0:
        raise HTTPException(
            status_code=400,
            detail="Reservations must start and end at 30-minute intervals (xx:00 or xx:30).",
        )


def validate_duration_limits(start_utc: datetime, end_utc: datetime) -> None:
    """
    Validates that reservation duration is within allowed limits.

    Parameters
    ----------
    start_utc: datetime
        Reservation start time in UTC.
    end_utc: datetime
        Reservation end time in UTC.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If the duration is shorter than 30 minutes or longer than 8 hours.
    """
    duration = end_utc - start_utc
    if duration < MIN_DURATION:
        raise HTTPException(status_code=400, detail="Reservation duration must be at least 30 minutes.")
    if duration > MAX_DURATION:
        raise HTTPException(status_code=400, detail="Reservation duration must be at most 8 hours.")


def validate_single_local_day(start_local: datetime, end_local: datetime) -> None:
    """
    Validates that the reservation stays within a single local day.

    Parameters
    ----------
    start_local: datetime
        Reservation start time in Europe/Helsinki local time.
    end_local: datetime
        Reservation end time in Europe/Helsinki local time.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If the reservation spans multiple local dates.
    """
    if start_local.date() != end_local.date():
        raise HTTPException(status_code=400, detail="Reservation must be within a single local day (Europe/Helsinki).")


def validate_business_hours_local(start_local: datetime, end_local: datetime) -> None:
    """
    Validates that the reservation is within office hours in local time.

    Office hours are 08:00–16:00 (Europe/Helsinki). Start at exactly 16:00
    is not allowed because the office closes at that time.

    Parameters
    ----------
    start_local: datetime
        Reservation start time in Europe/Helsinki local time.
    end_local: datetime
        Reservation end time in Europe/Helsinki local time.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If the reservation start or end is outside office hours, or starts at 16:00.
    """
    if not (BUSINESS_START <= start_local.timetz().replace(tzinfo=None) <= BUSINESS_END):
        raise HTTPException(status_code=400, detail="Reservation start must be within office hours 08:00–16:00.")

    if not (BUSINESS_START <= end_local.timetz().replace(tzinfo=None) <= BUSINESS_END):
        raise HTTPException(status_code=400, detail="Reservation end must be within office hours 08:00–16:00.")

    if start_local.time() == BUSINESS_END:
        raise HTTPException(status_code=400, detail="Reservation cannot start at 16:00 (office closes).")


def validate_business_rules(start_utc: datetime, end_utc: datetime) -> None:
    """
    Validates business rules for a room reservation time interval.

    The function enforces logical time ordering, prevents reservations in the past,
    restricts reservations to business hours (08:00–16:00 Europe/Helsinki),
    requires 30-minute time blocks, and enforces minimum and maximum duration limits.

    Parameters
    ----------
    start_utc: datetime
        Reservation start time as a timezone-aware datetime in UTC.
    end_utc: datetime
        Reservation end time as a timezone-aware datetime in UTC.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If any of the business rules are violated.
    """
    validate_time_order(start_utc, end_utc)
    validate_not_in_past(start_utc)

    start_local = to_helsinki(start_utc)
    end_local = to_helsinki(end_utc)

    validate_30_min_blocks_local(start_local, end_local)
    validate_duration_limits(start_utc, end_utc)
    validate_single_local_day(start_local, end_local)
    validate_business_hours_local(start_local, end_local)


class CreateReservationRequest(BaseModel):
    """
    Request model for creating a new room reservation.

    The start and end times must be provided in ISO 8601 format.
    If the timestamp does not include a timezone offset, it is
    interpreted as Europe/Helsinki local time.
    """
    start: str = Field(..., description="ISO 8601 datetime (local Europe/Helsinki if no offset)")
    end: str = Field(..., description="ISO 8601 datetime (local Europe/Helsinki if no offset)")


class ReservationResponse(BaseModel):
    """
    Response model representing a room reservation.

    All timestamps are returned in ISO 8601 format using
    Europe/Helsinki local time.
    """
    id: str
    room: str
    start: str  # ISO 8601 in Europe/Helsinki
    end: str    # ISO 8601 in Europe/Helsinki


@dataclass(frozen=True)
class Reservation:
    """
    Internal domain model representing a room reservation.

    The reservation times are stored internally in UTC to ensure
    consistent comparison and overlap detection.
    """
    id: str
    room: str
    start_utc: datetime
    end_utc: datetime


class InMemoryStore:
    """
    Thread-safe in-memory storage for room reservations.

    Reservations are stored per room and kept in UTC for consistent
    comparison and overlap detection. This storage is intended for
    demo and development use only (no persistence).
    """


    def __init__(self) -> None:
        """
        Initializes the in-memory reservation store.

        Creates an empty reservation list for each supported room and
        initializes a lock to ensure thread-safe access.
        """
        self._lock: Lock = Lock()
        self._by_room: Dict[str, List[Reservation]] = {room: [] for room in ROOMS}


    def list_room(self, room: str) -> List[Reservation]:
        """
        Returns all reservations for a given room.

        The reservations are returned sorted by start time in ascending order.

        Parameters
        ----------
        room: str
            Normalized room identifier.

        Returns
        -------
        reservations: List[Reservation]
            List of reservations for the room, sorted by start time.
        """
        with self._lock:
            return sorted(self._by_room[room], key=lambda r: r.start_utc)


    def create(self, room: str, start_utc: datetime, end_utc: datetime) -> Reservation:
        """
        Creates a new reservation for a room.

        The reservation is validated against business rules and checked
        for overlaps with existing reservations in the same room.

        Parameters
        ----------
        room: str
            Normalized room identifier.
        start_utc: datetime
            Reservation start time in UTC.
        end_utc: datetime
            Reservation end time in UTC.

        Returns
        -------
        reservation: Reservation
            The newly created reservation.

        Raises
        ------
        HTTPException
            If business rules are violated or the reservation overlaps
            with an existing reservation in the same room.
        """
        validate_business_rules(start_utc, end_utc)

        with self._lock:
            existing = self._by_room[room]
            for r in existing:
                if overlaps(start_utc, end_utc, r.start_utc, r.end_utc):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Reservation overlaps with an existing reservation in the same room.",
                    )

            new_res = Reservation(
                id=str(uuid4()),
                room=room,
                start_utc=start_utc,
                end_utc=end_utc,
            )
            existing.append(new_res)
            return new_res


    def delete(self, room: str, reservation_id: str) -> None:
        """
        Deletes an existing reservation from a room.

        Parameters
        ----------
        room: str
            Normalized room identifier.
        reservation_id: str
            Unique identifier of the reservation to delete.

        Returns
        -------
        None

        Raises
        ------
        HTTPException
            If the reservation with the given id does not exist.
        """
        with self._lock:
            reservations = self._by_room[room]
            for i, r in enumerate(reservations):
                if r.id == reservation_id:
                    reservations.pop(i)
                    return

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found.",
        )


store = InMemoryStore()
app = FastAPI(title="Meeting Room Booking API", version="1.0.0")


def to_response(r: Reservation) -> ReservationResponse:
    """
    Converts an internal Reservation object into an API response model.

    The reservation timestamps are converted from UTC to Europe/Helsinki
    local time and formatted as ISO 8601 strings.

    Parameters
    ----------
    r: Reservation
        Internal reservation domain object with UTC timestamps.

    Returns
    -------
    response: ReservationResponse
        Reservation response model with timestamps in Europe/Helsinki local time.
    """
    start_local = to_helsinki(r.start_utc).isoformat()
    end_local = to_helsinki(r.end_utc).isoformat()
    return ReservationResponse(
        id=r.id,
        room=r.room,
        start=start_local,
        end=end_local,
    )


@app.post(
    "/rooms/{room_id}/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    room_id: str = Path(..., description="Room id (A or B)"),
    body: CreateReservationRequest = ...,
) -> ReservationResponse:
    """
    Creates a new reservation for a given room.

    The request body must contain start and end times in ISO 8601 format.
    Business rules and overlap checks are applied before the reservation
    is stored.

    Parameters
    ----------
    room_id: str
        Room identifier from the request path.
    body: CreateReservationRequest
        Request payload containing reservation start and end times.

    Returns
    -------
    reservation: ReservationResponse
        The newly created reservation with timestamps in Europe/Helsinki
        local time.

    Raises
    ------
    HTTPException
        If the room does not exist, business rules are violated, or the
        reservation overlaps with an existing reservation.
    """
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
    """
    Returns all reservations for a given room.

    The reservations are returned in ascending order by start time.
    This endpoint returns all reservations regardless of whether they
    are in the past or future.

    Parameters
    ----------
    room_id: str
        Room identifier from the request path.

    Returns
    -------
    reservations: list[ReservationResponse]
        List of reservations for the room with timestamps in
        Europe/Helsinki local time.

    Raises
    ------
    HTTPException
        If the room does not exist.
    """
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
    """
    Deletes an existing reservation from a room.

    Parameters
    ----------
    room_id: str
        Room identifier from the request path.
    reservation_id: str
        Unique identifier of the reservation to delete.

    Returns
    -------
    None

    Raises
    ------
    HTTPException
        If the room does not exist or the reservation cannot be found.
    """
    room = ensure_room(room_id)
    store.delete(room, reservation_id)
    return None