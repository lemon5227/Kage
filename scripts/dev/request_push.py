"""Ask the Mac push agent to push a branch:  python scripts/dev/request_push.py evidence/2026-10-14 [--wait]"""
import json, sys, time, uuid
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
queue = repo / '.kage-push'
branch = sys.argv[1]
name = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
(queue / 'requests').mkdir(parents=True, exist_ok=True)
(queue / 'requests' / f'{name}.json').write_text(json.dumps({'branch': branch}))
print('requested', name)
if '--wait' in sys.argv:
    result = queue / 'results' / f'{name}.json'
    for _ in range(150):
        if result.exists():
            print(result.read_text()); break
        time.sleep(2)
    else:
        print('no result after 300s: is the launchd agent installed? see docs/plans/cards/W0-7.md')
