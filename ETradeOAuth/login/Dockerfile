FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Google Cloud SDK for Secret Manager access
RUN curl https://sdk.cloud.google.com | bash
ENV PATH $PATH:/root/google-cloud-sdk/bin

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY oauth_backend.py .

# Copy oauth_keepalive module files
COPY keepalive_oauth.py .
COPY keepalive_start.py .

# Expose port
EXPOSE 8080

# Run the OAuth backend application
CMD ["python3", "oauth_backend.py"]

