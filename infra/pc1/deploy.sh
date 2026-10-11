#!/bin/bash
# Install or update the PC1 orchestrator on the Linux host / LXC (Ubuntu 24.04, Python 3.12).
#
# First install:   build a bundle on your dev machine (see docs/DEPLOYMENT.md §3), copy it to PC1, then
#                  sudo bash infra/pc1/deploy.sh /path/to/vpc_bundle.tgz
# Update:          same command with a new bundle; the venv, env file and database are kept.
#
# It never writes secrets: /etc/voice-pc-control.env must be created from voice-pc-control.env.example.
set -euo pipefail
BUNDLE=${1:?usage: deploy.sh <bundle.tgz>}
APP=/opt/voice-pc-control
HERE=$(cd "$(dirname "$0")" && pwd)

id vpc >/dev/null 2>&1 || useradd --system --home-dir /var/lib/vpc --create-home --shell /usr/sbin/nologin vpc
mkdir -p "$APP" /var/lib/vpc
rm -rf "$APP/mobile-pwa/dist"
tar -xzf "$BUNDLE" -C "$APP"

if [ ! -f /etc/voice-pc-control.env ]; then
  install -m 640 -o root -g vpc "$HERE/voice-pc-control.env.example" /etc/voice-pc-control.env
  echo "!! created /etc/voice-pc-control.env from the example — fill in the CHANGE_ME values, then rerun."
  exit 1
fi
sed -i -e '$a\' /etc/voice-pc-control.env   # guarantee trailing newline

[ -x "$APP/.venv/bin/python" ] || python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --quiet --upgrade pip
"$APP/.venv/bin/pip" install --quiet -r "$APP/requirements.txt" faster-whisper
chown -R root:root "$APP"
chown -R vpc:vpc /var/lib/vpc

install -m 644 "$HERE/voice-pc-control.service" /etc/systemd/system/voice-pc-control.service
install -m 750 "$HERE/vpc-cli" /usr/local/bin/vpc-cli
systemctl daemon-reload
systemctl enable voice-pc-control >/dev/null
systemctl restart voice-pc-control
for i in $(seq 1 40); do curl -sf localhost:8000/health >/dev/null && break; sleep 3; done
echo "service: $(systemctl is-active voice-pc-control)  health: $(curl -s localhost:8000/health)"
