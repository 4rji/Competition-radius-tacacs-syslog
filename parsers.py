"""Small, modular parsers for SYSLOG, RADIUS, and TACACS+ log lines."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


IP_PATTERN = r"(?:\d{1,3}\.){3}\d{1,3}"
AAA_ACCOUNTING_PATTERN = re.compile(
    rf"^\s*(?P<timestamp>\d{{4}}-\d{{2}}-\d{{2}}\s+"
    rf"\d{{2}}:\d{{2}}:\d{{2}}\s+[+-]\d{{4}})\s+"
    rf"(?P<router_ip>{IP_PATTERN})\s+"
    rf"(?P<username>\S+)\s+"
    rf"(?P<port>\S+)\s+"
    rf"(?P<remote_ip>{IP_PATTERN})\s+"
    rf"(?P<action>start|stop)\b",
    re.IGNORECASE,
)
SYSLOG_PACKET_PATTERN = re.compile(
    rf"\bIP\s+(?P<source_ip>{IP_PATTERN})\.\d+\s*>\s*"
    rf"{IP_PATTERN}\.514:\s+SYSLOG\s+local0\.(?:notice|warning)\b",
    re.IGNORECASE,
)
DIGI_SYSLOG_PATTERN = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}T"
    r"\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+"
    r"(?P<host>[0-9A-F]{12})\s+",
    re.IGNORECASE,
)
DIGI_WEB_SESSION_PATTERN = re.compile(
    rf"\buser\s+User\s+(?P<username>\S+)\s+"
    rf"(?P<action>successfully\s+opened|logout)\s+web\s+session\s+"
    rf"from(?:\s+IP)?\s+(?P<remote_ip>{IP_PATTERN})\b",
    re.IGNORECASE,
)


def _search(pattern: str, line: str, flags: int = re.IGNORECASE) -> str | None:
    match = re.search(pattern, line, flags)
    return match.group(1) if match else None


def _event(
    line: str,
    participant_ip: str | None,
    service: str,
    status: str,
    event_type: str,
    username: str | None = None,
    *,
    participant_id: str | None = None,
    remote_ip: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    event = {
        "participant_ip": participant_ip,
        "service": service,
        "status": status,
        "event_type": event_type,
        "username": username,
        "raw": line.strip(),
    }
    if participant_id:
        event["participant_id"] = participant_id
    if remote_ip:
        event["remote_ip"] = remote_ip
    if timestamp:
        event["timestamp"] = timestamp
    return event


def _normalize_timestamp(value: str, format_string: str | None = None) -> str | None:
    try:
        parsed = (
            datetime.strptime(value, format_string)
            if format_string
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except ValueError:
        return None
    return parsed.isoformat()


def parse_syslog(line: str) -> dict[str, Any] | None:
    """Detect either a stored Digi syslog line or captured SYSLOG UDP traffic."""
    digi_match = DIGI_SYSLOG_PATTERN.search(line)
    if digi_match:
        return _event(
            line=line,
            participant_ip=None,
            participant_id=digi_match.group("host"),
            service="syslog",
            status="green",
            event_type="syslog_received",
            timestamp=_normalize_timestamp(digi_match.group("timestamp")),
        )

    packet_match = SYSLOG_PACKET_PATTERN.search(line)
    if packet_match:
        return _event(
            line=line,
            participant_ip=packet_match.group("source_ip"),
            service="syslog",
            status="green",
            event_type="syslog_received",
        )

    return None


def parse_digi_radius_session(line: str) -> dict[str, Any] | None:
    """Treat adminradius Digi web sessions as RADIUS activity."""
    digi_match = DIGI_SYSLOG_PATTERN.search(line)
    session_match = DIGI_WEB_SESSION_PATTERN.search(line)
    if (
        not digi_match
        or not session_match
        or session_match.group("username").lower() != "adminradius"
    ):
        return None

    is_login = session_match.group("action").lower().startswith("successfully")
    return _event(
        line=line,
        participant_ip=None,
        participant_id=digi_match.group("host"),
        service="radius",
        status="green" if is_login else "red",
        event_type="web_session_opened" if is_login else "web_session_logout",
        username=session_match.group("username"),
        remote_ip=session_match.group("remote_ip"),
        timestamp=_normalize_timestamp(digi_match.group("timestamp")),
    )


def parse_aaa_accounting(line: str) -> dict[str, Any] | None:
    """Parse tac_plus accounting records for TACACS+ and RADIUS SSH users."""
    match = AAA_ACCOUNTING_PATTERN.search(line)
    if not match:
        return None

    username = match.group("username")
    username_lower = username.lower()
    if username_lower == "admintac":
        service = "tacacs"
    elif username_lower == "adminradius":
        service = "radius"
    else:
        return None

    action = match.group("action").lower()
    is_start = action == "start"
    return _event(
        line=line,
        participant_ip=match.group("router_ip"),
        service=service,
        status="green" if is_start else "red",
        event_type="accounting_start" if is_start else "accounting_stop",
        username=username,
        remote_ip=match.group("remote_ip"),
        timestamp=_normalize_timestamp(
            match.group("timestamp"),
            "%Y-%m-%d %H:%M:%S %z",
        ),
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
    events = parse_log_events(line)
    return events[0] if events else None


def parse_log_events(line: str) -> list[dict[str, Any]]:
    """Return all normalized events represented by one log line."""
    if not line or not line.strip() or line.lstrip().startswith("#"):
        return []

    events: list[dict[str, Any]] = []
    syslog_event = parse_syslog(line)
    if syslog_event:
        events.append(syslog_event)

    digi_radius_event = parse_digi_radius_session(line)
    if digi_radius_event:
        events.append(digi_radius_event)

    # A stored Digi line has already been fully classified above. The
    # remaining parsers cover independent AAA, FreeRADIUS, and TACACS+ logs.
    if syslog_event:
        return events

    for parser in (parse_aaa_accounting, parse_radius, parse_tacacs):
        event = parser(line)
        if event:
            events.append(event)
            break
    return events
