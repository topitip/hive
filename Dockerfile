FROM python:3.13-slim
WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy workspace config and install deps
COPY pyproject.toml ./
COPY core/pyproject.toml core/pyproject.toml
COPY tools/ tools/
RUN uv sync --frozen --no-dev --extra server 2>/dev/null || \
    uv pip install --system aiohttp httpx litellm pydantic anthropic mcp fastmcp

# Copy framework source
COPY core/ core/
COPY exports/ exports/
COPY server.py .

ENV HIVE_PORT=8080
ENV PYTHONPATH=/app/core
EXPOSE 8080

CMD ["python", "server.py"]
