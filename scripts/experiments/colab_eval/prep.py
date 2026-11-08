# Runs on the Colab VM (colab exec): assemble the uploaded chunks, restore earlier progress, start 'adapter-eval'.
import glob, hashlib, os, site, subprocess, tarfile


def join(pattern, dest):
    parts = sorted(glob.glob(pattern))
    if not parts:
        return None
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'wb') as out:
        for q in parts:
            out.write(open(q, 'rb').read())
    return hashlib.sha256(open(dest, 'rb').read()).hexdigest()[:16]


names = open('/content/names.txt').read().split()
for n in names:
    print(n, join(f'/content/{n}.a*', f'/content/input/e1/{n}-adapter/adapter.gguf'))
print('llama-bin', join('/content/lb.a*', '/content/lb.tgz'))         # the Kaggle build (sm75, CUDA 12)
tarfile.open('/content/lb.tgz').extractall('/content/input', filter='data')
b = join('/content/bakout.a*', '/content/bak.tgz')
if b:                                                                  # stream_run resumes per task
    os.makedirs('/content/work', exist_ok=True)
    tarfile.open('/content/bak.tgz').extractall('/content/work', filter='data')
    print('restored', b)
subprocess.run('pip install -q nvidia-cuda-runtime-cu12 nvidia-cublas-cu12', shell=True)
ld = ':'.join(sorted({os.path.dirname(p) for p in glob.glob(site.getsitepackages()[0] + '/nvidia/*/lib/lib*.so.12')}))
subprocess.run('rm -rf /content/Kage /content/tools; git clone -q -b dev --depth 1 '
               'https://github.com/lemon5227/Kage.git /content/Kage', shell=True)
subprocess.Popen(f'cd /content/Kage && LD_LIBRARY_PATH={ld}:$LD_LIBRARY_PATH KAGE_WORK=/content/work '
                 f'KAGE_TOOLS=/content/tools KAGE_INPUT=/content/input KAGE_PHASE="adapter-eval {" ".join(names)}" '
                 'nohup python scripts/experiments/kaggle_e1.py >> /content/eval.out 2>&1 &', shell=True, start_new_session=True)
print('started', subprocess.run('git -C /content/Kage log --oneline -1', shell=True, capture_output=True, text=True).stdout)
