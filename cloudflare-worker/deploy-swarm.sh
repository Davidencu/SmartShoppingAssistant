#!/usr/bin/env bash
# deploy-swarm.sh — deploy N identical SmartShop proxy workers
#
# Usage:
#   ./deploy-swarm.sh <count> <shared-secret>
#
# Example (5 workers, secret = "my-secret-123"):
#   ./deploy-swarm.sh 5 my-secret-123
#
# After the script finishes:
#   - N workers are live at https://smartshop-proxy-{1..N}.<account>.workers.dev
#   - Copy the resulting URLs into your backend .env as a comma-separated list:
#       CF_WORKER_URLS=https://smartshop-proxy-1...workers.dev,https://smartshop-proxy-2...workers.dev
#       CF_WORKER_SECRET=my-secret-123

set -euo pipefail

COUNT="${1:-3}"
SECRET="${2:-}"

if [[ -z "$SECRET" ]]; then
  echo "Usage: $0 <count> <shared-secret>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

URLS=()

for i in $(seq 1 "$COUNT"); do
  NAME="smartshop-proxy-${i}"
  echo "──────────────────────────────────────────"
  echo "Deploying worker: $NAME"

  # Deploy (--name overrides the name in wrangler.toml for this deployment)
  wrangler deploy --name "$NAME" 2>&1

  # Set the secret for this specific worker
  echo "$SECRET" | wrangler secret put WORKER_SECRET --name "$NAME"

  # Capture the worker URL (workers.dev subdomain)
  ACCOUNT_SUBDOMAIN=$(wrangler whoami 2>/dev/null | grep -oP '(?<=account: ).*' | head -1 | tr '[:upper:]' '[:lower:]' | tr ' ' '-' || echo "your-account")
  URLS+=("https://${NAME}.${ACCOUNT_SUBDOMAIN}.workers.dev")

  echo "Deployed: ${URLS[-1]}"
done

echo ""
echo "══════════════════════════════════════════"
echo "All $COUNT workers deployed successfully."
echo ""
echo "Add to backend/.env:"
echo ""
printf "CF_WORKER_URLS="
IFS=','; echo "${URLS[*]}"
echo "CF_WORKER_SECRET=${SECRET}"
echo "══════════════════════════════════════════"
