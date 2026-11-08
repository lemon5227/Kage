# Runs on the Colab VM: is the eval still running, and its last status line.
import subprocess
print(subprocess.run('echo PROCS $(ps aux | grep -c "[k]aggle_e1.py"); tail -1 /content/work/e1/kaggle-status.jsonl 2>/dev/null '
                     '| cut -c1-200; tail -c 600 /content/eval.out', shell=True, capture_output=True, text=True).stdout)
