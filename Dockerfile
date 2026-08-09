FROM python:3.12-slim

ARG APP_VERSION
LABEL org.opencontainers.image.title="GameLibrary" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="https://github.com/douwjacobs/GameLibrary"
ENV APP_VERSION=${APP_VERSION}

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Refuse images whose OCI metadata does not match the application release.
RUN test -n "${APP_VERSION}" \
    && test "${APP_VERSION}" = "$(tr -d '\r\n' < /app/VERSION)"
RUN sed -i 's/\r$//' /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/startweb-docker.sh
RUN chmod a+x /app/entrypoint.sh
RUN chmod a+x /app/startweb-docker.sh

EXPOSE 5006
ENTRYPOINT ["/bin/bash","/app/entrypoint.sh"]
