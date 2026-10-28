#!/usr/bin/env python3
"""Regenerate the Overleaf project from a draft version: python3 make_overleaf.py v0.7

Abstract -> metadata, hand-typed heading numbers removed (LaTeX numbers sections), \\appendix before the first
appendix, figures copied, and main.tex made pure ASCII so pdfLaTeX and XeLaTeX both compile it. Writes main.tex,
figures/ and ../kage-paper-overleaf.zip.
"""
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
version = sys.argv[1] if len(sys.argv) > 1 else 'v0.7'
src = (HERE.parent / version / 'draft.md').read_text()

front, body = re.match(r'(---\n.*?\n---\n)(.*)', src, re.S).groups()
abstract = re.search(r'## Abstract\n\n(.*?)\n\n(?=## )', body, re.S).group(1)
body = body.replace(f'## Abstract\n\n{abstract}\n\n', '', 1)
front = front.replace('\n---\n', '\nabstract: |\n  ' + abstract.replace('\n', '\n  ') + '\n---\n', 1)
first_appendix = True


def heading(m):
    global first_appendix
    hashes, title = m.group(1), m.group(2)
    appendix = re.match(r'Appendix [A-Z]\. (.*)', title)
    if appendix:
        prefix = '\\appendix\n\n' if first_appendix else ''
        first_appendix = False
        return f'{prefix}{hashes} {appendix.group(1)}'
    return f'{hashes} ' + re.sub(r'^(?:[A-Z]\.)?\d+(?:\.\d+)*\.? ', '', title)


body = re.sub(r'^(#{2,4}) (.*)$', heading, body, flags=re.M)
md = HERE / 'main.md'
md.write_text(front + body)
subprocess.run(['pandoc', str(md), '-s', '-o', str(HERE / 'main.tex'), '--number-sections',
                '--shift-heading-level-by=-1', '-V', 'documentclass=article', '-V', 'geometry:margin=2.0cm',
                '-V', 'fontsize=10pt', '-V', 'colorlinks=true', '-V', 'linkcolor=blue', '-V', 'urlcolor=blue'],
               check=True, cwd=HERE)
md.unlink()
tex = (HERE / 'main.tex').read_text()
tex = re.sub(r'pdfauthor=\{([^}]*)\}', lambda m: 'pdfauthor={' + m.group(1).replace(' · ', ', ') + '}', tex)
for char, ascii_ in {'−': '\\ensuremath{-}', '…': '\\ldots{}', '·': '\\textperiodcentered{}', '×': '\\ensuremath{\\times}',
                     '→': '\\ensuremath{\\rightarrow}', '≈': '\\ensuremath{\\approx}', '≥': '\\ensuremath{\\geq}',
                     '≤': '\\ensuremath{\\leq}', '–': '--', '—': '---', '’': "'", '‘': '`', '“': '``', '”': "''",
                     'é': "\\'{e}", '²': '\\textsuperscript{2}'}.items():
    tex = tex.replace(char, ascii_)
left = sorted({c for c in tex if ord(c) > 127})
if left:
    raise SystemExit(f'non-ASCII characters left in main.tex: {left}')
(HERE / 'main.tex').write_text(tex)
shutil.rmtree(HERE / 'figures', ignore_errors=True)
shutil.copytree(HERE.parent / version / 'figures', HERE / 'figures')
with zipfile.ZipFile(HERE.parent / 'kage-paper-overleaf.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for path in ['main.tex', 'latexmkrc', 'README.md', *sorted(str(p.relative_to(HERE)) for p in (HERE / 'figures').iterdir())]:
        z.write(HERE / path, path)
print('main.tex, figures/, ../kage-paper-overleaf.zip from', version)
