#!/bin/bash

cat >> ~/.bashrc < EOL
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
alias BL='journalctl --user -f -u FinTracker'
alias BR='systemctl --user restart FinTracker'
EOL

source ~/.bashrc

mkdir -p ~/.config/systemd/user/

sudo loginctl enable-linger $USER

cat > ~/.config/systemd/user/FinTracker.service <<EOL
[Unit]
Description=FinTracker Service
After=network.target
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=$HOME/Application/FinTrack/.env
ExecStart=podman compose up -d
ExecStop=podman compose stop
WorkingDirectory=$HOME/Application/FinTrack/docker
TimeoutStartSec=0
Restart=no
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target

EOL

systemctl --user daemon-reload
systemctl --user enable FinTracker
systemctl --user start FinTracker

