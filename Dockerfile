FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev netcat-traditional && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code

COPY req.txt .
RUN pip install --no-cache-dir -r req.txt

COPY app app
COPY alembic alembic
COPY alembic.ini alembic.ini
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1
CMD ["/entrypoint.sh"]
