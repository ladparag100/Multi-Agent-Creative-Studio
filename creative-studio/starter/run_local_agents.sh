#!/usr/bin/env bash
# Starts all 5 specialist agents as local A2A servers, then launches the
# Streamlit UI (which runs the Creative Director in-process). Ctrl+C stops
# everything.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No .venv found. Run first:"
  echo "  uv venv --python 3.11 .venv"
  echo "  source .venv/bin/activate"
  echo "  uv pip install \"google-adk[a2a]==1.31.1\" \"google-genai>=1.51.0\" \"uvicorn[standard]>=0.25.0\" \"python-dotenv>=1.0.0\" \"google-cloud-storage>=2.10.0\" \"pydantic>=2.0.0\" streamlit --prerelease=allow"
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f .env ]; then
  echo "No .env found. Copy .env.example to .env and fill in GOOGLE_CLOUD_PROJECT / GCS_IMAGES_BUCKET first."
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

STRATEGIST_PORT="${STRATEGIST_PORT:-8081}"
COPYWRITER_PORT="${COPYWRITER_PORT:-8082}"
DESIGNER_PORT="${DESIGNER_PORT:-8083}"
CRITIC_PORT="${CRITIC_PORT:-8084}"
PM_PORT="${PM_PORT:-8085}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8080}"

PIDS=()
cleanup() {
  echo ""
  echo "Stopping specialist agents..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

start_agent() {
  local name="$1" dir="$2" port="$3"
  echo "Starting $name on http://localhost:$port ..."
  (cd "$dir" && PORT="$port" PUBLIC_PORT="$port" python agent.py) &
  PIDS+=($!)
}

start_agent "brand_strategist" agents/brand_strategist "$STRATEGIST_PORT"
start_agent "copywriter"       agents/copywriter       "$COPYWRITER_PORT"
start_agent "designer"         agents/designer         "$DESIGNER_PORT"
start_agent "critic"           agents/critic           "$CRITIC_PORT"
start_agent "project_manager"  agents/project_manager  "$PM_PORT"

echo ""
echo "Waiting for agents to come up..."
for port in "$STRATEGIST_PORT" "$COPYWRITER_PORT" "$DESIGNER_PORT" "$CRITIC_PORT" "$PM_PORT"; do
  for _ in $(seq 1 20); do
    if curl -sf "http://localhost:$port/.well-known/agent.json" > /dev/null 2>&1; then
      echo "  port $port: OK"
      break
    fi
    sleep 1
  done
done

echo ""
echo "All 5 specialist agents are up. Launching Streamlit UI on http://localhost:$STREAMLIT_PORT ..."
streamlit run streamlit_app.py --server.port "$STREAMLIT_PORT" --server.address 0.0.0.0
