import pytest
from fastapi.testclient import TestClient

from main import app, store

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """
    Clears the in-memory reservation store before each test.

    This fixture runs automatically for every test case to ensure
    that tests remain independent and do not affect each other
    through shared in-memory state.
    """
    for room in store._by_room:
        store._by_room[room].clear()


def test_create_reservation_success():
    """
    Tests successful creation of a reservation.

    Verifies that a valid reservation request returns HTTP 201,
    includes a generated reservation id, and returns the correct
    room and timestamps in the response.
    """
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
    """
    Tests that overlapping reservations in the same room are rejected.

    Creates an initial reservation and then attempts to create another
    reservation that overlaps in time. The API must return HTTP 409.
    """
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
    """
    Tests that a reservation with an invalid time interval is rejected.

    Attempts to create a reservation where the end time is before
    the start time. The API must return HTTP 400.
    """
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
    """
    Tests that creating a reservation for a non-existent room fails.

    Attempts to create a reservation for an unsupported room id.
    The API must return HTTP 404.
    """
    response = client.post(
        "/rooms/X/reservations",
        json={
            "start": "2026-02-02T09:00:00",
            "end": "2026-02-02T10:00:00",
        },
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()