#!/bin/bash
# Canonical draft.md -> paper.tex -> paper.pdf. No proprietary system fonts.
set -euo pipefail
cd "$(dirname "$0")"
pandoc ../draft.md -s -o paper.tex --pdf-engine=tectonic \
  -V documentclass=article -V geometry:margin=2.2cm -V fontsize=10pt \
  -V colorlinks=true -V linkcolor=blue -V urlcolor=blue
tectonic paper.tex --keep-logs >build.stdout.log 2>tectonic.log || { tail -30 tectonic.log; exit 1; }
printf '%s/paper.pdf\n' "$PWD"
