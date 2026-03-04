FROM python:3.10.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Update packages and install git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements files
COPY requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt 

# Copy all Python application files
COPY app.py main.py flow.py nodes.py ./
COPY utils/ ./utils/
COPY templates/ ./templates/
COPY static/ ./static/
COPY monitoring/ ./monitoring/

# Create necessary directories
RUN mkdir -p output uploads

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Run the Flask web app (default) or allow overriding with CLI
CMD ["python", "app.py"]
