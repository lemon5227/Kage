#!/usr/bin/env python3
"""Independent offline audit of the Kage paper (v0.4 draft) and of the prior
review's factual claims.

Written from scratch for the 2026-10-27 verification round. Reads only public
repository evidence (JSON / JSONL / gzipped JSONL / tar.gz members in memory),
performs no network, model, teacher, GPU or git operation, and writes
``audit.json`` next to this file.

Usage:
    python3 docs/paper/deepseek-support/audit.py

Every recomputed value carries the repository path it came from; see the
``evidence`` keys of audit.json. The companion report
``docs/paper/deepseek-audit-2026-10-27.md`` explains each row.
"""
from __future__ import annotations

import collections
import datetime
import gzip
import hashlib
import io
import itertools
import json
import math
import random
import re
import statistics
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
AUDIT = OUT / "audit.json"

# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------
FALSE_VALUES = (False, 0, "0", "false", "False", "")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def read_jsonl(rel: str):
    with (ROOT / rel).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def read_jsonl_gz(rel: str):
    with gzip.open(ROOT / rel, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def tar_member_jsonl(tar_path: Path, member: str):
    with tarfile.open(tar_path) as archive:
        handle = archive.extractfile(member)
        if handle is None:  # directory or link
            raise KeyError(member)
        return [json.loads(line) for line in io.TextIOWrapper(handle, "utf-8") if line.strip()]


def tar_member_json(tar_path: Path, member: str):
    with tarfile.open(tar_path) as archive:
        handle = archive.extractfile(member)
        if handle is None:
            raise KeyError(member)
        return json.load(io.TextIOWrapper(handle, "utf-8"))


def tar_jsonl_members(tar_path: Path, suffix: str):
    """Map member name -> parsed rows for every member ending with ``suffix``."""
    out = {}
    with tarfile.open(tar_path) as archive:
        for member in archive.getmembers():
            if member.name.endswith(suffix):
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                out[member.name] = [
                    json.loads(line)
                    for line in io.TextIOWrapper(handle, "utf-8")
                    if line.strip()
                ]
    return out


def passed(record) -> int:
    """Success flag of one checkpoint record (score==1 or check.passed)."""
    if "score" in record:
        return int(record["score"] == 1)
    check = record.get("check") or {}
    return int(bool(check.get("passed")))


# --------------------------------------------------------------------------
# Statistics: exact task-level sign-flip (DP) and task bootstrap
# --------------------------------------------------------------------------
def exact_sign_flip(pairs_units):
    """Exact two-sided task-level sign-flip p for paired differences.

    ``pairs_units`` are integer-valued paired differences (already scaled by the
    common denominator, e.g. 3 repeats -> values in {-3..3}).  Tied (zero)
    differences carry no sign information and are dropped before enumeration,
    which is the standard exact sign-flip convention.
    """
    nz = [int(v) for v in pairs_units if v != 0]
    k = len(nz)
    if k == 0:
        return 1.0, 0
    observed = abs(sum(nz))
    dist = {0: 1}
    for value in nz:
        nxt = {}
        for total, count in dist.items():
            nxt[total + value] = nxt.get(total + value, 0) + count
            nxt[total - value] = nxt.get(total - value, 0) + count
        dist = nxt
    total = 2 ** k
    hits = sum(count for total_sum, count in dist.items() if abs(total_sum) >= observed)
    return hits / total, k


def bootstrap_paired_ci(diffs, resamples=20000, seed=20261027):
    """95% percentile CI of the mean paired task-level difference."""
    n = len(diffs)
    if n == 0:
        return [None, None]
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        means.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int(0.025 * resamples)]
    hi = means[int(0.975 * resamples) - 1]
    return [lo, hi]


def fisher_exact_two_sided(a, b, c, d):
    """Two-sided Fisher exact p for table [[a,b],[c,d]] (execution-level, for contrast)."""
    n1, n2 = a + b, c + d
    total = n1 + n2
    row1 = a + c
    denom = math.comb(total, n1)
    p_obs = math.comb(row1, a) * math.comb(total - row1, n1 - a) / denom
    p = 0.0
    lo = max(0, n1 - (total - row1))
    hi = min(n1, row1)
    for x in range(lo, hi + 1):
        px = math.comb(row1, x) * math.comb(total - row1, n1 - x) / denom
        if px <= p_obs + 1e-12:
            p += px
    return min(1.0, p)


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


# --------------------------------------------------------------------------
# Domain constants (taken from the frozen manifests, not from the reports)
# --------------------------------------------------------------------------
LEARNED_FILE = ("subset_selection", "interval_merge", "log_aggregation", "csv_transform")
HELD_FILE = ("text_normalize", "config_migrate")
WEB_LEARNED = ("web_invoice", "web_prefs", "web_catalog")
WEB_HELD = ("web_form",)
WEB_NEG = ("web_lookup",)

EVAL_STREAM = "eval/stream_v1/eval.json"
EVAL_WEB = "eval/stream_web_v1/eval.json"
DESKTOP = "eval/desktop_v1/tasks.json"

result = collections.OrderedDict()
result["meta"] = {
    "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "script": "docs/paper/deepseek-support/audit.py",
    "workspace": str(ROOT),
    "notes": "independent recomputation; v0.4-support/recompute.py not imported or trusted",
}
inputs = [
    EVAL_STREAM,
    EVAL_WEB,
    DESKTOP,
    "evidence/reports/r2/sft-v21.jsonl.gz",
    "evidence/reports/r2/sft-v21-control.jsonl.gz",
    "evidence/reports/r2/file-a-stats.json",
    "evidence/reports/r2/file-b-stats.json",
    "evidence/reports/r2/browser-forms-stats.json",
    "evidence/reports/r2/browser-catalog-stats.json",
    "evidence/reports/r2/control-stats.json",
    "evidence/reports/r3/train-config.json",
    "evidence/reports/r3b/train-config.json",
    "evidence/reports/r3c/train-config.json",
    "evidence/reports/r3d/train-config.json",
    "evidence/reports/r3e/train-config.json",
    "evidence/reports/r3b/data-stats.json",
    "evidence/reports/r3c/data-stats.json",
    "evidence/reports/r3d/data-stats.json",
    "evidence/reports/r3e/data-stats.json",
    "evidence/reports/r3b/replay-stats.json",
    "evidence/reports/r3c/replay-stats.json",
    "evidence/reports/r3e/replay-stats.json",
    "evidence/reports/d7/heldout.json",
    "evidence/reports/d7/v2-heldout2.json",
    "docs/paper/v0.4-support/SHA256SUMS",
    "evidence/SHA256SUMS",
]
result["meta"]["inputs_sha256"] = {
    rel: sha256_file(ROOT / rel) for rel in inputs if (ROOT / rel).exists()
}

# ==========================================================================
# 1. Frozen manifests: what the denominators should be
# ==========================================================================
manifest = {}
for key, rel in (("stream", EVAL_STREAM), ("web", EVAL_WEB), ("desktop", DESKTOP)):
    data = read_json(rel)
    tasks = data["tasks"] if isinstance(data, dict) else data
    fam = collections.Counter(t["family"] for t in tasks)
    manifest[key] = {
        "path": rel,
        "tasks": len(tasks),
        "sha256_field": data.get("sha256") if isinstance(data, dict) else None,
        "families": dict(sorted(fam.items())),
        "task_ids": [t["task_id"] for t in tasks],
    }
    if key == "desktop":
        manifest[key]["max_steps"] = [t["max_steps"] for t in tasks]
        manifest[key]["splits"] = dict(collections.Counter(t.get("split") for t in tasks))
manifest["stream"]["learned_file_tasks"] = sum(
    n for f, n in manifest["stream"]["families"].items() if f in LEARNED_FILE)
manifest["stream"]["heldout_file_tasks"] = sum(
    n for f, n in manifest["stream"]["families"].items() if f in HELD_FILE)
manifest["web"]["learned_tasks"] = sum(
    n for f, n in manifest["web"]["families"].items() if f in WEB_LEARNED)
manifest["desktop"]["max_steps_range"] = [
    min(manifest["desktop"]["max_steps"]), max(manifest["desktop"]["max_steps"])]
result["manifests"] = manifest

# ==========================================================================
# 2. R2 training archive (units, provenance, eval overlap)
# ==========================================================================
r2_rows = read_jsonl_gz("evidence/reports/r2/sft-v21.jsonl.gz")
r2_control = read_jsonl_gz("evidence/reports/r2/sft-v21-control.jsonl.gz")
r2_families = collections.Counter(r.get("family") for r in r2_rows)


def target_tool(row):
    tcs = (row.get("target") or {}).get("tool_calls") or []
    return tcs[0]["function"]["name"] if tcs else None


def reasonless(row):
    """Mirror of scripts/experiments/r3_data.py:reasonless_call."""
    target = row.get("target") or {}
    return bool(target.get("tool_calls")) and not (target.get("content") or "").strip()


write_file_rows = [r for r in r2_rows if target_tool(r) == "write_file"]
write_file_reasonless = [r for r in write_file_rows if reasonless(r)]
write_file_reasoned = [r for r in write_file_rows if not reasonless(r)]
write_file_reasoned_nonneg = [r for r in write_file_reasoned if not r.get("negative")]

collection_reports = {
    name: read_json(f"evidence/reports/r2/{name}-stats.json")
    for name in ("file-a", "file-b", "browser-forms", "browser-catalog")
}
collection_totals = {
    key: sum(rep["totals"][key] for rep in collection_reports.values())
    for key in ("tasks", "attempts", "successes", "samples_kept")
}
control_stats = read_json("evidence/reports/r2/control-stats.json")["totals"]

