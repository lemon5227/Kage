import sys
import os
import uvicorn
import asyncio
from core.server import app, kage_server

# --- Path Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(current_dir, "core"))

def main():
    print("\n================================================")
    print("   👻 Project Kage (Shadow) - Phase 4: The Body")
    print("================================================")
    print("🚀 Starting Kage Backend Server...")
    print("   WebSocket: ws://127.0.0.1:12345/ws")
    print("------------------------------------------------")

    # Start the FastAPI/Uvicorn Server
    # We use asyncio to run it
    try:
        uvicorn.run(app, host="127.0.0.1", port=12345)
    except KeyboardInterrupt:
        print("\n⚠️ Server Stopped.")

if __name__ == "__main__":
    main()