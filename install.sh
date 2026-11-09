#!/bin/sh
# Run on runcater as root: (re)install the tokcat systemd service.
# App files are expected to already be in /opt/tokcat.
set -eu
install -m 0644 /opt/tokcat/tokcat.service /etc/systemd/system/tokcat.service
systemctl daemon-reload
systemctl enable tokcat
systemctl restart tokcat
sleep 1
systemctl is-active tokcat
