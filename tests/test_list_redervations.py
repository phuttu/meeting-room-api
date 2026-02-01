import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta

from main import Reservation, app, store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """
    Clears the in-memory reservation store before each test.

    This fixture runs automatically to ensure that each test starts
    with a clean state and does not depend on reservations created
    by previous tests.
    """
    for room in store._by_room:
        store._by_room[room].clear()


def create_reservation(room: str, start: str, end: str):
    """
    Helper function for creating a reservation via the API.

    Parameters
    ----------
    room: str
        Room identifier (e.g. "A" or "B").
    start: str
        Reservation start time in ISO 8601 format.
    end: str
        Reservation end time in ISO 8601 format.

    Returns
    -------
    response
        HTTP response object returned by the API.
    """
    return client.post(
        f"/rooms/{room}/reservations",
        json={"start": start, "end": end},
    )


def test_list_reservations_returns_sorted_by_start_time():
    """
    Tests that reservations are returned sorted by start time.

    Creates multiple reservations for the same room in a non-chronological
    order and verifies that the API response lists them in ascending
    order based on their start time.
    """
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
    """
    Tests the structure and data types of the reservation list response.

    Verifies that the endpoint returns a list of reservations and that
    each reservation contains the expected fields with correct types.
    """
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
    """
    Tests that past reservations are included in the reservation listing.

    Inserts a past reservation directly into the in-memory store and
    creates a future reservation via the API. Verifies that both past
    and future reservations are returned by the list endpoint.
    """
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