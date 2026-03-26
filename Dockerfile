FROM python:3.12-slim

# Set working directory
WORKDIR /workspace

# Install system dependencies for moviepy
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Fix ImageMagick policy to allow text processing
COPY imagemagick-policy.xml /etc/ImageMagick-6/policy.xml

# Refresh font cache
RUN fc-cache -f -v

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /workspace/output

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command
CMD ["python", "main.py"]
