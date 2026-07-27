from importlib import metadata

try:
    __version__ = metadata.version("efi_conv")
except metadata.PackageNotFoundError:  # pragma: no cover
    # Running from a source checkout without an installed distribution.
    __version__ = "0.0.0+unknown"
