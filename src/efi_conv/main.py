import logging
import logging.config
import os

# Configure logging before importing local modules
log = logging.getLogger(__name__)
loglevel = os.environ.get(f"{__package__.upper()}_LOGLEVEL", "INFO").upper()
logging_config = {
    "version": 1,
    "formatters": {
        "simple": {
            "format": "%(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": loglevel,
            "formatter": "simple",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        __package__: {
            "level": "DEBUG",
            "handlers": ["console"],
        },
    },
    "disable_existing_loggers": False,
}
logging.config.dictConfig(logging_config)

from .core import check, diff, from_, harvest  # noqa: E402, F401
from .core.cli import cli_main  # noqa: E402, F401
