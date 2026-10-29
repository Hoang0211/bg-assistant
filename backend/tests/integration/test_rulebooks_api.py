from pathlib import Path
from typing import Any

import pytest
from httpx2 import AsyncClient, Response

from app.config import get_settings
from tests.helpers import make_pdf, post_game


async def upload(
    client: AsyncClient, game_id: int, data: bytes, filename: str = "rules.pdf"
) -> Response:
    return await client.post(
        f"/api/games/{game_id}/rulebooks",
        files={"file": (filename, data, "application/pdf")},
    )


async def add_rulebook(
    client: AsyncClient, game_id: int, data: bytes, filename: str = "rules.pdf"
) -> dict[str, Any]:
    response = await upload(client, game_id, data, filename)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_list_game_rulebooks_returns_only_that_games_rulebooks(
    api_client: AsyncClient,
) -> None:
    game_1 = await post_game(api_client, name="Game 1")
    game_2 = await post_game(api_client, name="Game 2")
    await add_rulebook(api_client, game_1["id"], make_pdf(1))
    rulebook_2 = await add_rulebook(api_client, game_2["id"], make_pdf(1), "rules_2.pdf")
    rulebook_3 = await add_rulebook(api_client, game_2["id"], make_pdf(1), "rules_3.pdf")

    response = await api_client.get(f"/api/games/{game_2['id']}/rulebooks")

    assert response.status_code == 200
    assert response.json() == [rulebook_2, rulebook_3]


async def test_list_game_rulebooks_returns_404_for_an_unknown_game(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/games/999/rulebooks")

    assert response.status_code == 404
    assert response.json() == {"detail": "game 999 does not exist"}


async def test_post_rulebook_returns_201_with_the_stored_rulebook(api_client: AsyncClient) -> None:
    game = await post_game(api_client)

    response = await upload(api_client, game["id"], make_pdf(3))

    assert response.status_code == 201
    body = response.json()
    assert body["game_id"] == game["id"]
    assert body["game_name"] == "Game"
    assert body["filename"] == "rules.pdf"
    assert body["page_count"] == 3
    assert body["status"] == "uploaded"
    assert "sha256" not in body
    assert "storage_path" not in body


async def test_post_rulebook_returns_404_for_an_unknown_game(api_client: AsyncClient) -> None:
    response = await upload(api_client, 999, make_pdf(1))

    assert response.status_code == 404
    assert response.json() == {"detail": "game 999 does not exist"}


async def test_post_rulebook_returns_413_for_a_file_over_the_limit(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = await post_game(api_client)
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)

    response = await upload(api_client, game["id"], make_pdf(1))

    assert response.status_code == 413
    assert response.json() == {"detail": "the PDF is over 0 MB"}


async def test_post_rulebook_returns_422_for_a_duplicate(api_client: AsyncClient) -> None:
    game_1 = await post_game(api_client, name="Game 1")
    game_2 = await post_game(api_client, name="Game 2")
    original = await add_rulebook(api_client, game_1["id"], make_pdf(1))

    response = await upload(api_client, game_2["id"], make_pdf(1))

    assert response.status_code == 422
    assert response.json() == {
        "detail": "this PDF is already in the library, for Game 1",
        "duplicate_of": {"rulebook_id": original["id"], "game_id": game_1["id"], "name": "Game 1"},
    }


async def test_post_rulebook_returns_422_for_an_unreadable_file(api_client: AsyncClient) -> None:
    game = await post_game(api_client)

    response = await upload(api_client, game["id"], b"not a pdf")

    assert response.status_code == 422
    assert response.json() == {"detail": "the file is not a readable PDF"}


async def test_list_rulebooks_returns_every_rulebook_with_its_game_name(
    api_client: AsyncClient,
) -> None:
    game_1 = await post_game(api_client, name="Game 1")
    game_2 = await post_game(api_client, name="Game 2")
    rulebook_3 = await add_rulebook(api_client, game_2["id"], make_pdf(1), "rules_3.pdf")
    rulebook_1 = await add_rulebook(api_client, game_1["id"], make_pdf(1), "rules_1.pdf")
    rulebook_2 = await add_rulebook(api_client, game_2["id"], make_pdf(1), "rules_2.pdf")

    response = await api_client.get("/api/rulebooks")

    assert response.status_code == 200
    assert response.json() == [rulebook_1, rulebook_2, rulebook_3]


async def test_get_rulebook_file_returns_200_with_the_whole_pdf(api_client: AsyncClient) -> None:
    game = await post_game(api_client)
    data = make_pdf(3)
    rulebook = await add_rulebook(api_client, game["id"], data)

    response = await api_client.get(f"/api/rulebooks/{rulebook['id']}/file")

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"] == "inline; filename*=utf-8''Game%20-%20rules.pdf"
    )


