#!/usr/bin/env bash
set -euo pipefail

# Run on the Tencent Cloud Ubuntu host after extracting a release under /tmp/qingpao-release.
release=$(cd "$(dirname "$0")/.." && pwd)
backup=/opt/qingpao/backups/release-$(date +%Y%m%d-%H%M%S)
sudo install -d -m 0755 /opt/qingpao/app/server /opt/qingpao/app/public /opt/qingpao/data/uploads "$backup"
sudo cp -a /opt/qingpao/app/. "$backup" 2>/dev/null || true
sudo install -m 0644 "$release/server/app.py" /opt/qingpao/app/server/app.py
sudo install -m 0644 "$release/server/requirements.txt" /opt/qingpao/app/server/requirements.txt
sudo install -m 0644 "$release/public/index.html" /opt/qingpao/app/public/index.html
sudo install -m 0644 "$release/deploy/qingpao.service" /etc/systemd/system/qingpao.service
sudo install -m 0644 "$release/deploy/qingpao.nginx" /etc/nginx/sites-available/qingpao
sudo ln -sfn /etc/nginx/sites-available/qingpao /etc/nginx/sites-enabled/qingpao
sudo chown -R ubuntu:ubuntu /opt/qingpao/app /opt/qingpao/data
sudo systemctl daemon-reload
sudo systemctl enable --now qingpao
sudo nginx -t
sudo systemctl reload nginx
curl -fsS http://127.0.0.1:8120/api/me >/dev/null
printf 'Qingpao installed. Backup: %s\n' "$backup"
