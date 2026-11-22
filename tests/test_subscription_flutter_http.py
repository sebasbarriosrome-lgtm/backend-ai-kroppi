"""Run the Flutter client over TCP against FastAPI and a disposable PostgreSQL DB."""

import os
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_urlsafe
from threading import Thread
from time import monotonic, sleep

import jwt
import pytest
import uvicorn
from fastapi import FastAPI

from app import config
from app.core import security
from app.routers import subscriptions
from app.services import subscription_service
from tests.test_subscription_postgres import account, postgres, scalar  # noqa: F401


def test_flutter_subscription_http(postgres, monkeypatch):
    frontend = os.environ.get("KROPPI_QA_FLUTTER_DIR")
    if not frontend:
        pytest.skip("Set KROPPI_QA_FLUTTER_DIR to the Flutter project directory")
    flutter = shutil.which("flutter")
    assert flutter, "Flutter must be on PATH"
    frontend = Path(frontend).resolve(strict=True)
    test_path = "test/integration/subscription_http_test.dart"
    assert (frontend / test_path).is_file()

    with postgres() as conn:
        free = account(conn)
        premium = account(conn, "premium")
        downgraded = account(conn, "premium")
        for owner in (free, premium, premium):
            conn.execute("insert into farms (owner_id) values (%s)", (owner,))
        for _ in range(3):
            conn.execute("insert into diagnostics (user_id) values (%s)", (free,))
        farms = [scalar(conn, "insert into farms (owner_id) values (%s) returning id", downgraded)
                 for _ in range(10)]
        crops = [scalar(conn, "insert into crops (farm_id) values (%s) returning id", farm)
                 for farm in farms[:8]]
        for index in range(12):
            conn.execute("insert into plots (crop_id) values (%s)", (crops[index % len(crops)],))
        for _ in range(4):
            conn.execute("insert into diagnostics (user_id) values (%s)", (downgraded,))
        conn.execute("update profiles set premium_until = now() where id = %s", (downgraded,))

    # Substitute the PostgREST transport. Subscription state comes from the real SQL RPC.
    def rpc(name, user_id):
        assert name == "subscription_status"
        with postgres() as conn:
            conn.execute("set role service_role")
            return scalar(conn, "select subscription_status(%s)", user_id)

    monkeypatch.setattr(subscription_service, "_rpc", rpc)
    secret = token_urlsafe(48)
    issuer = "http://127.0.0.1/auth/v1"
    monkeypatch.setattr(security, "_ISSUER", issuer)
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", secret)

    def token(user, lifetime):
        return jwt.encode(
            {"sub": str(user), "iss": issuer, "aud": "authenticated",
             "exp": datetime.now(timezone.utc) + lifetime},
            secret, algorithm="HS256",
        )

    app = FastAPI()
    app.include_router(subscriptions.router)
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = monotonic() + 10
            while not server.started and thread.is_alive() and monotonic() < deadline:
                sleep(0.05)
            assert server.started, "FastAPI did not start on loopback"
            subprocess.run(
                [flutter, "test", "--no-pub", "--reporter", "expanded", test_path],
                cwd=frontend,
                env={**os.environ,
                     "KROPPI_QA_URL": f"http://127.0.0.1:{port}",
                     "KROPPI_QA_FREE_JWT": token(free, timedelta(minutes=5)),
                     "KROPPI_QA_PREMIUM_JWT": token(premium, timedelta(minutes=5)),
                     "KROPPI_QA_DOWNGRADED_JWT": token(downgraded, timedelta(minutes=5)),
                     "KROPPI_QA_EXPIRED_JWT": token(free, -timedelta(minutes=5))},
                check=True,
                timeout=120,
            )
        finally:
            server.should_exit = True
            thread.join(timeout=10)
