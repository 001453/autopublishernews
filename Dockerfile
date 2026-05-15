FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine.py bot.py dashboard.py x_watch.py ./
COPY templates/ ./templates/
COPY scripts/ ./scripts/
COPY panel_config.json ./panel_config.json

RUN chmod +x scripts/start_bot_chrome.sh scripts/run_vps.sh

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV X_PROFILE_DIR=/app/data/x_profile
ENV PANEL_CONFIG_PATH=/app/data/panel_config.json
ENV AUTO_START_SCHEDULER=1
ENV PANEL_HOST=0.0.0.0
ENV PANEL_PORT=8765
ENV USE_EXISTING_CHROME=0
ENV BROWSER_CHANNEL=chromium
ENV HEADLESS=0
ENV BOT_CDP_PORT=9333

EXPOSE 8765
VOLUME ["/app/data"]

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD curl -sf http://127.0.0.1:8765/api/health || exit 1

CMD ["bash", "scripts/run_vps.sh"]