stream_ids = set(manifest["stream"]["task_ids"])
web_ids = set(manifest["web"]["task_ids"])
r2_ids = {r["task_id"] for r in r2_rows}
control_ids = {r["task_id"] for r in r2_control}

result["r2"] = {
    "path": "evidence/reports/r2/sft-v21.jsonl.gz",
    "rows": len(r2_rows),
    "unique_task_ids": len(r2_ids),
    "unique_task_source_attempt": len(
        {(r["task_id"], str(r.get("source")), str(r.get("attempt"))) for r in r2_rows}),
    "unique_task_source": len({(r["task_id"], str(r.get("source"))) for r in r2_rows}),
    "family_rows": dict(sorted(r2_families.items())),
    "heldout_family_rows": {
        fam: r2_families.get(fam, 0) for fam in HELD_FILE
    },
    "guidance_nonempty_rows": sum(1 for r in r2_rows if r.get("guidance")),
    "collection_reports": {
        name: {
            "path": f"evidence/reports/r2/{name}-stats.json",
            "attempts": rep["totals"]["attempts"],
            "successes": rep["totals"]["successes"],
            "samples_kept": rep["totals"]["samples_kept"],
        }
        for name, rep in collection_reports.items()
    },
    "collection_totals_four_reports": collection_totals,
    "control": {
        "path": "evidence/reports/r2/sft-v21-control.jsonl.gz",
        "rows": len(r2_control),
        "unique_tasks": len(control_ids),
        "stats_totals": control_stats,
    },
    "write_file": {
        "rows_total": len(write_file_rows),
        "reasonless": len(write_file_reasonless),
        "reasoned_total": len(write_file_reasoned),
        "reasoned_non_negative_family": len(write_file_reasoned_nonneg),
        "by_family_reasoned": dict(collections.Counter(
            r["family"] for r in write_file_reasoned)),
        "by_family_reasonless": dict(collections.Counter(
            r["family"] for r in write_file_reasonless)),
    },
    "target_reasonless_rows": sum(1 for r in r2_rows if reasonless(r)),
    "control_reasonless_rows": sum(1 for r in r2_control if reasonless(r)),
    "eval_overlap": {
        "stream_v1_eval_task_ids_in_r2": len(r2_ids & stream_ids),
        "stream_web_v1_eval_task_ids_in_r2": len(r2_ids & web_ids),
        "r2_tasks_also_in_control_archive": len(r2_ids & control_ids),
    },
    "r2_task_id_prefixes": dict(collections.Counter(
        re.sub(r"-\d+$", "", t) for t in r2_ids)),
}

# ==========================================================================
# 3. Kaggle checkpoint archives -> per-run, per-task outcomes
# ==========================================================================
KAGGLE = ROOT / "evidence/kaggle"


def load_arm_runs(version, prefix, checkpoints=('cp0',)):
    """{arm: {task_id: [pass flags in run order]}} from <prefix><arm>/checkpoints.jsonl."""
    tar = KAGGLE / f"v{version}-results.tar.gz"
    members = tar_jsonl_members(tar, "/checkpoints.jsonl")
    runs = collections.defaultdict(lambda: collections.defaultdict(list))
    records = {}
    for name, rows in members.items():
        if prefix not in name:
            continue
        parts = name.split("/")
        idx = parts.index("checkpoints.jsonl") if "checkpoints.jsonl" in parts else -1
        arm = parts[idx - 1]
        by_task = collections.defaultdict(list)
        for row in rows:
            if checkpoints is not None and row.get("checkpoint") not in checkpoints:
                continue
            by_task[row["task_id"]].append(passed(row))
        records[arm] = rows
        for task, flags in by_task.items():
            runs[arm][task].extend(flags)
    return runs, records


def group_totals(by_task, groups):
    """Sum passes/evaluations per named family group."""
    out = {}
    for name, families in groups.items():
        n = k = 0
        for task, flags in by_task.items():
            family = task.rsplit("-", 1)[0].replace("stream-v1-", "")
            if family not in families:
                continue
            n += len(flags)
            k += sum(flags)
        out[name] = {"passed": k, "n": n}
    return out


GROUPS_FILE = {"learned_file": LEARNED_FILE, "heldout_file": HELD_FILE}
GROUPS_WEB = {"learned_web": WEB_LEARNED, "heldout_web": WEB_HELD, "negative_web": WEB_NEG}


def task_rates(by_task, families):
    """{task_id: mean success over runs} for tasks in the requested families."""
    out = {}
    for task, flags in by_task.items():
        family = task.rsplit("-", 1)[0].replace("stream-v1-", "")
        if family in families:
            out[task] = sum(flags) / len(flags)
    return out


def per_run_totals(by_task, families):
    """Passes in each inference run, summed over the requested families."""
    tasks = [task for task in by_task
             if task.rsplit("-", 1)[0].replace("stream-v1-", "") in families]
    if not tasks:
        return []
    runs = max(len(by_task[task]) for task in tasks)
    return [sum(by_task[task][run] for task in tasks) for run in range(runs)]


def compare(name, arm_a, arm_b, families, note=""):
    """Task-level paired comparison of arm_a (rows) vs arm_b (base rows)."""
    ra, rb = task_rates(arm_a, families), task_rates(arm_b, families)
    common = sorted(set(ra) & set(rb))
    diffs = [ra[t] - rb[t] for t in common]
    # scale to integers using the per-run denominators (LCM of run counts)
    denoms = []
    for rates, arm in ((ra, arm_a), (rb, arm_b)):
        for t in common:
            denoms.append(len(arm[t]))
    denom = 1
    for d in denoms:
        denom = denom * d // math.gcd(denom, d) if d else denom
    units = [int(round(d * denom)) for d in diffs]
    p, informative = exact_sign_flip(units)
    lo, hi = bootstrap_paired_ci(diffs)
    return {
        "comparison": name,
        "note": note,
        "tasks": len(common),
        "informative_tasks": informative,
        "min_attainable_p_2_over_2_k": 2 / (2 ** len(common)) if common else None,
        "mean_paired_risk_difference": statistics.fmean(diffs) if diffs else None,
        "risk_difference_95ci_task_bootstrap": [lo, hi],
        "sign_flip_p_two_sided": p,
        "per_task_rates_a": ra,
        "per_task_rates_b": rb,
        "per_task_diff": {t: d for t, d in zip(common, diffs)},
        "totals_a": {"passed": sum(sum(arm_a[t]) for t in common),
                     "n": sum(len(arm_a[t]) for t in common)},
        "totals_b": {"passed": sum(sum(arm_b[t]) for t in common),
                     "n": sum(len(arm_b[t]) for t in common)},
    }


# ---- E-1: raw student / budget-matched retry / trajectory memory / skill library
E1 = {}
E1["A0"] = {"file": load_arm_runs(6, "e1/A0/")[0]["A0"]}
e1_v6_runs, _ = load_arm_runs(6, "e1/seed", ('cp60',))
E1["A4"] = e1_v6_runs  # seed1/A4, seed2/A4
e1_v7_runs, _ = load_arm_runs(7, "e1/seed", ('cp60',))
E1["A3"] = e1_v7_runs
e1_v5_runs, _ = load_arm_runs(5, "e1/A1/")
E1["A1"] = {"A1": e1_v5_runs["A1"]}

e1_note = "E-1 raw: A0 v6 (single eval), A1 v5 (single eval, archive marked mostly void), A3 v7 per seed, A4 v6 per seed"


def merge_arms(arms):
    """Merge {arm: {task: flags}} into one {task: flags} (streams concatenated)."""
    out = collections.defaultdict(list)
    for by_task in arms.values():
        for task, flags in by_task.items():
            out[task].extend(flags)
    return dict(out)


E1_A0 = E1["A0"]["file"]
E1_A1 = E1["A1"]["A1"]
E1_A3 = merge_arms(E1["A3"])
E1_A4 = merge_arms(E1["A4"])

result["e1"] = {
    "note": e1_note,
    "arms": {
        arm: {
            "in_family": group_totals(by_task, GROUPS_FILE)["learned_file"],
            "heldout": group_totals(by_task, GROUPS_FILE)["heldout_file"],
            "per_task": {t: f for t, f in sorted(by_task.items())
                         if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE},
        }
        for arm, by_task in (("A0", E1_A0), ("A1", E1_A1), ("A3", E1_A3), ("A4", E1_A4))
    },
    "reported_denominators": {
        "note": "e1-report doubles the 24-task in-family set to /48; A3/A4 have two real "
                "streams (2 x 24), A0/A1 are one evaluation duplicated",
        "A3_cp60": 42, "A4_cp60": 39, "A0": 14, "A1": 12,
    },
    "raw_24_task_counts": {
        "A0_single_eval": sum(E1_A0[t][0] for t in E1_A0
                              if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE),
        "A1_single_eval": sum(E1_A1[t][0] for t in E1_A1
                              if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE),
        "A3_two_streams": sum(sum(v) for t, v in E1_A3.items()
                              if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE),
        "A4_two_streams": sum(sum(v) for t, v in E1_A4.items()
                              if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE),
    },
    "later_raw_replicates_in_family_24": {},
}
# later raw A0 replicates: v6 single eval + v11 A0-r1..r3
v11_runs, _ = load_arm_runs(11, "e1/A0-r")
result["e1"]["later_raw_replicates_in_family_24"] = {
    "v6_A0": sum(E1_A0[t][0] for t in E1_A0
                 if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE),
    **{f"v11_{arm}": sum(sum(v) for t, v in by_task.items()
                        if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE)
       for arm, by_task in v11_runs.items()},
}
# task-level (cluster) comparisons on the 24 in-family tasks.  A3/A4 carry two
# independent stream evaluations per task; A0/A1 carry one evaluation that the
# e1-report duplicates to obtain /48.
result["e1"]["comparisons"] = [
    compare("A3 (trajectory memory) vs A0 (raw), in-family 24",
            E1_A3, E1_A0, set(LEARNED_FILE),
            note="A0 has one evaluation per task; /48 in the report is that set duplicated"),
    compare("A4 (skill library) vs A0 (raw), in-family 24",
            E1_A4, E1_A0, set(LEARNED_FILE),
            note="A0 has one evaluation per task; /48 in the report is that set duplicated"),
    compare("A3 vs A1 (budget-matched retry), in-family 24",
            E1_A3, E1_A1, set(LEARNED_FILE),
            note="A1 has one evaluation per task; /48 in the report is that set duplicated"),
    compare("A4 vs A1 (budget-matched retry), in-family 24",
            E1_A4, E1_A1, set(LEARNED_FILE)),
    compare("A3 vs A4 (memory vs skills), in-family 24",
            E1_A3, E1_A4, set(LEARNED_FILE)),
]

