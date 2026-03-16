#!/bin/bash

# Kage Startup Script
# Usage: ./run.sh

# Color definitions
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}👻 Starting Project Kage...${NC}"

# Function to handle shutdown
cleanup() {
    echo -e "\n${RED}🛑 Shutting down Kage...${NC}"

    # Best-effort: kill any leaked Kage backend on port 12345.
    # Only terminate processes that look like Kage (avoid killing unrelated services).
    if command -v lsof >/dev/null 2>&1; then
        PIDS=$(lsof -ti tcp:12345 2>/dev/null | tr '\n' ' ')
        for pid in $PIDS; do
            cmd=$(ps -o command= -p "$pid" 2>/dev/null | tr -d '\n')
            cmd_l=$(echo "$cmd" | tr '[:upper:]' '[:lower:]')
            if echo "$cmd_l" | grep -q "kage" && (echo "$cmd_l" | grep -q "main.py" || echo "$cmd_l" | grep -q "kage-server"); then
                echo -e "${RED}   Killing leaked backend PID $pid: $cmd${NC}"
                kill -TERM "$pid" 2>/dev/null
                sleep 0.2
                kill -KILL "$pid" 2>/dev/null
            fi
        done
    fi
    
    # Kill any remaining background jobs
    kill $(jobs -p) 2>/dev/null
    
    echo -e "${GREEN}✅ Kage shutdown complete${NC}"
    exit 0
}

# Trap Ctrl+C (SIGINT) and SIGTERM
trap cleanup SIGINT SIGTERM

# 1. Activate Conda Environment
# Try to find conda source
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -z "$CONDA_BASE" ]; then
    # Fallback for common install locations if 'conda' not in PATH
    if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/miniconda3/etc/profile.d/conda.sh"
    elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
        source "$HOME/anaconda3/etc/profile.d/conda.sh"
    fi
else
    source "$CONDA_BASE/etc/profile.d/conda.sh"
fi

echo -e "${GREEN}🐍 Activating Conda Environment: kage${NC}"
conda activate kage

# 2. Start Frontend (Foreground). Tauri starts/stops backend.
echo -e "${GREEN}💅 Starting Frontend (Tauri)...${NC}"
cd kage-avatar
npm run tauri dev

# Usage:
# - Tauri owns the backend process and stops it on tray Quit.
# - Ctrl+C triggers this script's cleanup for leaked processes.
