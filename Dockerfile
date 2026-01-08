# Dockerfile for Google Cloud Run
FROM python:3.11-slim

# Build timestamp to force fresh builds (no cache)
ARG BUILD_TIMESTAMP=unknown
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory to the ORB strategy folder
WORKDIR /app
RUN mkdir -p "easy0DTE"

# Copy requirements first for better caching
COPY ["requirements.txt", "./requirements.txt"]

# Set Python to NEVER create bytecode files
ENV PYTHONDONTWRITEBYTECODE=1

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy BUILD_ID first to bust Docker cache when code changes
COPY ["BUILD_ID.txt", "./BUILD_ID.txt"]
RUN echo "📦 Build ID: $(cat BUILD_ID.txt) - Forces fresh layer"

# Copy ORB Strategy essential files (exclude historical data for smaller image)
COPY ["main.py", "./main.py"]
COPY ["modules", "./modules"]
# Copy data directory structure (Rev 00232: Fixed to handle optional subdirectories)
COPY ["data/watchlist/", "./data/watchlist/"]
COPY ["data/score/", "./data/score/"]
COPY ["data/holidays_custom.json", "./data/"]
COPY ["data/holidays_future_proof.json", "./data/"]
COPY ["configs", "./configs"]

# Exclude historical_intraday_data for production image size optimization
# This data is only needed for local backtesting, not cloud deployment

# Copy 0DTE Strategy modules (already copied by rsync in deploy script)
COPY ["easy0DTE/modules", "easy0DTE/modules"]

# Copy 0DTE Strategy configs (critical for deployment)
COPY ["easy0DTE/configs", "easy0DTE/configs"]

# Copy 0DTE BUILD_ID and VERSION (for tracking) - optional files
# Use shell to copy if files exist (Docker COPY doesn't support shell redirection)
RUN if [ -f "easy0DTE/BUILD_ID.txt" ]; then cp easy0DTE/BUILD_ID.txt easy0DTE/; fi && \
    if [ -f "easy0DTE/VERSION.txt" ]; then cp easy0DTE/VERSION.txt easy0DTE/; fi

# AGGRESSIVE: Remove ALL Python cache files and verify VERSION changed
RUN find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find . -name "*.pyc" -delete 2>/dev/null || true && \
    find . -name "*.pyo" -delete 2>/dev/null || true && \
    echo "✅ Python cache cleared after code copy" && \
    if [ -f VERSION.txt ]; then echo "📦 Build version: $(cat VERSION.txt)"; else echo "⚠️ No VERSION.txt"; fi

# Create necessary directories first
RUN mkdir -p logs data data/watchlist data/score

# Verify critical files exist and list them for debugging
RUN echo "=== Checking watchlist files ===" && \
    ls -lh data/watchlist/ && \
    if [ -f "data/watchlist/core_list.csv" ]; then \
        echo "✅ core_list.csv exists - $(wc -l < data/watchlist/core_list.csv) lines"; \
    else \
        echo "❌ core_list.csv NOT FOUND!"; \
    fi

# Set environment variables (PYTHONDONTWRITEBYTECODE already set earlier)
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV HOST=0.0.0.0

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application (Cloud Run entrypoint)
# Clear any runtime cache before starting
CMD find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find . -name "*.pyc" -delete 2>/dev/null || true && \
    python -B main.py --cloud-mode