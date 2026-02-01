import pytest
from fastapi.testclient import TestClient

from main import app, store


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_store():
    """
    Clears the in-memory reservation store before each test.

    This fixture ensures that each test runs with a clean state so that
    reservations created in one test do not affect other tests.
    """
    for room in store._by_room:
        store._by_room[room].clear()


def create_reservation(room: str, start: str, end: str) -> str:
    """
    Helper function to create a reservation via the API.

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
    reservation_id: str
        The unique identifier of the created reservation.
    """
    response = client.post(
        f"/rooms/{room}/reservations",
        json={"start": start, "end": end},
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("room", ["A", "B"])
def test_delete_reservation_success(room: str):
    """
    Tests successful deletion of a reservation.

    Creates a reservation for the given room, deletes it, and verifies
    that the reservation no longer appears in the room's reservation list.
    """
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
    """
    Tests deletion of a non-existent reservation.

    Attempts to delete a reservation with an id that does not exist.
    The API must return HTTP 404.
    """
    response = client.delete(f"/rooms/{room}/reservations/nonexistent-id")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.parametrize("room", ["A", "B"])
def test_delete_only_affects_correct_room(room: str):
    """
    Tests that deleting a reservation only affects the specified room.

    Creates one reservation in the target room and another in a different
    room. After deleting the reservation in the target room, verifies that
    the other room's reservation remains intact.
    """
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