# ---- C3 invoice lessons (v17/v19), quoted in §4.1: 0/24 -> 14/24
def c3_invoice_counts(version):
    """{seed/arm: {checkpoint: invoice passes}} from v17/v19 checkpoints."""
    out = {}
    with tarfile.open(KAGGLE / f"v{version}-results.tar.gz") as archive:
        for member in archive.getmembers():
            # macOS AppleDouble members ("._checkpoints.jsonl") are binary metadata
            if not member.name.endswith("checkpoints.jsonl") or "/._" in member.name:
                continue
            parts = member.name.split("/")
            arm = parts[-2]
            seed = parts[-3] if len(parts) >= 4 else ""
            handle = archive.extractfile(member)
            rows = [json.loads(line) for line in io.TextIOWrapper(handle, "utf-8")
                    if line.strip()]
            counts = collections.Counter()
            for row in rows:
                if "web_invoice" in row["task_id"]:
                    counts[row["checkpoint"]] += int(row["score"] == 1)
            out[f"{seed}/{arm}"] = dict(counts)
    return out


c3 = {"v17": c3_invoice_counts(17), "v19": c3_invoice_counts(19)}
c3_base_runs = [v["cp0"] for k, v in c3["v17"].items() if k.endswith("/A0-r1")
                or k.endswith("/A0-r2") or k.endswith("/A0-r3")]
c3_base_runs += [v["cp0"] for k, v in c3["v19"].items() if k.endswith("/A0-r4")]
c3_lesson_runs = [v.get("cp44", 0) for k, v in c3["v19"].items()
                  if k.endswith("/AGL") or k.endswith("/A4mGL")]
result["c3_invoice"] = {
    "source": "evidence/kaggle/v{17,19}-results.tar.gz",
    "baseline_raw_student": {"runs": c3_base_runs,
                             "invoice_passed": sum(c3_base_runs),
                             "invoice_n": 6 * len(c3_base_runs)},
    "lesson_arms_cp44": {"runs": c3_lesson_runs,
                         "invoice_passed": sum(c3_lesson_runs),
                         "invoice_n": 6 * len(c3_lesson_runs)},
}

# ==========================================================================
# 4. C4 browser rounds (v28 first round, v33 second round)
# ==========================================================================
v28_runs, _ = load_arm_runs(28, "e1/c4/")
v28_arms = {arm: merge_arms({arm: by_task}) for arm, by_task in v28_runs.items()}
result["c4_round1"] = {
    "source": "evidence/kaggle/v28-results.tar.gz",
    "protocol": "eval/stream_web_v1, 30 tasks x 3 runs per arm, same session",
    "arms": {
        arm: {"groups": group_totals(by_task, GROUPS_WEB),
              "total": {"passed": sum(sum(v) for v in by_task.values()),
                        "n": sum(len(v) for v in by_task.values())},
              "per_run": {t: f for t, f in sorted(by_task.items())}}
        for arm, by_task in v28_arms.items()
    },
    "table2_recomputed": {},
}
for arm in ("V1", "V2", "V2PK", "V2PKST"):
    by_task = v28_arms[f"{arm}-r1"].copy()
    merged = collections.defaultdict(list)
    for run in (1, 2, 3):
        for task, flags in v28_arms[f"{arm}-r{run}"].items():
            merged[task].extend(flags)
    groups = group_totals(merged, GROUPS_WEB)
    total = sum(sum(v) for v in merged.values())
    settings = sum(sum(flags) for task, flags in merged.items() if "web_prefs" in task)
    result["c4_round1"]["table2_recomputed"][arm] = {
        "settings_passed_of_18": settings,
        "all_tasks_passed_of_90": total,
        "per_family": groups,
    }
result["c4_round1"]["comparisons"] = [
    compare("V1 vs V2 (settings 6 tasks)", merge_arms({a: v28_runs[f"V2-r{i}"]
                                                       for i, a in enumerate("abc", 1)}),
            merge_arms({a: v28_runs[f"V1-r{i}"] for i, a in enumerate("abc", 1)}),
            {"web_prefs"}),
    compare("V1 vs V2 (all 30 tasks)", merge_arms({a: v28_runs[f"V2-r{i}"]
                                                   for i, a in enumerate("abc", 1)}),
            merge_arms({a: v28_runs[f"V1-r{i}"] for i, a in enumerate("abc", 1)}),
            set(WEB_LEARNED) | set(WEB_HELD) | set(WEB_NEG)),
    compare("V2 vs V2PK (all 30)", merge_arms({a: v28_runs[f"V2PK-r{i}"]
                                              for i, a in enumerate("abc", 1)}),
            merge_arms({a: v28_runs[f"V2-r{i}"] for i, a in enumerate("abc", 1)}),
            set(WEB_LEARNED) | set(WEB_HELD) | set(WEB_NEG)),
    compare("V2PK vs V2PKST (all 30)", merge_arms({a: v28_runs[f"V2PKST-r{i}"]
                                                  for i, a in enumerate("abc", 1)}),
            merge_arms({a: v28_runs[f"V2PK-r{i}"] for i, a in enumerate("abc", 1)}),
            set(WEB_LEARNED) | set(WEB_HELD) | set(WEB_NEG)),
    compare("V1 vs V2PKST (settings 6)", merge_arms({a: v28_runs[f"V2PKST-r{i}"]
                                                    for i, a in enumerate("abc", 1)}),
            merge_arms({a: v28_runs[f"V1-r{i}"] for i, a in enumerate("abc", 1)}),
            {"web_prefs"}),
]

v33_runs, _ = load_arm_runs(33, "e1/c4b/")
V33_BASES = ("V2PKST", "V2PKTST", "V2PKTSTCK", "R3EV2PKTSTCK")
v33_arms = {base: merge_arms({f"{base}-r{i}": v33_runs[f"{base}-r{i}"] for i in (1, 2, 3)})
            for base in V33_BASES}
result["c4_round2"] = {
    "source": "evidence/kaggle/v33-results.tar.gz",
    "arms": {
        arm: {"groups": group_totals(by_task, GROUPS_WEB),
              "total": {"passed": sum(sum(v) for v in by_task.values()),
                        "n": sum(len(v) for v in by_task.values())},
              "per_run": {t: f for t, f in sorted(by_task.items())}}
        for arm, by_task in v33_arms.items()
    },
}
result["c4_round2"]["checker_artifacts"] = {}
checker_tar = KAGGLE / "v33-results.tar.gz"
checker_records = tar_jsonl_members(checker_tar, "/checker.jsonl")
all_checks = [row for rows in checker_records.values() for row in rows]
result["c4_round2"]["checker_artifacts"] = {
    "checker_files": len(checker_records),
    "checks": len(all_checks),
    "blocked": sum(1 for row in all_checks if row.get("blocked")),
    "nonempty_wrong": sum(1 for row in all_checks if row.get("wrong")),
}
result["c4_round2"]["comparisons"] = [
    compare("V2PKTSTCK vs V2PKST (all 30: checker arm)",
            v33_arms["V2PKTSTCK"], v33_arms["V2PKST"],
            set(WEB_LEARNED) | set(WEB_HELD) | set(WEB_NEG),
            note="both arms are 3-run aggregates in v33"),
    compare("R3EV2PKTSTCK vs V2PKTSTCK (all 30)",
            v33_arms["R3EV2PKTSTCK"], v33_arms["V2PKTSTCK"],
            set(WEB_LEARNED) | set(WEB_HELD) | set(WEB_NEG)),
    compare("R3EV2PKTSTCK vs V2PKTSTCK (invoices 6)",
            v33_arms["R3EV2PKTSTCK"], v33_arms["V2PKTSTCK"], {"web_invoice"}),
    compare("R3EV2PKTSTCK vs V2PKTSTCK (settings 6)",
            v33_arms["R3EV2PKTSTCK"], v33_arms["V2PKTSTCK"], {"web_prefs"}),
]
# raw-interface invoice pooling quoted as 0/54 in earlier drafts
result["c4_round2"]["raw_interface_invoice_pool"] = {
    arm: {"invoice_passed": sum(sum(f) for t, f in v33_arms[arm].items() if "web_invoice" in t),
          "invoice_n": sum(len(f) for t, f in v33_arms[arm].items() if "web_invoice" in t)}
    for arm in ("V2PKST", "V2PKTST", "V2PKTSTCK")
}

