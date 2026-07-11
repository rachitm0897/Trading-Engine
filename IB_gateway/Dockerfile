FROM python:3.12-slim
ARG IBC_VERSION=3.23.0
ARG IB_GATEWAY_INSTALLER_URL=https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx supervisor xvfb fluxbox x11vnc novnc websockify default-jre tini gettext-base procps \
    libxrender1 libxtst6 libxi6 libfreetype6 libgtk-3-0 libasound2 libnss3 libxss1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 ibgateway && mkdir -p /opt/ibc /opt/ibgateway /data /run/nginx && \
    curl -fsSL "https://github.com/IbcAlpha/IBC/releases/download/${IBC_VERSION}/IbcLinux-${IBC_VERSION}.zip" -o /tmp/ibc.zip && \
    unzip -q /tmp/ibc.zip -d /opt/ibc && chmod +x /opt/ibc/*.sh && rm /tmp/ibc.zip && \
    curl -fsSL "$IB_GATEWAY_INSTALLER_URL" -o /tmp/ibgateway.sh && chmod +x /tmp/ibgateway.sh && \
    /tmp/ibgateway.sh -q -dir /opt/ibgateway || /tmp/ibgateway.sh -q && rm /tmp/ibgateway.sh && \
    chown -R ibgateway:ibgateway /home/ibgateway /opt/ibc /opt/ibgateway /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x entrypoint.sh start-ibgateway.sh && mkdir -p /var/log/supervisor
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:${PORT:-8080}/healthz || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "./entrypoint.sh"]

