#!/usr/bin/env bash
# Arranca la captura tcpdump + el scoreboard en modo live, leyendo las dos
# fuentes a la vez: IP (tcpdump) y MAC (/var/log/syslog).
#
# Uso:
#   ./run-live.sh                # interfaz 'any' por default
#   IFACE=enp0s13f0u1u4 ./run-live.sh
set -euo pipefail

IFACE="${IFACE:-any}"
CAP_FILE="${CAP_FILE:-/tmp/digi-scoreboard-syslog.log}"
SYSLOG_FILE="${SYSLOG_FILE:-/var/log/syslog}"
TACACS_FILE="${TACACS_FILE:-/var/log/tac_plus_acct.log}"

cd "$(dirname "$0")"

# Captura fresca: el shell (como tu usuario) crea/vacia el archivo antes de sudo,
# asi queda con tu dueno y la app lo puede leer.
: > "$CAP_FILE"

echo "Capturando UDP/514 en '$IFACE' -> $CAP_FILE (pide sudo una vez)"
sudo tcpdump -l -n -i "$IFACE" 'udp port 514' > "$CAP_FILE" &

cleanup() {
  echo
  echo "Deteniendo tcpdump..."
  sudo pkill -f "tcpdump -l -n -i $IFACE" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Le doy un segundo a tcpdump para abrir el socket antes de arrancar la app.
sleep 1

echo "Arrancando scoreboard (live) -> http://localhost:8000"
LOG_MODE=live \
LIVE_FROM_START=true \
LIVE_LOG_FILES="$CAP_FILE,$SYSLOG_FILE,$TACACS_FILE" \
python app.py
