#!/bin/bash
set -e

SESSION="ema"
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Clean up any previous session
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create new session with backend window
tmux new-session -d -s "$SESSION" -n "backend"

# Backend: uv venv, install deps, run uvicorn from repo root
tmux send-keys -t "$SESSION:backend" \
  "cd $REPO_ROOT/backend && uv venv --clear && source .venv/bin/activate && uv pip install -r requirements.txt && cd $REPO_ROOT && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload" Enter

# Frontend: install deps, run dev server
tmux new-window -t "$SESSION" -n "frontend"
tmux send-keys -t "$SESSION:frontend" \
  "cd $REPO_ROOT/frontend && npx next dev" Enter

# Select backend window (don't attach — you're already in a tmux session)
tmux select-window -t "$SESSION:backend"

echo "Session '$SESSION' created with 2 windows:"
echo "  backend  — tmux select-window -t \$SESSION:backend"
echo "  frontend — tmux select-window -t \$SESSION:frontend"
echo "Or use: tmux switch-client -t \$SESSION"
