#!/usr/bin/env bash
# Instala el scoreboard en /opt/digi-scoreboard y lo registra como servicio systemd.
# Uso: sudo ./install.sh
set -euo pipefail

INSTALL_DIR="/opt/digi-scoreboard"
SERVICE_NAME="digi-scoreboard"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
APP_USER="${SUDO_USER:-$(whoami)}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: ejecuta con sudo: sudo ./install.sh" >&2
  exit 1
fi

echo "==> Copiando archivos a $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='*.pyc' \
  "$SRC_DIR/" "$INSTALL_DIR/"

chown -R "$APP_USER":"$APP_USER" "$INSTALL_DIR"

echo "==> Creando entorno virtual"
sudo -u "$APP_USER" python3 -m venv "$INSTALL_DIR/.venv"
sudo -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet \
  -r "$INSTALL_DIR/requirements.txt"

echo "==> Creando servicio systemd: $SERVICE_FILE"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Digi Access Scoreboard
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/app.py
Restart=on-failure
RestartSec=5
Environment=LOG_MODE=live
Environment=LIVE_FROM_START=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> Habilitando e iniciando el servicio"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "Instalacion completa."
echo "  Estado:        systemctl status $SERVICE_NAME"
echo "  Logs:          journalctl -u $SERVICE_NAME -f"
echo "  Scoreboard:    http://localhost:8001"
echo "  Configuracion: http://localhost:8001/config/"