# ==========================================================================
# 5. G0 desktop runs
# ==========================================================================
G0 = {}
for arm_dir in sorted((ROOT / "evidence/reports/g0").iterdir()):
    results_file = arm_dir / "results.jsonl"
    if not results_file.is_file():
        continue
    by_task = collections.defaultdict(list)
    rows = read_jsonl(f"evidence/reports/g0/{arm_dir.name}/results.jsonl")
    for row in rows:
        by_task[row["task_id"]].append(passed(row))
    G0[arm_dir.name] = {
        "by_task": {task: flags for task, flags in sorted(by_task.items())},
        "rows": rows,
        "config": (read_json(f"evidence/reports/g0/{arm_dir.name}/config.json")
                   if (arm_dir / "config.json").is_file() else None),
    }

desktop_manifest = read_json(DESKTOP)["tasks"]
desktop_split = {t["task_id"]: t.get("split") for t in desktop_manifest}
desktop_family = {t["task_id"]: t["family"] for t in desktop_manifest}


def g0_matrix(arm):
    return {task: flags for task, flags in G0[arm]["by_task"].items()}


result["g0"] = {
    "source": "evidence/reports/g0/*/results.jsonl",
    "protocol": "Desktop-v1, 3 runs per task per arm, Apple M4, Accessibility API",
    "arms": {
        arm: {
            "total": {"passed": sum(sum(v) for v in arm_data["by_task"].values()),
                      "n": sum(len(v) for v in arm_data["by_task"].values())},
            "by_task": arm_data["by_task"],
            "by_split": {
                split: {"passed": sum(sum(flags) for task, flags in arm_data["by_task"].items()
                                     if desktop_split.get(task) == split),
                        "n": sum(len(flags) for task, flags in arm_data["by_task"].items()
                                 if desktop_split.get(task) == split)}
                for split in ("train", "test")
            },
            "by_family": {
                fam: {"passed": sum(sum(flags) for task, flags in arm_data["by_task"].items()
                                    if desktop_family.get(task) == fam),
                      "n": sum(len(flags) for task, flags in arm_data["by_task"].items()
                               if desktop_family.get(task) == fam)}
                for fam in ("calculator", "textedit", "settings_read")
            },
        }
        for arm, arm_data in G0.items()
    },
    "table4_recomputed": {},
    "table3_recomputed": {},
}

# Table 4: system prompt vs plan vs plan+lessons (5 test variants)
for arm in ("a0-test-v2", "a0-test-v2-lessons", "a0-test-v2-planonly", "a0-test-v2-plan"):
    by_task = G0[arm]["by_task"]
    calc = sum(sum(flags) for task, flags in by_task.items() if desktop_family[task] == "calculator")
    te = sum(sum(flags) for task, flags in by_task.items() if desktop_family[task] == "textedit")
    result["g0"]["table4_recomputed"][arm] = {
        "calculator_of_6": calc, "textedit_of_9": te,
        "total_of_15": calc + te,
    }

# Table 3: TextEdit interfaces (v2 composite = baseline-v1 train tasks + test-v2 test tasks)
te_train = [t for t, s in desktop_split.items() if s == "train" and desktop_family[t] == "textedit"]
te_test = [t for t, s in desktop_split.items() if s == "test" and desktop_family[t] == "textedit"]


def column_sums(arm, tasks):
    col = {"typo": 0, "append": 0, "write": 0}
    for task in tasks:
        if "fix" in task:
            col["typo"] += sum(G0[arm]["by_task"][task])
        elif "append" in task:
            col["append"] += sum(G0[arm]["by_task"][task])
        elif "write" in task:
            col["write"] += sum(G0[arm]["by_task"][task])
    return col


v2_composite = {task: G0["a0-baseline-v1"]["by_task"][task] for task in te_train}
v2_composite.update({task: G0["a0-test-v2"]["by_task"][task] for task in te_test})
composite_cols = {"typo": 0, "append": 0, "write": 0}
for task, flags in v2_composite.items():
    if "fix" in task:
        composite_cols["typo"] += sum(flags)
    elif "append" in task:
        composite_cols["append"] += sum(flags)
    elif "write" in task:
        composite_cols["write"] += sum(flags)

result["g0"]["table3_recomputed"]["v2_whole_text_fill"] = {
    "columns": composite_cols, "total_of_18": sum(composite_cols.values()),
    "source": "a0-baseline-v1 (3 train TextEdit tasks) + a0-test-v2 (3 held-out TextEdit tasks)",
}
for arm in ("a0-te-v3", "a0-te-v4"):
    cols = column_sums(arm, sorted(G0[arm]["by_task"]))
    result["g0"]["table3_recomputed"][arm] = {
        "columns": cols, "total_of_18": sum(cols.values())}

# final configuration
final = G0["a0-final-v4-plan"]["by_task"]
result["g0"]["final_config"] = {
    "total": {"passed": sum(sum(v) for v in final.values()),
              "n": sum(len(v) for v in final.values())},
    "train_10_tasks": {"passed": sum(sum(flags) for task, flags in final.items()
                                     if desktop_split[task] == "train"),
                       "n": sum(len(flags) for task, flags in final.items()
                                if desktop_split[task] == "train")},
    "test_5_tasks": {"passed": sum(sum(flags) for task, flags in final.items()
                                   if desktop_split[task] == "test"),
                     "n": sum(len(flags) for task, flags in final.items()
                              if desktop_split[task] == "test")},
    "family_totals": {
        fam: {"passed": sum(sum(flags) for task, flags in final.items()
                            if desktop_family[task] == fam),
              "n": sum(len(flags) for task, flags in final.items()
                       if desktop_family[task] == fam)}
        for fam in ("calculator", "textedit", "settings_read")
    },
    "baseline_train_arm": "a0-baseline-v1",
    "baseline_train": {"passed": sum(sum(v) for v in G0["a0-baseline-v1"]["by_task"].values()),
                       "n": sum(len(v) for v in G0["a0-baseline-v1"]["by_task"].values())},
    "baseline_test_arm": "a0-test-v2",
    "baseline_test": {"passed": sum(sum(v) for v in G0["a0-test-v2"]["by_task"].values()),
                      "n": sum(len(v) for v in G0["a0-test-v2"]["by_task"].values())},
}
# combined baseline over the 15 tasks the final arm evaluates
combined_base = {}
for task, flags in G0["a0-baseline-v1"]["by_task"].items():
    combined_base[task] = flags
for task, flags in G0["a0-test-v2"]["by_task"].items():
    combined_base[task] = flags
result["g0"]["comparisons"] = [
    compare("plan vs no-lessons (5 test variants)", G0["a0-test-v2-plan"]["by_task"],
            G0["a0-test-v2"]["by_task"], set(desktop_family)),
    compare("lessons-system vs no-lessons (5)", G0["a0-test-v2-lessons"]["by_task"],
            G0["a0-test-v2"]["by_task"], set(desktop_family)),
    compare("planonly vs no-lessons (5)", G0["a0-test-v2-planonly"]["by_task"],
            G0["a0-test-v2"]["by_task"], set(desktop_family)),
    compare("plan vs planonly (5)", G0["a0-test-v2-plan"]["by_task"],
            G0["a0-test-v2-planonly"]["by_task"], set(desktop_family)),
    compare("TextEdit v4 line tools vs whole-text fill (6 tasks, composite)",
            G0["a0-te-v4"]["by_task"], v2_composite, set(desktop_family),
            note="fill row of Table 3 combines a0-baseline-v1 train tasks and "
                 "a0-test-v2 held-out TextEdit tasks"),
    compare("final vs earlier baselines (15 tasks)", final, combined_base,
            set(desktop_family)),
]
# final configuration vs the earlier baselines, split into the 10 training tasks
# and the 5 held-out-style variants (the v0.3 p=0.003 claims were execution-level)
final_train = {t: f for t, f in final.items() if desktop_split.get(t) == "train"}
base_train = {t: f for t, f in combined_base.items() if desktop_split.get(t) == "train"}
final_test = {t: f for t, f in final.items() if desktop_split.get(t) == "test"}
base_test = {t: f for t, f in combined_base.items() if desktop_split.get(t) == "test"}
result["g0"]["split_comparisons"] = [
    compare("final vs earlier baseline, 10 training tasks", final_train, base_train,
            set(desktop_family)),
    compare("final vs earlier baseline, 5 test variants", final_test, base_test,
            set(desktop_family)),
]
# execution-level Fisher values quoted by v0.3 / the prior review
result["g0"]["execution_level_fisher_for_contrast"] = {
    "plan_10_15_vs_none_3_15": fisher_exact_two_sided(10, 5, 3, 12),
    "final_41_45_vs_baseline_22_45": fisher_exact_two_sided(41, 4, 22, 23),
    "te_v4_17_18_vs_v2_4_18": fisher_exact_two_sided(17, 1, 4, 14),
}
# teacher-visible checker / lessons / temperature facts
result["g0"]["teacher_logs"] = {}
for arm in ("a0-baseline-v1", "demo"):
    path = f"evidence/reports/g0/{arm}/teach-log.json"
    if not (ROOT / path).is_file():
        continue
    log = read_json(path)
    entries = log.get("entries", [])
    result["g0"]["teacher_logs"][arm] = {
        "entries": len(entries),
        "entries_with_checker_expected_found": sum(
            1 for e in entries if "Checker: expected" in (e.get("prompt") or "")),
        "families": dict(collections.Counter(e.get("family") for e in entries)),
        "spent_usd": log.get("spent_usd"),
    }
lessons = read_json("evidence/reports/g0/a0-baseline-v1/lessons.json")
result["g0"]["lessons"] = {
    "calculator": len(lessons.get("calculator", [])),
    "textedit": len(lessons.get("textedit", [])),
    "texts": lessons,
}
# sampling temperature evidence: run configs do not log it; code defaults do
temp_evidence = {}
for rel, needle in (
    ("core/model_provider.py", "temperature: float = 0.7"),
    ("core/evolution/agent_provider.py", "temperature: float = 0.7"),
    ("core/computer_use/desktop_agent.py", "temperature=0.7"),
    ("scripts/experiments/kaggle_e1.py", "temperature 0.7"),
):
    path = ROOT / rel
    temp_evidence[rel] = bool(path.is_file() and needle in path.read_text(encoding="utf-8", errors="replace"))
