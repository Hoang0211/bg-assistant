from alembic.config import Config

from alembic import command


def test_migrations_match_the_models(database_url: str) -> None:
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.check(alembic_config)
