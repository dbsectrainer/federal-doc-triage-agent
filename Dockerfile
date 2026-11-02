FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (see .dockerignore for excluded files)
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# This is a CLI service, not an HTTP server.  The health check verifies that
# the workflow graph and agent imports load successfully.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "from workflows.graph import create_workflow; create_workflow()" || exit 1

# Default command
CMD ["python", "-m", "agents.demo", "samples/sample_foia_request.txt"]
