from pydantic_settings import BaseSettings, SettingsConfigDict

# Derive the prefix from the top level package rather than this
# module's package: __package__ is "efi_conv.core" here, and
# environment variable names cannot contain a dot.
ENV_PREFIX = f"{__package__.split('.')[0].upper()}_"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    line_limit: int = 250
    text_limit: int = 8192


settings = Settings()
