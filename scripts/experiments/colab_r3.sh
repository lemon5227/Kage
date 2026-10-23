#!/bin/bash
# Colab helper for R3 training (the notebook cell stays one short line; Colab's editor auto-closes
# brackets and quotes, which broke longer typed commands on 10-21).
#   bash colab_r3.sh fla smoke     install flash-linear-attention, run the 2-step smoke, show its key lines
#   bash colab_r3.sh run           real training in the FOREGROUND (log: /content/train.log). Use this one:
#                                  a background job leaves the cell idle and Colab recycles the VM after
#                                  ~1 h idle, losing /content (10-22: a finished adapter was lost that way).
#                                  With Drive mounted, everything is under MyDrive/kage/work and a rerun resumes.
#   bash colab_r3.sh train         same in the background (only if the tab stays active)
#   bash colab_r3.sh status        last progress lines of the real training
# Compute units are billed while a runtime is attached, idle or not (A100 about 5.3 CU/h). End every training cell
# with `from google.colab import runtime; runtime.unassign()` so the runtime is released the moment the work is done
# (a bash subprocess cannot do it: unassign needs the notebook kernel).  Example cell:
#   import subprocess; subprocess.run('R3PHASE=r3d-train bash /content/Kage/scripts/experiments/colab_r3.sh run', shell=True)
#   from google.colab import runtime; runtime.unassign()
set -u
# Update the checkout BEFORE running: bash reads a script while executing it, so a `git pull` from inside this
# file would run a mix of old and new lines (10-22: the Drive copy step silently did not run). Call it as
#   !git -C /content/Kage pull -q; bash /content/Kage/scripts/experiments/colab_r3.sh run
[ -d /content/Kage ] || git clone -q -b dev --depth 1 https://github.com/lemon5227/Kage.git /content/Kage
cd /content/Kage
# With Drive mounted the whole work dir (data, checkpoints every 25 steps, adapters, logs) lives on the user's Drive,
# so a recycled runtime loses nothing: rerunning the same command resumes (10-22: two finished/half-finished runs lost).
if [ -d /content/drive/MyDrive ]; then export KAGE_WORK=/content/drive/MyDrive/kage/work; else export KAGE_WORK=/content/work; fi
export KAGE_TOOLS=/content/tools
mkdir -p "$KAGE_WORK"
P=${R3PHASE:-r3-train}                 # r3b-train: random replay mix; r3c-train: LESS-selected replay mix
TAR=$KAGE_WORK/${P%-train}-adapter.tar.gz
KEY='^\{"step"|lora_b_max_abs|falling back|Error|failed|packaged'
for action in "$@"; do
  case "$action" in
    fla) pip install -q flash-linear-attention > /content/fla.log 2>&1; tail -3 /content/fla.log; pip show flash-linear-attention | head -2 ;;
    smoke) KAGE_PHASE="$P smoke" python scripts/experiments/kaggle_e1.py > /content/smoke.log 2>&1
           echo "exit $?"; grep -E "$KEY" /content/smoke.log ;;
    run) KAGE_PHASE=$P python scripts/experiments/kaggle_e1.py >> "$KAGE_WORK/$P.log" 2>&1
         echo "exit $?"; grep -E "$KEY|\"epoch\"|resumed_from" "$KAGE_WORK/$P.log" | tail -8; ls -la "$TAR" ;;
    train) nohup env KAGE_PHASE=$P python scripts/experiments/kaggle_e1.py > /content/train.log 2>&1 &
           echo "started pid $!" ;;
    status) grep -E "$KEY|\"epoch\"|resumed_from" "$KAGE_WORK/$P.log" | tail -6; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv ;;
  esac
done
