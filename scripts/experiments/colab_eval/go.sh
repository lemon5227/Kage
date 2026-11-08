#!/bin/bash
# 'adapter-eval' on a free Colab T4 that survives VM loss (runbook pitfalls 28-30).
#   scripts/experiments/colab_eval/go.sh <work dir> <adapter root> <name>...
#   e.g. go.sh /Users/wenbo/Kage/artifacts/colab-eval/r3fg artifacts/r3f-ckpt/v49 r3fg0 r3fg1
# <adapter root>/**/<name>-adapter/adapter.gguf are uploaded with the Kaggle-built llama-server (LLAMA_BIN, BUILD_COMMIT
# must match kaggle_e1.py) in 20 MB parts; the VM is polled every 3 min (an idle free VM is pruned), the progress is
# packed and downloaded every 30 min into <work dir>/bak, and a lost VM is replaced (retry every 30 min while no free
# T4 is offered) and restored from it. Results land in <work dir>/results/e1-results.tar.gz.
set -u
W=$1; A=$2; shift 2; NAMES="$*"; S=${COLAB_SESSION:-kage-ev}; H=$(cd "$(dirname "$0")" && pwd)
LLAMA_BIN=${LLAMA_BIN:-/Users/wenbo/Kage/artifacts/r3f-ckpt/v47/llama-bin}
mkdir -p "$W/up"; echo "$NAMES" > "$W/up/names.txt"
if [ ! -f "$W/up/lb.done" ]; then
  tar czf "$W/lb.tgz" -C "$(dirname "$LLAMA_BIN")" "$(basename "$LLAMA_BIN")" && split -b 20m "$W/lb.tgz" "$W/up/lb.a"
  for n in $NAMES; do
    g=$(find "$A" -path "*/$n-adapter/adapter.gguf" | head -1); [ -n "$g" ] || { echo "no adapter for $n under $A"; exit 1; }
    echo "$n $(shasum -a 256 "$g" | cut -c1-16)"; split -b 20m "$g" "$W/up/$n.a"
  done
  rm "$W/lb.tgz"; touch "$W/up/lb.done"
fi
ex() { colab exec -s $S -f "$1" --timeout "${2:-60}" 2>&1 | grep -v -i 'token\|new version\|colab update\|update_check'; }
up() { for f in "$@"; do for t in 1 2 3; do colab upload -s $S "$f" "/content/$(basename "$f")" >/dev/null 2>&1 && break; [ $t = 3 ] && return 1; done; done; }
fetch() {  # $1 bak|res: pack on the VM, download the parts, check the sha, then replace $W/$1
  echo "$1" > "$W/pack.txt"; up "$W/pack.txt" || return 1
  out=$(ex "$H/pack.py" 600); sha=$(echo "$out" | sed -n 's/^SHA //p'); [ -n "$sha" ] || return 1
  rm -rf "$W/$1.new"; mkdir -p "$W/$1.new"
  for p in $(echo "$out" | sed -n 's/^PART //p'); do colab download -s $S "$p" "$W/$1.new/$(basename "$p")" >/dev/null 2>&1 || return 1; done
  [ "$(cat "$W/$1.new"/* | shasum -a 256 | cut -d' ' -f1)" = "$sha" ] || return 1
  rm -rf "$W/$1"; mv "$W/$1.new" "$W/$1"; echo "$(date '+%m-%d %H:%M') fetched $1 $(du -sh "$W/$1" | cut -f1)"
}
for attempt in $(seq 1 60); do
  colab sessions 2>/dev/null | grep -q "\[$S\]" || until colab new -s $S --gpu T4 >/dev/null 2>&1; do
    echo "$(date '+%m-%d %H:%M') no free T4; retry in 30 min"; sleep 1800; done
  echo "$(date '+%m-%d %H:%M') session up (attempt $attempt)"
  up "$W"/up/*.a* "$W/up/names.txt" $( [ -d "$W/bak" ] && ls "$W"/bak/* ) || { echo upload failed; colab stop -s $S >/dev/null 2>&1; continue; }
  ex "$H/prep.py" 900 | grep -v Deprecation | tail -6
  i=0; miss=0
  while true; do
    sleep 180; out=$(ex "$H/status.py")
    if ! echo "$out" | grep -q PROCS; then miss=$((miss+1)); [ $miss -ge 3 ] && { echo "$(date '+%m-%d %H:%M') session lost"; break; }; continue; fi
    miss=0; i=$((i+1)); echo "$(date '+%m-%d %H:%M') $(echo "$out" | grep '"msg"' | tail -1 | cut -c1-160)" >> "$W/keepalive.log"
    if echo "$out" | grep -q "PROCS 0"; then
      fetch bak; if fetch res; then
        mkdir -p "$W/results"; cat "$W"/res/* > "$W/results/e1-results.tar.gz"
        echo "$(date '+%m-%d %H:%M') EVAL-DONE $W/results/e1-results.tar.gz"; colab stop -s $S >/dev/null 2>&1; exit 0
      fi
      echo "$(date '+%m-%d %H:%M') EVAL-EXITED-NO-RESULTS"; echo "$out" | tail -15; exit 2
    fi
    [ $((i % 10)) -eq 0 ] && fetch bak
  done
done
exit 1
