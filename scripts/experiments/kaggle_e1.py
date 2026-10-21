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


def job_env(info: dict, gpu: int) -> dict:
    return {**os.environ, 'KAGE_MODEL_PATH': info['model'], 'KAGE_LLAMA_SERVER': info['server'],
            'CUDA_VISIBLE_DEVICES': str(gpu), 'KAGE_TEACHER_LEDGER': str(OUT / 'teacher-ledger.sqlite'),
            'KAGE_TEACHER_CAP_USD': str(PHASE_CAP['usd'] + LEDGER_HEADROOM_USD)}


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


def run_jobs(info: dict, jobs: list[tuple[str, list[str]]], label: str) -> None:
    """Run jobs at most MAX_PARALLEL at a time; restart a job that exits non-zero (it resumes per task)."""
    gpus = max(1, len(info['gpus']))
    pending = [(name, argv, 1) for name, argv in jobs]
    running: dict[str, tuple] = {}
    slot_gpu = {}
    log(f'{label} started', jobs=[n for n, _ in jobs], max_parallel=MAX_PARALLEL)
    last_mem = 0.0
    while pending or running:
        while pending and len(running) < MAX_PARALLEL:
            name, argv, attempt = pending.pop(0)
            used = [slot_gpu[n] for n in running]
            gpu = min(range(gpus), key=lambda g: used.count(g))
            slot_gpu[name] = gpu
            logf = (OUT / f'{name}.log').open('a')
            env = {**job_env(info, gpu), 'KAGE_RUN_SUFFIX': f'-a{attempt}' if attempt > 1 else ''}
            proc = subprocess.Popen([PY, *argv], cwd=ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT)
            running[name] = (proc, logf, argv, attempt)
            log(f'{name} launched', attempt=attempt, gpu=gpu)
            time.sleep(20)                 # stagger model loads
        for name in list(running):
            proc, logf, argv, attempt = running[name]
            if proc.poll() is None:
                continue
            logf.close()
            del running[name]
            log(f'{name} exit', code=proc.returncode, attempt=attempt, **memory_snapshot())
            if proc.returncode != 0 and attempt < MAX_ATTEMPTS:
                pending.append((name, argv, attempt + 1))
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


def rsr_smoke_jobs(guidance: dict[str, list[Path]]) -> list[tuple[str, list[str]]]:
    """Three parallel collect jobs: file families, browser invoice/prefs, browser catalog.

    The frozen student runs practice tasks with guidance at temperature 0.6 (two attempts per task),
    plus two read-only negatives per family. File tasks: demonstrations only (rules were extracted for
    browser tasks only). Browser tasks: demonstration + rules (C3/v19: A4mGL was the strongest arm and
    its invoice gains spread across distinct tasks)."""
    groups = [
        ('file', 'subset_selection,interval_merge,log_aggregation,csv_transform', 'demo', guidance['file'], []),
        ('browser-forms', 'web_invoice,web_prefs', 'both', guidance['web'], guidance['web-lessons']),
        ('browser-catalog', 'web_catalog', 'both', guidance['web'], guidance['web-lessons']),
    ]
    jobs = []
    for index, (name, families, kind, memories, playbooks) in enumerate(groups):
        jobs.append((f'rsr-{name}', [RSR_SCRIPT, 'collect', '--root', str(OUT / 'rsr' / name),
                                     '--port', str(18600 + index), '--families', families,
                                     '--seeds', '8', '--k', '2', '--temperature', '0.6',
                                     '--guidance', kind, '--negatives', '2',
                                     '--skill-runner', 'process',
                                     *[item for memory in memories for item in ('--memory', str(memory))],
                                     *[item for book in playbooks for item in ('--playbook', str(book))]]))
    return jobs


# ---------------------------------------------------------------- P4-L3: LoRA distillation
HF_MODEL = 'InternScience/Agents-A1-4B'
HF_REVISION = '945c40a4aa6f534d434a353207b8d42ecf7a5293'
SFT_DATA = ROOT / 'evidence' / 'distill' / 'sft.jsonl'
LORA_REPLICATES = 3


def lora_setup() -> dict:
    """Training stack + full-precision base weights + llama.cpp's LoRA→GGUF converter (same commit)."""
    sh([PY, '-m', 'pip', 'install', '-q', '-U', 'transformers', 'peft', 'accelerate'])
    from huggingface_hub import snapshot_download
    hf = Path(snapshot_download(HF_MODEL, revision=HF_REVISION, local_dir=str(TOOLS / 'hf-model'),
                                allow_patterns=['*.json', '*.safetensors', '*.jinja', '*.txt', 'tokenizer*']))
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
    import torch
    import transformers
    info = {'hf_model': str(hf), 'transformers': transformers.__version__, 'torch': torch.__version__,
            'converter': str(src / 'convert_lora_to_gguf.py')}
    log('lora setup done', **info)
    return info


def train_and_convert(linfo: dict, out: Path, extra: list[str]) -> Path:
    adapter = out / 'adapter'
    sh([PY, 'scripts/experiments/lora_train.py', '--data', str(SFT_DATA), '--model', linfo['hf_model'],
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
    p.add_argument('--phase', choices=['all', 'smoke', 'setup', 'calibration', 'e1', 'rerun', 'e1b', 'e1c', 'e2', 'e2b', 'lora-smoke', 'lora',
                                        'c-cal', 'c2', 'c3', 'rsr-smoke', 'package'], default='all')
    args = p.parse_args(argv)
    # The notebook command never changes; the phase to run is controlled from the repository so a
    # git push is enough to switch smoke -> full run (editing the web notebook is not needed).
    control = ROOT / 'scripts' / 'experiments' / 'kaggle_phase'
    only = None
    if control.exists() and control.read_text().strip():
        args.phase, *only = control.read_text().split()      # e.g. "rerun A3-s1 A3-s2"
        log('phase from repository control file', phase=args.phase, only=only)
    if args.phase in ('e2', 'e2b'):
        PHASE_CAP['usd'] = E2_CAP_USD if args.phase == 'e2' else E2B_CAP_USD
    if args.phase == 'c2':
        PHASE_CAP['usd'] = C2_CAP_USD
    if args.phase == 'c3':
        PHASE_CAP['usd'] = C3_CAP_USD
    needs_setup = args.phase in ('all', 'smoke', 'setup', 'calibration', 'e1', 'rerun', 'e1b', 'e1c', 'e2',
                                 'e2b', 'lora-smoke', 'lora', 'c-cal', 'c2', 'c3', 'rsr-smoke')
    info = (setup(teacher_config=args.phase != 'rsr-smoke') if needs_setup
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
    if args.phase == 'rsr-smoke':
        # R2: guided practice runs -> guidance-free SFT rows. No teacher, no cloud calls.
        browser_setup()
        os.environ['KAGE_CTX'] = BROWSER_CTX
        jobs = rsr_smoke_jobs(rsr_guidance())
        run_jobs(info, jobs, 'rsr-smoke')
        for name, _ in jobs:
            subprocess.run([PY, RSR_SCRIPT, 'build', '--root', str(OUT / 'rsr' / name)], cwd=ROOT, check=False)
        with tarfile.open(WORK / 'e1-results.tar.gz', 'w:gz') as tar:
            tar.add(OUT, arcname='e1', filter=lambda t: None if t.name.endswith(('.gguf', 'deepseek.json')) else t)
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
