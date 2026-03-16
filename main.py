import sys
import os

# Debug Print for Bootloader
print("🦖 Kage Bootloader: Initializing...", flush=True)

import uvicorn
import asyncio

# Imports moved to main() to prevent import-time side effects
# from core.server import app, kage_server

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

    # Start uvicorn in background thread (non-blocking)
    import threading
    
    def run_server():
        print("🦖 Kage Bootloader: Importing Core Server (in thread)...", flush=True)
        from core.server import app
        print("🦖 Kage Bootloader: Core Server Imported.", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=12345, log_level="warning")
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print("🚀 Server started in background thread")

    # Check if Tauri is handling the tray (set by run.sh when using Tauri frontend)
    # Also skip in frozen mode (PyInstaller) since Tauri handles the tray
    skip_tray = (
        os.environ.get("KAGE_NO_TRAY", "").lower() in ("1", "true", "yes") or
        getattr(sys, 'frozen', False)  # Skip tray in PyInstaller bundle
    )
    
    if skip_tray:
        print("🔧 Skipping Python tray (Tauri handles it)")
        # Just keep server running without tray
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n⚠️ Server Stopped.")
    else:
        # Start System Tray on main thread (macOS requirement)
        try:
            from core.tray import KageTray
            
            def on_quit():
                print("\n⚠️ Quit from tray menu")
                os._exit(0)
            
            tray = KageTray(on_quit=on_quit)
            print("🎯 System Tray started (right-click for menu)")
            tray.run()  # This blocks on main thread
        except Exception as e:
            print(f"⚠️ Tray not available: {e}")
            # If tray fails, just keep server running
            try:
                while True:
                    import time
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n⚠️ Server Stopped.")

if __name__ == "__main__":
    # Fix for PyInstaller multiprocessing on macOS/Windows
    import multiprocessing
    multiprocessing.freeze_support()

    print("🦖 Kage Bootloader: Importing Core Server...", flush=True)
    # Move import here so it doesn't run in child processes before freeze_support
    from core.server import app
    print("🦖 Kage Bootloader: Core Server Imported.", flush=True)

    main()