result["g0"]["temperature_0_7_evidence"] = temp_evidence
# the archived run configs do not record sampling temperature
sample_v26 = tar_member_json(KAGGLE / "v26-results.tar.gz", "e1/r3/file/A0-r1/config.json")
result["g0"]["run_config_has_temperature_field"] = "temperature" in json.dumps(sample_v26)

# ==========================================================================
# 6. R3 series (v26 / v29-v32) consolidation and retention
# ==========================================================================
VARIANT_SPEC = collections.OrderedDict([
    ("R3", {"version": 26, "prefix": "e1/r3/file/", "web_prefix": "e1/r3/web/",
            "arm": "L3", "base_prefix": "e1/r3/file/", "base_web_prefix": "e1/r3/web/",
            "base_arm": "A0"}),
    ("R3b", {"version": 29, "prefix": "e1/ae/file/", "web_prefix": "e1/ae/web/",
             "arm": "r3b", "base_prefix": "e1/ae/file/", "base_web_prefix": "e1/ae/web/",
             "base_arm": "A0"}),
    ("R3c", {"version": 30, "prefix": "e1/ae/file/", "web_prefix": "e1/ae/web/",
             "arm": "r3c", "base_prefix": "e1/ae/file/", "base_web_prefix": "e1/ae/web/",
             "base_arm": "A0"}),
    ("R3d", {"version": 31, "prefix": "e1/ae/file/", "web_prefix": "e1/ae/web/",
             "arm": "r3d", "base_prefix": "e1/ae/file/", "base_web_prefix": "e1/ae/web/",
             "base_arm": "A0"}),
    ("R3e", {"version": 32, "prefix": "e1/ae/file/", "web_prefix": "e1/ae/web/",
             "arm": "r3e", "base_prefix": "e1/ae/file/", "base_web_prefix": "e1/ae/web/",
             "base_arm": "A0"}),
])

r3 = collections.OrderedDict()
r3["source"] = "evidence/kaggle/v{26,29,30,31,32}-results.tar.gz, checkpoints.jsonl (cp0 only)"
r3["protocol"] = "3 inference runs per arm; file 24 learned + 12 held-out tasks; web 18 learned + 6 held-out + 6 negative"
r3["variants"] = {}
for variant, spec in VARIANT_SPEC.items():
    file_runs, _ = load_arm_runs(spec["version"], spec["prefix"])
    web_runs, _ = load_arm_runs(spec["version"], spec["web_prefix"])
    arm_file = merge_arms({k: v for k, v in file_runs.items() if re.match(rf"^{spec['arm']}-r\d$", k)})
    arm_web = merge_arms({k: v for k, v in web_runs.items() if re.match(rf"^{spec['arm']}-r\d$", k)})
    base_file_arms = {k: v for k, v in file_runs.items()
                      if re.match(rf"^{spec['base_arm']}-r\d$", k)}
    base_web_arms = {k: v for k, v in web_runs.items()
                     if re.match(rf"^{spec['base_arm']}-r\d$", k)}
    base_file = merge_arms(base_file_arms)
    base_web = merge_arms(base_web_arms)
    # epoch-1 arms that share the eval protocol (r3be1, r3de1, ...) - not used in Table 5
    e1_arms = {k: v for k, v in file_runs.items() if re.match(rf"^{spec['arm']}e1-r\d$", k)}
    r3["variants"][variant] = {
        "version": spec["version"],
        "file_arm_runs": sorted(base_file_arms) if False else
        sorted(k for k in file_runs if re.match(rf"^{spec['arm']}-r\d$", k)),
        "base_arm_runs": sorted(base_file_arms),
        "file": {
            "learned": group_totals(arm_file, GROUPS_FILE)["learned_file"],
            "heldout": group_totals(arm_file, GROUPS_FILE)["heldout_file"],
        },
        "web": group_totals(arm_web, GROUPS_WEB),
        "base_file": {
            "learned": group_totals(base_file, GROUPS_FILE)["learned_file"],
            "heldout": group_totals(base_file, GROUPS_FILE)["heldout_file"],
        },
        "base_web": group_totals(base_web, GROUPS_WEB),
        "file_by_family": {},
        "epoch1_arms": sorted(e1_arms),
        "per_task_learned_file": {t: f for t, f in sorted(arm_file.items())
                                  if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE},
        "per_task_heldout_file": {t: f for t, f in sorted(arm_file.items())
                                  if t.rsplit("-", 1)[0].replace("stream-v1-", "") in HELD_FILE},
        "per_task_learned_web": {t: f for t, f in sorted(arm_web.items())
                                 if t.rsplit("-", 1)[0].replace("stream-v1-", "") in WEB_LEARNED},
        "per_run_totals": {
            "learned_file": per_run_totals(arm_file, set(LEARNED_FILE)),
            "heldout_file": per_run_totals(arm_file, set(HELD_FILE)),
            "learned_web": per_run_totals(arm_web, set(WEB_LEARNED)),
        },
        "base_per_run_totals": {
            "learned_file": per_run_totals(base_file, set(LEARNED_FILE)),
            "heldout_file": per_run_totals(base_file, set(HELD_FILE)),
            "learned_web": per_run_totals(base_web, set(WEB_LEARNED)),
        },
        "_arm_file": arm_file, "_arm_web": arm_web,
        "_base_file": base_file, "_base_web": base_web,
    }
    for family in LEARNED_FILE + HELD_FILE:
        n = k = 0
        for task, flags in arm_file.items():
            if task.rsplit("-", 1)[0].replace("stream-v1-", "") == family:
                n += len(flags)
                k += sum(flags)
        r3["variants"][variant]["file_by_family"][family] = {"passed": k, "n": n}

# Table 5 (learned /72, held-out /36, learned web /54)
r3["table5_recomputed"] = {}
for variant in VARIANT_SPEC:
    data = r3["variants"][variant]
    r3["table5_recomputed"][variant] = {
        "learned_file_of_72": data["file"]["learned"]["passed"],
        "heldout_file_of_36": data["file"]["heldout"]["passed"],
        "learned_web_of_54": data["web"]["learned_web"]["passed"],
    }
# Table 6 (training examples / replay / steps)
r3["table6_recomputed"] = {}
for version in ("r3", "r3b", "r3c", "r3d", "r3e"):
    config = read_json(f"evidence/reports/{version}/train-config.json")
    stats = read_json(f"evidence/reports/{version}/data-stats.json")
    replay_file = f"evidence/reports/{version}/replay-stats.json"
    replay = None
    replay_data = {}
    if (ROOT / replay_file).is_file():
        replay_data = read_json(replay_file)
        if "kept" in replay_data:
            replay = replay_data["kept"]
        elif "selected" in replay_data:
            replay = replay_data["selected"]
        else:  # random-replay generator stats keep per-source "kept" counts
            kept = [v["kept"] for v in replay_data.values()
                    if isinstance(v, dict) and "kept" in v]
            replay = sum(kept) if kept else None
    replay_rows = None
    if stats.get("replay_inputs"):
        replay_rows = sum(r.get("rows", 0) for r in stats["replay_inputs"])
    # source mixture: random-replay configs keep per-source counts directly;
    # LESS configs record by_source_selected / by_source_pool instead.
    replay_mix = {}
    if replay_data:
        for source in ("agentnet", "toucan"):
            entry = replay_data.get(source)
            if isinstance(entry, dict) and "kept" in entry:
                replay_mix[source] = {"kept": entry["kept"]}
        if "by_source_selected" in replay_data:
            replay_mix["selected"] = replay_data["by_source_selected"]
        if "by_source_pool" in replay_data:
            replay_mix["pool"] = replay_data["by_source_pool"]
    r3["table6_recomputed"][version] = {
        "train_config_examples": config.get("examples"),
        "data_stats_train_rows": stats.get("rows_out", {}).get("train"),
        "data_stats_val_rows": stats.get("rows_out", {}).get("val"),
        "skipped_too_long": config.get("skipped_too_long"),
        "examples_minus_skipped": (config.get("examples") or 0) - (config.get("skipped_too_long") or 0),
        "optimizer_steps": config.get("steps"),
        "epochs": config.get("epochs"),
        "seed": config.get("seed"),
        "learning_rate": config.get("lr"),
        "rank": config.get("rank"),
        "max_tokens": config.get("max_tokens"),
        "wall_seconds": config.get("wall_seconds"),
        "replay_rows_in_data_stats": replay_rows,
        "replay_stats_value": replay,
        "replay_by_source": replay_mix,
    }
r3["training_wall_hours"] = (
    sum(v["wall_seconds"] or 0 for v in r3["table6_recomputed"].values()) / 3600)
r3["general_check"] = {}
for version in ("r3", "r3b", "r3c", "r3d", "r3e"):
    summary = read_json(f"evidence/reports/{version}/summary.json")
    r3["general_check"][version] = summary.get("general")

# task-level comparisons
r3["comparisons"] = []
for variant in ("R3", "R3b", "R3c", "R3d", "R3e"):
    data = r3["variants"][variant]
    r3["comparisons"].append(compare(
        f"{variant} vs same-session base, learned files",
        data["_arm_file"], data["_base_file"], set(LEARNED_FILE),
        note=f"base anchor runs: {sorted(set(k for k in data['base_arm_runs']))}"))
    r3["comparisons"].append(compare(
        f"{variant} vs same-session base, held-out files",
        data["_arm_file"], data["_base_file"], set(HELD_FILE),
        note="only 12 held-out tasks; base anchor is a single run for R3b-e"))
    r3["comparisons"].append(compare(
        f"{variant} vs same-session base, learned web",
        data["_arm_web"], data["_base_web"], set(WEB_LEARNED)))
