FROM python:3.12-slim

ARG APP_VERSION
LABEL org.opencontainers.image.title="GameLibrary" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/douwjacobs/GameLibrary"
ENV APP_VERSION=${APP_VERSION}

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 gamelibrary \
    && useradd --uid 10001 --gid gamelibrary --create-home \
        --home-dir /home/gamelibrary --shell /usr/sbin/nologin gamelibrary

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=gamelibrary:gamelibrary . .

# Refuse images whose OCI metadata does not match the application release.
RUN test -n "${APP_VERSION}" \
    && test "${APP_VERSION}" = "$(tr -d '\r\n' < /app/VERSION)"
RUN sed -i 's/\r$//' /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/startweb-docker.sh
RUN chmod a+x /app/entrypoint.sh /app/startweb-docker.sh \
    && mkdir -p /backups /app/sharewarez/static/library \
    && chown -R gamelibrary:gamelibrary \
        /app /backups /home/gamelibrary

EXPOSE 5006
USER 10001:10001
ENTRYPOINT ["/bin/bash","/app/entrypoint.sh"]
