#!/bin/bash
# Build deepseek-v0.4 paper from draft.md (pandoc + tectonic, free fonts).
set -euo pipefail
cd "$(dirname "$0")"
pandoc draft.md -s -o paper.tex --pdf-engine=tectonic \
  -V documentclass=article -V geometry:margin=2.0cm -V fontsize=10pt \
  -V colorlinks=true -V linkcolor=blue -V urlcolor=blue -V fig_caption=true
tectonic paper.tex --keep-logs >build.stdout.log 2>tectonic.log || { tail -30 tectonic.log; exit 1; }
printf '%s/paper.pdf\n' "$PWD"
