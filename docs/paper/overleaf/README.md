# Overleaf project

- Compiler: pdfLaTeX or XeLaTeX both work: `main.tex` is pure ASCII (minus signs as `\ensuremath{-}`, ellipses as `\ldots{}`, middle dots as `\textperiodcentered{}`). Keep it ASCII when editing under pdfLaTeX, or switch to XeLaTeX (Menu → Compiler) to type Unicode directly.
- `main.tex` is generated from `../v0.7/draft.md` by `python3 make_overleaf.py v0.7` with automatic section numbering. Body text references such as
  "Section 10" or "Appendix B.1" are typed by hand; update them if you reorder sections.
- Numbers, tables and figures are checked against `../v0.5-support/verify.json`; figures come from
  `../v0.7-support/make_figures.py`.
