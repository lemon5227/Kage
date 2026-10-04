"""Record an owned worker process before loading browser or model code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main():
    run_root, run_id = Path(sys.argv[1]), sys.argv[2]
    workspace = run_root / f'run_{run_id}'
    workspace.mkdir(parents=True, exist_ok=True)
    stopped = workspace / 'stop.requested'
    if stopped.exists():
        return
    if os.getpgrp() != os.getpid():
        raise SystemExit('browser worker must own its process group')
    owner = workspace / 'worker-owner.json'
    pending = workspace / f'worker-owner.{os.getpid()}.tmp'
    pending.write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp()}))
    os.replace(pending, owner)
    if stopped.exists():
        return
    from core.computer_use import task_worker
    if stopped.exists():
        return
    task_worker.main()


if __name__ == '__main__':
    main()
