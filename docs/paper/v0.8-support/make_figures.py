#!/usr/bin/env python3
"""Build the v0.8 figures from raw evidence (adapted from deepseek-support/make_figures.py).

Changes: Fig. 2(b) adds the second student (Nemotron-3-Nano-4B, evidence/reports/g0-nemotron); the workflow
figure states that the ordering is a proposed procedure, not a tested result.

Reads only public repository artifacts (Kaggle archives, G0 results.jsonl).
Writes docs/paper/v0.8/figures/fig{0,1,2,3,4}*.pdf
v0.7 adds Fig. 4, the pre-registered desktop confirmation (evidence/reports/g0-confirm).
v0.8: Fig. 0 notes the three R3 training seeds; other figures unchanged.
"""
from __future__ import annotations
import collections, json, tarfile
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/paper/v0.8/figures"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8.5,
    "axes.titlesize": 9, "axes.labelsize": 8.5, "xtick.labelsize": 7.2,
    "ytick.labelsize": 7.5, "legend.fontsize": 7.2, "axes.spines.top": False,
    "axes.spines.right": False, "pdf.fonttype": 42,
})
C_BASE = "#6b7280"; C_TRAIN = "#b45309"; C_HELDOUT = "#1d4ed8"; C_ACCENT = "#0f766e"

def ck_runs(version: int, contain: str, arm: str):
    tar = tarfile.open(ROOT / f"evidence/kaggle/v{version}-results.tar.gz")
    for m in tar.getmembers():
        if m.name.endswith(f"/{arm}/checkpoints.jsonl") and contain in m.name:
            rows = [json.loads(l) for l in tar.extractfile(m).read().decode().splitlines()]
            acc = collections.defaultdict(list)
            for r in rows:
                if r["checkpoint"] == "cp0":
                    acc[r["task_id"]].append(float(r["score"] == 1))
            return {t: sum(v) / len(v) for t, v in acc.items()}
    raise KeyError((version, contain, arm))

def task_family(task_id: str) -> str:
    return task_id.rsplit("-", 1)[0].replace("stream-v1-", "")

LEARNED = ["subset_selection", "interval_merge", "log_aggregation", "csv_transform"]
HELDOUT = ["text_normalize", "config_migrate"]
NICE = {"subset_selection": "subset", "interval_merge": "interval", "log_aggregation": "log",
        "csv_transform": "csv", "text_normalize": "text-norm", "config_migrate": "config-mig"}

# ---------------------------------------------------------------- Fig. 1
base = ck_runs(26, "e1/r3/file", "A0-r1")
base2 = ck_runs(26, "e1/r3/file", "A0-r2")
base3 = ck_runs(26, "e1/r3/file", "A0-r3")
base = {t: (base[t] + base2[t] + base3[t]) / 3 for t in base}
trained = collections.defaultdict(dict)
for i in (1, 2, 3):
    r = ck_runs(26, "e1/r3/file", f"L3-r{i}")
    for t, v in r.items():
        trained[t][i] = v
trained = {t: sum(v.values()) / 3 for t, v in trained.items()}

fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.75), gridspec_kw={"width_ratios": [24, 12], "wspace": 0.20})
for ax, fams, title in [(axes[0], LEARNED, "In-family: 24 tasks (same generators)"),
                        (axes[1], HELDOUT, "Held-out: 12 tasks (different generators)")]:
    tasks = [t for f in fams for t in sorted(t for t in base if task_family(t) == f)]
    xs = list(range(len(tasks)))
    for i, t in enumerate(tasks):
        y0, y1 = base[t], trained[t]
        ax.plot([i, i], [y0, y1], color="#9ca3af", lw=0.8, zorder=1)
        ax.scatter([i], [y0], s=13, facecolors="white", edgecolors=C_BASE, linewidths=0.8, zorder=2)
        ax.scatter([i], [y1], s=15, color=C_TRAIN if fams is LEARNED else C_HELDOUT, zorder=3)
    ax.set_ylim(-0.05, 1.05); ax.set_yticks([0, .25, .5, .75, 1])
    ax.set_ylabel("success rate (3 runs)" if ax is axes[0] else "")
    ax.set_xticks(xs)
    ax.set_xticklabels([""] * len(xs))
    # family brackets and labels
    start = 0
    for f in fams:
        n = sum(1 for t in tasks if task_family(t) == f)
        ax.annotate(NICE[f], xy=((start + n / 2 - 0.5), -0.22), xycoords=("data", "axes fraction"),
                    ha="center", va="top", fontsize=7.2)
        if start:
            ax.axvline(start - 0.5, color="#e5e7eb", lw=0.6, zorder=0)
        start += n
    ax.set_title(title, pad=4)
    ax.grid(axis="y", color="#f3f4f6", lw=0.5)