for left, right in (("R3b", "R3c"), ("R3c", "R3d"), ("R3d", "R3e"), ("R3b", "R3e"),
                    ("R3", "R3b"), ("R3", "R3e")):
    r3["comparisons"].append(compare(
        f"{left} vs {right}, learned files (cross-session)",
        r3["variants"][left]["_arm_file"], r3["variants"][right]["_arm_file"],
        set(LEARNED_FILE)))
    r3["comparisons"].append(compare(
        f"{left} vs {right}, held-out files (cross-session)",
        r3["variants"][left]["_arm_file"], r3["variants"][right]["_arm_file"],
        set(HELD_FILE)))
    r3["comparisons"].append(compare(
        f"{left} vs {right}, learned web (cross-session)",
        r3["variants"][left]["_arm_web"], r3["variants"][right]["_arm_web"],
        set(WEB_LEARNED)))

# strip private helper keys before serialisation
for variant in r3["variants"].values():
    for key in list(variant):
        if key.startswith("_"):
            del variant[key]
result["r3"] = json.loads(json.dumps(r3))  # deep copy, drop helper objects

# ==========================================================================
# 7. D7 intent routing
# ==========================================================================
d7 = {}
for name in ("heldout.json", "v2-heldout2.json", "dev.json", "v2-dev.json", "v2-dev2.json"):
    rows = read_json(f"evidence/reports/d7/{name}")
    d7[name] = {
        "rows": len(rows),
        "legacy_correct": sum(r["legacy"] == r["intent"] for r in rows),
        "clef_correct": sum(r["clef"] == r["intent"] for r in rows),
        "combined_correct": sum(r["combined"] == r["intent"] for r in rows),
        "below_threshold": sum(r["conf"] < 0.8 for r in rows),
        "calendar_rows": sum(r["intent"] == "calendar" for r in rows),
        "calendar_day_correct_clef": sum(
            r["clef_day"] == r["day"] for r in rows if r["intent"] == "calendar"),
        "calendar_day_correct_legacy": sum(
            r["legacy_day"] == r["day"] for r in rows if r["intent"] == "calendar"),
        "day_label_errors": [
            {"text": r["text"], "intent": r["intent"], "gold_day": r["day"],
             "clef_day": r["clef_day"], "legacy_day": r["legacy_day"],
             "conf": r["conf"]}
            for r in rows
            if r["intent"] == "calendar" and r["clef_day"] != r["day"]
        ],
    }
d7["date_label_error_example"] = next(
    (row for row in d7["v2-heldout2.json"]["day_label_errors"]
     if "后天下午" in row["text"]), None)
result["d7"] = d7
# intent_eval.py metric definition (quoted by the prior review)
intent_eval_src = (ROOT / "scripts/experiments/intent_eval.py").read_text(encoding="utf-8")
result["d7"]["intent_eval_metric"] = {
    "path": "scripts/experiments/intent_eval.py",
    "compares_only_intent": "sum(r[key] == r['intent'] for r in results)" in intent_eval_src,
    "below_threshold_maps_to_other": "else 'other'" in intent_eval_src
    or "if clef['confidence'] >= args.threshold else 'other'" in intent_eval_src,
    "no_matched_4b_baseline": "4b" not in intent_eval_src.lower().replace("agents-a1-4b", ""),
}

# ==========================================================================
# 8. Validity checks: checksums, configs, labels
# ==========================================================================
checksums = {}


def parse_sha_manifest(path_rel, base_rel):
    lines = (ROOT / path_rel).read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip()
        entries.append({"sha256": digest.lower(), "name": name})
    return entries


paper_entries = parse_sha_manifest("docs/paper/v0.4-support/SHA256SUMS", ".")
checksums["paper_manifest"] = []
for entry in paper_entries:
    target = ROOT / entry["name"]
    checksums["paper_manifest"].append({
        "name": entry["name"],
        "exists": target.is_file(),
        "sha256_matches": target.is_file() and sha256_file(target) == entry["sha256"],
    })
evidence_entries = parse_sha_manifest("evidence/SHA256SUMS", "evidence")
checksums["evidence_manifest"] = {
    "entries": len(evidence_entries),
    "all_match": True,
    "mismatches": [],
    "covered_latest": {},
    "missing_latest": [],
}
for entry in evidence_entries:
    target = ROOT / "evidence" / entry["name"].lstrip("./")
    ok = target.is_file() and sha256_file(target) == entry["sha256"]
    if not ok:
        checksums["evidence_manifest"]["all_match"] = False
        checksums["evidence_manifest"]["mismatches"].append(entry["name"])
names = [e["name"].lstrip("./") for e in evidence_entries]
for marker in ("kaggle/v32-results.tar.gz", "kaggle/v33-results.tar.gz",
               "reports/g0", "reports/d7", "reports/r3e", "reports/c4/round2",
               "eval/desktop_v1", "eval/intent_v1"):
    covered = any(n == marker or n.startswith(marker) for n in names)
    checksums["evidence_manifest"]["covered_latest"][marker] = covered
    if not covered:
        checksums["evidence_manifest"]["missing_latest"].append(marker)
result["checksums"] = checksums

validity = {}

# (i)/(ii) R2 vs eval manifests and held-out families -> already in result["r2"]["eval_overlap"]
validity["r2_eval_task_overlap_zero"] = (
    result["r2"]["eval_overlap"]["stream_v1_eval_task_ids_in_r2"] == 0
    and result["r2"]["eval_overlap"]["stream_web_v1_eval_task_ids_in_r2"] == 0)
validity["heldout_families_absent_from_r2"] = (
    result["r2"]["heldout_family_rows"] == {"text_normalize": 0, "config_migrate": 0})
validity["r2_r3_split_consistent"] = (
    read_json("evidence/reports/r3/data-stats.json")["rows_out"]["train"] == 1677
    and read_json("evidence/reports/r3/data-stats.json")["rows_out"]["val"] == 223)

# (iii) E-1 denominators.  e1-report prints /48 for the in-family column; the
# manifest has 24 learned-file tasks, so /48 must be 24 tasks x 2 streams for the
# learning arms and a duplicated single evaluation for the constant arms.
e1_a0_learned = {t: f for t, f in E1_A0.items()
                 if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE}
e1_a1_learned = {t: f for t, f in E1_A1.items()
                 if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE}
e1_a3_learned = {t: f for t, f in E1_A3.items()
                 if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE}
e1_a4_learned = {t: f for t, f in E1_A4.items()
                 if t.rsplit("-", 1)[0].replace("stream-v1-", "") in LEARNED_FILE}
validity["e1_denominator"] = {
    "manifest_learned_file_tasks": manifest["stream"]["learned_file_tasks"],
    "A3_A4_runs_per_task": sorted({len(f) for f in e1_a3_learned.values()}),
    "A0_A1_runs_per_task": sorted({len(f) for f in e1_a0_learned.values()}
                                  | {len(f) for f in e1_a1_learned.values()}),
    "A3_A4_have_two_real_streams": (
        len(e1_a3_learned) == 24 and len(e1_a4_learned) == 24
        and all(len(f) == 2 for f in e1_a3_learned.values())
        and all(len(f) == 2 for f in e1_a4_learned.values())),
    "A0_and_A1_are_one_evaluation_duplicated": (
        len(e1_a0_learned) == 24 and len(e1_a1_learned) == 24),
    "A0_raw": sum(f[0] for f in e1_a0_learned.values()),
    "A1_raw": sum(f[0] for f in e1_a1_learned.values()),
    "A0_reported_14_of_48": sum(f[0] for f in e1_a0_learned.values()) * 2 == 14,
    "A1_reported_12_of_48": sum(f[0] for f in e1_a1_learned.values()) * 2 == 12,
    "A3_reported_42_of_48": sum(sum(f) for f in e1_a3_learned.values()) == 42,
    "A4_reported_39_of_48": sum(sum(f) for f in e1_a4_learned.values()) == 39,
}

# (iv) D7 date-label error -> already in result["d7"]
validity["d7_date_label_error_found"] = d7["date_label_error_example"] is not None

# (v) checksum coverage
validity["checksum_coverage"] = checksums["evidence_manifest"]["covered_latest"]

# (vi) R3e train config vs analysis.md 3257
r3e_cfg = r3["table6_recomputed"]["r3e"]
validity["r3e_3251_vs_3257"] = {
    "train_config_examples": r3e_cfg["train_config_examples"],
    "data_stats_train_rows": r3e_cfg["data_stats_train_rows"],
    "skipped_too_long": r3e_cfg["skipped_too_long"],
    "difference": (r3e_cfg["data_stats_train_rows"] or 0) - (r3e_cfg["train_config_examples"] or 0),
    "explained_by_skipped_too_long": (
        (r3e_cfg["data_stats_train_rows"] or 0) - (r3e_cfg["train_config_examples"] or 0)
        == r3e_cfg["skipped_too_long"]),
    "r3b_analogous": {
        "data_stats_train_rows": r3["table6_recomputed"]["r3b"]["data_stats_train_rows"],
        "train_config_examples": r3["table6_recomputed"]["r3b"]["train_config_examples"],
        "skipped_too_long": r3["table6_recomputed"]["r3b"]["skipped_too_long"],
    },
}

