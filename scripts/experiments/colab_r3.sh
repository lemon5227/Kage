#!/bin/bash
# Colab helper for R3 training (the notebook cell stays one short line; Colab's editor auto-closes
# brackets and quotes, which broke longer typed commands on 10-21).
#   bash colab_r3.sh fla smoke     install flash-linear-attention, run the 2-step smoke, show its key lines
#   bash colab_r3.sh train         start the real training in the background (log: /content/train.log)
#   bash colab_r3.sh status        last progress lines of the real training
set -u
cd /content/Kage && git pull -q
export KAGE_WORK=/content/work KAGE_TOOLS=/content/tools
KEY='^\{"step"|lora_b_max_abs|falling back|Error|failed|packaged'
for action in "$@"; do
  case "$action" in
    fla) pip install -q flash-linear-attention > /content/fla.log 2>&1; tail -3 /content/fla.log; pip show flash-linear-attention | head -2 ;;
    smoke) KAGE_PHASE="r3-train smoke" python scripts/experiments/kaggle_e1.py > /content/smoke.log 2>&1
           echo "exit $?"; grep -E "$KEY" /content/smoke.log ;;
    train) nohup env KAGE_PHASE=r3-train python scripts/experiments/kaggle_e1.py > /content/train.log 2>&1 &
           echo "started pid $!" ;;
    status) grep -E "$KEY|\"epoch\"" /content/train.log | tail -6; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv ;;
  esac
done