async def test_get_rulebook_file_returns_206_for_a_range(api_client: AsyncClient) -> None:
    game = await post_game(api_client)
    data = make_pdf(3)
    rulebook = await add_rulebook(api_client, game["id"], data)

    response = await api_client.get(
        f"/api/rulebooks/{rulebook['id']}/file", headers={"Range": "bytes=0-99"}
    )

    assert response.status_code == 206
    assert response.content == data[:100]
    assert response.headers["content-range"] == f"bytes 0-99/{len(data)}"


async def test_get_rulebook_file_returns_404_for_an_unknown_id(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/rulebooks/999/file")

    assert response.status_code == 404
    assert response.json() == {"detail": "rulebook 999 does not exist"}


async def test_patch_rulebook_returns_200_with_the_new_filename(api_client: AsyncClient) -> None:
    game = await post_game(api_client)
    rulebook = await add_rulebook(api_client, game["id"], make_pdf(1), "rules.pdf")

    response = await api_client.patch(
        f"/api/rulebooks/{rulebook['id']}", json={"filename": "new_rules.pdf"}
    )

    assert response.status_code == 200
    assert response.json() == {**rulebook, "filename": "new_rules.pdf"}


async def test_patch_rulebook_returns_200_with_the_new_game(api_client: AsyncClient) -> None:
    game_1 = await post_game(api_client, name="Game 1")
    game_2 = await post_game(api_client, name="Game 2")
    rulebook = await add_rulebook(api_client, game_1["id"], make_pdf(1))

    response = await api_client.patch(
        f"/api/rulebooks/{rulebook['id']}", json={"game_id": game_2["id"]}
    )

    assert response.status_code == 200
    assert response.json() == {**rulebook, "game_id": game_2["id"], "game_name": "Game 2"}


async def test_patch_rulebook_returns_404_for_an_unknown_id(api_client: AsyncClient) -> None:
    response = await api_client.patch("/api/rulebooks/999", json={"filename": "new_rulebook.pdf"})

    assert response.status_code == 404
    assert response.json() == {"detail": "rulebook 999 does not exist"}


async def test_patch_rulebook_returns_422_for_a_null_filename(api_client: AsyncClient) -> None:
    game = await post_game(api_client)
    rulebook = await add_rulebook(api_client, game["id"], make_pdf(1))

    response = await api_client.patch(f"/api/rulebooks/{rulebook['id']}", json={"filename": None})

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == "Value error, filename cannot be null"
    listed = await api_client.get(f"/api/games/{game['id']}/rulebooks")
    assert listed.json() == [rulebook]


async def test_patch_rulebook_returns_422_for_a_move_to_a_missing_game(
    api_client: AsyncClient,
) -> None:
    game = await post_game(api_client)
    rulebook = await add_rulebook(api_client, game["id"], make_pdf(1))

    response = await api_client.patch(f"/api/rulebooks/{rulebook['id']}", json={"game_id": 999})

    assert response.status_code == 422
    assert response.json() == {"detail": "game 999 does not exist"}
    listed = await api_client.get(f"/api/games/{game['id']}/rulebooks")
    assert listed.json() == [rulebook]


async def test_delete_rulebook_returns_204_and_removes_the_rulebook(
    api_client: AsyncClient, tmp_path: Path
) -> None:
    game = await post_game(api_client)
    rulebook = await add_rulebook(api_client, game["id"], make_pdf(1))

    response = await api_client.delete(f"/api/rulebooks/{rulebook['id']}")

    assert response.status_code == 204
    file = await api_client.get(f"/api/rulebooks/{rulebook['id']}/file")
    assert file.status_code == 404
    assert list(tmp_path.iterdir()) == []


async def test_delete_rulebook_returns_404_for_an_unknown_id(api_client: AsyncClient) -> None:
    response = await api_client.delete("/api/rulebooks/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "rulebook 999 does not exist"}
