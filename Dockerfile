FROM python:3.14-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY agent ./agent

RUN pip install --no-cache-dir uv \
    && uv sync --no-dev --frozen

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "agent.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
