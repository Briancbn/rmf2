FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Build deps for vda5050_core C++ extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake g++ git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps as a cached layer before copying source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy source and install the project itself
COPY src ./src
RUN uv sync --frozen

CMD ["uv", "run", "uvicorn", "rmf2_vda5050_master.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]
