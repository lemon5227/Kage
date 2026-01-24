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
    # Kill background jobs (Backend)
    kill $(jobs -p) 2>/dev/null
    exit
}

# Trap Ctrl+C (SIGINT)
trap cleanup SIGINT

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

# 2. Start Backend (Background)
echo -e "${GREEN}🧠 Starting Backend (main.py)...${NC}"
python main.py &
BACKEND_PID=$!

# Wait a moment for backend to initialize
sleep 2

# 3. Start Frontend (Foreground)
echo -e "${GREEN}💅 Starting Frontend (Tauri)...${NC}"
cd kage-avatar
npm run tauri dev

# Usage:
# The script waits here because 'npm run tauri dev' is interactive/blocking.
# When you close the Tauri window or hit Ctrl+C, the trap triggers 'cleanup'.
wait $BACKEND_PID