axes[0].scatter([], [], s=13, facecolors="white", edgecolors=C_BASE, label="base (v26)")
axes[0].scatter([], [], s=15, color=C_TRAIN, label="R3 adapter")
fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.45, 1.02))

fig.savefig(OUT / "fig3_r3_per_task.pdf", bbox_inches="tight", pad_inches=0.03)
plt.close(fig)

# ---------------------------------------------------------------- Fig. 2
def g0_rates(arm: str):
    acc = collections.defaultdict(list)
    for line in (ROOT / f"evidence/reports/g0/{arm}/results.jsonl").read_text().splitlines():
        r = json.loads(line); acc[r["task_id"]].append(float(r["check"]["passed"]))
    return {t: sum(v) / len(v) for t, v in acc.items()}

def g0_counts(arm: str):
    rows = [json.loads(l) for l in (ROOT / f"evidence/reports/g0/{arm}/results.jsonl").read_text().splitlines()]
    return sum(int(r["check"]["passed"]) for r in rows), len(rows)

fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.45), gridspec_kw={"wspace": 0.46})
# (a) C4 browser settings, per task
v1 = ck_runs(28, "e1/c4", "V1-r1"); v1b = ck_runs(28, "e1/c4", "V1-r2"); v1c = ck_runs(28, "e1/c4", "V1-r3")
v2 = ck_runs(28, "e1/c4", "V2-r1"); v2b = ck_runs(28, "e1/c4", "V2-r2"); v2c = ck_runs(28, "e1/c4", "V2-r3")
prefs = sorted(t for t in v1 if "web_prefs" in t)
v1m = {t: (v1[t] + v1b[t] + v1c[t]) / 3 for t in prefs}
v2m = {t: (v2[t] + v2b[t] + v2c[t]) / 3 for t in prefs}
ax = axes[0]
for i, t in enumerate(prefs):
    ax.plot([i, i], [v1m[t], v2m[t]], color="#9ca3af", lw=0.8)
    ax.scatter([i], [v1m[t]], s=14, facecolors="white", edgecolors=C_BASE, linewidths=0.8)
    ax.scatter([i], [v2m[t]], s=15, color=C_ACCENT)
