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