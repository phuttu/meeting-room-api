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