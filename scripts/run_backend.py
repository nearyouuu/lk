from __future__ import annotations

import os
import socket
import time

import uvicorn
from alembic import command
from alembic.config import Config


def wait_for_db() -> None:
    host = os.getenv("DB_HOST")
    if not host:
        return

    port = int(os.getenv("DB_PORT", "5432"))
    attempts = int(os.getenv("DB_WAIT_ATTEMPTS", "30"))
    delay = float(os.getenv("DB_WAIT_DELAY", "2"))

    for attempt in range(1, attempts + 1):
        try:
            with socket.create_connection((host, port), timeout=3):
                print(f"Database is ready on {host}:{port}")
                return
        except OSError:
            print(f"Waiting for DB {host}:{port} ({attempt}/{attempts})...")
            time.sleep(delay)

    raise RuntimeError(f"Database is not reachable on {host}:{port}")


def run_migrations() -> None:
    if os.getenv("SKIP_MIGRATIONS") == "1":
        return

    if not os.path.exists("alembic.ini") or not os.path.isdir("alembic"):
        print("Alembic files not found, skipping migrations")
        return

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")


def main() -> None:
    wait_for_db()
    run_migrations()

    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "6123"))

    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
