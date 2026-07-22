FROM python:3.12-slim

ARG TARGETARCH
ARG IBC_VERSION=3.23.0
ARG IB_GATEWAY_INSTALLER_URL=https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh
ARG OCI_SOURCE=https://github.com/rachitm0897/trading-engine
ARG OCI_VERSION=unspecified
ARG OCI_REVISION=unspecified
ARG OCI_CREATED=unspecified
ARG OCI_TITLE="Trading Engine IB Gateway"
ARG OCI_DESCRIPTION="One-session IBKR Gateway, IBC, noVNC, and Django API service"

LABEL org.opencontainers.image.source="$OCI_SOURCE" \
      org.opencontainers.image.version="$OCI_VERSION" \
      org.opencontainers.image.revision="$OCI_REVISION" \
      org.opencontainers.image.created="$OCI_CREATED" \
      org.opencontainers.image.title="$OCI_TITLE" \
      org.opencontainers.image.description="$OCI_DESCRIPTION"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN selected_arch="${TARGETARCH:-amd64}" && \
    if [ "$selected_arch" != "amd64" ]; then \
      echo "Unsupported target architecture: IB Gateway is packaged only for linux/amd64" >&2; \
      exit 64; \
    fi

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl unzip nginx supervisor xvfb fluxbox x11vnc novnc websockify default-jre tini gettext-base procps \
    libxrender1 libxtst6 libxi6 libfreetype6 libgtk-3-0 libasound2 libnss3 libxss1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 ibgateway && mkdir -p /opt/ibc /opt/ibgateway /data /run/nginx && \
    curl -fsSL "https://github.com/IbcAlpha/IBC/releases/download/${IBC_VERSION}/IbcLinux-${IBC_VERSION}.zip" -o /tmp/ibc.zip && \
    unzip -q /tmp/ibc.zip -d /opt/ibc && chmod +x /opt/ibc/*.sh && rm /tmp/ibc.zip && \
    curl -fsSL "$IB_GATEWAY_INSTALLER_URL" -o /tmp/ibgateway.sh && chmod +x /tmp/ibgateway.sh && \
    /tmp/ibgateway.sh -q -dir /opt/ibgateway || /tmp/ibgateway.sh -q && rm /tmp/ibgateway.sh && \
    mkdir -p /opt/Jts/ibgateway && ln -s /opt/ibgateway /opt/Jts/ibgateway/1045 && \
    chown -R ibgateway:ibgateway /home/ibgateway /opt/ibc /opt/ibgateway /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY manage.py runtime_config.py entrypoint.sh start-ibgateway.sh supervisord.conf nginx.conf.template proxy_headers.conf ./
COPY broker ./broker
COPY config ./config
COPY gateway_service ./gateway_service
RUN chmod +x entrypoint.sh start-ibgateway.sh /opt/ibc/scripts/*.sh && mkdir -p /var/log/supervisor
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:${PORT:-8080}/healthz || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "./entrypoint.sh"]
