import pytest
from pydantic import ValidationError

from app.schemas.rulebooks import RulebookUpdate


@pytest.mark.parametrize(
    "body",
    [
        {"filename": None},
        {"game_id": None},
        {"filename": ""},
        {"filename": "   "},
        {"filename": "x" * 256},
    ],
)
def test_rulebook_update_rejects_an_invalid_field(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RulebookUpdate.model_validate(body)
