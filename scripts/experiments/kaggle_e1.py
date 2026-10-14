"""Run the E-1 experiment (and a small calibration check) on a Kaggle GPU notebook.

Notebook (Accelerator: GPU T4 x2, Internet on, Secret DEEPSEEK_API_KEY):

    !git clone -b claude/task-progress-861574 --depth 1 https://github.com/lemon5227/Kage.git
    !cd Kage && python scripts/experiments/kaggle_e1.py

Same student as on the Mac: InternScience/Agents-A1-4B-Q4_K_M-GGUF at the locked revision (sha256
checked) served by llama.cpp at the same commit and arguments, CUDA instead of Metal. Skills run in a
subprocess (no Docker on Kaggle; the VM itself is disposable). All arms run on this host only.

Design (E-1, reduced without changing any comparison):
  A0, A1 never change state -> evaluated once on the frozen eval set (A0's run doubles as the shared
  cp0 of the learning arms); A3/A4 x seed1/seed2 run their 60-task stream with checkpoints 30 and 60.
Teacher spend runs under KAGE_TEACHER_CAP_USD on a fresh ledger here and is charged back to the
home ledger afterwards (see the worklog). Everything lands in /kaggle/working/e1 + a tarball.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get('KAGE_WORK', '/kaggle/working'))
OUT = WORK / 'e1'
TOOLS = Path(os.environ.get('KAGE_TOOLS', '/kaggle/tmp'))
MODEL_REPO = 'InternScience/Agents-A1-4B-Q4_K_M-GGUF'
MODEL_REVISION = 'd92b02e27074b27542384f72bc0e72203c970f0f'
MODEL_FILE = 'Agents-A1-4B-Q4_K_M.gguf'
MODEL_SHA256 = 'd93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062'
LLAMA_COMMIT = 'b29c606e2'              # = Homebrew llama.cpp 0.4.1 build 10964 used on the Mac
TEACHER = {'provider_type': 'openai', 'base_url': 'https://api.deepseek.com', 'model_name': 'deepseek-flash',
           'timeout_sec': 120}
E1_CAP_USD = 0.40                       # task book §4 allocation for E-1
DEADLINE_S = 11 * 3600                  # Kaggle stops sessions at 12 h; leave time to package
PY = sys.executable
PIP = ['jsonschema', 'numpy', 'jieba', 'rank-bm25', 'defusedxml', 'lxml', 'openpyxl', 'pypdf', 'pillow',
       'tqdm', 'huggingface_hub', 'fastapi', 'uvicorn', 'websockets', 'edge-tts', 'pygame', 'psutil']

START = time.time()


def log(msg: str, **fields) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    row = {'t': round(time.time() - START, 1), 'msg': msg, **fields}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    with (OUT / 'kaggle-status.jsonl').open('a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def sh(cmd: list[str] | str, **kw) -> None:
    subprocess.run(cmd, check=True, shell=isinstance(cmd, str), **kw)


def setup() -> dict:
    sh([PY, '-m', 'pip', 'install', '-q', *PIP])
    if not shutil.which('lsof'):
        sh('apt-get -qq update && apt-get -qq install -y lsof >/dev/null')
    TOOLS.mkdir(parents=True, exist_ok=True)
    server = TOOLS / 'llama.cpp' / 'build' / 'bin' / 'llama-server'
    if not server.exists():
        src = TOOLS / 'llama.cpp'
        if not src.exists():
            sh(['git', 'clone', '-q', 'https://github.com/ggml-org/llama.cpp', str(src)])
        sh(['git', '-C', str(src), 'checkout', '-q', LLAMA_COMMIT])
        shutil.rmtree(src / 'build', ignore_errors=True)        # never reuse a failed configure cache
        # Kaggle's toolkit ships libcuda only as a stub; CUDA::cuda_driver must be found there.
        stubs = '/usr/local/cuda/lib64/stubs'
        sh(['cmake', '-S', str(src), '-B', str(src / 'build'), '-DGGML_CUDA=ON', '-DCMAKE_CUDA_ARCHITECTURES=75',
            f'-DCMAKE_LIBRARY_PATH={stubs}', f'-DCMAKE_EXE_LINKER_FLAGS=-L{stubs}', f'-DCMAKE_SHARED_LINKER_FLAGS=-L{stubs}',
            '-DLLAMA_CURL=OFF', '-DCMAKE_BUILD_TYPE=Release'], stdout=subprocess.DEVNULL)
        sh(['cmake', '--build', str(src / 'build'), '--target', 'llama-server', '-j', str(os.cpu_count() or 4)],
           stdout=subprocess.DEVNULL)
    from huggingface_hub import hf_hub_download
    model = Path(hf_hub_download(MODEL_REPO, MODEL_FILE, revision=MODEL_REVISION, local_dir=str(TOOLS / 'model')))
    digest = hashlib.sha256()
    with model.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise SystemExit(f'model sha256 mismatch: {digest.hexdigest()}')
    write_teacher_config()
    version = subprocess.run([str(server), '--version'], capture_output=True, text=True).stderr.strip()[:300]
    gpus = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                          capture_output=True, text=True).stdout.strip().splitlines()
    info = {'server': str(server), 'server_version': version, 'model': str(model), 'model_sha256': MODEL_SHA256,
            'gpus': gpus, 'llama_commit': LLAMA_COMMIT, 'repo_head': subprocess.run(
                ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()}
    (OUT / 'host.json').write_text(json.dumps(info, indent=1))
    log('setup done', **{k: info[k] for k in ('gpus', 'repo_head')})
    return info


def write_teacher_config() -> None:
    path = Path('~/.config/kage/teachers/deepseek.json').expanduser()
    if path.exists():
        return
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        from kaggle_secrets import UserSecretsClient          # available inside Kaggle notebooks
        client = UserSecretsClient()
        for label in ('DEEPSEEK_API_KEY', 'deepseek'):
            try:
                key = client.get_secret(label)
                break
            except Exception:
                continue
        if not key:
            raise SystemExit('no Kaggle secret named DEEPSEEK_API_KEY or deepseek is attached')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'model': {'cloud_api': {**TEACHER, 'api_key': key}}}))
    path.chmod(0o600)


def job_env(info: dict, gpu: int) -> dict:
    return {**os.environ, 'KAGE_MODEL_PATH': info['model'], 'KAGE_LLAMA_SERVER': info['server'],
            'CUDA_VISIBLE_DEVICES': str(gpu), 'KAGE_TEACHER_LEDGER': str(OUT / 'teacher-ledger.sqlite'),
            'KAGE_TEACHER_CAP_USD': str(E1_CAP_USD)}


def run_jobs(info: dict, jobs: list[tuple[str, list[str]]], label: str) -> None:
    gpus = max(1, len(info['gpus']))
    procs = []
    for i, (name, argv) in enumerate(jobs):
        logf = (OUT / f'{name}.log').open('a')
        procs.append((name, subprocess.Popen([PY, *argv], cwd=ROOT, env=job_env(info, i % gpus),
                                             stdout=logf, stderr=subprocess.STDOUT), logf))
        time.sleep(20)                     # stagger model loads
    log(f'{label} started', jobs=[n for n, _, _ in procs])
    while any(p.poll() is None for _, p, _ in procs):
        if time.time() - START > DEADLINE_S:
            log('deadline reached; stopping jobs (all runs resume per task next time)')
            for _, p, _ in procs:
                p.terminate()
            break
        time.sleep(60)
    for name, p, f in procs:
        p.wait()
        f.close()
        log(f'{name} exit', code=p.returncode)


def calibration_jobs() -> list[tuple[str, list[str]]]:
    """Kaggle-side difficulty check: 4 calibration seeds per capability family, three parallel jobs."""
    script = 'scripts/experiments/stream_calibrate.py'
    groups = [['subset_selection', 'interval_merge'], ['log_aggregation', 'csv_transform'],
              ['text_normalize', 'config_migrate']]
    return [(f'calibration-{i}', [script, '--root', str(OUT / 'calibration' / f'part{i}'), '--per-family', '4',
                                  '--families', ','.join(g), '--port', str(18090 + i), '--skill-runner', 'process'])
            for i, g in enumerate(groups)]


def e1_jobs() -> list[tuple[str, list[str]]]:
    script, m = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_v1'
    common = ['--eval-manifest', str(m / 'eval.json'), '--skill-runner', 'process',
              '--teacher-cache', str(OUT / 'teacher-cache'), '--experiment-cap-usd', str(E1_CAP_USD)]
    jobs = []
    for i, arm in enumerate(['A0', 'A1']):
        jobs.append((f'{arm}', [script, '--arm', arm, '--root', str(OUT / arm), '--eval-only', 'cp0',
                                '--stream-manifest', str(m / 'stream-seed1.json'), '--port', str(18101 + i), *common]))
    port = 18103
    for seed in (1, 2):
        for arm in ('A3', 'A4'):
            jobs.append((f'{arm}-s{seed}', [script, '--arm', arm, '--root', str(OUT / f'seed{seed}' / arm),
                                            '--stream-manifest', str(m / f'stream-seed{seed}.json'),
                                            '--checkpoints', '30,60', '--port', str(port), *common]))
            port += 1
    return jobs


def package() -> None:
    subprocess.run([PY, 'scripts/experiments/stream_report.py', '--arm-dir', f'A0={OUT / "A0"}',
                    '--arm-dir', f'A1={OUT / "A1"}',
                    *[x for s in (1, 2) for a in ('A3', 'A4') for x in ('--arm-dir', f'{a}={OUT / f"seed{s}" / a}')],
                    '--constant', 'A0', '--constant', 'A1', '--cp0-from', 'A0', '--out', str(OUT / 'report')],
                   cwd=ROOT, check=False)
    with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
        tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
    log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--phase', choices=['all', 'smoke', 'setup', 'calibration', 'e1', 'package'], default='all')
    args = p.parse_args(argv)
    info = setup() if args.phase in ('all', 'smoke', 'setup', 'calibration', 'e1') else json.loads((OUT / 'host.json').read_text())
    if args.phase == 'smoke':
        # One local task end to end (server start, CUDA inference, sandboxed checker) + teacher config present.
        run_jobs(info, [('smoke', ['scripts/experiments/stream_calibrate.py', '--root', str(OUT / 'smoke'),
                                   '--per-family', '1', '--families', 'log_aggregation', '--port', '18099',
                                   '--skill-runner', 'process'])], 'smoke')
        print((OUT / 'smoke' / 'results.jsonl').read_text(), flush=True)
        log('teacher config present', ok=Path('~/.config/kage/teachers/deepseek.json').expanduser().exists())
        return
    if args.phase in ('all', 'calibration'):
        run_jobs(info, calibration_jobs(), 'calibration')
    if args.phase in ('all', 'e1'):
        run_jobs(info, e1_jobs(), 'e1')
    if args.phase in ('all', 'e1', 'package'):
        package()


if __name__ == '__main__':
    main()
