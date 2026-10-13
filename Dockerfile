# Base image Python 3.12 slim
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jakarta

# Install system dependencies (tzdata for correct timezone handling)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    ca-certificates \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY pyproject.toml .
COPY config.json .
COPY task_filters.json .
COPY dialogues.json .
COPY ayaka/ ./ayaka/

# Run as an unprivileged user (uid 1000 matches the usual host owner of bind-mounted files)
RUN useradd --uid 1000 --create-home ayaka \
    && mkdir -p /app/data \
    && chown -R ayaka:ayaka /app
USER ayaka

# Default command: run Ayaka 24/7 daemon bot
CMD ["python", "-m", "ayaka.main"]
