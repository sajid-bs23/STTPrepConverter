FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first
COPY requirements.txt ./

# Install dependencies as root
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app

# Copy application source
COPY app/ ./app/
COPY scripts/ ./scripts/

# Ensure scripts are executable
RUN chmod +x scripts/*.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
