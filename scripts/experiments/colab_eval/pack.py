# Runs on the Colab VM: pack the eval progress ('bak') or the finished results ('res') into 20 MB parts to download.
import glob, hashlib, os, subprocess
kind = open('/content/pack.txt').read().strip()
for f in glob.glob(f'/content/{kind}out.*'):
    os.remove(f)
src = ("tar czf /content/bakout.tgz -C /content/work --exclude='*.gguf' e1" if kind == 'bak'
       else 'cp /content/work/e1-results.tar.gz /content/resout.tgz')
subprocess.run(f'{src} && split -b 20m /content/{kind}out.tgz /content/{kind}out.a', shell=True, check=True)
print('SHA', hashlib.sha256(open(f'/content/{kind}out.tgz', 'rb').read()).hexdigest())
for p in sorted(glob.glob(f'/content/{kind}out.a*')):
    print('PART', p)
