import logging


def configure_logging() -> None:
    """Print warnings from every library, and the app's own logs from INFO up."""
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("app").setLevel(logging.INFO)
