# Production-Grade Containerization for Telemetry Event Simulator
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install security updates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create an unprivileged user
RUN groupadd -g 10002 telemgroup && \
    useradd -u 10002 -g telemgroup -s /bin/false -m telemuser

COPY alert_generator.py .
RUN chown -R telemuser:telemgroup /app

USER 10002:10002

CMD ["python", "alert_generator.py"]
