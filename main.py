import sys
import os

# Debug Print for Bootloader
print("🦖 Kage Bootloader: Initializing...", flush=True)

import uvicorn
import asyncio

print("🦖 Kage Bootloader: Importing Core Server...", flush=True)
from core.server import app, kage_server
print("🦖 Kage Bootloader: Core Server Imported.", flush=True)

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
    # Fix for PyInstaller multiprocessing on macOS/Windows
    import multiprocessing
    multiprocessing.freeze_support()
    
    main()