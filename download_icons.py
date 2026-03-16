import os
import requests

ICONS = [
    "user", "mic", "cpu", "settings-2", "trash-2", 
    "chevron-down", "check", "activity", "box", "volume-2",
    "zap", "layers", "power", "monitor", "refresh-cw"
]

BASE_URL = "https://unpkg.com/lucide-static@latest/icons/"
TARGET_DIR = "/Users/wenbo/Kage/kage-avatar/public/icons"

if not os.path.exists(TARGET_DIR):
    os.makedirs(TARGET_DIR)

print(f"Downloading {len(ICONS)} icons to {TARGET_DIR}...")

for icon in ICONS:
    try:
        url = f"{BASE_URL}{icon}.svg"
        res = requests.get(url)
        if res.status_code == 200:
            with open(os.path.join(TARGET_DIR, f"{icon}.svg"), "wb") as f:
                f.write(res.content)
            print(f"✅ Downloaded {icon}.svg")
        else:
            print(f"❌ Failed {icon}.svg ({res.status_code})")
    except Exception as e:
        print(f"⚠️ Error {icon}: {e}")