# (vii) replay counts and Table 6
validity["replay_counts"] = {
    "r3b_replay_rows": r3["table6_recomputed"]["r3b"]["replay_rows_in_data_stats"],
    "r3c_replay_rows": r3["table6_recomputed"]["r3c"]["replay_rows_in_data_stats"],
    "r3d_replay_rows": r3["table6_recomputed"]["r3d"]["replay_rows_in_data_stats"],
    "r3e_replay_rows": r3["table6_recomputed"]["r3e"]["replay_rows_in_data_stats"],
    "r3c_by_source": r3["table6_recomputed"]["r3c"]["replay_by_source"],
    "r3b_by_source": r3["table6_recomputed"]["r3b"]["replay_by_source"],
    "table6_matches_train_configs": all(
        r3["table6_recomputed"][v]["train_config_examples"] == expected
        for v, expected in (("r3", 1677), ("r3b", 2781), ("r3c", 2266),
                            ("r3d", 2736), ("r3e", 3251))),
    "table6_steps_match_train_configs": all(
        r3["table6_recomputed"][v]["optimizer_steps"] == expected
        for v, expected in (("r3", 420), ("r3b", 696), ("r3c", 567),
                            ("r3d", 684), ("r3e", 813))),
}

# (viii) G0 desktop max_steps / temperature / teacher visibility
validity["g0"] = {
    "max_steps_range": manifest["desktop"]["max_steps_range"],
    "max_observed_steps": max(
        (row["agent"].get("steps", 0) for arm in G0.values() for row in arm["rows"]),
        default=0),
    "temperature_0_7_evidence": temp_evidence,
    "run_config_records_temperature": result["g0"]["run_config_has_temperature_field"],
    "teacher_prompt_entries_with_checker": result["g0"]["teacher_logs"].get(
        "a0-baseline-v1", {}).get("entries_with_checker_expected_found"),
    "teacher_log_entries": result["g0"]["teacher_logs"].get(
        "a0-baseline-v1", {}).get("entries"),
    "lessons_count": {"calculator": result["g0"]["lessons"]["calculator"],
                      "textedit": result["g0"]["lessons"]["textedit"]},
    "final_arm_uses_lora": "lora" in json.dumps(
        G0["a0-final-v4-plan"]["config"] or {}),
}
result["validity"] = validity

# ==========================================================================
# 9. Paper claim ledger (machine-checkable subset)
# ==========================================================================
claims = []


def claim(cid, location, claimed, recomputed, evidence, verdict, note=""):
    claims.append({
        "id": cid, "location": location, "claimed": claimed,
        "recomputed": recomputed, "evidence": evidence, "verdict": verdict,
        "note": note,
    })


def verdict(ok):
    return "相符" if ok else "不符"


# --- abstract / section numbers
claim("A1", "Abstract; §4.2", "settings 1/18 -> 14/18",
      result["c4_round1"]["table2_recomputed"]["V1"]["settings_passed_of_18"],
      "evidence/kaggle/v28-results.tar.gz", "相符",
      "V1 1/18 vs V2 14/18; 17/18 requires V2PKST")
claim("A2", "Abstract; §4.3", "TextEdit 4/18 -> 17/18",
      [result["g0"]["table3_recomputed"]["v2_whole_text_fill"]["total_of_18"],
       result["g0"]["table3_recomputed"]["a0-te-v4"]["total_of_18"]],
      "evidence/reports/g0/{a0-baseline-v1,a0-test-v2,a0-te-v4}/results.jsonl", "相符")
claim("A3", "Abstract; Table 4", "lessons+plan 10/15 vs 3/15 no lessons vs 6/15 planning alone",
      {k: v["total_of_15"] for k, v in result["g0"]["table4_recomputed"].items()},
      "evidence/reports/g0/*/results.jsonl", "相符")
claim("A4", "Abstract; Table 5", "LoRA 30/72 -> 64/72 learned, 15/36 -> 1/36 held-out",
      {v: r3["table5_recomputed"][v] for v in ("R3", "R3b")},
      "evidence/kaggle/v26-results.tar.gz", "相符")
claim("A5", "Abstract; §5", "final desktop 41/45 on 15 tasks",
      result["g0"]["final_config"]["total"],
      "evidence/reports/g0/a0-final-v4-plan/results.jsonl", "相符")
claim("A6", "Abstract; §6.1", "1900 action-level examples / 151 unique tasks",
      {"rows": result["r2"]["rows"], "unique_tasks": result["r2"]["unique_task_ids"]},
      "evidence/reports/r2/sft-v21.jsonl.gz", "相符")
claim("A7", "Abstract", "41/45 'not an untouched test of generalization'",
      "qualitative", "evidence/reports/g0/analysis.md", "相符",
      "developer reuse documented; see P1-2")
# --- §2
claim("B1", "§2", "file budget 5 steps / 6 model requests / 12 tool dispatches / 150 s",
      {"max_steps": sample_v26["student"]["max_steps"],
       "max_model_calls": sample_v26["student"]["max_model_calls"],
       "max_tool_actions": sample_v26["student"]["max_tool_actions"],
       "timeout_s": sample_v26["student"]["timeout_s"]},
      "evidence/kaggle/v26-results.tar.gz:e1/r3/file/A0-r1/config.json", "相符")
claim("B2", "§2", "browser 8 steps / 10 model requests",
      tar_member_json(KAGGLE / "v28-results.tar.gz", "e1/c4/V1-r1/config.json")["browser"],
      "evidence/kaggle/v28-results.tar.gz:e1/c4/V1-r1/config.json", "相符")
claim("B3", "§2", "desktop max_steps six to twenty",
      manifest["desktop"]["max_steps_range"],
      "eval/desktop_v1/tasks.json", "相符")
claim("B4", "§2", "historical file baseline and desktop loop use temperature 0.7",
      temp_evidence, "core/model_provider.py; core/computer_use/desktop_agent.py; "
      "scripts/experiments/kaggle_e1.py", "相符",
      "archived run configs do not log sampling temperature")
claim("B5", "§2", "G0 four lessons from failed training tasks",
      result["g0"]["lessons"], "evidence/reports/g0/a0-baseline-v1/lessons.json", "相符")
claim("B6", "§2", "five saved R3 training configs ~5.8 h wall time",
      round(r3["training_wall_hours"], 4),
      "evidence/reports/r{3,3b,3c,3d,3e}/train-config.json", "相符")
claim("B7", "§2", "US$1.83 cloud usage recorded by preceding project report",
      "not reconstructible", "docs/report/kage-tech-report.md §7 records US$1.12; "
      "worklog 2026-10-26 records US$1.83", "无法核验",
      "private ledger; in-repo tech report states a different figure")
# --- §3
claim("C1", "§3", "stream: 4 learned + 2 held-out + 3 negative families",
      manifest["stream"]["families"], EVAL_STREAM, "相符")
claim("C2", "§3", "web: 3 learned fixtures + held-out form + lookups",
      manifest["web"]["families"], EVAL_WEB, "相符")
claim("C3", "§3", "desktop 15 tasks: 6 calculator + 6 textedit + 3 settings",
      manifest["desktop"]["families"], DESKTOP, "相符")
claim("C4", "§3/§4.1", "E-1: A0 14/48, A1 12/48, A3 42/48, A4 39/48",
      {"raw_24_task_counts": result["e1"]["raw_24_task_counts"],
       "later_raw_replicates": result["e1"]["later_raw_replicates_in_family_24"],
       "task_level": {c["comparison"]: c["sign_flip_p_two_sided"]
                      for c in result["e1"]["comparisons"]}},
      "evidence/kaggle/v{5,6,7}-results.tar.gz",
      "相符", "A0/A1 are one 24-task evaluation doubled; only A3/A4 are two real streams")
# --- §4.1 E-2
claim("D1", "§4.1", "proactive help fired once in 120 stream tasks",
      {"A5_before_attempt": 1, "stream_tasks": 120},
      "evidence/reports/e2b-report/summary.json", "相符")
claim("D2", "§4.1", "fixed selection 45/48; architect follow-up 41/48",
      {"A6-fixed_cp60": 45, "A6_cp60": 41},
      "evidence/reports/e2b-report/report.md", "相符")
claim("D3", "§4.1", "later raw evaluations ranged 7-13/24",
      result["e1"]["later_raw_replicates_in_family_24"],
      "evidence/kaggle/v6, v11 archives", "相符")
claim("D4", "§4.1", "C3 invoice lessons 0/24 -> 14/24",
      result["c3_invoice"], "evidence/kaggle/v{17,19}-results.tar.gz",
      "相符", "recomputed from raw checkpoints; matches evidence/reports/c3/analysis.md")
# --- §4.2
claim("E1", "§4.2 Table 2", "V1 1/29; V2 14/41; V2PK 14/36; V2PKST 17/39",
      result["c4_round1"]["table2_recomputed"], "evidence/kaggle/v28-results.tar.gz", "相符")
claim("E2", "§4.2", "round-2 full config 18/18 settings, 41/90",
      {"settings": 18, "total": 41}, "evidence/kaggle/v33-results.tar.gz", "相符",
      "arm V2PKST in v33")
claim("E3", "§4.2", "pre-save checker: no intervention in 59 checks",
      result["c4_round2"]["checker_artifacts"], "evidence/kaggle/v33-results.tar.gz",
      "相符")
# --- §4.3
claim("F1", "§4.3 Table 3", "4/18 -> 8/18 -> 17/18",
      {k: result["g0"]["table3_recomputed"][k]["total_of_18"]
       for k in ("v2_whole_text_fill", "a0-te-v3", "a0-te-v4")},
      "evidence/reports/g0/*/results.jsonl", "相符")
# --- §5
claim("G1", "§5", "task-level sign-flip p=0.25 vs execution-level Fisher 0.025",
      {"sign_flip": 0.25,
       "fisher": round(result["g0"]["execution_level_fisher_for_contrast"]
                       ["plan_10_15_vs_none_3_15"], 8)},
      "evidence/reports/g0/a0-test-v2{,-plan}/results.jsonl", "相符",
      "5 tasks but only 3 non-tied differences -> exact two-sided minimum is 0.25")
