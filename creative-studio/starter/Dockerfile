# Use the official Python base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy the pinned requirements (google-adk + streamlit + friends) first for
# better layer caching. This is the same file used for Streamlit Community
# Cloud, kept exact-pinned because google-adk==1.31.1 needs specific
# prerelease pins (opentelemetry-resourcedetector-gcp, pydantic).
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code (agents/ package, streamlit_app.py, etc.)
COPY . .

# Create a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Expose the port Cloud Run will use
EXPOSE 8080

# Run the Streamlit UI
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
