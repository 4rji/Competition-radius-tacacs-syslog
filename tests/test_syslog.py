import asyncio
import json
import unittest
from pathlib import Path

from parsers import parse_log_events, parse_syslog
from state import ScoreboardState


BASE_DIR = Path(__file__).resolve().parents[1]


class SyslogParserTests(unittest.TestCase):
    def test_decoded_tcpdump_packet(self) -> None:
        event = parse_syslog(
            "10:55:01.117927 enp0s3 In IP 10.10.65.73.47973 > "
            "10.10.65.214.514: SYSLOG local0.notice, length: 92"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["participant_ip"], "10.10.65.73")

    def test_undecoded_udp_packet(self) -> None:
        event = parse_syslog(
            "10:55:01.117927 enp0s3 In IP 10.10.65.77.47977 > "
            "10.10.65.214.514: UDP, length 92"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["participant_ip"], "10.10.65.77")

    def test_tcpdump_service_name_port(self) -> None:
        event = parse_syslog(
            "10:55:01.117927 IP 10.10.65.48.47948 > "
            "10.10.65.214.syslog: UDP, length 92"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["participant_ip"], "10.10.65.48")

    def test_stored_iso_line_with_ip_hostname(self) -> None:
        events = parse_log_events(
            "2026-06-24T16:13:19-05:00 10.10.65.78 "
            "user User admin POST page login"
        )

        self.assertEqual(events[0]["participant_ip"], "10.10.65.78")

    def test_stored_bsd_line_with_ip_hostname(self) -> None:
        event = parse_syslog(
            "Jun 24 16:13:19 10.10.65.79 user User admin POST page login"
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["participant_ip"], "10.10.65.79")

    def test_current_participant_receives_syslog_score(self) -> None:
        users = json.loads((BASE_DIR / "users.json").read_text(encoding="utf-8"))
        scoring = json.loads((BASE_DIR / "scoring.json").read_text(encoding="utf-8"))
        state = ScoreboardState(users, scoring)
        event = parse_syslog(
            "10:55:01.117927 IP 10.10.65.73.47973 > "
            "10.10.65.214.514: UDP, length 92"
        )

        changed = asyncio.run(state.apply_event(event))
        snapshot = asyncio.run(state.snapshot())
        ted = next(
            participant
            for participant in snapshot["participants"]
            if participant["router_ip"] == "10.10.65.73"
        )

        self.assertTrue(changed)
        self.assertEqual(ted["score"], 10)
        self.assertEqual(ted["services"]["syslog"]["status"], "green")


if __name__ == "__main__":
    unittest.main()
