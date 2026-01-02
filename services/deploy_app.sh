#!/bin/bash

# Append environment variables and aliases to ~/.bashrc
cat >> ~/.bashrc <<EOL
# Set up environment variables and aliases
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Alias for FinTracker service logs and restart
alias BL='journalctl --user -f -u FinTracker'
alias BR='systemctl --user restart FinTracker'
EOL

# Source the updated ~/.bashrc to apply changes
source ~/.bashrc

# Ensure the systemd user directory exists
mkdir -p ~/.config/systemd/user/

# Enable lingering for the user so systemd services continue running after logout
sudo loginctl enable-linger "$USER"

# Create the systemd service file for FinTracker
cat > ~/.config/systemd/user/FinTracker.service <<EOL
[Unit]
Description=FinTracker Service
After=network.target
Wants=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=$HOME/Application/FinTrack/.env
ExecStart=$HOME/.local/bin/podman-compose -f $HOME/Application/FinTrack/docker/docker-compose.yml up -d
ExecStop=$HOME/.local/bin/podman-compose -f $HOME/Application/FinTrack/docker/docker-compose.yml down
WorkingDirectory=$HOME/Application/FinTrack/docker
TimeoutStartSec=0
Restart=no
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOL

# Reload systemd configuration, enable and start the service
systemctl --user daemon-reload
systemctl --user enable FinTracker
systemctl --user start FinTracker

# Print a success message
echo "FinTracker service is now set up and running!"
