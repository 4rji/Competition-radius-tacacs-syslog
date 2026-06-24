"""Small, modular parsers for Digi, RADIUS, and TACACS+ log lines."""

from __future__ import annotations

import re
from typing import Any


IP_PATTERN = r"(?:\d{1,3}\.){3}\d{1,3}"


def _search(pattern: str, line: str, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, line, flags)
    return match.group(1) if match else None


def _event(
    line: str,
    participant_ip: str,
    service: str,
    status: str,
    event_type: str,
    username: str | None = None,
) -> dict[str, Any]:
    return {
        "participant_ip": participant_ip,
        "service": service,
        "status": status,
        "event_type": event_type,
        "username": username,
        "raw": line.strip(),
    }


def parse_digi_webui(line: str) -> dict[str, Any] | None:
    """Parse Digi WebUI opened/closed session messages."""
    service = _search(r"\bservice=(web|https|webui)\b", line)
    state = _search(r"\bstate=(opened|closed)\b", line)
    participant_ip = _search(rf"\bremote=({IP_PATTERN})\b", line)

    if not (service and state and participant_ip):
        return None

    username = _search(r"\bname=([^~\s]+)", line)
    is_open = state.lower() == "opened"
    return _event(
        line=line,
        participant_ip=participant_ip,
        service="webui",
        status="green" if is_open else "red",
        event_type="login_success" if is_open else "logout",
        username=username,
    )


def parse_radius(line: str) -> dict[str, Any] | None:
    """Parse common FreeRADIUS Access-Accept and accounting messages."""
    if not re.search(r"\bradiusd\b|Access-Accept|Acct-Status-Type|Login OK", line, re.I):
        return None

    participant_ip = (
        _search(rf"\bNAS-IP-Address\s*=\s*({IP_PATTERN})\b", line)
        or _search(rf"\bfrom client\s+({IP_PATTERN})\b", line)
    )
    if not participant_ip:
        return None

    username = (
        _search(r'\bUser-Name\s*=\s*"([^"]+)"', line)
        or _search(r"\bLogin OK:\s*\[([^\]]+)\]", line)
    )

    if re.search(r"\bAcct-Status-Type\s*=\s*Stop\b", line, re.I):
        return _event(line, participant_ip, "radius", "red", "accounting_stop", username)

    if re.search(r"\bAcct-Status-Type\s*=\s*Start\b", line, re.I):
        return _event(line, participant_ip, "radius", "green", "accounting_start", username)

    if re.search(r"\bAccess-Accept\b|\bLogin OK\b", line, re.I):
        return _event(line, participant_ip, "radius", "green", "access_accept", username)

    return None


def parse_tacacs(line: str) -> dict[str, Any] | None:
    """Parse the TACACS+ demo formats for the admintac account."""
    if not re.search(r"\btac_plus\b", line, re.I):
        return None

    username = _search(r'\buser="?([^"\s]+)"?', line)
    participant_ip = _search(rf"\bclient=({IP_PATTERN})\b", line)
    if not participant_ip or not username or username.lower() != "admintac":
        return None

    if re.search(r"\baction=logout\b|\bstatus=closed\b", line, re.I):
        return _event(line, participant_ip, "tacacs", "red", "logout", username)

    if re.search(r"\bstatus=success\b|\bresult=success\b", line, re.I):
        return _event(line, participant_ip, "tacacs", "green", "auth_success", username)

    return None


def parse_log_line(line: str) -> dict[str, Any] | None:
    """Run a line through each parser and return the first normalized event."""
    if not line or not line.strip() or line.lstrip().startswith("#"):
        return None

    for parser in (parse_digi_webui, parse_radius, parse_tacacs):
        event = parser(line)
        if event:
            return event
    return None
