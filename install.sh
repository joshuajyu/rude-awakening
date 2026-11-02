#!/usr/bin/env bash
# Install or update rude-awakening on this machine. Safe to rerun.
# Run as your normal user from the repo directory; it uses sudo where needed.
set -euo pipefail

cd "$(dirname "$0")"
DIR="$(pwd)"
RUN_USER="$(id -un)"
UNIT=/etc/systemd/system/rude-awakening.service

if [[ $EUID -eq 0 ]]; then
    echo "Run this as your normal user, not root (it calls sudo when needed)." >&2
    exit 1
fi

echo "==> Python virtualenv"
if ! python3 -c "import ensurepip" 2>/dev/null; then
    echo "    python3-venv is missing; installing it"
    sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv
fi
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Config (.env)"
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "    created .env from .env.example"
fi
if ! grep -qE '^WEBHOOK_TOKEN=.+' .env; then
    token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    sed -i "s|^WEBHOOK_TOKEN=.*|WEBHOOK_TOKEN=${token}|" .env
    grep -q '^WEBHOOK_TOKEN=' .env || echo "WEBHOOK_TOKEN=${token}" >> .env
    echo "    generated a new WEBHOOK_TOKEN (see: grep WEBHOOK_TOKEN .env)"
fi
chmod 600 .env

media_host="$(sed -n 's/^MEDIA_HOST=//p' .env)"
if [[ -n "$media_host" ]] && ! hostname -I | tr ' ' '\n' | grep -qx "$media_host"; then
    echo "    WARNING: MEDIA_HOST=$media_host is not an IP of this machine ($(hostname -I | xargs))"
fi

echo "==> systemd unit"
sed -e "s|@USER@|${RUN_USER}|g" -e "s|@DIR@|${DIR}|g" systemd/rude-awakening.service.in \
    | sudo tee "$UNIT" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --quiet rude-awakening

if grep -qE '^NEST_(IP|NAME)=.+' .env; then
    sudo systemctl restart rude-awakening
    sleep 2
    systemctl --no-pager --lines=5 status rude-awakening || true
else
    echo
    echo "Set NEST_IP and/or NEST_NAME in $DIR/.env, then run:"
    echo "    sudo systemctl restart rude-awakening"
fi

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
    media_port="$(sed -n 's/^MEDIA_PORT=//p' .env)"
    echo
    echo "ufw is active. If the Nest can't fetch the sound, allow the media port from the LAN:"
    echo "    sudo ufw allow from 10.0.0.0/24 to any port ${media_port:-8081} proto tcp"
fi
