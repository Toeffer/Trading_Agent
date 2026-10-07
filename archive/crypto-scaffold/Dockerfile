# Trading Agent — base container image
#
# NOTE: This is a TEMPLATE. The actual OpenClaw install command and entrypoint
# depend on OpenClaw's distribution mechanism (pip package, git clone, binary,
# etc.) which is not known at scaffold time. Replace the TODO(operator) lines
# once OpenClaw install is confirmed.

FROM python:3.11-slim

# ─── System deps ──────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    tzdata \
    gnupg \
    gpg-agent \
 && rm -rf /var/lib/apt/lists/*

ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ─── Non-root user ────────────────────────────────────────────────────────────
RUN useradd -m -u 1000 -s /bin/bash agent
WORKDIR /app

# ─── Python deps ──────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── OpenClaw install ─────────────────────────────────────────────────────────
# TODO(operator): replace with the real OpenClaw install once confirmed. Options:
#   pip install openclaw
#   pip install git+https://github.com/<org>/openclaw.git@<pin>
#   curl -L <release-url> -o /usr/local/bin/openclaw && chmod +x ...
#
# RUN pip install openclaw==<pin>

# ─── App code ─────────────────────────────────────────────────────────────────
COPY --chown=agent:agent . /app
USER agent

# Data and logs live on a mounted volume so they survive container rebuilds.
VOLUME ["/data"]

# Health check — verify config loads and SAE hash matches
HEALTHCHECK --interval=5m --timeout=30s --start-period=1m --retries=2 \
    CMD python scripts/preflight.py --quick || exit 1

# TODO(operator): replace with the real OpenClaw entrypoint
# CMD ["openclaw", "run", "--config", "/app/config/openclaw.json"]
CMD ["python", "-c", "print('Replace CMD with OpenClaw entrypoint — see Dockerfile TODO'); import time; time.sleep(3600)"]
