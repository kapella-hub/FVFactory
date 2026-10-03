FROM python:3.12-slim

# Set working directory
WORKDIR /workspace

# Install system dependencies for moviepy (curl + ca-certificates: the Node.js setup below)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    imagemagick \
    fonts-dejavu-core \
    fonts-liberation \
    fontconfig \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 + the headless script-LLM CLIs that app/llm.py shells out to (LLM_PROVIDER=claude_cli | codex).
# Auth: CLAUDE_CODE_OAUTH_TOKEN / CODEX_API_KEY in the mounted .env (the app hands each CLI only its own)
# or the mounted ~/.codex login; see docker-compose.yml.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code @openai/codex \
    && npm cache clean --force \
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
