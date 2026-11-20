#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd -P)
mkdir -p "$root/var/staging"
chmod 700 "$root/var"
for service in scholar-radar-api scholar-radar-worker; do
    systemctl --user enable "$root/deploy/$service.service"
done
systemctl --user daemon-reload
systemctl --user start scholar-radar-api.service scholar-radar-worker.service
systemctl --user is-active scholar-radar-api.service scholar-radar-worker.service
