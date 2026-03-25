FROM node:22-slim

# Install Python, system deps, and native build tools (for better-sqlite3)
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    git curl procps ffmpeg \
    build-essential \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally (available for agent tasks inside sandbox)
RUN npm install -g @anthropic-ai/claude-code

ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /orchestrator

# Dashboard dependencies
COPY dashboard/package*.json dashboard/
RUN cd dashboard && npm install --omit=dev

# Python dependencies
COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

# Copy source
COPY . .

EXPOSE 23714

COPY bin/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Ensure data dir exists with correct ownership before volume mount
RUN mkdir -p /orchestrator/data /orchestrator/tmp && \
    touch /orchestrator/data/events.db-wal /orchestrator/data/events.db-shm \
          /orchestrator/data/event_bus.db-wal /orchestrator/data/event_bus.db-shm

# Use existing non-root 'node' user (uid 1000) so claude --dangerously-skip-permissions works
RUN chown -R node:node /orchestrator

# Claude CLI reads credentials from ~/.claude/ but we mount them at /claude-home/
# Create symlink so CLI finds the OAuth credentials
RUN mkdir -p /home/node/.claude && \
    ln -sf /claude-home/.credentials.json /home/node/.claude/.credentials.json && \
    chown -R node:node /home/node/.claude

USER node

ENTRYPOINT ["/docker-entrypoint.sh"]
