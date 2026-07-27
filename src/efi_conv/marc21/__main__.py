"""Entry point for ``python -m efi_conv.marc21``."""

import sys

from . import main

if __name__ == "__main__":
    from ..main import cli_main  # noqa: F401  (configures logging)

    sys.exit(main())
