from httpx2 import AsyncClient

from tests.helpers import post_game


async def test_list_games_applies_the_query_filters(api_client: AsyncClient) -> None:
    await post_game(api_client, name="Game A", min_players=2, max_players=4, genres=["party"])
    await post_game(api_client, name="Game B", min_players=2, max_players=4, genres=["co-op"])
    await post_game(api_client, name="Game C", min_players=5, max_players=8, genres=["party"])
    await post_game(api_client, name="Game D", min_players=2, max_players=4, genres=["zombie"])

    response = await api_client.get(
        "/api/games", params={"players": 3, "genres": ["party", "co-op"]}
    )
    assert response.status_code == 200
    assert [game["name"] for game in response.json()] == ["Game A", "Game B"]


async def test_list_games_returns_422_for_an_invalid_filter(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/games", params={"players": 0})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "players"]


async def test_post_game_returns_201_with_the_stored_game(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/games", json={"name": "Game", "genres": [" Party ", "party", "Co-op"]}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Game"
    assert body["genres"] == ["party", "co-op"]
    assert isinstance(body["id"], int)
    assert body["created_at"] is not None


async def test_post_game_returns_422_for_an_invalid_body(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/games", json={"name": "Game", "min_players": 0})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "min_players"]


async def test_post_game_returns_422_for_a_missing_base_game(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/games", json={"name": "Game", "is_expansion": True, "base_game_id": 999}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "base game 999 does not exist"


async def test_get_game_returns_200_with_the_stored_game(api_client: AsyncClient) -> None:
    game = await post_game(api_client)

    response = await api_client.get(f"/api/games/{game['id']}")

    assert response.status_code == 200
    assert response.json() == game


async def test_get_game_returns_404_for_an_unknown_id(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/games/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "game 999 does not exist"}


async def test_get_game_returns_422_for_a_non_integer_id(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/games/abc")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "game_id"]


async def test_patch_game_changes_only_the_fields_sent(api_client: AsyncClient) -> None:
    game = await post_game(api_client)

    response = await api_client.patch(f"/api/games/{game['id']}", json={"max_players": 6})

    assert response.status_code == 200
    assert response.json() == {**game, "max_players": 6}


async def test_patch_game_returns_404_for_an_unknown_id(api_client: AsyncClient) -> None:
    response = await api_client.patch(
        "/api/games/999",
        json={"name": "New game"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "game 999 does not exist"}


async def test_patch_game_returns_422_for_null_in_a_required_field(api_client: AsyncClient) -> None:
    game = await post_game(api_client)

    response = await api_client.patch(f"/api/games/{game['id']}", json={"name": None})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["name"]


async def test_patch_game_returns_422_for_a_range_invalid_with_stored_values(
    api_client: AsyncClient,
) -> None:
    game = await post_game(api_client, min_players=4, max_players=6)

    response = await api_client.patch(f"/api/games/{game['id']}", json={"max_players": 2})

    assert response.status_code == 422
    assert "max_players must be at least min_players" in response.text


async def test_delete_game_returns_204_and_removes_the_game(api_client: AsyncClient) -> None:
    game = await post_game(api_client)
    response = await api_client.delete(f"/api/games/{game['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await api_client.get(f"/api/games/{game['id']}")).status_code == 404


async def test_delete_game_returns_404_for_an_unknown_id(api_client: AsyncClient) -> None:
    response = await api_client.delete("/api/games/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "game 999 does not exist"}
