"""Entry point for ``python -m efi_conv.ebucore``."""

import sys

from ..main import cli_main  # noqa: F401  (configures logging)
from . import main

if __name__ == "__main__":
    sys.exit(main())
