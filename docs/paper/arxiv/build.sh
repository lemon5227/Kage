#!/bin/bash
# draft.md -> paper.tex (pandoc) -> paper.pdf (tectonic). The .tex is what an arXiv submission uploads.
set -e
cd "$(dirname "$0")"
pandoc ../draft.md -s -o paper.tex --pdf-engine=tectonic \
  -V documentclass=article -V geometry:margin=2.2cm -V fontsize=10pt -V mainfont="Times New Roman" \
  -V CJKmainfont="Songti SC" -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
  --metadata title="Interface First, Then Teach, Then Consolidate: Self-Evolution of a 4B Local Computer-Use Agent on a Four-Dollar Teacher Budget" \
  --metadata author="Wenbo Yan" --metadata date="October 2026"
# pandoc puts the markdown H1 inside the body as well; drop it (the title block already has it).
python3 - <<'PY'
import re
s = open('paper.tex').read()
s = re.sub(r'\\section\{Interface First, Then Teach.*?\}\\label\{[^}]*\}\n', '', s, count=1, flags=re.S)
open('paper.tex', 'w').write(s)
PY
tectonic paper.tex >/dev/null 2>tectonic.log || (tail -20 tectonic.log; exit 1)
echo "$(pwd)/paper.pdf"
