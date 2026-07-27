"""Run the EFG converter as ``python -m efi_conv.en15907``.

The interface lives in the package itself, as it does for the
converters that are a single module; a package needs this entry point
in addition.

"""

import sys

from ..main import cli_main  # noqa: F401  (configures logging)
from . import main

if __name__ == "__main__":
    sys.exit(main())
