import uvicorn

from .config import get_settings
from .logging_config import configure_logging


def cli() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.assert_safe_startup()
    uvicorn.run(
        "trading_bot.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    cli()
