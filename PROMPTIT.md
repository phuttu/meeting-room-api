# Promptit ja tekoälyn käyttö

Tässä dokumentissa kuvataan, miten tekoälyä (ChatGPT) hyödynnettiin
Meeting Room Booking API -projektin toteutuksessa.

---

**Prompti**
Toteuta yksinkertainen kokoushuoneiden varausrajapinta (API). 
Toiminnallisuudet: 
API:n tulee tarjota seuraavat endpointit: 
-Varauksen luonti (POST): varaa huone tietylle aikavälille 
-Varauksen peruutus (DELETE): poistaa olemassa olevan varauksen
 -Varausten katselu (GET): listaa kaikki tietyn huoneen varaukset 

Toimintalogiikka: 
-Varaukset eivät saa mennä päällekkäin saman huoneen sisällä 
-Varaukset eivät voi sijoittua menneisyyteen 
-Aloitusajan täytyy olla ennen lopetusaikaa

Tekniset rajaukset:
 -Käytä Pythonia ja FastAPI-kehystä 
-Käytetään in-memory-tallennusta (ei tietokantaa)

 Oletukset: 
-Huoneita on kaksi: A ja B
 -Varaukset tehdään toimiston paikallisajassa (Europe/Helsinki) 
-Aikaleimat annetaan ISO 8601 -muodossa
 -Ei autentikointia tai käyttäjähallintaa 
-Varaukset ovat sallittuja vain virka-aikaan (08:00–16:00) 
-Varauksen kesto on vähintään 30 minuuttia ja enintään 8 tuntia -Varaus voi olla tuleville päiville

**Vastaus**
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Dict, List
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path, status
from pydantic import BaseModel, Field
from zoneinfo import ZoneInfo
import threading


APP_TZ = ZoneInfo("Europe/Helsinki")
BUSINESS_START = time(8, 0)
BUSINESS_END = time(16, 0)
MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(hours=8)

ROOMS = {"A", "B"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_room(room_id: str) -> str:
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

    if start_utc < now_utc():
        raise HTTPException(status_code=400, detail="Reservation start time cannot be in the past.")

    duration = end_utc - start_utc
    if duration < MIN_DURATION:
        raise HTTPException(status_code=400, detail="Reservation duration must be at least 30 minutes.")
    if duration > MAX_DURATION:
        raise HTTPException(status_code=400, detail="Reservation duration must be at most 8 hours.")

    # Business hours check in Helsinki local time
    start_local = to_helsinki(start_utc)
    end_local = to_helsinki(end_utc)

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
        self._lock = threading.Lock()
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
):
    room = ensure_room(room_id)
    start_utc = parse_iso_to_utc(body.start)
    end_utc = parse_iso_to_utc(body.end)
    created = store.create(room, start_utc, end_utc)
    return to_response(created)


@app.get("/rooms/{room_id}/reservations", response_model=list[ReservationResponse])
def list_reservations(room_id: str = Path(..., description="Room id (A or B)")):
    room = ensure_room(room_id)
    reservations = store.list_room(room)
    return [to_response(r) for r in reservations]


@app.delete("/rooms/{room_id}/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reservation(
    room_id: str = Path(..., description="Room id (A or B)"),
    reservation_id: str = Path(..., description="Reservation id (UUID)"),
):
    room = ensure_room(room_id)
    store.delete(room, reservation_id)
    return None

**Prompti**
Koodin logiikka ei salli tällä hetkellä varausta ajalle klo. 13.00 jos varaus tehdään esimerkiksi muutaman sekunnin sen jälkeen. Tämä on periaatteessa menneisyydessä, mutta muokataan koodia niin että varaus hyväksytään minuutin aikaikkunalla. Silloin huoneen voi varata vielä "nykyhetkeen" jos kello näyttää varaushetkellä 13.00

**Vastaus**
Etsi tämä kohta:
if start_utc < now_utc():
    raise HTTPException(status_code=400, detail="Reservation start time cannot be in the past.")

ja korvaa se tällä:
Kopioi koodi
now = now_utc()
now_floor_to_minute = now.replace(second=0, microsecond=0)

if start_utc < now_floor_to_minute:
    raise HTTPException(status_code=400, detail="Reservation start time cannot be in the past.")

**Prompti**
Nykyinen logiikka sallii varaukset mihin tahansa minuuttiin (esim. 13:10–14:45). Korjaa varauslogiikka niin, että varaukset ovat sallittuja vain 30 minuutin lohkoissa (aloitus ja lopetus vain klo xx:00 tai xx:30). Älä muuta muuta logiikkaa.

