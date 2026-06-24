"""Digi Access Scoreboard FastAPI application."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from parsers import parse_log_events
from state import ScoreboardState


BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("uvicorn.error")
LOG_MODE = os.environ.get("LOG_MODE", "demo").lower()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


USERS_CONFIG = load_json(BASE_DIR / "users.json")
SCORING_CONFIG = load_json(BASE_DIR / "scoring.json")
PERSISTENCE_PATH = (
    Path(os.environ["STATE_FILE"]).expanduser()
    if os.environ.get("STATE_FILE")
    else None
)
scoreboard = ScoreboardState(USERS_CONFIG, SCORING_CONFIG, PERSISTENCE_PATH)


class ManualEvent(BaseModel):
    participant_ip: str
    service: str
    status: str
    event_type: str = "manual_event"
    username: str | None = None
    raw: str = Field(default="manual event", max_length=5000)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self.lock:
            self.connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self.lock:
            if websocket in self.connections:
                self.connections.remove(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        async with self.lock:
            connections = list(self.connections)
        stale: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)


connections = ConnectionManager()
unknown_participant_identifiers: set[str] = set()


async def state_snapshot() -> dict[str, Any]:
    snapshot = await scoreboard.snapshot()
    snapshot["mode"] = LOG_MODE
    return snapshot


async def broadcast_state() -> None:
    await connections.broadcast(await state_snapshot())


async def process_log_line(line: str) -> None:
    events = parse_log_events(line)
    if not events:
        return

    changed = False
    for event in events:
        try:
            changed = await scoreboard.apply_event(event) or changed
        except ValueError as error:
            # Report each unknown source once instead of silently losing its events.
            participant_key = event.get("participant_ip") or event.get("participant_id")
            identifier = str(participant_key)
            if (
                identifier not in unknown_participant_identifiers
                and len(unknown_participant_identifiers) < 100
            ):
                unknown_participant_identifiers.add(identifier)
                logger.warning("Ignoring log event: %s", error)
            continue
    if changed:
        await broadcast_state()


async def demo_log_reader() -> None:
    log_path = Path(os.environ.get("LOG_FILE", BASE_DIR / "sample_logs.txt"))
    loop_demo = os.environ.get("DEMO_LOOP", "true").lower() in {"1", "true", "yes"}

    while True:
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            await asyncio.sleep(2)
            continue

        for line in lines:
            await process_log_line(line)
            await asyncio.sleep(random.uniform(1, 3))

        if not loop_demo:
            return


def live_log_paths() -> list[Path]:
    configured = os.environ.get("LIVE_LOG_FILES")
    if configured:
        values = configured.split(",")
    elif os.environ.get("LOG_FILE"):
        values = [os.environ["LOG_FILE"]]
    else:
        values = ["/var/log/syslog", "/var/log/tac_plus_acct.log"]
    return [Path(value.strip()).expanduser() for value in values if value.strip()]


async def live_log_reader(log_path: Path) -> None:
    start_at_end = os.environ.get("LIVE_FROM_START", "false").lower() not in {
        "1",
        "true",
        "yes",
    }
    opened_once = False
    last_error: str | None = None

    while True:
        try:
            with log_path.open(encoding="utf-8", errors="replace") as file:
                if last_error:
                    logger.info("Now tailing %s", log_path)
                    last_error = None
                if start_at_end and not opened_once:
                    file.seek(0, 2)
                opened_once = True
                opened_inode = os.fstat(file.fileno()).st_ino
                while True:
                    line = file.readline()
                    if line:
                        await process_log_line(line)
                    else:
                        await asyncio.sleep(0.5)
                        try:
                            file_status = log_path.stat()
                        except OSError:
                            break
                        if (
                            file_status.st_ino != opened_inode
                            or file_status.st_size < file.tell()
                        ):
                            break
        except OSError as error:
            error_message = f"{type(error).__name__}: {error}"
            if error_message != last_error:
                logger.warning("Cannot read %s (%s); retrying", log_path, error)
                last_error = error_message
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = []
    if LOG_MODE == "demo":
        tasks.append(asyncio.create_task(demo_log_reader()))
    elif LOG_MODE == "live":
        logger.info(
            "Live mode: tailing %s",
            ", ".join(str(path) for path in live_log_paths()),
        )
        tasks.extend(
            asyncio.create_task(live_log_reader(log_path))
            for log_path in live_log_paths()
        )

    yield

    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Digi Access Scoreboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/img", StaticFiles(directory=BASE_DIR / "img"), name="img")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return await state_snapshot()


@app.post("/api/reset")
async def reset_state() -> dict[str, Any]:
    await scoreboard.reset()
    snapshot = await state_snapshot()
    await connections.broadcast(snapshot)
    return snapshot


@app.post("/api/event")
async def post_event(event: ManualEvent) -> dict[str, Any]:
    try:
        await scoreboard.apply_event(event.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    snapshot = await state_snapshot()
    await connections.broadcast(snapshot)
    return {"ok": True, "state": snapshot}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await connections.connect(websocket)
    try:
        await websocket.send_json(await state_snapshot())
        while True:
            # The browser sends a small keepalive; state updates are server-driven.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await connections.disconnect(websocket)
    except Exception:
        await connections.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
