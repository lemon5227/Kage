"""Run the E-1 experiment (and a small calibration check) on a Kaggle GPU notebook.

Notebook (Accelerator: GPU T4 x2, Internet on, Secret DEEPSEEK_API_KEY):

    !cd /kaggle/tmp && git clone -b dev --depth 1 https://github.com/lemon5227/Kage.git
    !cd /kaggle/tmp/Kage && python scripts/experiments/kaggle_e1.py

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
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get('KAGE_WORK', '/kaggle/working'))
OUT = WORK / 'e1'
TOOLS = Path(os.environ.get('KAGE_TOOLS', '/kaggle/tmp'))
INPUT = Path(os.environ.get('KAGE_INPUT', '/kaggle/input'))
MODEL_REPO = 'InternScience/Agents-A1-4B-Q4_K_M-GGUF'
MODEL_REVISION = 'd92b02e27074b27542384f72bc0e72203c970f0f'
MODEL_FILE = 'Agents-A1-4B-Q4_K_M.gguf'
MODEL_SHA256 = 'd93c393a9bd5139a4b5cfe24d31ef553c5a497bfb8afec178a354ecbf508f062'
LLAMA_COMMIT = 'b29c606e2'              # = Homebrew llama.cpp 0.4.1 build 10964 used on the Mac
CUDA_ARCHS = '75'                       # T4. The notebook only offers T4 x2 (no P100; checked 10-18).
BUILD_STAMP = LLAMA_COMMIT              # if another GPU is ever added: build '60;75' and change the stamp
TEACHER = {'provider_type': 'openai', 'base_url': 'https://api.deepseek.com', 'model_name': 'deepseek-flash',
           'timeout_sec': 120}
E1_CAP_USD = 0.80                       # E-1 allocation after the user raised the total to US$2 (2026-10-15)
E2B_CAP_USD = 0.40                      # E-2b: A6 rerun after the architect fix (home ledger ~US$0.95 left)
E2_CAP_USD = 0.50                       # E-2 allocation (home ledger had US$1.19 left after E-1c)
LEDGER_HEADROOM_USD = 0.10              # ledger cap above the experiment cap: reservations never starve the stop
DEADLINE_S = 11 * 3600                  # Kaggle stops sessions at 12 h; leave time to package
PY = sys.executable
PIP = ['jsonschema', 'numpy', 'jieba', 'rank-bm25', 'defusedxml', 'lxml', 'openpyxl', 'pypdf', 'pillow',
       'tqdm', 'huggingface_hub', 'fastapi', 'uvicorn', 'websockets', 'edge-tts', 'pygame', 'psutil']

START = time.time()
PHASE_CAP = {'usd': E1_CAP_USD}         # set per phase in main(); E-2 uses its own allocation


def log(msg: str, **fields) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    row = {'t': round(time.time() - START, 1), 'msg': msg, **fields}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    with (OUT / 'kaggle-status.jsonl').open('a') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def sh(cmd: list[str] | str, **kw) -> None:
    subprocess.run(cmd, check=True, shell=isinstance(cmd, str), **kw)


def find_prebuilt() -> Path | None:
    """A dataset under /kaggle/input holding llama-server + libs and a BUILD_COMMIT file for LLAMA_COMMIT."""
    for stamp in Path('/kaggle/input').glob('**/BUILD_COMMIT'):
        if stamp.read_text().strip() == BUILD_STAMP and (stamp.parent / 'llama-server').exists():
            return stamp.parent
    return None


def save_build(bin_dir: Path) -> None:
    """Put the compiled server and its shared libraries in the output, to become a reusable dataset."""
    out = WORK / 'llama-bin'
    out.mkdir(parents=True, exist_ok=True)
    for f in bin_dir.iterdir():
        if f.name == 'llama-server' or '.so' in f.name:
            shutil.copy2(f, out / f.name)
    (out / 'BUILD_COMMIT').write_text(BUILD_STAMP + '\n')
    log('saved llama-server build for reuse', files=sorted(p.name for p in out.iterdir()))


def cuda_root() -> str:
    """Print what this host offers, then pick the system CUDA toolkit that contains nvcc."""
    probe = ('which -a nvcc; ls -d /usr/local/cuda* 2>&1; ls /usr/local/cuda/lib64/stubs 2>&1 | head -5; '
             "ldconfig -p | grep -i libcuda; find / -name 'libcuda.so*' -not -path '/proc/*' -not -path '/root/.julia/*' "
             "2>/dev/null | head -5; cmake --version | head -1")
    print(subprocess.run(probe, shell=True, capture_output=True, text=True).stdout, flush=True)
    for root in ['/usr/local/cuda', *sorted(str(p) for p in Path('/usr/local').glob('cuda-*'))]:
        if Path(root, 'bin', 'nvcc').exists():
            return root
    raise SystemExit('no CUDA toolkit with nvcc under /usr/local')


def setup(*, teacher_config: bool = True) -> dict:
    sh([PY, '-m', 'pip', 'install', '-q', *PIP])
    if not shutil.which('lsof'):
        sh('apt-get -qq update && apt-get -qq install -y lsof >/dev/null')
    TOOLS.mkdir(parents=True, exist_ok=True)
    server = TOOLS / 'llama.cpp' / 'build' / 'bin' / 'llama-server'
    prebuilt = find_prebuilt()
    if prebuilt is not None and not server.exists():
        # Reuse a server compiled by an earlier run (attached as a private dataset), same commit only.
        server.parent.mkdir(parents=True, exist_ok=True)
        for f in prebuilt.iterdir():
            shutil.copy2(f, server.parent / f.name)
        server.chmod(0o755)
        probe = subprocess.run([str(server), '--version'], capture_output=True, text=True)
        if probe.returncode == 0:
            log('reused prebuilt llama-server', source=str(prebuilt))
            save_build(server.parent)    # pass it on: the next run's input is this run's output (v7 rebuilt)
        else:                                   # e.g. the image changed its CUDA runtime: rebuild
            log('prebuilt llama-server does not run here; rebuilding', error=probe.stderr[-300:])
            shutil.rmtree(server.parent)
    if not server.exists():
        src = TOOLS / 'llama.cpp'
        if not src.exists():
            sh(['git', 'clone', '-q', 'https://github.com/ggml-org/llama.cpp', str(src)])
        sh(['git', '-C', str(src), 'checkout', '-q', LLAMA_COMMIT])
        shutil.rmtree(src / 'build', ignore_errors=True)        # never reuse a failed configure cache
        cuda = cuda_root()
        stubs = f'{cuda}/lib64/stubs'
        # Pin the system toolkit (a pip-installed nvcc may shadow it).
        # The build image has no libcuda (not even a stub); GGML_CUDA_NO_VMM drops llama.cpp's direct
        # link to the driver (used only for the VMM memory pool). Kernels and numerics are unchanged.
        sh(['cmake', '-S', str(src), '-B', str(src / 'build'), '-DGGML_CUDA=ON', '-DGGML_CUDA_NO_VMM=ON',
            f'-DCMAKE_CUDA_ARCHITECTURES={CUDA_ARCHS}',
            f'-DCUDAToolkit_ROOT={cuda}', f'-DCMAKE_CUDA_COMPILER={cuda}/bin/nvcc',
            f'-DCMAKE_LIBRARY_PATH={stubs}', f'-DCMAKE_EXE_LINKER_FLAGS=-L{stubs}', f'-DCMAKE_SHARED_LINKER_FLAGS=-L{stubs}',
            '-DLLAMA_CURL=OFF', '-DCMAKE_BUILD_TYPE=Release'], stdout=subprocess.DEVNULL)
        sh(['cmake', '--build', str(src / 'build'), '--target', 'llama-server', '-j', str(os.cpu_count() or 4)],
           stdout=subprocess.DEVNULL)
        save_build(server.parent)
    from huggingface_hub import hf_hub_download
    model = Path(hf_hub_download(MODEL_REPO, MODEL_FILE, revision=MODEL_REVISION, local_dir=str(TOOLS / 'model')))
    digest = hashlib.sha256()
    with model.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise SystemExit(f'model sha256 mismatch: {digest.hexdigest()}')
    if teacher_config:                    # rsr-smoke never calls a teacher
        write_teacher_config()
    version = subprocess.run([str(server), '--version'], capture_output=True, text=True).stderr.strip()[:300]
    gpus = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
                          capture_output=True, text=True).stdout.strip().splitlines()
    info = {'server': str(server), 'server_version': version, 'model': str(model), 'model_sha256': MODEL_SHA256,
            'gpus': gpus, 'llama_commit': LLAMA_COMMIT, 'repo_head': subprocess.run(
                ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()}
    info['kv_cache'] = probe_kv_cache(info)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'host.json').write_text(json.dumps(info, indent=1))
    log('setup done', **{k: info[k] for k in ('gpus', 'repo_head')})
    return info


def probe_kv_cache(info: dict) -> str:
    """Start one server with the q8_0 KV cache; if it cannot start (no flash attention on this GPU),
    use f16 for every job and run fewer servers at once (f16 needs about twice the memory)."""
    global MAX_PARALLEL
    probe = OUT / 'kv-probe'
    probe.mkdir(parents=True, exist_ok=True)
    env = {'KAGE_MODEL_PATH': info['model'], 'KAGE_LLAMA_SERVER': info['server'], 'KAGE_CTX': BROWSER_CTX,
           'KAGE_KV': 'q8_0'}
    code = subprocess.run([PY, '-c', 'import sys; sys.path.insert(0, "scripts/experiments"); '
                           'from local_service import LocalService; from pathlib import Path; '
                           f'svc = LocalService(18999, Path("{probe}")); svc.__enter__(); svc.__exit__(None, None, None)'],
                          cwd=ROOT, env={**os.environ, **env}, capture_output=True, text=True, timeout=300).returncode
    kv = 'q8_0' if code == 0 else 'f16'
    if kv == 'f16':
        MAX_PARALLEL = min(MAX_PARALLEL, 3)
    os.environ['KAGE_KV'] = kv
    log('kv cache', type=kv, max_parallel=MAX_PARALLEL, gpus=info.get('gpus'))
    return kv


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
            except Exception as exc:
                print(f'secret {label!r}: {type(exc).__name__}: {str(exc)[:200]}', flush=True)
        if not key:
            raise SystemExit('no Kaggle secret named DEEPSEEK_API_KEY or deepseek is attached')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'model': {'cloud_api': {**TEACHER, 'api_key': key}}}))
    path.chmod(0o600)


def job_env(info: dict, gpu: int, extra: dict | None = None) -> dict:
    env = {**os.environ, 'KAGE_MODEL_PATH': info['model'], 'KAGE_LLAMA_SERVER': info['server'],
           'CUDA_VISIBLE_DEVICES': str(gpu), 'KAGE_TEACHER_LEDGER': str(OUT / 'teacher-ledger.sqlite'),
           'KAGE_TEACHER_CAP_USD': str(PHASE_CAP['usd'] + LEDGER_HEADROOM_USD)}
    return {**env, **(extra or {})}


MAX_PARALLEL = 4            # v5: six concurrent servers -> three were killed mid-run (likely memory)
MAX_ATTEMPTS = 6            # a job that exits non-zero (infrastructure crash) resumes per task


def memory_snapshot() -> dict:
    out = {}
    try:
        mem = subprocess.run(['free', '-m'], capture_output=True, text=True).stdout.split('\n')[1].split()
        out['ram_used_mb'], out['ram_total_mb'] = int(mem[2]), int(mem[1])
    except Exception:
        pass
    try:
        gpu = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True).stdout.strip().splitlines()
        out['gpu_mb'] = [line.replace(' ', '') for line in gpu]
    except Exception:
        pass
    return out


def run_jobs(info: dict, jobs: list[tuple], label: str) -> None:
    """Run jobs at most MAX_PARALLEL at a time; restart a job that exits non-zero (it resumes per task).

    A job is ``(name, argv)`` or ``(name, argv, env)``; the extra env applies to that job only
    (e.g. KAGE_LORA for the adapter runs, never for the plain A0 controls).
    """
    gpus = max(1, len(info['gpus']))
    pending = [(job[0], job[1], job[2] if len(job) > 2 else {}, 1) for job in jobs]
    running: dict[str, tuple] = {}
    slot_gpu = {}
    log(f'{label} started', jobs=[job[0] for job in jobs], max_parallel=MAX_PARALLEL)
    last_mem = 0.0
    while pending or running:
        while pending and len(running) < MAX_PARALLEL:
            name, argv, extra, attempt = pending.pop(0)
            used = [slot_gpu[n] for n in running]
            gpu = min(range(gpus), key=lambda g: used.count(g))
            slot_gpu[name] = gpu
            logf = (OUT / f'{name}.log').open('a')
            env = {**job_env(info, gpu, extra), 'KAGE_RUN_SUFFIX': f'-a{attempt}' if attempt > 1 else ''}
            proc = subprocess.Popen([PY, *argv], cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
            running[name] = (proc, logf, argv, extra, attempt)
            log(f'{name} launched', attempt=attempt, gpu=gpu)
            time.sleep(20)                 # stagger model loads
        for name in list(running):
            proc, logf, argv, extra, attempt = running[name]
            if proc.poll() is None:
                continue
            logf.close()
            del running[name]
            log(f'{name} exit', code=proc.returncode, attempt=attempt, **memory_snapshot())
            if proc.returncode != 0 and attempt < MAX_ATTEMPTS:
                pending.append((name, argv, extra, attempt + 1))
        if time.time() - last_mem > 300:
            log('resources', running=sorted(running), **memory_snapshot())
            last_mem = time.time()
        if time.time() - START > DEADLINE_S:
            log('deadline reached; stopping jobs (all runs resume per task next time)')
            for proc, logf, _, _ in running.values():
                proc.terminate()
                proc.wait()
                logf.close()
            return
        time.sleep(15)


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


def previous_output() -> Path | None:
    """The e1/ directory of an earlier run attached as notebook input (if any)."""
    for cache in Path('/kaggle/input').glob('**/e1/teacher-cache'):
        return cache.parent
    return None


def seed_from_previous(prev: Path, roots: list[str]) -> None:
    """Reuse what was already paid for: real teacher demos and cached skill proposals.

    Only 'passed'/'failed' teacher results are reused; 'crashed' and 'budget_exhausted' were not
    demonstrations (v5). Paths inside results point at /kaggle/working/e1, which this copy recreates.
    """
    src, dst = prev / 'teacher-cache', OUT / 'teacher-cache'
    if not dst.exists():
        shutil.copytree(src, dst)
        dropped = 0
        for f in (dst / 'results').glob('*.json'):
            if json.loads(f.read_text()).get('status') not in ('passed', 'failed'):
                f.unlink()
                dropped += 1
        log('teacher cache reused', kept=len(list((dst / 'results').glob('*.json'))), dropped=dropped)
    for root in roots:
        old = prev / root / 'mutations'
        if old.exists() and not (OUT / root / 'mutations').exists():
            shutil.copytree(old, OUT / root / 'mutations')
            log('skill proposals reused', root=root)


def rerun_jobs(only: list[str] | None = None) -> list[tuple[str, list[str]]]:
    """Jobs to (re)run; default = everything except A1 (no teacher, clean in v5). v7: only A3-s1/A3-s2."""
    jobs = [job for job in e1_jobs() if job[0] != 'A1']
    return [job for job in jobs if job[0] in only] if only else jobs


def e1b_jobs() -> list[tuple[str, list[str]]]:
    """E-1b: A4 retrained with relevance-ranked skill preview (diagnosis: alphabetical preview hid the
    matching skill in all 8 A4 cp60 in-family failures). Same stream/eval/budgets as E-1."""
    jobs = []
    for job_name, argv in e1_jobs():
        if not job_name.startswith('A4-'):
            continue
        argv = list(argv)
        argv[argv.index('--root') + 1] = argv[argv.index('--root') + 1].replace('/A4', '/A4r')
        jobs.append((job_name.replace('A4', 'A4r'), argv + ['--skill-preview', 'preview_relevant']))
    return jobs


def e1c_jobs() -> list[tuple[str, list[str]]]:
    """E-1c: capability round after E-1/E-1b. A4g = skills verified on earlier same-family tasks with one
    generalization rewrite; A4m = A4g + trajectory memory. Both use relevance-ranked preview."""
    jobs = []
    for job_name, argv in e1_jobs():
        if not job_name.startswith('A4-'):
            continue
        for arm in ('A4g', 'A4m'):
            a = list(argv)
            a[a.index('--arm') + 1] = arm
            a[a.index('--root') + 1] = a[a.index('--root') + 1].replace('/A4', '/' + arm)
            a[a.index('--port') + 1] = str(int(a[a.index('--port') + 1]) + (10 if arm == 'A4g' else 20))
            jobs.append((job_name.replace('A4', arm), a + ['--skill-preview', 'preview_relevant']))
    return jobs


E2_ARMS = ('A4mG', 'A5', 'A6', 'A6-fixed')


def e2_jobs() -> list[tuple[str, list[str]]]:
    """E-2 (P3): relevance gate + agent-side clusters (A4mG), gated proactive help (A5), background
    evolution with L2 skill-selection architect (A6) and its fixed-rule control (A6-fixed).
    Same frozen stream/eval/student budgets as E-1; cp0 is A0's (the empty gate is A0's prompt)."""
    script, m = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_v1'
    common = ['--eval-manifest', str(m / 'eval.json'), '--skill-runner', 'process',
              '--teacher-cache', str(OUT / 'teacher-cache'), '--experiment-cap-usd', str(E2_CAP_USD)]
    jobs, port = [], 18201
    for seed in (1, 2):
        for arm in E2_ARMS:
            jobs.append((f'{arm}-s{seed}', [script, '--arm', arm, '--root', str(OUT / f'seed{seed}' / arm),
                                            '--stream-manifest', str(m / f'stream-seed{seed}.json'),
                                            '--checkpoints', '30,60', '--port', str(port), *common]))
            port += 1
    # The evolving arms take longest: start them first so the pool's tail is short.
    return sorted(jobs, key=lambda job: not job[0].startswith('A6'))


def e2b_jobs() -> list[tuple[str, list[str]]]:
    """E-2b: A6 x2 again (v10: the architect never answered within its turn budget, so L2 was not tested),
    plus three same-environment A0 evaluations: identical requests gave different held-out scores across runs
    (temperature 0.7), and A0's single v6 evaluation is not a fair constant for v10-era arms."""
    script, m = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_v1'
    common = ['--eval-manifest', str(m / 'eval.json'), '--skill-runner', 'process',
              '--teacher-cache', str(OUT / 'teacher-cache'), '--experiment-cap-usd', str(E2B_CAP_USD)]
    jobs = [job for job in e2_jobs() if job[0] in ('A6-s1', 'A6-s2')]
    for i in range(1, 4):
        jobs.append((f'A0-r{i}', [script, '--arm', 'A0', '--root', str(OUT / f'A0-r{i}'), '--eval-only', 'cp0',
                                  '--stream-manifest', str(m / 'stream-seed1.json'), '--port', str(18230 + i), *common]))
    return jobs