ax.set_ylim(-0.05, 1.05); ax.set_yticks([0, .5, 1]); ax.set_xticks(range(len(prefs)))
ax.set_xticklabels([str(i+1) for i in range(len(prefs))], fontsize=7)
ax.set_title("(a) Browser settings", pad=4)
ax.set_ylabel("success rate (3 runs)")
ax.scatter([], [], s=14, facecolors="white", edgecolors=C_BASE, label="implicit")
ax.scatter([], [], s=15, color=C_ACCENT, label="explicit")
ax.legend(frameon=False, loc="upper left", fontsize=6.6)
# (b) TextEdit tool ladder
ax = axes[1]
labels = ["fill", "+replace\n/append", "line\nlists"]
vals, tots = [], []
for arm in ("a0-baseline-v1", "a0-te-v3", "a0-te-v4"):
    rows = [json.loads(l) for l in (ROOT / f"evidence/reports/g0/{arm}/results.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["family"] == "textedit"]
    if arm == "a0-baseline-v1":
        extra = [json.loads(l) for l in (ROOT / "evidence/reports/g0/a0-test-v2/results.jsonl").read_text().splitlines()]
        extra = [r for r in extra if r["family"] == "textedit"]
        rows = rows + extra
    vals.append(sum(int(r["check"]["passed"]) for r in rows)); tots.append(len(rows))
bars = ax.bar(range(3), [v / t for v, t in zip(vals, tots)], color=["#d1d5db", "#f59e0b", C_TRAIN], width=0.62)
for i, (v, t) in enumerate(zip(vals, tots)):
    ax.text(i - 0.12, v / t + 0.03, f"{v}/{t}", ha="center", fontsize=7.0)
# second student: whole-text fill (v2 training + variant runs) and line lists (v4), same six tasks
NEMO = ROOT / "evidence/reports/g0-nemotron"
def nemo_te(arms):
    rows = [json.loads(l) for a in arms for l in (NEMO / a / "results.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["family"] == "textedit" and not r.get("error")]
    return sum(int(bool(r["check"]["passed"])) for r in rows), len(rows)
for i, arms in ((0, ("a0-train-v2", "a0-test-v2")), (2, ("a0-te-v4",))):
    v, t = nemo_te(arms)
    ax.scatter([i + 0.2], [v / t], marker="D", s=22, facecolors="white", edgecolors="#111827", linewidths=0.9, zorder=4)
    ax.text(i + 0.36, v / t + 0.03, f"{v}/{t}", ha="left", fontsize=6.6, color="#111827")
ax.scatter([], [], marker="D", s=22, facecolors="white", edgecolors="#111827", label="2nd student")
ax.legend(frameon=False, loc="upper left", fontsize=6.4)
ax.set_ylim(0, 1.1); ax.set_xticks(range(3)); ax.set_xticklabels(labels)
ax.set_title("(b) TextEdit tools", pad=4)
# (c) G0 lesson presentation
ax = axes[2]
conds = [("none", "a0-test-v2"), ("system", "a0-test-v2-lessons"), ("plan\nonly", "a0-test-v2-planonly"),
         ("beside\n+plan", "a0-test-v2-plan")]
vals = [g0_counts(a)[0] for _, a in conds]; tot = g0_counts(conds[0][1])[1]
cols = ["#d1d5db", "#d1d5db", "#fbbf24", C_TRAIN]
ax.bar(range(4), [v / tot for v in vals], color=cols, width=0.62)
for i, v in enumerate(vals):
    ax.text(i, v / tot + 0.02, f"{v}/{tot}", ha="center", fontsize=7.2)
ax.set_ylim(0, 0.85); ax.set_xticks(range(4)); ax.set_xticklabels([c for c, _ in conds])
ax.set_title("(c) Lesson presentation", pad=4)
fig.savefig(OUT / "fig2_interventions.pdf", bbox_inches="tight", pad_inches=0.03)
plt.close(fig)

# ---------------------------------------------------------------- Fig. 3
fig, ax = plt.subplots(figsize=(7.0, 1.9)); ax.axis("off")
steps = [
    ("1. Interface", "observation fields\n& action representation", "settings 1→14/18\nTextEdit 4→17/18 (2nd 0→16)\nnew tasks 3→18 (2nd 2→17)"),
    ("2. Presentation", "where guidance appears\n& whether it is applied", "new Calculator tasks:\nsystem 6/30, beside 19/30\nbeside + plan 23/30"),
    ("3. Retention", "acquisition vs loss\nacross task families", "in-family 30/72→64/72\nheld-out 15/36→1/36"),
    ("4. Capability", "attributed last", "proposed order;\nnot itself tested"),
]
xs = [0.02, 0.27, 0.52, 0.77]; w, h = 0.21, 0.62
colors = ["#ecfdf5", "#fef3c7", "#fee2e2", "#eef2ff"]
edges = ["#059669", "#d97706", "#dc2626", "#4f46e5"]
for (title, mid, ev), x, fc, ec in zip(steps, xs, colors, edges):
    box = FancyBboxPatch((x, 0.17), w, h, boxstyle="round,pad=0.012,rounding_size=0.02",
                         facecolor=fc, edgecolor=ec, linewidth=1.0)
    ax.add_patch(box)
    ax.text(x + w / 2, 0.69, title, ha="center", va="center", fontsize=8.4, fontweight="bold", color=ec)
    ax.text(x + w / 2, 0.48, mid, ha="center", va="center", fontsize=6.8)
    ax.text(x + w / 2, 0.28, ev, ha="center", va="center", fontsize=6.0, color="#374151")
for x in xs[:-1]:
    ax.add_patch(FancyArrowPatch((x + w + 0.006, 0.48), (x + 0.25 - 0.006, 0.48),
                                 arrowstyle="-|>", mutation_scale=9, lw=1.0, color="#6b7280"))
ax.set_xlim(0, 1); ax.set_ylim(0, 1)
fig.savefig(OUT / "fig1_diagnostic_order.pdf", bbox_inches="tight")
plt.close(fig)

# ---------------------------------------------------------------- Fig. 4: pre-registered confirmation
CONF = ROOT / "evidence/reports/g0-confirm"
def conf_rows(raw, arm):
    return [json.loads(l) for l in (CONF / raw / arm / "results.jsonl").read_text().splitlines()]
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.2), gridspec_kw={"width_ratios": [2.3, 1]})
arms = [("calc-none", "none"), ("calc-system", "system\nprompt"), ("calc-planonly", "plan\nonly"),
        ("calc-adjacent", "beside\ntask"), ("calc-plan", "beside task\n+ plan")]
ax = axes[0]
for i, (arm, label) in enumerate(arms):
    rows = conf_rows("raw", arm)
    g = sum(r["check"].get("passed", False) for r in rows if r.get("kind") == "grouping") / 30
    c = sum(r["check"].get("passed", False) for r in rows if r.get("kind") == "precedence_control") / 6
    ax.bar(i - 0.18, g, 0.36, color=C_ACCENT, label="grouping (10 tasks)" if i == 0 else None)
    ax.bar(i + 0.18, c, 0.36, color="#d1d5db", edgecolor=C_BASE, label="precedence control (2 tasks)" if i == 0 else None)
    ax.text(i - 0.18, g + 0.02, f"{round(g*30)}/30", ha="center", fontsize=6.6)
    ax.text(i + 0.18, c + 0.02, f"{round(c*6)}/6", ha="center", fontsize=6.6)
ax.set_xticks(range(len(arms))); ax.set_xticklabels([a[1] for a in arms])
ax.set_ylim(0, 1.12); ax.set_ylabel("success rate")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), ncol=2, frameon=False)
ax.set_title("(a) Calculator: where the rules appear (primary student)")
ax = axes[1]
for j, (raw, name) in enumerate((("raw", "primary"), ("raw-nemotron", "second"))):
    for k, (arm, col) in enumerate((("te-v2", "#d1d5db"), ("te-v4", C_ACCENT))):
        v = sum(r["check"].get("passed", False) for r in conf_rows(raw, arm)) / 18
        ax.bar(j + (k - 0.5) * 0.36, v, 0.36, color=col, edgecolor=C_BASE if k == 0 else col,
               label=("whole-text fill (v2)", "line tools (v4)")[k] if j == 0 else None)
        ax.text(j + (k - 0.5) * 0.36, v + 0.02, f"{round(v*18)}/18", ha="center", fontsize=6.6)
