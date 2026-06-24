"""In-memory scoreboard state and scoring behavior."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ScoreboardState:
    def __init__(
        self,
        users_config: dict[str, Any],
        scoring_config: dict[str, Any],
        persistence_path: Path | None = None,
    ) -> None:
        self.lock = asyncio.Lock()
        self.scoring = scoring_config
        self.services = list(scoring_config["services"])
        self.persistence_path = persistence_path
        self.recent_events: list[dict[str, Any]] = []
        self.participants: dict[str, dict[str, Any]] = {}
        self.participant_aliases: dict[str, str] = {}

        for participant in users_config["participants"]:
            router_ip = participant["router_ip"]
            self.participants[router_ip] = {
                "name": participant["name"],
                "display_name": participant.get("display_name") or participant["name"],
                "router_ip": router_ip,
                "score": 0,
                "services": {
                    service: {"status": "red", "last_seen": None}
                    for service in self.services
                },
            }
            aliases = [
                router_ip,
                participant.get("syslog_host"),
                participant.get("router_id"),
                *participant.get("aliases", []),
            ]
            for alias in aliases:
                if alias:
                    self.participant_aliases[str(alias).lower()] = router_ip

        self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        if not self.persistence_path or not self.persistence_path.exists():
            return
        try:
            saved = json.loads(self.persistence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        for router_ip, saved_participant in saved.get("participants", {}).items():
            participant = self.participants.get(router_ip)
            if not participant:
                continue
            participant["score"] = int(saved_participant.get("score", 0))
            for service in self.services:
                saved_service = saved_participant.get("services", {}).get(service, {})
                if saved_service.get("status") in {"green", "red"}:
                    participant["services"][service]["status"] = saved_service["status"]
                participant["services"][service]["last_seen"] = saved_service.get("last_seen")

        events = saved.get("recent_events", [])
        self.recent_events = events[-100:] if isinstance(events, list) else []

    def _persist_unlocked(self) -> None:
        if not self.persistence_path:
            return
        payload = {
            "participants": self.participants,
            "recent_events": self.recent_events,
        }
        try:
            self.persistence_path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # Persistence is optional; a write failure must not stop the live demo.
            pass

    async def apply_event(self, event: dict[str, Any]) -> bool:
        participant_key = event.get("participant_ip") or event.get("participant_id")
        router_ip = self.participant_aliases.get(str(participant_key).lower())
        service = str(event.get("service", "")).lower()
        status = str(event.get("status", "")).lower()

        if not router_ip:
            raise ValueError(
                f"No participant is assigned to router identifier {participant_key!r}"
            )
        if service not in self.services:
            raise ValueError(f"Unknown service {service!r}; expected one of {self.services}")
        if status not in {"green", "red"}:
            raise ValueError("status must be 'green' or 'red'")

        async with self.lock:
            received_at = isoformat()
            timestamp = event.get("timestamp") or received_at
            participant = self.participants[router_ip]
            participant["services"][service] = {
                "status": status,
                # Freshness is based on when this process received the event.
                # Device clocks may be offset or use a different timezone.
                "last_seen": received_at,
            }
            normalized = {
                "timestamp": timestamp,
                "received_at": received_at,
                "participant_ip": router_ip,
                "participant_name": participant["display_name"],
                "service": service,
                "status": status,
                "event_type": event.get("event_type", "manual_event"),
                "username": event.get("username"),
                "remote_ip": event.get("remote_ip"),
                "raw": event.get("raw", ""),
            }
            self.recent_events.append(normalized)
            self.recent_events = self.recent_events[-100:]
            self._persist_unlocked()
        return True

    async def apply_score_tick(self) -> bool:
        points = int(self.scoring["points_per_service_per_minute"])
        changed = False
        async with self.lock:
            for participant in self.participants.values():
                green_count = sum(
                    1
                    for service in self.services
                    if participant["services"][service]["status"] == "green"
                )
                if green_count:
                    participant["score"] += green_count * points
                    changed = True
            if changed:
                self._persist_unlocked()
        return changed

    async def expire_stale_services(self) -> bool:
        timeout_seconds = int(self.scoring["service_timeout_seconds"])
        now = utc_now()
        changed = False

        async with self.lock:
            for participant in self.participants.values():
                for service in self.services:
                    service_state = participant["services"][service]
                    if service_state["status"] != "green":
                        continue
                    last_seen = parse_timestamp(service_state["last_seen"])
                    if not last_seen or (now - last_seen).total_seconds() <= timeout_seconds:
                        continue

                    service_state["status"] = "red"
                    event = {
                        "timestamp": isoformat(now),
                        "participant_ip": participant["router_ip"],
                        "participant_name": participant["display_name"],
                        "service": service,
                        "status": "red",
                        "event_type": "timeout",
                        "username": None,
                        "raw": f"Service timed out after {timeout_seconds} seconds without refresh",
                    }
                    self.recent_events.append(event)
                    changed = True

            if changed:
                self.recent_events = self.recent_events[-100:]
                self._persist_unlocked()
        return changed

    async def reset(self) -> None:
        async with self.lock:
            for participant in self.participants.values():
                participant["score"] = 0
                for service in self.services:
                    participant["services"][service] = {
                        "status": "red",
                        "last_seen": None,
                    }
            self.recent_events = []
            self._persist_unlocked()

    async def snapshot(self) -> dict[str, Any]:
        async with self.lock:
            participants = deepcopy(list(self.participants.values()))
            recent_events = deepcopy(self.recent_events)

        participants.sort(
            key=lambda item: (
                -item["score"],
                -sum(
                    service["status"] == "green"
                    for service in item["services"].values()
                ),
                item["display_name"].lower(),
            )
        )

        active_services = 0
        for rank, participant in enumerate(participants, start=1):
            participant["rank"] = rank
            participant["green_services_count"] = sum(
                service["status"] == "green"
                for service in participant["services"].values()
            )
            active_services += participant["green_services_count"]
            timestamps = [
                service["last_seen"]
                for service in participant["services"].values()
                if service["last_seen"]
            ]
            participant["last_seen"] = max(timestamps) if timestamps else None

        return {
            "updated_at": isoformat(),
            "scoring": deepcopy(self.scoring),
            "summary": {
                "participant_count": len(participants),
                "active_services": active_services,
                "maximum_active_services": len(participants) * len(self.services),
                "leader": participants[0]["display_name"] if participants else None,
                "leader_score": participants[0]["score"] if participants else 0,
            },
            "participants": participants,
            "recent_events": list(reversed(recent_events[-50:])),
        }
