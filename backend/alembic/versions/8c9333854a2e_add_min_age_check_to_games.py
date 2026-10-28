"""add min age check to games

Revision ID: 8c9333854a2e
Revises: 6036f97cce08
Create Date: 2026-10-27 16:54:05.311390

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c9333854a2e"
down_revision: str | Sequence[str] | None = "6036f97cce08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(op.f("ck_games_min_age_not_negative"), "games", "min_age >= 0")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_games_min_age_not_negative"), "games", type_="check")
