#!/bin/sh
# Installeert of werkt bij: Activiteitenformulier in een Debian/Ubuntu LXC. Draai als root.
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/activiteiten
[ "$(id -u)" -eq 0 ] || { echo "Draai dit als root."; exit 1; }

apt-get update -qq
apt-get install -y -qq python3 python3-venv tzdata ca-certificates >/dev/null

id activiteiten >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin activiteiten
mkdir -p "$APP" /var/lib/activiteiten
rm -rf "$APP/app"
cp -r "$SRC/app" "$SRC/requirements.txt" "$APP/"
[ -d "$APP/venv" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R root:root "$APP"
chown activiteiten:activiteiten /var/lib/activiteiten
chmod 700 /var/lib/activiteiten

if [ ! -f /etc/activiteiten.env ]; then
  cp "$SRC/deploy/activiteiten.env.example" /etc/activiteiten.env
  echo "Nieuw: /etc/activiteiten.env aangemaakt. Vul GARMIN_API_KEY en APP_PASSWORD in."
fi
chown root:activiteiten /etc/activiteiten.env
chmod 640 /etc/activiteiten.env

cp "$SRC"/deploy/activiteiten.service "$SRC"/deploy/activiteiten-garmin.service "$SRC"/deploy/activiteiten-garmin.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now activiteiten.service activiteiten-garmin.timer
systemctl restart activiteiten.service

PORT=$(grep -E '^PORT=' /etc/activiteiten.env | cut -d= -f2); PORT=${PORT:-8080}
IP=$(hostname -I | awk '{print $1}')
echo "Klaar. Open http://$IP:$PORT"
