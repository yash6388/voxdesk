#!/usr/bin/env bash
# Start the backend's supporting services together (Ctrl+C stops all of them):
#   MCP booking server   :8001
#   Knowledge agent (A2A) :8101
#   Booking agent (A2A)   :8102
# Run the API separately:  uv run uvicorn app.main:app --reload
set -euo pipefail
cd "$(dirname "$0")/.."

trap 'kill 0' EXIT INT TERM

run() {
  local name=$1; shift
  # Prefix every log line with the service name so the combined output stays readable.
  uv run "$@" 2>&1 | sed -u "s/^/[$name] /" &
}

run mcp       python -m app.mcp.server
run knowledge python -m app.agents.knowledge
run booking   python -m app.agents.booking

wait