**Vastaus**
# Allow reservations only in 30-minute blocks (xx:00 or xx:30)
if start_utc.minute % 30 != 0 or end_utc.minute % 30 != 0:
    raise HTTPException(
        status_code=400,
        detail="Reservations must start and end at 30-minute intervals (xx:00 or xx:30)."
    )

**Prompti**
Nykyinen 30 minuutin aikablokkivalidaatio tehdään UTC-ajassa.
Korjaa logiikka niin, että 30 minuutin lohkot tarkistetaan Europe/Helsinki-paikallisajassa
(aloitus ja lopetus vain klo xx:00 tai xx:30 paikallista aikaa).
Älä muuta muuta varauslogiikkaa.

**Vastaus**
# Convert to Helsinki local time for local rules
start_local = to_helsinki(start_utc)
end_local = to_helsinki(end_utc)

# Allow reservations only in 30-minute blocks in Helsinki local time (xx:00 or xx:30)
if start_local.minute % 30 != 0 or end_local.minute % 30 != 0:
    raise HTTPException(
        status_code=400,
        detail="Reservations must start and end at 30-minute intervals (xx:00 or xx:30)."
    )

**Prompti**
Lisää FastAPI-endpointteihin eksplisiittiset paluuarvon tyypitykset

**Vastaus**
def create_reservation(
    room_id: str = Path(..., description="Room id (A or B)"),
    body: CreateReservationRequest = ...,
) -> ReservationResponse:

def list_reservations(
    room_id: str = Path(..., description="Room id (A or B)")
) -> list[ReservationResponse]:

def delete_reservation(
    room_id: str = Path(..., description="Room id (A or B)"),
    reservation_id: str = Path(..., description="Reservation id (UUID)"),
) -> None:

**Prompti**
Pilko validate_business_rules-funktio pienempiin, selkeästi nimettyihin apufunktioihin yhden vastuun periaatteen mukaisesti.
Säilytä nykyinen toiminnallisuus ja poikkeuskäytös muuttumattomana.
Lisää jokaiselle uudelle funktiolle kattavat docstringit nykyisen dokumentaatiotyylin mukaisesti.

**Vastaus**
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

**Prompti**
Kirjoita pytest-testit FastAPI-sovellukselle varauksen luontiin. Testaa onnistunut varaus sekä virhetilanteet (päällekkäinen varaus, virheellinen aikaväli, olematon huone).

**Vastaus**
import pytest
from fastapi.testclient import TestClient

from main import app, store  

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """
    Clears in-memory store before each test to keep tests independent.
    """
    for room in store._by_room:
        store._by_room[room].clear()


def test_create_reservation_success():
    response = client.post(
        "/rooms/A/reservations",
        json={
            "start": "2026-02-02T09:00:00",
            "end": "2026-02-02T10:00:00",
        },
    )

    assert response.status_code == 201
    body = response.json()

    assert body["room"] == "A"
    assert body["start"].startswith("2026-02-02T09:00")
    assert body["end"].startswith("2026-02-02T10:00")
    assert "id" in body


def test_create_reservation_overlap():
    # First reservation
    client.post(
        "/rooms/A/reservations",
        json={
            "start": "2026-02-02T09:00:00",
            "end": "2026-02-02T10:00:00",
        },
    )

    # Overlapping reservation
    response = client.post(
        "/rooms/A/reservations",
        json={
            "start": "2026-02-02T09:30:00",
            "end": "2026-02-02T10:30:00",
        },
    )

    assert response.status_code == 409
    assert "overlaps" in response.json()["detail"].lower()


def test_create_reservation_invalid_time_interval():
    response = client.post(
        "/rooms/A/reservations",
        json={
            "start": "2026-02-02T10:00:00",
            "end": "2026-02-02T09:00:00",
        },
    )

    assert response.status_code == 400
    assert "start time must be before end time" in response.json()["detail"].lower()


