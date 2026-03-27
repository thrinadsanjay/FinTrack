#!/bin/bash

cd /home/ubuntu/fintracker

if [ ! -f .previous_version ]; then
  echo "No previous version found."
  exit 1
fi

ROLLBACK_VERSION=$(cat .previous_version)
echo "Rolling back to $ROLLBACK_VERSION"

# Update .env
sed -i "s/^VERSION=.*/VERSION=$ROLLBACK_VERSION/" .env

# Pull image (if not already)
docker pull ghcr.io/yourrepo/fintracker:$ROLLBACK_VERSION

# Restart
docker compose up -d

echo "Rollback complete."
