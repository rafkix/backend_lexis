# ⚠️ logging.py deb nomlamang — Python built-in bilan conflict bo'ladi!
from logging.config import dictConfig


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
    "loggers": {
        "uvicorn": {"level": "INFO"},
        "sqlalchemy.engine": {"level": "WARNING"},
    },
}


def setup_logging() -> None:
    dictConfig(LOGGING_CONFIG)
