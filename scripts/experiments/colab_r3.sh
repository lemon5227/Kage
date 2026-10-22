#!/bin/bash
# Colab helper for R3 training (the notebook cell stays one short line; Colab's editor auto-closes
# brackets and quotes, which broke longer typed commands on 10-21).
#   bash colab_r3.sh fla smoke     install flash-linear-attention, run the 2-step smoke, show its key lines
#   bash colab_r3.sh run           real training in the FOREGROUND (log: /content/train.log). Use this one:
#                                  a background job leaves the cell idle and Colab recycles the VM after
#                                  ~1 h idle, losing /content (10-22: a finished adapter was lost that way).
#                                  Put files.download('/content/work/r3-adapter.tar.gz') in the same cell.
#                                  With Drive mounted at /content/drive it also copies to MyDrive/kage/.
#   bash colab_r3.sh train         same in the background (only if the tab stays active)
#   bash colab_r3.sh status        last progress lines of the real training
set -u
# Update the checkout BEFORE running: bash reads a script while executing it, so a `git pull` from inside this
# file would run a mix of old and new lines (10-22: the Drive copy step silently did not run). Call it as
#   !git -C /content/Kage pull -q; bash /content/Kage/scripts/experiments/colab_r3.sh run
[ -d /content/Kage ] || git clone -q -b dev --depth 1 https://github.com/lemon5227/Kage.git /content/Kage
cd /content/Kage
export KAGE_WORK=/content/work KAGE_TOOLS=/content/tools
P=${R3PHASE:-r3-train}                 # R3PHASE=r3b-train for the R3b mix (replay + reasoning filter)
TAR=/content/work/${P%-train}-adapter.tar.gz
KEY='^\{"step"|lora_b_max_abs|falling back|Error|failed|packaged'
for action in "$@"; do
  case "$action" in
    fla) pip install -q flash-linear-attention > /content/fla.log 2>&1; tail -3 /content/fla.log; pip show flash-linear-attention | head -2 ;;
    smoke) KAGE_PHASE="$P smoke" python scripts/experiments/kaggle_e1.py > /content/smoke.log 2>&1
           echo "exit $?"; grep -E "$KEY" /content/smoke.log ;;
    run) KAGE_PHASE=$P python scripts/experiments/kaggle_e1.py > /content/train.log 2>&1
         echo "exit $?"; grep -E "$KEY|\"epoch\"" /content/train.log | tail -8
         # keep a copy on the user's Google Drive when it is mounted (survives a recycled VM)
         if [ -d /content/drive/MyDrive ]; then
           mkdir -p /content/drive/MyDrive/kage && cp $TAR /content/train.log /content/drive/MyDrive/kage/ \
             && echo "copied to Google Drive: MyDrive/kage/"
         fi ;;
    train) nohup env KAGE_PHASE=$P python scripts/experiments/kaggle_e1.py > /content/train.log 2>&1 &
           echo "started pid $!" ;;
    status) grep -E "$KEY|\"epoch\"" /content/train.log | tail -6; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv ;;
  esac
done
