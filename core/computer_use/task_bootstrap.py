"""Record an owned worker process before loading browser or model code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main():
    run_root, run_id = Path(sys.argv[1]), sys.argv[2]
    module = sys.argv[3] if len(sys.argv) == 4 else 'task_worker'
    if len(sys.argv) not in {3, 4} or module not in {'task_worker', 'demonstration_worker'}:
        raise SystemExit('unsupported browser worker module')
    workspace = run_root / f'run_{run_id}'
    workspace.mkdir(parents=True, exist_ok=True)
    stopped = workspace / 'stop.requested'
    if stopped.exists():
        return
    if os.getpgrp() != os.getpid():
        raise SystemExit('browser worker must own its process group')
    owner = workspace / 'worker-owner.json'
    pending = workspace / f'worker-owner.{os.getpid()}.tmp'
    pending.write_text(json.dumps({'pid': os.getpid(), 'pgid': os.getpgrp(),
                                    'run_id': run_id, 'run_root': str(run_root.resolve())}))
    os.replace(pending, owner)
    if stopped.exists():
        return
    import importlib
    worker = importlib.import_module('core.computer_use.' + module)
    if stopped.exists():
        return
    worker.main()


if __name__ == '__main__':
    main()