ax.set_xticks([0, 1]); ax.set_xticklabels(["primary", "second student"]); ax.set_ylim(0, 1.12)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=1, frameon=False); ax.set_title("(b) TextEdit, six new tasks")
fig.tight_layout()
fig.savefig(OUT / "fig4_confirmation.pdf", bbox_inches="tight", pad_inches=0.03)
plt.close(fig)
print("wrote", sorted(p.name for p in OUT.glob("*.pdf")))

# ---------------------------------------------------------------- System overview (v0.6)
fig, ax = plt.subplots(figsize=(7.0, 2.9)); ax.axis("off"); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
def box(x, y, w, h, title, body, fc, ec):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,rounding_size=0.015",
                                facecolor=fc, edgecolor=ec, linewidth=0.9))
    ax.text(x + w / 2, y + h - 0.055, title, ha="center", va="top", fontsize=7.6, fontweight="bold", color=ec)
    ax.text(x + w / 2, y + h / 2 - 0.045, body, ha="center", va="center", fontsize=6.3, color="#1f2937")
def arrow(a, b, text="", dy=0.0, style="-|>", color="#6b7280", ls="-"):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle=style, mutation_scale=8, lw=0.9, color=color, linestyle=ls))
    if text:
        ax.text((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy, text, ha="center", va="center", fontsize=5.9, color="#374151")
box(0.01, 0.56, 0.20, 0.36, "Student (4B)", "Agents-A1-4B, Q4_K_M\nllama.cpp, local\n(second student:\nNemotron-3-Nano-4B)", "#ecfdf5", "#059669")
box(0.29, 0.56, 0.20, 0.36, "Interface", "observation format\n(e.g. checkbox state)\naction tools\n(e.g. line lists)", "#fef3c7", "#d97706")
box(0.57, 0.56, 0.20, 0.36, "Environment", "file workspace\nlocal browser fixtures\nmacOS apps via\nAccessibility API", "#f3f4f6", "#4b5563")
box(0.81, 0.56, 0.18, 0.36, "Checker", "programmatic,\noutside the\nstudent prompt", "#eef2ff", "#4f46e5")
box(0.29, 0.05, 0.20, 0.36, "Teacher (cloud)", "demonstrations,\nrules from failures\nUS$4 ledger", "#fee2e2", "#dc2626")
box(0.01, 0.05, 0.20, 0.36, "Guidance", "memory / skills\n(TF-IDF gate),\nrules in system prompt\nor beside the task", "#fff7ed", "#c2410c")
box(0.57, 0.05, 0.42, 0.36, "Consolidation (R2 → R3)", "guided re-execution → verified rollouts\n→ guidance removed → action-level examples\n→ LoRA (rank 16, three seeds for R3)\n→ evaluated without guidance", "#fdf2f8", "#be185d")
arrow((0.21, 0.74), (0.29, 0.74), "actions")
arrow((0.49, 0.74), (0.57, 0.74), "")
arrow((0.77, 0.74), (0.81, 0.74), "")
arrow((0.90, 0.56), (0.47, 0.41), "", color="#4f46e5", ls="--")
ax.text(0.915, 0.475, "pass / fail\n(G0 teacher: expected\nvs found)", ha="left", va="center", fontsize=5.9, color="#4f46e5")
arrow((0.29, 0.23), (0.21, 0.23), "")
arrow((0.11, 0.41), (0.11, 0.56), "")
arrow((0.49, 0.23), (0.57, 0.23), "guided runs", dy=0.04)
arrow((0.62, 0.41), (0.18, 0.56), "adapter", dy=0.03, color="#be185d", ls="--")
fig.savefig(OUT / "fig0_system.pdf", bbox_inches="tight", pad_inches=0.02)
plt.close(fig)
print('wrote fig0_system.pdf')