# ---------------------------------------------------------------- C: browser families
PLAYWRIGHT = 'playwright==1.63.0'           # = the Mac experiment venv
BROWSER_CTX = '16384'                       # 8 steps x ~1k tokens of DOM observation + system prompt
BROWSER_FAMILIES = ['web_form', 'web_invoice', 'web_prefs', 'web_catalog', 'web_lookup']


def browser_setup() -> None:
    """Headless Chromium for the page-scoped browser chain (root VM: Playwright adds --no-sandbox)."""
    sh([PY, '-m', 'pip', 'install', '-q', PLAYWRIGHT])
    sh([PY, '-m', 'playwright', 'install', '--with-deps', 'chromium'])
    log('browser ready', version=subprocess.run([PY, '-m', 'playwright', '--version'], capture_output=True,
                                                 text=True).stdout.strip())


def browser_calibration_jobs(families: list[str] | None = None, per_family: int = 12) -> list[tuple[str, list[str]]]:
    """Raw student (A0) on calibration seeds of the browser families, one job per family; no cloud calls.
    ``kaggle_phase`` may name families ("c-cal web_form web_invoice") to recalibrate only those."""
    script = 'scripts/experiments/stream_calibrate.py'
    return [(f'c-cal-{f}', [script, '--root', str(OUT / 'c-calibration' / f), '--per-family', str(per_family),
                            '--families', f, '--port', str(18300 + i), '--skill-runner', 'process'])
            for i, f in enumerate(families or BROWSER_FAMILIES)]


