"""R3t-family LoRA training on Modal: one seed per container, resumable (docs/plans/r3f-forgetting-fix.md).

  modal run --detach scripts/experiments/modal_r3t.py --tags f0,f1 --ckpt-dir artifacts/r3f-ckpt/v47
  modal volume get kage-r3t f0/work/e1 <dest>          # logs, checkpoint, finished adapter.gguf

Same entry point and recipe as the Kaggle notebook ('r3t-train <tag>' in kaggle_e1.py: fp16, 8192 tokens, rank 16,
checkpoint every 25 steps), only on a bigger GPU. Each tag gets its own work dir on the Volume 'kage-r3t'; the
container commits the Volume every few minutes, so a preempted or retried container resumes from the last checkpoint.
A previous version's checkpoint (<ckpt-dir>/e1/<name>-adapter/adapter-ckpt.pt) is uploaded as that tag's input once.
"""
from pathlib import Path
import os
import subprocess
import threading
import time

import modal

GPU = os.environ.get('KAGE_MODAL_GPU', 'A100-40GB')
REPO = 'https://github.com/lemon5227/Kage.git'
app = modal.App('kage-r3t')
vol = modal.Volume.from_name('kage-r3t', create_if_missing=True)
image = (modal.Image.debian_slim(python_version='3.12')
         .apt_install('git')
         .pip_install('torch==2.11.0', 'numpy', 'huggingface_hub', 'jsonschema'))


@app.function(image=image, gpu=GPU, timeout=24 * 3600, volumes={'/vol': vol},
              retries=modal.Retries(max_retries=3, initial_delay=30.0))
def train(tag: str, commit: str) -> str:
    root = Path('/root/Kage')
    if not root.exists():
        subprocess.run(['git', 'clone', '-q', '-b', 'dev', REPO, str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'checkout', '-q', commit], check=True)
    env = {**os.environ, 'KAGE_WORK': f'/vol/{tag}/work', 'KAGE_INPUT': f'/vol/{tag}/input',
           'KAGE_TOOLS': '/root/tools', 'KAGE_PHASE': f'r3t-train {tag}'}
    stop = threading.Event()

    def keep_committing():                      # checkpoints reach the Volume even if the container dies
        while not stop.wait(300):
            vol.commit()

    threading.Thread(target=keep_committing, daemon=True).start()
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True)
    print(f'{tag}: commit {commit}, gpu {gpu.stdout.strip()}', flush=True)
    code = subprocess.run(['python', 'scripts/experiments/kaggle_e1.py'], cwd=root, env=env).returncode
    stop.set()
    vol.commit()
    status = Path(f'/vol/{tag}/work/e1/kaggle-status.jsonl').read_text().splitlines()[-1]
    return f'{tag}: exit {code}; {status}'


@app.local_entrypoint()
def main(tags: str, ckpt_dir: str = '', commit: str = ''):
    commit = commit or subprocess.run(['git', 'rev-parse', 'origin/dev'], capture_output=True, text=True,
                                      check=True).stdout.strip()
    names = {}
    for tag in tags.split(','):                # 'f0' -> 'r3f0', the adapter dir the trainer resumes from
        prefix = tag.rstrip('0123456789')
        names[tag] = {'': 'r3t', 'g': 'r3g', 'f': 'r3f'}[prefix] + tag[len(prefix):]
    for tag, name in names.items():             # upload once: a rerun must not replace the input of a resumed run
        ckpt = Path(ckpt_dir) / 'e1' / f'{name}-adapter' / 'adapter-ckpt.pt'
        if not ckpt_dir or not ckpt.exists():
            continue
        try:
            vol.listdir(f'/{tag}/input')
            print(f'{tag}: input checkpoint already on the Volume')
        except Exception:                       # not found
            with vol.batch_upload() as batch:
                batch.put_file(ckpt, f'/{tag}/input/e1/{name}-adapter/adapter-ckpt.pt')
            print(f'{tag}: uploaded {ckpt}')
    for line in train.starmap([(tag, commit) for tag in names]):
        print(line)
