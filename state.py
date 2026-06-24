"""In-memory scoreboard state and scoring behavior."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


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
        self.one_time_services = set(scoring_config.get("one_time_services", []))
        self.one_time_points = int(scoring_config.get("one_time_points", 10))
        self.first_login_points = int(
            scoring_config.get("points_per_service_first_login", 10)
        )
        self.persistence_path = persistence_path
        self.recent_events: list[dict[str, Any]] = []
        self.participants: dict[str, dict[str, Any]] = {}
        self.participant_aliases: dict[str, str] = {}
        self.participant_networks: list[tuple[Any, str]] = []
        configured_networks: dict[Any, str] = {}

        for participant in users_config["participants"]:
            router_ip = str(participant["router_ip"])
            if router_ip in self.participants:
                raise ValueError(f"Duplicate router_ip {router_ip!r} in users.json")
            self.participants[router_ip] = {
                "name": participant["name"],
                "display_name": participant.get("display_name") or participant["name"],
                "router_ip": router_ip,
                "score": 0,
                "score_updated_at": None,
                "services": {
                    service: {
                        "status": "red",
                        "last_seen": None,
                        "earned": False,
                        "earned_at": None,
                    }
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

            additional_subnets = participant.get("subnets", [])
            if isinstance(additional_subnets, str):
                additional_subnets = [additional_subnets]
            network_values = [
                *([router_ip] if "/" in router_ip else []),
                *([participant["subnet"]] if participant.get("subnet") else []),
                *additional_subnets,
            ]
            for value in network_values:
                try:
                    network = ip_network(str(value), strict=False)
                except ValueError as error:
                    raise ValueError(
                        f"Invalid subnet {value!r} configured for {participant['name']!r}"
                    ) from error

                existing_router = configured_networks.get(network)
                if existing_router and existing_router != router_ip:
                    raise ValueError(
                        f"Subnet {network} is assigned to both "
                        f"{existing_router!r} and {router_ip!r}"
                    )
                configured_networks[network] = router_ip
                self.participant_networks.append((network, router_ip))

        self.participant_networks.sort(
            key=lambda item: item[0].prefixlen,
            reverse=True,
        )

        self._load_persisted_state()

    def _resolve_participant(self, participant_key: Any) -> str | None:
        if participant_key is None:
            return None

        value = str(participant_key).strip()
        exact_match = self.participant_aliases.get(value.lower())
        if exact_match:
            return exact_match

        try:
            address = ip_address(value)
        except ValueError:
            return None

        for network, router_ip in self.participant_networks:
            if address.version == network.version and address in network:
                return router_ip
        return None

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
            participant["score_updated_at"] = saved_participant.get("score_updated_at")
            for service in self.services:
                saved_service = saved_participant.get("services", {}).get(service, {})
                if saved_service.get("status") in {"green", "red", "logged"}:
                    participant["services"][service]["status"] = saved_service["status"]
                participant["services"][service]["last_seen"] = saved_service.get("last_seen")
                participant["services"][service]["earned"] = bool(
                    saved_service.get(
                        "earned",
                        saved_service.get("status") in {"green", "logged"},
                    )
                )
                participant["services"][service]["earned_at"] = saved_service.get(
                    "earned_at"
                )

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
        router_ip = self._resolve_participant(participant_key)
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
            current_service = participant["services"][service]
            if (
                service in self.one_time_services
                and current_service["status"] == "green"
            ):
                return False

            first_success = status == "green" and not current_service["earned"]
            if first_success:
                points = (
                    self.one_time_points
                    if service in self.one_time_services
                    else self.first_login_points
                )
                participant["score"] += points
                if not participant["score_updated_at"]:
                    participant["score_updated_at"] = received_at

            if service in self.one_time_services:
                display_status = "green"
            elif status == "green":
                display_status = "green"
            elif current_service["earned"]:
                display_status = "logged"
            else:
                display_status = "red"

            participant["services"][service] = {
                "status": display_status,
                # Freshness is based on when this process received the event.
                # Device clocks may be offset or use a different timezone.
                "last_seen": received_at,
                "earned": current_service["earned"] or first_success,
                "earned_at": (
                    received_at if first_success else current_service["earned_at"]
                ),
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

    async def reset(self) -> None:
        async with self.lock:
            for participant in self.participants.values():
                participant["score"] = 0
                participant["score_updated_at"] = None
                for service in self.services:
                    participant["services"][service] = {
                        "status": "red",
                        "last_seen": None,
                        "earned": False,
                        "earned_at": None,
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
                item["score_updated_at"] or "9999",
                item["display_name"].lower(),
            )
        )

        completed_services = 0
        for rank, participant in enumerate(participants, start=1):
            participant["rank"] = rank
            participant["green_services_count"] = sum(
                service["earned"]
                for service in participant["services"].values()
            )
            completed_services += participant["green_services_count"]
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
                "active_services": completed_services,
                "maximum_active_services": len(participants) * len(self.services),
                "leader": participants[0]["display_name"] if participants else None,
                "leader_score": participants[0]["score"] if participants else 0,
            },
            "participants": participants,
            "recent_events": list(reversed(recent_events[-50:])),
        }
