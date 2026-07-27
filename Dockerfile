# Pull in base image
#
# Pinned to a specific minor version rather than the floating "3" tag
# so that two builds of the same commit produce the same interpreter.
FROM docker.io/library/python:3.13-slim-trixie AS python-base

# Image information
LABEL org.opencontainers.image.source=https://github.com/AV-EFI/efi-conv
LABEL org.opencontainers.image.description="Check module and converter scripts related to the AVefi schema"
LABEL org.opencontainers.image.licenses=MIT
LABEL org.opencontainers.image.authors="Elias Oltmanns <elias.oltmanns@gwdg.de>, Andreas Kasper <andreas.kasper@hdf.de>"

# Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # This is where our app + requirements + virtual environment will live
    PYSETUP_PATH="/app"

# Adjust PATH
ENV PATH=$PYSETUP_PATH/.venv/bin:$PATH

WORKDIR $PYSETUP_PATH

# `builder-base` stage is used to build deps + create our virtual environment
FROM python-base AS builder-base

# git is only needed to resolve the VCS dependency at build time and
# must not end up in the production image.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

# Install UV
RUN pip install --no-cache-dir uv

# Copy project requirement files here to ensure they will be cached.
COPY pyproject.toml uv.lock ./

# Install runtime deps
RUN uv sync --locked --no-dev --no-install-project --no-python-downloads

# Copy the source code
COPY LICENSE README.md ./
COPY src/ ./src/

# Install main app
RUN uv sync --locked --no-dev


# Production image used for runtime
FROM python-base AS production

# Run as an unprivileged user so that files written into the mounted
# working directory are not owned by root on the host.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid $GID efi \
    && useradd --uid $UID --gid $GID --create-home --shell /usr/sbin/nologin efi

# Cache location for the AVefi JSON schema, writable by that user
ENV XDG_CACHE_HOME=/home/efi/.cache

# Create mount point and make it the working directory
RUN mkdir -p /data && chown efi:efi /data
WORKDIR /data

# Copy app directory including dependencies
COPY --from=builder-base $PYSETUP_PATH $PYSETUP_PATH

USER efi

# Cache the current JSON schema for the check module. Note that this
# pins the schema to whatever upstream main looked like at build time;
# run `efi-conv check --update-schema` to refresh it.
RUN efi-conv check -u

# Set entry point
ENTRYPOINT [ "efi-conv" ]
