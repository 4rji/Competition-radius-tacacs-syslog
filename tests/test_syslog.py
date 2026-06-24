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

    def test_real_tcpdump_sample_scores_configured_source_ip(self) -> None:
        users = json.loads((BASE_DIR / "users.json").read_text(encoding="utf-8"))
        scoring = json.loads((BASE_DIR / "scoring.json").read_text(encoding="utf-8"))
        state = ScoreboardState(users, scoring)
        event = parse_syslog(
            "peer 15:58:49.572593 enp0s3 In  IP "
            "10.10.65.57.43527 > 10.10.65.214.514: "
            "SYSLOG local0.notice, length: 117"
        )

        changed = asyncio.run(state.apply_event(event))
        snapshot = asyncio.run(state.snapshot())
        participant = next(
            participant
            for participant in snapshot["participants"]
            if participant["router_ip"] == "10.10.65.57"
        )

        self.assertTrue(changed)
        self.assertEqual(participant["score"], 10)
        self.assertEqual(participant["services"]["syslog"]["status"], "green")

    def test_real_digi_message_scores_even_when_login_fails(self) -> None:
        users = json.loads((BASE_DIR / "users.json").read_text(encoding="utf-8"))
        scoring = json.loads((BASE_DIR / "scoring.json").read_text(encoding="utf-8"))
        state = ScoreboardState(users, scoring)
        event = parse_syslog(
            "2026-06-24T20:38:04-05:00 00409DDE26B5 user User admin "
            "POST page login from IP 10.10.65.237 via port  (ID 7f74a3aceb)"
        )

        changed = asyncio.run(state.apply_event(event))
        snapshot = asyncio.run(state.snapshot())
        havi = next(
            participant
            for participant in snapshot["participants"]
            if participant["router_ip"] == "10.10.65.72"
        )

        self.assertTrue(changed)
        self.assertEqual(havi["score"], 10)
        self.assertEqual(havi["services"]["syslog"]["status"], "green")

    def test_local_tacacs_failure_is_not_digi_syslog(self) -> None:
        event = parse_syslog(
            "2026-06-24T15:38:05.658545-05:00 ts-lab-ubuntu-util "
            "tac_plus[22537]: 10.10.65.72 pap login for 'admin' "
            "from unknown on unknown failed"
        )

        self.assertIsNone(event)


class ParticipantSubnetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scoring = json.loads(
            (BASE_DIR / "scoring.json").read_text(encoding="utf-8")
        )

    def test_router_ip_can_be_a_subnet(self) -> None:
        state = ScoreboardState(
            {
                "participants": [
                    {"name": "Subnet lab", "router_ip": "10.20.30.0/24"}
                ]
            },
            self.scoring,
        )

        changed = asyncio.run(
            state.apply_event(
                {
                    "participant_ip": "10.20.30.99",
                    "service": "syslog",
                    "status": "green",
                }
            )
        )
        snapshot = asyncio.run(state.snapshot())

        self.assertTrue(changed)
        self.assertEqual(snapshot["participants"][0]["score"], 10)

    def test_optional_subnet_alias_maps_to_primary_router(self) -> None:
        state = ScoreboardState(
            {
                "participants": [
                    {
                        "name": "Lab router",
                        "router_ip": "10.10.65.72",
                        "subnets": ["172.20.4.0/24"],
                    }
                ]
            },
            self.scoring,
        )

        asyncio.run(
            state.apply_event(
                {
                    "participant_ip": "172.20.4.88",
                    "service": "syslog",
                    "status": "green",
                }
            )
        )
        snapshot = asyncio.run(state.snapshot())

        self.assertEqual(snapshot["participants"][0]["router_ip"], "10.10.65.72")
        self.assertEqual(snapshot["participants"][0]["score"], 10)

    def test_exact_ip_has_priority_over_broader_subnet(self) -> None:
        state = ScoreboardState(
            {
                "participants": [
                    {
                        "name": "Subnet owner",
                        "router_ip": "10.10.65.72",
                        "subnet": "10.10.65.0/24",
                    },
                    {"name": "Exact owner", "router_ip": "10.10.65.73"},
                ]
            },
            self.scoring,
        )

        asyncio.run(
            state.apply_event(
                {
                    "participant_ip": "10.10.65.73",
                    "service": "syslog",
                    "status": "green",
                }
            )
        )
        snapshot = asyncio.run(state.snapshot())
        scores = {
            participant["display_name"]: participant["score"]
            for participant in snapshot["participants"]
        }

        self.assertEqual(scores["Exact owner"], 10)
        self.assertEqual(scores["Subnet owner"], 0)

    def test_duplicate_subnet_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "assigned to both"):
            ScoreboardState(
                {
                    "participants": [
                        {
                            "name": "One",
                            "router_ip": "10.1.0.10",
                            "subnet": "10.1.0.0/24",
                        },
                        {
                            "name": "Two",
                            "router_ip": "10.1.0.20",
                            "subnet": "10.1.0.0/24",
                        },
                    ]
                },
                self.scoring,
            )


if __name__ == "__main__":
    unittest.main()