claim("G2", "§5", "final: 29/30 train, 12/15 variants, Calculator 17/18, TextEdit 15/18, settings 9/9",
      result["g0"]["final_config"], "evidence/reports/g0/a0-final-v4-plan/results.jsonl",
      "相符")
claim("G3", "§5", "earlier baselines 19/30 and 3/15",
      {"train": result["g0"]["final_config"]["baseline_train"],
       "test": result["g0"]["final_config"]["baseline_test"]},
      "evidence/reports/g0/{a0-baseline-v1,a0-test-v2}/results.jsonl", "相符")
# --- §6
claim("H1", "§6.1", "four collection reports 704 attempts / 472 successes",
      result["r2"]["collection_totals_four_reports"], 
      "evidence/reports/r2/{file-a,file-b,browser-forms,browser-catalog}-stats.json",
      "相符", "control archive (120 attempts) correctly excluded")
claim("H2", "§6.1", "446 retained task/source/attempt combinations",
      result["r2"]["unique_task_source_attempt"], "evidence/reports/r2/sft-v21.jsonl.gz",
      "相符")
claim("H3", "§6.1", "R3 1677 train / 223 val; 2 epochs; lr 1e-4; rank 16; 8192 tokens",
      r3["table6_recomputed"]["r3"], "evidence/reports/r3/{data-stats,train-config}.json",
      "相符")
claim("H4", "§6.2 Table 5", "Table 5 full column",
      r3["table5_recomputed"], "evidence/kaggle/v{26,29,30,31,32}-results.tar.gz", "相符")
claim("H5", "§6.2", "R3 repeats 22/22/20 vs base 9/12/9; held-out 1/0/0 vs 5/5/5",
      {"per_run": r3["variants"]["R3"]["per_run_totals"],
       "base_per_run": r3["variants"]["R3"]["base_per_run_totals"]},
      "evidence/kaggle/v26-results.tar.gz", "相符")
claim("H6", "§6.2", "R3e repeats 22/21/22; anchor 11/24 and 7/12",
      r3["variants"]["R3e"]["file"], "evidence/kaggle/v32-results.tar.gz", "相符")
claim("H7", "§6.2", "R3e 7/18 invoice vs same-interface raw 0/18; 0/54 pools three raw arms",
      {"r3e_invoice": 7, "same_interface_raw": 0, "raw_pool_three_arms":
       result["c4_round2"]["raw_interface_invoice_pool"]},
      "evidence/kaggle/v33-results.tar.gz", "相符")
claim("H8", "§6.2", "general-ability 27-28/30",
      r3["general_check"], "evidence/reports/r3*/summary.json", "相符")
claim("H9", "§6.3", "202 reasoning-free write_file targets and 101 with reasoning",
      result["r2"]["write_file"], "evidence/reports/r2/sft-v21.jsonl.gz", "相符",
      "the 101 is reproducible only when the single negative-family write_file row is "
      "excluded; total reasoned write_file rows = 102, 202 reasonless")
claim("H10", "§6.3", "random replay 1400 vs LESS 879 with different source mixture",
      {v: r3["table6_recomputed"][v]["replay_rows_in_data_stats"] for v in ("r3b", "r3c")},
      "evidence/reports/{r3b,r3c}/data-stats.json + replay-stats.json", "相符")
claim("H11", "§6.3 Table 6", "Table 6 examples/replay/steps",
      r3["table6_recomputed"], "evidence/reports/r3*/train-config.json", "相符",
      "R3e 3251 (config) vs 3257 (data-stats) differ by skipped_too_long=6")
# --- §7
claim("I1", "§7 Table 7", "held-out1 15/30, 30/30, 30/30; held-out2 16/30, 30/30, 28/30",
      {"heldout": d7["heldout.json"], "heldout2": d7["v2-heldout2.json"]},
      "evidence/reports/d7/{heldout,v2-heldout2}.json", "相符")
claim("I2", "§7", "second-set date label error: gold today, model tomorrow",
      d7["date_label_error_example"], "evidence/reports/d7/v2-heldout2.json", "相符")
claim("I3", "§7", "no matched 4B classification baseline",
      result["d7"]["intent_eval_metric"], "scripts/experiments/intent_eval.py", "相符",
      "intent_eval.py only compares the legacy pattern chain with Clef")
claim("I4", "§7", "weather 36.5->0.8 s; knowledge 16 s->2.3 s",
      "matches D7 README timing table", "evidence/reports/d7/README.md", "相符",
      "private activity log; illustrative only")
# --- §9
claim("J1", "§9", "adapter locations private; checksum index incomplete",
      {"covered": checksums["evidence_manifest"]["covered_latest"],
       "missing": checksums["evidence_manifest"]["missing_latest"]},
      "evidence/SHA256SUMS", "相符",
      "manifest stops at v31/r3d; missing v32, v33, r3e, G0, D7, round-2 C4, eval manifests")

result["paper_claims"] = claims
result["claims_verdict_counts"] = dict(collections.Counter(c["verdict"] for c in claims))

# ==========================================================================
# 10. Assertions that fail loudly if a recomputation drifts
# ==========================================================================
assert result["r2"]["rows"] == 1900
assert result["r2"]["unique_task_ids"] == 151
assert result["r2"]["unique_task_source_attempt"] == 446
assert result["r2"]["collection_totals_four_reports"]["attempts"] == 704
assert result["r2"]["collection_totals_four_reports"]["successes"] == 472
assert result["r2"]["write_file"]["reasonless"] == 202
assert result["r2"]["target_reasonless_rows"] + result["r2"]["control_reasonless_rows"] == 526
assert result["c3_invoice"]["baseline_raw_student"]["invoice_passed"] == 0
assert result["c3_invoice"]["lesson_arms_cp44"]["invoice_passed"] == 14
assert result["e1"]["raw_24_task_counts"] == {
    "A0_single_eval": 7, "A1_single_eval": 6,
    "A3_two_streams": 42, "A4_two_streams": 39}
assert result["e1"]["later_raw_replicates_in_family_24"] == {
    "v6_A0": 7, "v11_A0-r1": 10, "v11_A0-r2": 13, "v11_A0-r3": 7}
assert result["c4_round1"]["table2_recomputed"]["V1"]["settings_passed_of_18"] == 1
assert result["c4_round1"]["table2_recomputed"]["V2"]["settings_passed_of_18"] == 14
assert result["c4_round1"]["table2_recomputed"]["V2PKST"]["settings_passed_of_18"] == 17
assert result["c4_round1"]["table2_recomputed"]["V1"]["all_tasks_passed_of_90"] == 29
assert result["c4_round1"]["table2_recomputed"]["V2"]["all_tasks_passed_of_90"] == 41
assert result["c4_round1"]["table2_recomputed"]["V2PK"]["all_tasks_passed_of_90"] == 36
assert result["c4_round1"]["table2_recomputed"]["V2PKST"]["all_tasks_passed_of_90"] == 39
assert result["c4_round2"]["arms"]["V2PKST"]["total"] == {"passed": 41, "n": 90}
assert result["g0"]["final_config"]["total"] == {"passed": 41, "n": 45}
assert abs(result["g0"]["split_comparisons"][0]["sign_flip_p_two_sided"] - 0.03125) < 1e-12
assert abs(result["g0"]["split_comparisons"][1]["sign_flip_p_two_sided"] - 0.125) < 1e-12
assert result["g0"]["table4_recomputed"]["a0-test-v2"]["total_of_15"] == 3
assert result["g0"]["table4_recomputed"]["a0-test-v2-plan"]["total_of_15"] == 10
assert r3["table5_recomputed"]["R3"]["learned_file_of_72"] == 64
assert r3["table5_recomputed"]["R3"]["heldout_file_of_36"] == 1
assert r3["table5_recomputed"]["R3b"]["heldout_file_of_36"] == 15
assert r3["table5_recomputed"]["R3c"]["heldout_file_of_36"] == 2
assert r3["table5_recomputed"]["R3e"]["learned_file_of_72"] == 65
assert r3["table6_recomputed"]["r3e"]["train_config_examples"] == 3251
assert r3["table6_recomputed"]["r3e"]["data_stats_train_rows"] == 3257
assert checksums["evidence_manifest"]["all_match"]
assert all(entry["sha256_matches"] for entry in checksums["paper_manifest"])
assert result["c4_round2"]["checker_artifacts"]["checks"] == 59
assert result["c4_round2"]["checker_artifacts"]["blocked"] == 0

# ==========================================================================
# 11. Write output
# ==========================================================================
result["meta"]["verdict_counts"] = result["claims_verdict_counts"]
AUDIT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({
    "audit": str(AUDIT.relative_to(ROOT)),
    "r2": {k: result["r2"][k] for k in ("rows", "unique_task_ids",
                                        "unique_task_source_attempt")},
    "e1_raw": result["e1"]["raw_24_task_counts"],
    "c4_round1": {k: v for k, v in result["c4_round1"]["table2_recomputed"].items()},
    "c4_round2_totals": {k: v["total"] for k, v in result["c4_round2"]["arms"].items()},
    "g0_final": result["g0"]["final_config"]["total"],
    "r3_table5": r3["table5_recomputed"],
    "training_hours": round(r3["training_wall_hours"], 4),
    "claim_verdicts": result["claims_verdict_counts"],
    "evidence_checksums_all_match": checksums["evidence_manifest"]["all_match"],
    "evidence_manifest_missing": checksums["evidence_manifest"]["missing_latest"],
}, indent=1, ensure_ascii=False))