C2_CAP_USD = 0.80                           # C2 browser learning run (home ledger ~US$2.67 left on 10-17)
C2_ARMS = ('A3', 'A4mG')
C2_CONSTANT = ('A0-r1', 'A0-r2', 'A0-r3', 'A1')


def c2_jobs() -> list[tuple[str, list[str]]]:
    """C2: learning on browser tasks. A0 x3 same-environment replicates and A1 at cp0 (constant arms);
    A3 (memory, Jaccard) and A4mG (memory behind the relevance gate) x2 streams, checkpoints 22/44; their cp0
    (empty memory = A0's prompt) is A0-r1's."""
    script, m = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_web_v1'
    common = ['--eval-manifest', str(m / 'eval.json'), '--skill-runner', 'process',
              '--teacher-cache', str(OUT / 'teacher-cache-web'), '--experiment-cap-usd', str(C2_CAP_USD)]
    jobs, port = [], 18400
    for seed in (1, 2):
        for arm in C2_ARMS:
            port += 1
            jobs.append((f'web-{arm}-s{seed}', [script, '--arm', arm, '--root', str(OUT / 'web' / f'seed{seed}' / arm),
                                                '--stream-manifest', str(m / f'stream-seed{seed}.json'),
                                                '--checkpoints', '22,44', '--port', str(port), *common]))
    for name in C2_CONSTANT:
        port += 1
        jobs.append((f'web-{name}', [script, '--arm', name.split('-')[0], '--root', str(OUT / 'web' / name),
                                     '--eval-only', 'cp0', '--stream-manifest', str(m / 'stream-seed1.json'),
                                     '--port', str(port), *common]))
    return jobs


def c2_report() -> None:
    web = OUT / 'web'
    arms = [x for s in (1, 2) for a in C2_ARMS for x in ('--arm-dir', f'{a}-s{s}={web / f"seed{s}" / a}')]
    arms += [x for n in C2_CONSTANT for x in ('--arm-dir', f'{n}={web / n}')]
    arms += [x for n in C2_CONSTANT for x in ('--constant', n)]
    subprocess.run([PY, 'scripts/experiments/stream_report.py', *arms, '--cp0-from', 'A0-r1',
                    '--out', str(OUT / 'web-report')], cwd=ROOT, check=False)


C3_CAP_USD = 0.30                           # C3 teacher-written lessons run
C3_ARMS = ('A4mGL', 'AGL', 'A4mG')          # demo + lessons, lessons only, and A4mG rerun on this hardware
                                            # (v18 moved to a P100: v17's T4 numbers are another environment)
C3_CONSTANT = ('A0-r4',)                    # fresh same-environment constant and shared cp0


def c3_jobs() -> list[tuple[str, list[str]]]:
    """C3: teacher-written, task-scoped browser lessons. A4mGL = A4mG + lessons; AGL = lessons only.
    One A0 evaluation is the constant arm and the learning arms' cp0 (empty playbook = A0's prompt)."""
    script, m = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_web_v1'
    common = ['--eval-manifest', str(m / 'eval.json'), '--skill-runner', 'process',
              '--teacher-cache', str(OUT / 'teacher-cache-web'), '--experiment-cap-usd', str(C3_CAP_USD)]
    jobs, port = [], 18500
    for seed in (1, 2):
        for arm in C3_ARMS:
            port += 1
            jobs.append((f'web-{arm}-s{seed}', [script, '--arm', arm, '--root', str(OUT / 'web' / f'seed{seed}' / arm),
                                                '--stream-manifest', str(m / f'stream-seed{seed}.json'),
                                                '--checkpoints', '22,44', '--port', str(port), *common]))
    for name in C3_CONSTANT:
        port += 1
        jobs.append((f'web-{name}', [script, '--arm', name.split('-')[0], '--root', str(OUT / 'web' / name),
                                     '--eval-only', 'cp0', '--stream-manifest', str(m / 'stream-seed1.json'),
                                     '--port', str(port), *common]))
    return jobs


def c3_report() -> None:
    web = OUT / 'web'
    arms = [x for s in (1, 2) for a in C3_ARMS for x in ('--arm-dir', f'{a}-s{s}={web / f"seed{s}" / a}')]
    arms += [x for n in C3_CONSTANT for x in ('--arm-dir', f'{n}={web / n}')]
    arms += [x for n in C3_CONSTANT for x in ('--constant', n)]
    subprocess.run([PY, 'scripts/experiments/stream_report.py', *arms, '--cp0-from', 'A0-r4',
                    '--out', str(OUT / 'web-report-c3')], cwd=ROOT, check=False)


# ---------------------------------------------------------------- R2: guided fresh execution
RSR_GUIDANCE = OUT / 'rsr-guidance'
RSR_SCRIPT = 'scripts/experiments/rsr_collect.py'
RSR_MEMBERS = {
    'file': [('v10-results.tar.gz', 'e1/seed1/A4mG/memory.jsonl'),
             ('v10-results.tar.gz', 'e1/seed2/A4mG/memory.jsonl')],
    'web': [('v17-results.tar.gz', 'e1/web/seed1/A4mG/memory.jsonl'),
            ('v17-results.tar.gz', 'e1/web/seed2/A4mG/memory.jsonl')],
    # C3 (v19): demo + rules was the strongest browser arm, so browser runbooks include its rules.
    'web-lessons': [('v19-results.tar.gz', 'e1/web/seed1/A4mGL/playbook.json'),
                    ('v19-results.tar.gz', 'e1/web/seed2/A4mGL/playbook.json')],
}


def rsr_guidance() -> dict[str, list[Path]]:
    """A4mG demonstrations from the file (v10) and browser (v17) runs, extracted verbatim."""
    out = {}
    for kind, members in RSR_MEMBERS.items():
        paths = []
        for index, (archive, member) in enumerate(members, 1):
            path = RSR_GUIDANCE / f'{kind}-{index}{Path(member).suffix}'
            if not path.exists():                      # exact member names: skip AppleDouble entries
                RSR_GUIDANCE.mkdir(parents=True, exist_ok=True)
                with tarfile.open(ROOT / 'evidence' / 'kaggle' / archive) as tar:
                    path.write_bytes(tar.extractfile(member).read())
            paths.append(path)
        out[kind] = paths
    return out


def rsr_smoke_jobs(guidance: dict[str, list[Path]], *, seeds: int = 8, k: int = 2,
                   control: bool = False) -> list[tuple[str, list[str]]]:
    """Collect jobs: file families (two jobs), browser invoice/prefs, browser catalog.

    The frozen student runs practice tasks with guidance at temperature 0.6 (k attempts per task),
    plus two read-only negatives per family. File tasks: demonstrations only (rules were extracted for
    browser tasks only). Browser tasks: demonstration + rules (C3/v19: A4mGL was the strongest arm and
    its invoice gains spread across distinct tasks). ``control`` adds one job that runs all seven
    families WITHOUT guidance on the first 8 seeds, k=2 (v20 follow-up: guidance vs sampling)."""
    groups = [
        ('file-a', 'subset_selection,interval_merge', 'demo', guidance['file'], []),
        ('file-b', 'log_aggregation,csv_transform', 'demo', guidance['file'], []),
        ('browser-forms', 'web_invoice,web_prefs', 'both', guidance['web'], guidance['web-lessons']),
        ('browser-catalog', 'web_catalog', 'both', guidance['web'], guidance['web-lessons']),
    ]
    common = ['--temperature', '0.6', '--negatives', '2', '--skill-runner', 'process']
    jobs = []
    for index, (name, families, kind, memories, playbooks) in enumerate(groups):
        jobs.append((f'rsr-{name}', [RSR_SCRIPT, 'collect', '--root', str(OUT / 'rsr' / name),
                                     '--port', str(18600 + index), '--families', families,
                                     '--seeds', str(seeds), '--k', str(k), '--guidance', kind, *common,
                                     *[item for memory in memories for item in ('--memory', str(memory))],
                                     *[item for book in playbooks for item in ('--playbook', str(book))]]))
    if control:
        families = 'subset_selection,interval_merge,log_aggregation,csv_transform,web_invoice,web_prefs,web_catalog'
        jobs.append(('rsr-control', [RSR_SCRIPT, 'collect', '--root', str(OUT / 'rsr' / 'control'),
                                     '--port', '18610', '--families', families, '--seeds', '8', '--k', '2',
                                     '--guidance', 'none', *common]))
    return jobs


# ---------------------------------------------------------------- P4-L3: LoRA distillation
HF_MODEL = 'InternScience/Agents-A1-4B'
HF_REVISION = '945c40a4aa6f534d434a353207b8d42ecf7a5293'
SFT_DATA = ROOT / 'evidence' / 'distill' / 'sft.jsonl'
LORA_REPLICATES = 3


