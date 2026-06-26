#!/usr/bin/env python3
"""Correlaciona IP origen -> MAC Digi desde un tcpdump -A de UDP/514.

Te imprime las parejas listas para pegar como `syslog_host` en users.json.

Uso:
  sudo tcpdump -l -n -A -i any 'udp port 514' | python3 harvest_macs.py
  (corta con Ctrl-C cuando ya viste a todos los participantes)
"""
from __future__ import annotations

import re
import sys

# Linea de cabecera tcpdump: ... IP <src>.<port> > <dst>.514:
HEADER = re.compile(
    r"\bIP\s+((?:\d{1,3}\.){3}\d{1,3})\.\d+\s*>\s*(?:\d{1,3}\.){3}\d{1,3}\.514:"
)
# MAC Digi: 12 hex en MAYUSCULAS (asi evitamos basura binaria del dump -A).
MAC = re.compile(r"\b([0-9A-F]{12})\b")


def main() -> None:
    current_ip: str | None = None
    seen: set[tuple[str, str]] = set()
    for line in sys.stdin:
        header = HEADER.search(line)
        if header:
            current_ip = header.group(1)
            continue
        if current_ip:
            mac = MAC.search(line)
            if mac:
                pair = (current_ip, mac.group(1))
                if pair not in seen:
                    seen.add(pair)
                    print(f'{pair[0]:<15} -> "syslog_host": "{pair[1]}"')
                current_ip = None


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