def test_create_reservation_nonexistent_room():
    response = client.post(
        "/rooms/X/reservations",
        json={
            "start": "2026-02-02T09:00:00",
            "end": "2026-02-02T10:00:00",
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

**Prompti**
Kirjoita pytest-testit varauslistauksen endpointille.
Testaa, että huoneen varaukset palautuvat oikeassa järjestyksessä ja oikeassa muodossa.
Älä suodata menneitä varauksia.

**Vastaus**
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

from main import Reservation, app, store 

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """
    Clears in-memory store before each test to keep tests independent.
    """
    for room in store._by_room:
        store._by_room[room].clear()


def create_reservation(room: str, start: str, end: str):
    return client.post(
        f"/rooms/{room}/reservations",
        json={"start": start, "end": end},
    )


def test_list_reservations_returns_sorted_by_start_time():
    # Create reservations out of order
    create_reservation("A", "2026-02-02T10:00:00", "2026-02-02T11:00:00")
    create_reservation("A", "2026-02-02T09:00:00", "2026-02-02T10:00:00")
    create_reservation("A", "2026-02-02T11:00:00", "2026-02-02T12:00:00")

    response = client.get("/rooms/A/reservations")

    assert response.status_code == 200
    data = response.json()

    assert len(data) == 3

    # Ensure ascending order by start time
    starts = [item["start"] for item in data]
    assert starts == sorted(starts)


def test_list_reservations_response_format():
    create_reservation("A", "2026-02-02T09:00:00", "2026-02-02T10:00:00")

    response = client.get("/rooms/A/reservations")

    assert response.status_code == 200
    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 1

    reservation = data[0]

    assert set(reservation.keys()) == {"id", "room", "start", "end"}
    assert reservation["room"] == "A"
    assert isinstance(reservation["id"], str)
    assert isinstance(reservation["start"], str)
    assert isinstance(reservation["end"], str)


def test_list_reservations_includes_past_reservations():
    # Manually insert a past reservation into the store
    past_start = datetime.now(timezone.utc) - timedelta(days=2)
    past_end = past_start + timedelta(hours=1)

    store._by_room["A"].append(
        Reservation(
            id="past-id",
            room="A",
            start_utc=past_start,
            end_utc=past_end,
        )
    )

    # Create a future reservation normally via API
    create_reservation("A", "2026-02-03T09:00:00", "2026-02-03T10:00:00")

    response = client.get("/rooms/A/reservations")

    assert response.status_code == 200
    data = response.json()

    # Both past and future reservations must be returned
    assert len(data) == 2

**Prompti**
Kirjoita pytest-testit varauksen poistoon. Testaa onnistunut poisto sekä virhetilanne, jossa varausta ei löydy. Varmista, että poistettu varaus ei enää näy listauksessa. Kokeile molempia: huone A ja B

**Vastaus**
import pytest
from fastapi.testclient import TestClient

from main import app, store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """
    Clears in-memory store before each test to keep tests independent.
    """
    for room in store._by_room:
        store._by_room[room].clear()


def create_reservation(room: str, start: str, end: str) -> str:
    response = client.post(
        f"/rooms/{room}/reservations",
        json={"start": start, "end": end},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("room", ["A", "B"])
def test_delete_reservation_success(room: str):
    reservation_id = create_reservation(
        room,
        "2026-02-02T09:00:00",
        "2026-02-02T10:00:00",
    )

    delete_response = client.delete(f"/rooms/{room}/reservations/{reservation_id}")
    assert delete_response.status_code == 204

    # Verify reservation is no longer listed
    list_response = client.get(f"/rooms/{room}/reservations")
    assert list_response.status_code == 200
    reservations = list_response.json()

    assert reservations == []


@pytest.mark.parametrize("room", ["A", "B"])
def test_delete_nonexistent_reservation(room: str):
    response = client.delete(f"/rooms/{room}/reservations/nonexistent-id")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.parametrize("room", ["A", "B"])
def test_delete_only_affects_correct_room(room: str):
    other_room = "B" if room == "A" else "A"

    id_to_delete = create_reservation(
        room,
        "2026-02-02T09:00:00",
        "2026-02-02T10:00:00",
    )

    other_id = create_reservation(
        other_room,
        "2026-02-02T11:00:00",
        "2026-02-02T12:00:00",
    )

    delete_response = client.delete(f"/rooms/{room}/reservations/{id_to_delete}")
    assert delete_response.status_code == 204

    # Deleted room should be empty
    response_room = client.get(f"/rooms/{room}/reservations")
    assert response_room.json() == []

    # Other room must still contain its reservation
    response_other = client.get(f"/rooms/{other_room}/reservations")
    data_other = response_other.json()

    assert len(data_other) == 1
    assert data_other[0]["id"] == other_id