def fresh_python(code: str) -> str:
    """Run code in a new interpreter (sees freshly installed packages) and return its stdout."""
    done = subprocess.run([PY, '-c', code], cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        log('fresh python failed', code=done.returncode, err=done.stderr[-800:])
        raise SystemExit(1)
    return done.stdout.strip()


LORA_PREFLIGHT = """
import sys, torch
from peft import LoraConfig, get_peft_model
sys.path.insert(0, 'scripts/experiments')
from lora_train import TARGETS
class Mlp(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.down_proj = torch.nn.Linear(8, 8)
class Layer(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.mlp = Mlp()
class Inner(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = torch.nn.ModuleList([Layer()])
class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = Inner()
for name, pattern in TARGETS.items():
    m = get_peft_model(Tiny(), LoraConfig(r=2, target_modules=pattern))
    assert any('lora_A' in n for n, _ in m.named_parameters()), name
print('ok')
"""


def lora_setup() -> dict:
    """Training stack + full-precision base weights + llama.cpp's LoRA→GGUF converter (same commit)."""
    sh([PY, '-m', 'pip', 'install', '-q', '-U', 'transformers', 'peft', 'accelerate'])
    # v22: the upgrade above replaces huggingface_hub on disk while this process still holds the old
    # modules (imported by setup() for the GGUF download); a later lazy import then mixes versions
    # (ImportError: BucketBatchError). Everything that needs the upgraded stack runs in a fresh process.
    hf = Path(fresh_python(
        'from huggingface_hub import snapshot_download\n'
        f'print(snapshot_download({HF_MODEL!r}, revision={HF_REVISION!r}, local_dir={str(TOOLS / "hf-model")!r}, '
        "allow_patterns=['*.json', '*.safetensors', '*.jinja', '*.txt', 'tokenizer*']))").splitlines()[-1])
    src = TOOLS / 'llama.cpp'
    if not (src / 'convert_lora_to_gguf.py').exists():
        shutil.rmtree(src / '.git', ignore_errors=True)
        sh(['git', 'clone', '-q', 'https://github.com/ggml-org/llama.cpp', str(src / 'tmp-src')])
        sh(['git', '-C', str(src / 'tmp-src'), 'checkout', '-q', LLAMA_COMMIT])
        for f in (src / 'tmp-src').iterdir():
            dest = src / f.name
            if not dest.exists():
                shutil.move(str(f), dest)
        shutil.rmtree(src / 'tmp-src', ignore_errors=True)
    sh([PY, '-m', 'pip', 'install', '-q', str(src / 'gguf-py'), 'sentencepiece', 'protobuf'])
    # v24: Kaggle ships torchao 0.10; peft 0.21 checks it while wrapping any Linear and raises
    # ImportError (needs >0.16). We do not use torchao.
    subprocess.run([PY, '-m', 'pip', 'uninstall', '-q', '-y', 'torchao'], capture_output=True)
    versions = json.loads(fresh_python('import json, torch, transformers, peft\n'
                                       "print(json.dumps({'torch': torch.__version__, 'transformers': "
                                       "transformers.__version__, 'peft': peft.__version__}))").splitlines()[-1])
    # Wrap a tiny stand-in with the real target pattern before spending minutes loading the 4B model:
    # catches peft dispatcher/import problems and a target regex that matches nothing.
    fresh_python(LORA_PREFLIGHT)
    log('lora preflight ok')
    info = {'hf_model': str(hf), **versions, 'converter': str(src / 'convert_lora_to_gguf.py')}
    log('lora setup done', **info)
    return info


def train_and_convert(linfo: dict, out: Path, extra: list[str], data: Path = SFT_DATA) -> Path:
    adapter = out / 'adapter'
    if (adapter / 'train-config.json').exists():          # finished before a Colab disconnect: only convert
        log('training already finished; converting only', adapter=str(adapter))
    else:
        sh([PY, 'scripts/experiments/lora_train.py', '--data', str(data), '--model', linfo['hf_model'],
            '--out', str(adapter), *extra], cwd=ROOT, env={**os.environ, 'CUDA_VISIBLE_DEVICES': '0'})
    gguf = out / 'adapter.gguf'
    sh([PY, linfo['converter'], str(adapter), '--base', linfo['hf_model'], '--outfile', str(gguf),
        '--outtype', 'f16'], cwd=ROOT)
    log('adapter converted', gguf=str(gguf), mb=round(gguf.stat().st_size / 2**20, 1))
    return gguf


def lora_eval_jobs(n: int = LORA_REPLICATES) -> list[tuple[str, list[str]]]:
    """The LoRA student without skills or memory, evaluated n times (GPU outputs are not bit-reproducible)."""
    script, m = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_v1'
    return [(f'L3-r{i}', [script, '--arm', 'A0', '--root', str(OUT / f'L3-r{i}'), '--eval-only', 'cp0',
                          '--stream-manifest', str(m / 'stream-seed1.json'), '--eval-manifest', str(m / 'eval.json'),
                          '--skill-runner', 'process', '--port', str(18300 + i)]) for i in range(1, n + 1)]


# ---------------------------------------------------------------- R3: LoRA-1 without guidance
R2_DATA = ROOT / 'evidence' / 'reports' / 'r2' / 'sft-v21.jsonl.gz'
R3_DATA_SCRIPT = 'scripts/experiments/r3_data.py'
# v24: at 6144 tokens 119 of 360 web_catalog samples (its later steps) were dropped; the longest R2 sample is 7758.
R3_MAX_TOKENS = 8192
R3_RUNS = 3


def prepare_r3_data(extra: list[str] = (), name: str = 'r3-data', sft: Path | None = None) -> Path:
    """Validate the R2 samples and split them into train/val (refuses transfer families and eval seeds)."""
    data = OUT / name
    try:
        sh([PY, R3_DATA_SCRIPT, '--sft', str(sft or R2_DATA), '--out', str(data), *extra], cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        log('r3 data build failed', code=exc.returncode)
        raise SystemExit(1)
    stats = json.loads((data / 'data-stats.json').read_text())
    log('r3 data ready', rows=stats['rows_out'], tasks=stats['tasks'], dropped=stats['dropped'])
    return data


def r3_adapter(linfo: dict, data: Path, out: Path, extra: list[str]) -> Path:
    """Train and convert; a failure stops the phase here, before any eval job can see a missing adapter."""
    try:
        gguf = train_and_convert(linfo, out, extra, data=data / 'train.jsonl')
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        log('r3 train/convert failed; eval jobs not started', error=str(exc)[-800:])
        raise SystemExit(1)
    if not gguf.exists():
        log('r3 adapter missing after convert; eval jobs not started', path=str(gguf))
        raise SystemExit(1)
    return gguf


R3_TRAIN_ARGS = ['--epochs', '2', '--rank', '16', '--lr', '1e-4', '--targets', 'safe', '--max-tokens', '8192']


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


R2_CONTROL = ROOT / 'evidence' / 'reports' / 'r2' / 'sft-v21-control.jsonl.gz'
AGENTNET = ('xlangai/AgentNet', 'agentnet_win_mac_18k.jsonl')
TOUCAN = ('Agent-Ark/Toucan-1.5M', 'SFT/train-00000-of-00003.parquet')


def prepare_replay(n: tuple[int, int] = (800, 600), name: str = 'replay') -> Path:
    """R3b replay rows (AgentNet GUI steps as text + Toucan tool calls), built where the training runs."""
    paths = fresh_python(
        'from huggingface_hub import hf_hub_download\n'
        f'print(hf_hub_download({AGENTNET[0]!r}, {AGENTNET[1]!r}, repo_type="dataset", local_dir={str(TOOLS / "replay-src")!r}))\n'
        f'print(hf_hub_download({TOUCAN[0]!r}, {TOUCAN[1]!r}, repo_type="dataset", local_dir={str(TOOLS / "replay-src")!r}))'
    ).splitlines()[-2:]
    out = OUT / name
    if (out / 'replay.jsonl').exists() and (out / 'replay-stats.json').exists():
        return out / 'replay.jsonl'
    sh([PY, 'scripts/experiments/replay_data.py', '--agentnet', paths[0], '--toucan', paths[1], '--out', str(out),
        '--agentnet-n', str(n[0]), '--toucan-n', str(n[1])], cwd=ROOT)
    stats = json.loads((out / 'replay-stats.json').read_text())
    log('replay ready', agentnet=stats['agentnet'], toucan=stats['toucan'])
    return out / 'replay.jsonl'


def r3b_train_only(smoke: bool = False) -> None:
    """R3b on Colab: R2 + the base student's own unguided successes, reasoning-free tool calls removed, plus GUI /
    tool-use replay (random sample); adapters after epoch 1 and 2 both converted."""
    linfo = lora_setup()              # installs huggingface_hub/pandas used by prepare_replay
    train_mix(linfo, prepare_replay(), 'r3b', smoke)


def r3c_train_only(smoke: bool = False) -> None:
    """R3c on Colab: as R3b, but the replay rows are chosen from a 10k pool by LESS gradient influence (towards the
    base student's own reasoned successes and the R2 validation rows) with a diversity cap (less_select.py).
    Every finished step is kept under OUT and skipped on a rerun (Colab recycles runtimes; OUT is on Drive)."""
    sfx = '-smoke' if smoke else ''
    linfo = lora_setup()
    pool = prepare_replay((300, 200) if smoke else (5000, 5000), name=f'replay-pool{sfx}')
    rows = [line for line in pool.read_text().splitlines() if line.strip()]
    random.Random(0).shuffle(rows)
    warm_data = OUT / f'r3c-warmup{sfx}.jsonl'
    warm_data.write_text('\n'.join(rows[:max(20, len(rows) // 20)]) + '\n')      # LESS: ~5% of the pool
    warm = OUT / f'r3c-warmup{sfx}'
    if not (warm / 'optimizer.pt').exists():
        sh([PY, 'scripts/experiments/lora_train.py', '--data', str(warm_data), '--model', linfo['hf_model'],
            '--out', str(warm), '--targets', 'safe', '--max-tokens', str(R3_MAX_TOKENS), '--epochs', '2',
            '--save-optimizer'] + (['--smoke'] if smoke else []), cwd=ROOT,
           env={**os.environ, 'CUDA_VISIBLE_DEVICES': '0'})
    base = prepare_r3_data(['--sft', str(R2_CONTROL), '--require-reasoning'], name='r3c-targets')
    own = OUT / 'r3c-own.jsonl'
    with gzip.open(R2_CONTROL, 'rt') as f:
        own_rows = [line for line in f if line.strip() and not r3_reasonless(json.loads(line))]
    own.write_text(''.join(own_rows))
    selected = OUT / f'replay-less{sfx}'
    if not (selected / 'replay-stats.json').exists():
        sh([PY, 'scripts/experiments/less_select.py', '--model', linfo['hf_model'], '--warmup', str(warm),
            '--candidates', str(pool), '--target', f'own={own}', '--target', f'task={base / "val.jsonl"}',
            '--n', '40' if smoke else '1400', '--out', str(selected)], cwd=ROOT,
           env={**os.environ, 'CUDA_VISIBLE_DEVICES': '0'})
    log('less selection', **json.loads((selected / 'replay-stats.json').read_text()))
    train_mix(linfo, selected / 'replay.jsonl', 'r3c', smoke)


def r3_reasonless(row: dict) -> bool:
    target = row.get('target') or {}
    return bool(target.get('tool_calls')) and not (target.get('content') or '').strip()


R3D_DATA = ROOT / 'evidence' / 'reports' / 'r3d'


def r3e_train_only(smoke: bool = False) -> None:
    """R3e: rationalized R2 + own samples (as R3d) with the RANDOM replay of R3b — R3c showed the LESS-selected
    replay (aligned with our own tasks) does not protect transfer, the random one does."""
    linfo = lora_setup()
    train_mix(linfo, prepare_replay(), 'r3e', smoke, sft=R3D_DATA / 'sft-v21-rationalized.jsonl.gz',
              control=R3D_DATA / 'sft-v21-control-rationalized.jsonl.gz')


def r3d_train_only(smoke: bool = False) -> None:
    """R3d on Colab: every R2 step kept, reasoning-free targets given a teacher-written rationale
    (rationalize.py; the call itself unchanged), plus replay — the LESS selection from R3c when it exists on the
    shared Drive work dir, otherwise the random R3b replay."""
    linfo = lora_setup()
    less = OUT / 'replay-less' / 'replay.jsonl'
    replay = less if less.exists() else prepare_replay()
    log('r3d replay', source=str(replay))
    train_mix(linfo, replay, 'r3d', smoke, sft=R3D_DATA / 'sft-v21-rationalized.jsonl.gz',
              control=R3D_DATA / 'sft-v21-control-rationalized.jsonl.gz')


def train_mix(linfo: dict, replay: Path, tag: str, smoke: bool, sft: Path | None = None,
              control: Path | None = None) -> None:
    sfx = '-smoke' if smoke else ''
    data = prepare_r3_data(['--sft', str(control or R2_CONTROL), '--require-reasoning', '--replay', str(replay)],
                           name=f'{tag}-data{sfx}', sft=sft)
    out = OUT / f'{tag}-train{sfx}'
    args = (['--smoke', '--targets', 'safe', '--max-tokens', str(R3_MAX_TOKENS)] if smoke
            else R3_TRAIN_ARGS + ['--save-epochs', '--checkpoint-every', '25'])
    gguf = r3_adapter(linfo, data, out, args + ['--val', str(data / 'val.jsonl')])
    for epoch_dir in sorted(out.glob('adapter-epoch*')):
        sh([PY, linfo['converter'], str(epoch_dir), '--base', linfo['hf_model'], '--outfile',
            str(out / f'{epoch_dir.name}.gguf'), '--outtype', 'f16'], cwd=ROOT)
    shutil.copy(data / 'data-stats.json', out / 'data-stats.json')
    shutil.copy(replay.with_name('replay-stats.json'), out / 'replay-stats.json')
    tarball = WORK / (f'{tag}-adapter-smoke.tar.gz' if smoke else f'{tag}-adapter.tar.gz')
    with tarfile.open(tarball, 'w:gz') as tar:
        tar.add(out, arcname=f'{tag}-adapter')
    log(f'{tag} adapter packaged', tarball=str(tarball), gguf_sha256=sha256(gguf),
        epochs=sorted(p.name for p in out.glob('adapter-epoch*.gguf')), mb=round(tarball.stat().st_size / 2**20, 1))


def r3_train_only(smoke: bool = False) -> None:
    """Colab A100 (KAGE_WORK / KAGE_TOOLS set): data -> LoRA -> GGUF -> WORK/r3-adapter.tar.gz. No eval, no
    llama-server; the tarball becomes a Kaggle input for 'r3-eval'. 'r3-train smoke' trains 2 steps on the
    four longest samples to check memory before spending compute units on the real run."""
    data = prepare_r3_data()
    linfo = lora_setup()
    out = OUT / 'r3-train'
    args = (['--smoke', '--targets', 'safe', '--max-tokens', str(R3_MAX_TOKENS)] if smoke else R3_TRAIN_ARGS)
    gguf = r3_adapter(linfo, data, out, args + ['--val', str(data / 'val.jsonl')])
    shutil.copy(data / 'data-stats.json', out / 'data-stats.json')
    tarball = WORK / ('r3-adapter-smoke.tar.gz' if smoke else 'r3-adapter.tar.gz')
    with tarfile.open(tarball, 'w:gz') as tar:
        tar.add(out, arcname='r3-adapter')
    log('r3 adapter packaged', tarball=str(tarball), gguf_sha256=sha256(gguf), mb=round(tarball.stat().st_size / 2**20, 1))


# R3t (10-28, review: "one training seed"): the R3 recipe retrained with other seeds on Kaggle T4 x2 (Colab is
# gone). On a T4, head_dim 256 has no efficient attention kernel and the math path materialized a 3.5 GB score
# matrix for the 7.7k-token samples (v34-v37 smokes ran out of memory even with the layers split over both GPUs),
# so training uses causal attention in recomputed query chunks (lora_train --chunked-attention, numerically the
# same) and flash-linear-attention for the gated-delta layers. One seed per GPU, in parallel. Same data, cap,
# rank, targets, learning rate and epochs as R3; differences: fp16 with a loss scaler and the seed. (v38 smoke: 8192
# fits one T4 at 12.5 GB; torch reports bf16 as supported on a T4 but emulates it, ~23 min per step, so fp16.)
R3T_MAX_TOKENS = 8192
R3F_CAP = 150                   # samples per code-replay family: ~600 rows, the size planned for R3f
R3T_ENV = {'PYTORCH_CUDA_ALLOC_CONF': 'expandable_segments:True'}


# Training variants on R3's data and hyperparameters, one change each (docs/plans/r3f-forgetting-fix.md):
# tag prefix -> (adapter tag prefix, extra r3_data.py arguments). "r3t-train 1 2" = R3 seeds; "g0" = R3g seed 0.
R3F_SFT = ROOT / 'evidence' / 'reports' / 'r3f' / 'sft-replay.jsonl.gz'      # from 'r3f-collect', committed
R3T_VARIANTS = {'': ('r3t', []), 'g': ('r3g', ['--readback']), 'f': ('r3f', ['--sft', str(R3F_SFT)])}


def r3t_variant(tag: str) -> tuple[str, int, list[str]]:
    """'2' -> ('r3t2', 2, []), 'g0' -> ('r3g0', 0, ['--readback'])."""
    prefix, seed = tag.rstrip('0123456789'), tag[len(tag.rstrip('0123456789')):]
    if prefix not in R3T_VARIANTS or not seed:
        raise SystemExit(f'unknown r3t-train tag {tag!r}; expected <seed> or one of {sorted(R3T_VARIANTS)} + <seed>')
    name, extra = R3T_VARIANTS[prefix]
    return f'{name}{seed}', int(seed), extra


def r3t_setup(variants: tuple[tuple[str, ...], ...] = ((),)):
    """{data args: data dir} for each variant's data, plus the shared LoRA/llama setup."""
    data = {tuple(extra): prepare_r3_data(list(extra), name='r3-data' + ''.join(e for e in extra if e.startswith('--')).replace('--', '-'))
            for extra in dict.fromkeys(variants)}
    linfo = lora_setup()
    fla = subprocess.run([PY, '-m', 'pip', 'install', '-q', 'flash-linear-attention'], capture_output=True, text=True)
    probe = subprocess.run([PY, '-c', 'import fla, sys; print(fla.__version__)'], capture_output=True, text=True)
    log('flash-linear-attention', install=fla.returncode, version=probe.stdout.strip(), err=probe.stderr[-200:])
    prebuilt = find_prebuilt()
    if prebuilt is not None:
        save_build(prebuilt)                    # keep the llama-server build for the next (eval) version
    return data, linfo


def r3t_args(data: Path, cap: int, seed: int, smoke: bool) -> list[str]:
    return ((['--smoke'] if smoke else ['--epochs', '2', '--checkpoint-every', '25'])
            + ['--rank', '16', '--lr', '1e-4', '--targets', 'safe', '--max-tokens', str(cap), '--seed', str(seed),
               '--chunked-attention', '--dtype', 'fp16', '--val', str(data / 'val.jsonl')])


def r3t_smoke() -> None:
    """2 steps on the 4 longest samples, one GPU: memory and seconds per step at R3's 8192 cap."""
    data, linfo = r3t_setup()
    data = data[()]
    out = OUT / 'r3t-smoke'
    with (OUT / 'r3t-smoke.log').open('w') as log_file:
        code = subprocess.run([PY, 'scripts/experiments/lora_train.py', '--data', str(data / 'train.jsonl'),
                               '--model', linfo['hf_model'], '--out', str(out), *r3t_args(data, R3T_MAX_TOKENS, 1, True)],
                              cwd=ROOT, stdout=log_file, stderr=subprocess.STDOUT,
                              env={**os.environ, **R3T_ENV, 'CUDA_VISIBLE_DEVICES': '0'}).returncode
    config = out / 'train-config.json'
    log('r3t smoke', cap=R3T_MAX_TOKENS, code=code, config=json.loads(config.read_text()) if config.exists() else None)


def r3t_train(tags: list[str]) -> None:
    """One adapter per GPU in parallel; resumable across sessions (checkpoint every 25 steps, carried over from the
    previous version's output); stops before the session deadline and resumes in the next one. Finished adapters
    land in OUT/<name>-adapter/adapter.gguf (name r3t<seed>, r3g<seed>, ...), where 'adapter-eval <name>' finds them."""
    runs = [r3t_variant(tag) for tag in tags[:2]]
    datas, linfo = r3t_setup(tuple(tuple(extra) for _, _, extra in runs))
    stop_at = START + DEADLINE_S - 1200         # converting and packaging need ~20 minutes
    procs = {}
    for gpu, (tag, (name, number, extra)) in enumerate(zip(tags, runs)):
        data = datas[tuple(extra)]
        out = OUT / f'{name}-adapter'
        done = next(iter(INPUT.glob(f'**/e1/{name}-adapter/adapter.gguf')), None)
        if done is not None:                    # finished in an earlier version
            shutil.copytree(done.parent, out, dirs_exist_ok=True)
            log('r3t adapter carried over', tag=tag, source=str(done.parent))
            continue
        ckpt = next(iter(INPUT.glob(f'**/e1/{name}-adapter/adapter-ckpt.pt')), None)
        if ckpt is not None:
            out.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ckpt, out / 'adapter-ckpt.pt')
            log('r3t checkpoint carried over', tag=tag, source=str(ckpt))
        log_file = (OUT / f'{name}-train.log').open('a')
        procs[tag] = (subprocess.Popen([PY, 'scripts/experiments/lora_train.py', '--data', str(data / 'train.jsonl'),
                                         '--model', linfo['hf_model'], '--out', str(out / 'adapter'),
                                         *r3t_args(data, R3T_MAX_TOKENS, number, False)], cwd=ROOT,
                                        stdout=log_file, stderr=subprocess.STDOUT,
                                        env={**os.environ, **R3T_ENV, 'CUDA_VISIBLE_DEVICES': str(gpu)}), out)
        log('r3t training started', tag=tag, gpu=gpu)
        time.sleep(240)                         # stagger the two 4B loads: host RAM is 32 GB
    while procs:
        for tag, (proc, out) in list(procs.items()):
            code = proc.poll()
            if code is None and time.time() < stop_at:
                continue
            del procs[tag]
            if code is None:
                proc.terminate()
                proc.wait(timeout=300)
                log('r3t paused before the session deadline; resume in the next version', tag=tag)
            elif code:
                log('r3t training failed', tag=tag, code=code)
            else:
                gguf = out / 'adapter.gguf'
                sh([PY, linfo['converter'], str(out / 'adapter'), '--base', linfo['hf_model'], '--outfile', str(gguf),
                    '--outtype', 'f16'], cwd=ROOT)
                shutil.copy(datas[tuple(r3t_variant(tag)[2])] / 'data-stats.json', out / 'data-stats.json')
                for file in ('train-config.json', 'train-log.jsonl'):
                    if (out / 'adapter' / file).exists():
                        shutil.copy(out / 'adapter' / file, out / file)
                for heavy in (out / 'adapter').glob('*.safetensors'):   # converted; keep the output small
                    heavy.unlink()
                log('r3t adapter ready', tag=tag, gguf_sha256=sha256(gguf),
                    config=json.loads((out / 'train-config.json').read_text()) if (out / 'train-config.json').exists() else None)
        time.sleep(30)


def r3_input_adapter() -> Path:
    """The Colab-trained adapter from a Kaggle input dataset (r3-adapter/adapter.gguf, or the tarball)."""
    for gguf in INPUT.glob('**/r3-adapter/adapter.gguf'):
        break
    else:
        for tarball in INPUT.glob('**/r3-adapter.tar.gz'):
            with tarfile.open(tarball) as tar:
                tar.extractall(OUT, filter='data')
            gguf = OUT / 'r3-adapter' / 'adapter.gguf'
            break
        else:
            log('r3-eval: no r3-adapter input found; eval jobs not started')
            raise SystemExit(1)
    if not gguf.exists():
        log('r3-eval: adapter.gguf missing', path=str(gguf))
        raise SystemExit(1)
    log('r3 adapter from input', path=str(gguf), sha256=sha256(gguf))
    return gguf


def r3_eval_jobs(adapter: Path, n: int = R3_RUNS) -> list[tuple[str, list[str], dict[str, str]]]:
    """A0 with and without the adapter, n runs each, on both frozen eval sets.

    The adapter is a per-job environment entry: the A0 control jobs never get KAGE_LORA.
    Browser jobs also carry KAGE_CTX; ports are distinct so the runs can overlap.
    """
    script, jobs, port = 'scripts/experiments/stream_run.py', [], 18700
    for kind, manifest in (('file', ROOT / 'eval' / 'stream_v1'), ('web', ROOT / 'eval' / 'stream_web_v1')):
        for arm in ('L3', 'A0'):
            for index in range(1, n + 1):
                env = {'KAGE_LORA': str(adapter)} if arm == 'L3' else {}
                if kind == 'web':
                    env['KAGE_CTX'] = BROWSER_CTX
                jobs.append((f'{kind}-{arm}-r{index}', [
                    script, '--arm', 'A0', '--root', str(OUT / 'r3' / kind / f'{arm}-r{index}'),
                    '--eval-only', 'cp0', '--stream-manifest', str(manifest / 'stream-seed1.json'),
                    '--eval-manifest', str(manifest / 'eval.json'), '--skill-runner', 'process',
                    '--port', str(port)], env))
                port += 1
    return jobs


def _latest_checkpoints(root: Path) -> list[dict]:
    path = root / 'checkpoints.jsonl'
    if not path.exists():
        return []
    latest = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            latest[row['task_id']] = row          # a retried task replaces its earlier row
    return list(latest.values())


def input_adapters(tags: list[str]) -> dict[str, Path]:
    """{arm: gguf} for each tag's final adapter ('<tag>') and epoch-1 adapter ('<tag>e1') in the input datasets."""
    found = {}
    for tag in tags:
        for arm, name in ((tag, 'adapter.gguf'), (f'{tag}e1', 'adapter-epoch1.gguf')):
            hits = sorted(INPUT.glob(f'**/{tag}-adapter/{name}'))
            if hits:
                found[arm] = hits[0]
                log('input adapter', arm=arm, path=str(hits[0]), sha256=sha256(hits[0]))
    if not any(arm in found for arm in tags):
        log('adapter-eval: no final adapter found in the inputs', tags=tags)
        raise SystemExit(1)
    return found


def adapter_eval_jobs(adapters: dict[str, Path], n: int = R3_RUNS):
    """n runs per adapter per eval set + one A0 anchor per set; general check for each final adapter and A0."""
    script, jobs, port = 'scripts/experiments/stream_run.py', [], 19000
    arms = [(arm, {'KAGE_LORA': str(path)}, n) for arm, path in adapters.items()] + [('A0', {}, 1)]
    for kind, manifest in (('file', ROOT / 'eval' / 'stream_v1'), ('web', ROOT / 'eval' / 'stream_web_v1')):
        for arm, env, runs in arms:
            for index in range(1, runs + 1):
                jobs.append((f'{kind}-{arm}-r{index}', [
                    script, '--arm', 'A0', '--root', str(OUT / 'ae' / kind / f'{arm}-r{index}'), '--eval-only', 'cp0',
                    '--stream-manifest', str(manifest / 'stream-seed1.json'), '--eval-manifest', str(manifest / 'eval.json'),
                    '--skill-runner', 'process', '--port', str(port)],
                    dict(env, **({'KAGE_CTX': BROWSER_CTX} if kind == 'web' else {}))))
                port += 1
    general = [(f'general-{arm}', ['scripts/experiments/general_check.py', '--root', str(OUT / 'ae' / 'general' / arm),
                                   '--port', str(19090 + i)], {'KAGE_LORA': str(path)})
               for i, (arm, path) in enumerate(p for p in adapters.items() if not p[0].endswith('e1'))]
    return jobs, general


C4_ARMS = {                               # name -> interface environment (see core.evolution.stream.browser_interface)
    'V1': {},
    'V2': {'KAGE_BROWSER_OBS': 'compact-v2'},
    'V2PK': {'KAGE_BROWSER_OBS': 'compact-v2', 'KAGE_BROWSER_PACK': '1'},
    'V2PKST': {'KAGE_BROWSER_OBS': 'compact-v2', 'KAGE_BROWSER_PACK': '1', 'KAGE_BROWSER_STATE': '1'},
}


# C4 round 2 (10-24): the round-1 default (V2PKST) re-run as the v2 baseline; packing that keeps the text lines an
# archived page showed (hotel details); the Clef-goal pre-save checker; and an adapter under the full interface.
C4B_ARMS = {
    'V2PKST': C4_ARMS['V2PKST'],
    'V2PKTST': {'KAGE_BROWSER_OBS': 'compact-v2', 'KAGE_BROWSER_PACK': 'text', 'KAGE_BROWSER_STATE': '1'},
    'V2PKTSTCK': {'KAGE_BROWSER_OBS': 'compact-v2', 'KAGE_BROWSER_PACK': 'text', 'KAGE_BROWSER_STATE': '1',
                  'KAGE_BROWSER_CHECK': str(ROOT / 'eval' / 'stream_web_v1' / 'goals-clef.json')},
}


def c4_jobs(n: int = R3_RUNS, arms: dict | None = None, root: str = 'c4',
            port: int = 18900) -> list[tuple[str, list[str], dict[str, str]]]:
    """The frozen web eval set under each interface arm, n runs each; names 'web-ARM-rI'. An arm env may carry
    KAGE_LORA (an adapter on top of the student); otherwise it is the plain A0 student."""
    script, manifest, jobs = 'scripts/experiments/stream_run.py', ROOT / 'eval' / 'stream_web_v1', []
    for arm, env in (arms or C4_ARMS).items():
        for index in range(1, n + 1):
            jobs.append((f'web-{arm}-r{index}', [
                script, '--arm', 'A0', '--root', str(OUT / root / f'{arm}-r{index}'), '--eval-only', 'cp0',
                '--stream-manifest', str(manifest / 'stream-seed1.json'), '--eval-manifest', str(manifest / 'eval.json'),
                '--skill-runner', 'process', '--port', str(port)], {**env, 'KAGE_CTX': BROWSER_CTX}))
            port += 1
    return jobs


R3_SCALES = (0.25, 0.5, 0.75)


def r3_scale_jobs(adapter: Path, scales=R3_SCALES, n: int = R3_RUNS) -> list[tuple[str, list[str], dict[str, str]]]:
    """Scaled-adapter runs (n each) plus one A0 and one full-scale anchor per eval set; names 'kind-arm-run'."""
    script, jobs, port = 'scripts/experiments/stream_run.py', [], 18800
    arms = [(f'L3x{sc}', {'KAGE_LORA': str(adapter), 'KAGE_LORA_SCALE': str(sc)}, n) for sc in scales]
    arms += [('L3x1.0', {'KAGE_LORA': str(adapter)}, 1), ('A0', {}, 1)]
    for kind, manifest in (('file', ROOT / 'eval' / 'stream_v1'), ('web', ROOT / 'eval' / 'stream_web_v1')):
        for arm, env, runs in arms:
            for index in range(1, runs + 1):
                job_env = dict(env, **({'KAGE_CTX': BROWSER_CTX} if kind == 'web' else {}))
                jobs.append((f'{kind}-{arm}-r{index}', [
                    script, '--arm', 'A0', '--root', str(OUT / 'r3s' / kind / f'{arm}-r{index}'),
                    '--eval-only', 'cp0', '--stream-manifest', str(manifest / 'stream-seed1.json'),
                    '--eval-manifest', str(manifest / 'eval.json'), '--skill-runner', 'process',
                    '--port', str(port)], job_env))
                port += 1
    return jobs


def r3_general_jobs(adapter: Path) -> list[tuple[str, list[str], dict[str, str]]]:
    """General-ability spot check (R3 acceptance: no regression outside the benchmark), L3 and A0 once each."""
    return [(f'general-{arm}', ['scripts/experiments/general_check.py', '--root', str(OUT / 'r3' / 'general' / arm),
                                '--port', str(18790 + i)], {'KAGE_LORA': str(adapter)} if arm == 'L3' else {})
            for i, arm in enumerate(('L3', 'A0'))]


def r3_general_summary(jobs: list[tuple]) -> dict:
    out = {}
    for name, argv, _ in jobs:
        path = Path(argv[argv.index('--root') + 1]) / 'summary.json'
        out[name.split('-', 1)[1]] = json.loads(path.read_text()) if path.exists() else {'status': 'missing'}
    return out


def r3_summary(jobs: list[tuple]) -> dict:
    """Per eval set and run: pass counts per family and negative misuse (a run with no file is 'missing')."""
    summary = {}
    for name, argv, _ in jobs:
        kind, arm, run = name.split('-', 2)
        rows = _latest_checkpoints(Path(argv[argv.index('--root') + 1]))
        families, misuse = {}, {}
        for row in rows:
            family = row['family']
            entry = families.setdefault(family, {'passed': 0, 'total': 0})
            entry['total'] += 1
            entry['passed'] += int(float(row.get('score') or 0) >= 1.0)
            if row.get('negative'):
                misuse[family] = misuse.get(family, 0) + int(bool(row.get('misuse')))
        summary.setdefault(kind, {})[f'{arm}-{run}'] = {
            'families': families, 'negative_misuse': misuse,
            'passed': sum(entry['passed'] for entry in families.values()),
            'total': sum(entry['total'] for entry in families.values()),
            'status': 'ok' if rows else 'missing'}
    return summary


def package() -> None:
    subprocess.run([PY, 'scripts/experiments/stream_report.py', '--arm-dir', f'A0={OUT / "A0"}',
                    '--arm-dir', f'A1={OUT / "A1"}',
                    *[x for s in (1, 2) for a in ('A3', 'A4') for x in ('--arm-dir', f'{a}={OUT / f"seed{s}" / a}')],
                    '--constant', 'A0', '--constant', 'A1', '--cp0-from', 'A0', '--out', str(OUT / 'report')],
                   cwd=ROOT, check=False)
    with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
        tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
    log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))


PHASES = ('all', 'smoke', 'setup', 'calibration', 'e1', 'rerun', 'e1b', 'e1c', 'e2', 'e2b', 'lora-smoke', 'lora',
          'c-cal', 'c2', 'c3', 'rsr-smoke', 'rsr', 'r3-smoke', 'r3', 'r3-train', 'r3b-train', 'r3c-train', 'r3d-train', 'r3e-train', 'r3t-train', 'r3f-collect', 'r3-eval', 'r3-scale', 'c4', 'c4b', 'adapter-eval', 'package')


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--phase', choices=PHASES, default='all')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    # The notebook command never changes; the phase to run is controlled from the repository so a
    # git push is enough to switch smoke -> full run (editing the web notebook is not needed).
    control = ROOT / 'scripts' / 'experiments' / 'kaggle_phase'
    only = None
    if os.environ.get('KAGE_PHASE'):                         # Colab: the cell sets the phase itself
        args.phase, *only = os.environ['KAGE_PHASE'].split()
        log('phase from KAGE_PHASE', phase=args.phase, only=only)
    elif control.exists() and control.read_text().strip():
        args.phase, *only = control.read_text().split()      # e.g. "rerun A3-s1 A3-s2"
        log('phase from repository control file', phase=args.phase, only=only)
    if args.phase in ('e2', 'e2b'):
        PHASE_CAP['usd'] = E2_CAP_USD if args.phase == 'e2' else E2B_CAP_USD
    if args.phase == 'c2':
        PHASE_CAP['usd'] = C2_CAP_USD
    if args.phase == 'c3':
        PHASE_CAP['usd'] = C3_CAP_USD
    needs_setup = args.phase in ('all', 'smoke', 'setup', 'calibration', 'e1', 'rerun', 'e1b', 'e1c', 'e2',
                                 'e2b', 'lora-smoke', 'lora', 'c-cal', 'c2', 'c3', 'rsr-smoke', 'rsr',
                                 'r3-smoke', 'r3', 'r3-eval', 'r3-scale', 'c4', 'c4b', 'adapter-eval',
                                 'r3f-collect')
    if args.phase == 'r3-train':
        r3_train_only(smoke='smoke' in (only or []))
        return
    if args.phase == 'r3b-train':
        r3b_train_only(smoke='smoke' in (only or []))
        return
    if args.phase == 'r3c-train':
        r3c_train_only(smoke='smoke' in (only or []))
        return
    if args.phase == 'r3d-train':
        r3d_train_only(smoke='smoke' in (only or []))
        return
    if args.phase == 'r3e-train':
        r3e_train_only(smoke='smoke' in (only or []))
        return
    if args.phase == 'r3t-train':           # "r3t-train smoke", or "r3t-train 1 2" (one seed per GPU)
        r3t_smoke() if 'smoke' in only else r3t_train(only)
        return
    info = (setup(teacher_config=args.phase not in ('rsr-smoke', 'rsr', 'r3-smoke', 'r3', 'r3-eval', 'r3-scale', 'c4', 'c4b',
                                                    'adapter-eval', 'r3f-collect'))
            if needs_setup
            else json.loads((OUT / 'host.json').read_text()))
    if args.phase == 'c-cal':
        browser_setup()
        os.environ['KAGE_CTX'] = BROWSER_CTX
        run_jobs(info, browser_calibration_jobs(only or None), 'c-cal')
        from stream_calibrate import summarize
        rows = [json.loads(l) for f in sorted((OUT / 'c-calibration').glob('*/results.jsonl'))
                for l in f.read_text().splitlines() if l.strip()]
        log('c-cal summary', **summarize([r for r in rows if r.get('status') != 'crashed'], OUT / 'c-calibration'))
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'c2':
        browser_setup()
        os.environ['KAGE_CTX'] = BROWSER_CTX
        for cache in Path('/kaggle/input').glob('**/e1/teacher-cache-web'):       # reruns reuse paid demos
            if not (OUT / 'teacher-cache-web').exists():
                shutil.copytree(cache, OUT / 'teacher-cache-web')
                log('browser teacher cache reused', source=str(cache))
            break
        run_jobs(info, c2_jobs(), 'c2')
        c2_report()
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'c3':
        browser_setup()
        os.environ['KAGE_CTX'] = BROWSER_CTX
        for cache in Path('/kaggle/input').glob('**/e1/teacher-cache-web'):       # reruns reuse paid demos
            if not (OUT / 'teacher-cache-web').exists():
                shutil.copytree(cache, OUT / 'teacher-cache-web')
                log('browser teacher cache reused', source=str(cache))
            break
        run_jobs(info, c3_jobs(), 'c3')
        c3_report()
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase in ('rsr-smoke', 'rsr'):
        # R2: guided practice runs -> guidance-free SFT rows. No teacher, no cloud calls.
        browser_setup()
        os.environ['KAGE_CTX'] = BROWSER_CTX
        # 'rsr-smoke' (v20): 8 seeds x 2. 'rsr' (v21): 24 seeds x 4 toward ~2000 samples, plus the unguided control.
        jobs = (rsr_smoke_jobs(rsr_guidance()) if args.phase == 'rsr-smoke'
                else rsr_smoke_jobs(rsr_guidance(), seeds=24, k=4, control=True))
        run_jobs(info, jobs, 'rsr-smoke')
        for name, _ in jobs:
            # v20: the job name ('rsr-file') is not the root dir ('file'); a failed build must be visible.
            root = OUT / 'rsr' / name.removeprefix('rsr-')
            done = subprocess.run([PY, RSR_SCRIPT, 'build', '--root', str(root)], cwd=ROOT, capture_output=True, text=True)
            log('rsr build', job=name, code=done.returncode, out=done.stdout.strip()[-400:], err=done.stderr.strip()[-400:])
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'r3f-collect':
        # R3f (10-31): the frozen student's own unguided solutions to four code families it is never evaluated on,
        # as replay for the R3 data ('r3t-train f0'). No teacher, no cloud calls. "r3f-collect <seeds> <k>".
        seeds, k = (int(only[0]), int(only[1])) if len(only or []) >= 2 else (24, 4)
        groups = [(family, family) for family in ('rpn_eval', 'run_length', 'grid_rotate', 'version_sort')]
        jobs = [(f'r3f-{name}', [RSR_SCRIPT, 'collect', '--root', str(OUT / 'r3f' / name), '--port', str(18620 + i),
                                 '--families', families, '--seeds', str(seeds), '--k', str(k), '--guidance', 'none',
                                 '--temperature', '0.6', '--skill-runner', 'process'])
                for i, (name, families) in enumerate(groups)]
        run_jobs(info, jobs, 'r3f-collect')
        for name, _ in groups:
            done = subprocess.run([PY, RSR_SCRIPT, 'build', '--root', str(OUT / 'r3f' / name), '--cap', str(R3F_CAP)],
                                  cwd=ROOT, capture_output=True, text=True)
            log('r3f build', group=name, code=done.returncode, out=done.stdout.strip()[-400:], err=done.stderr.strip()[-400:])
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'adapter-eval':
        # R3b/R3c (10-23): Colab-trained adapters from input datasets, e.g. kaggle_phase "adapter-eval r3b r3c";
        # final and epoch-1 adapter of each tag, 3 runs per eval set, one A0 anchor, general check per final adapter.
        adapters = input_adapters(only or ['r3b'])
        browser_setup()
        jobs, general = adapter_eval_jobs(adapters)
        run_jobs(info, jobs + general, 'adapter-eval')
        summary = r3_summary(jobs)
        summary['general'] = r3_general_summary(general)
        (OUT / 'ae').mkdir(parents=True, exist_ok=True)
        (OUT / 'ae' / 'summary.json').write_text(json.dumps(summary, indent=1))
        log('adapter-eval summary', passed={kind: {run: f"{row.get('passed')}/{row.get('total')}" for run, row in runs.items()}
                                            for kind, runs in summary.items()})
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'c4':
        # C4 (10-23): is the web_prefs failure an interface problem? Same A0 student, four observation interfaces.
        browser_setup()
        jobs = c4_jobs()
        run_jobs(info, jobs, 'c4')
        summary = r3_summary(jobs)
        (OUT / 'c4').mkdir(parents=True, exist_ok=True)
        (OUT / 'c4' / 'summary.json').write_text(json.dumps(summary, indent=1))
        log('c4 summary', passed={run: f"{row.get('passed')}/{row.get('total')}" for run, row in summary['web'].items()})
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'c4b':
        # C4 round 2 (10-24); "c4b r3e" adds that adapter under the full round-2 interface.
        arms = dict(C4B_ARMS)
        for tag in only or []:
            arms[f'{tag.upper()}V2PKTSTCK'] = {**C4B_ARMS['V2PKTSTCK'], 'KAGE_LORA': str(input_adapters([tag])[tag])}
        browser_setup()
        jobs = c4_jobs(arms=arms, root='c4b', port=19300)
        run_jobs(info, jobs, 'c4b')
        summary = r3_summary(jobs)
        (OUT / 'c4b').mkdir(parents=True, exist_ok=True)
        (OUT / 'c4b' / 'summary.json').write_text(json.dumps(summary, indent=1))
        log('c4b summary', passed={run: f"{row.get('passed')}/{row.get('total')}" for run, row in summary['web'].items()})
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'r3-scale':
        # R3b (10-22): the same adapter at several scales (base <-> adapter interpolation) to trade in-family
        # gains against the transfer loss; A0 and scale 1.0 once each as same-session anchors.
        gguf = r3_input_adapter()
        browser_setup()
        jobs = r3_scale_jobs(gguf)
        run_jobs(info, jobs, 'r3-scale')
        summary = r3_summary(jobs)
        (OUT / 'r3s').mkdir(parents=True, exist_ok=True)
        (OUT / 'r3s' / 'summary.json').write_text(json.dumps(summary, indent=1))
        log('r3-scale summary', passed={kind: {run: f"{row.get('passed')}/{row.get('total')}" for run, row in runs.items()}
                                        for kind, runs in summary.items()})
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase in ('r3-smoke', 'r3', 'r3-eval'):
        # R3: LoRA-1 on guidance-free R2 samples, evaluated without skills, memory or lessons.
        # 'r3-eval' (10-21): the adapter was trained on a Colab A100 ('r3-train'; a T4 runs out of memory on
        # the 7.7k-token web_catalog samples) and arrives as a Kaggle input dataset.
        if args.phase == 'r3-eval':
            gguf = r3_input_adapter()
        else:
            data = prepare_r3_data()            # fail fast before downloading/training
            linfo = lora_setup()
        if args.phase == 'r3-smoke':
            out = OUT / 'r3-smoke'
            gguf = r3_adapter(linfo, data, out, ['--smoke', '--targets', 'safe', '--max-tokens', str(R3_MAX_TOKENS),
                                                '--val', str(data / 'val.jsonl')])
            browser_setup()
            jobs = [
                ('r3-smoke-file', ['scripts/experiments/stream_calibrate.py', '--root', str(out / 'file'),
                                   '--per-family', '1', '--families', 'log_aggregation', '--port', '18750',
                                   '--skill-runner', 'process'], {'KAGE_LORA': str(gguf)}),
                ('r3-smoke-web', ['scripts/experiments/stream_calibrate.py', '--root', str(out / 'web'),
                                  '--per-family', '1', '--families', 'web_invoice', '--port', '18751',
                                  '--skill-runner', 'process'], {'KAGE_LORA': str(gguf), 'KAGE_CTX': BROWSER_CTX}),
            ]
            run_jobs(info, jobs, 'r3-smoke')
            for name, _, _ in jobs:
                results = out / name.removeprefix('r3-smoke-') / 'results.jsonl'
                print(results.read_text() if results.exists() else '', flush=True)
        else:
            out = OUT / 'r3'
            if args.phase == 'r3':
                gguf = r3_adapter(linfo, data, out, R3_TRAIN_ARGS + ['--val', str(data / 'val.jsonl')])
            browser_setup()
            jobs, general = r3_eval_jobs(gguf), r3_general_jobs(gguf)
            run_jobs(info, jobs + general, 'r3')
            summary = r3_summary(jobs)
            summary['general'] = r3_general_summary(general)
            (out / 'summary.json').write_text(json.dumps(summary, indent=1))
            log('r3 summary', passed={kind: {run: f"{row.get('passed')}/{row.get('total')}" for run, row in runs.items()}
                                      for kind, runs in summary.items()})
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json', '.safetensors'))
                    and 'adapter' not in t.name else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase == 'smoke':
        # One local task end to end (server start, CUDA inference, sandboxed checker) + teacher config present.
        run_jobs(info, [('smoke', ['scripts/experiments/stream_calibrate.py', '--root', str(OUT / 'smoke'),
                                   '--per-family', '1', '--families', 'log_aggregation', '--port', '18099',
                                   '--skill-runner', 'process'])], 'smoke')
        print((OUT / 'smoke' / 'results.jsonl').read_text(), flush=True)
        log('teacher config present', ok=Path('~/.config/kage/teachers/deepseek.json').expanduser().exists())
        return
    if args.phase in ('lora-smoke', 'lora'):
        linfo = lora_setup()
        smoke = args.phase == 'lora-smoke'
        targets = only[0] if only else 'full'
        gguf = train_and_convert(linfo, OUT / 'lora', ['--smoke'] * smoke + ['--targets', targets])
        os.environ['KAGE_LORA'] = str(gguf)
        if smoke:      # one real task through llama-server with the adapter loaded
            run_jobs(info, [('lora-smoke', ['scripts/experiments/stream_calibrate.py', '--root', str(OUT / 'lora-smoke'),
                                            '--per-family', '1', '--families', 'log_aggregation', '--port', '18299',
                                            '--skill-runner', 'process'])], 'lora-smoke')
            print((OUT / 'lora-smoke' / 'results.jsonl').read_text(), flush=True)
        else:
            run_jobs(info, lora_eval_jobs(), 'lora')
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json', '.safetensors'))
                    and 'adapter' not in t.name else t)
        log('packaged', tarball=str(WORK / 'e1-results.tar.gz'))
        return
    if args.phase in ('all', 'calibration'):
        run_jobs(info, calibration_jobs(), 'calibration')
    if args.phase in ('all', 'e1'):
        run_jobs(info, e1_jobs(), 'e1')
    if args.phase == 'rerun':
        prev = previous_output()
        if prev is None:
            raise SystemExit('rerun needs the previous run output attached as input')
        seed_from_previous(prev, ['seed1/A4', 'seed2/A4'])
        run_jobs(info, rerun_jobs(only), 'rerun')
    if args.phase in ('e1b', 'e1c', 'e2', 'e2b'):
        prev = previous_output()
        if prev is None:
            raise SystemExit(f'{args.phase} needs the previous run output attached as input (teacher cache)')
        seed_from_previous(prev, [])
        run_jobs(info, {'e1b': e1b_jobs, 'e1c': e1c_jobs, 'e2': e2_jobs, 'e2b': e2b_jobs}[args.phase](), args.phase)
    if args.phase in ('all', 'e1', 'rerun', 'e1b', 'e1c', 'e2', 'e2b', 'package'):
        package()


if __name__ == '__main__':
    main()
