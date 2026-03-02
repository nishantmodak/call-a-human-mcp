FROM python:3.11-slim

WORKDIR /app

# Install the package and its dependencies
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# SSE server listens on this port
EXPOSE 8000

# Default to SSE transport bound to all interfaces so Docker port mapping works.
# Override CALL_HUMAN_CHANNEL and channel-specific vars via --env-file or -e flags.
ENV CALL_HUMAN_CHANNEL=slack

CMD ["call-a-human-mcp", "--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]
