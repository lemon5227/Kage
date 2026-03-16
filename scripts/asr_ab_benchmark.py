#!/usr/bin/env python3
"""A/B benchmark for Chinese ASR latency and accuracy.

Backends:
- funasr_paraformer (current baseline)
- qwen3_asr_0_6b (candidate)

It generates a small synthetic Chinese eval set via macOS `say` to ensure
deterministic references, then measures char error rate (CER) and latency.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


TEXTS = [
    "帮我查一下曹操说最新视频",
    "不是这个，是曹操说",
    "把亮度调高一点",
    "帮我查一下明天尼斯天气",
    "打开备忘录",
    "帮我在B站找最新视频",
]


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _cer(ref: str, hyp: str) -> float:
    r = "".join(str(ref or "").split())
    h = "".join(str(hyp or "").split())
    if not r:
        return 0.0 if not h else 1.0
    return _levenshtein(r, h) / max(1, len(r))


def _gen_audio(text: str, out_wav: Path, voice: str = "Ting-Ting") -> None:
    out_aiff = out_wav.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice, "-o", str(out_aiff), text], check=True)
    subprocess.run(
        ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(out_aiff), str(out_wav)],
        check=True,
    )
    try:
        out_aiff.unlink(missing_ok=True)
    except Exception:
        pass


@dataclass
class Row:
    text: str
    hyp: str
    cer: float
    latency_ms: float
    ok: bool
    error: str | None = None


def run_funasr(wavs: list[Path]) -> list[Row]:
    from funasr import AutoModel

    model = AutoModel(model="paraformer-zh", vad_model="fsmn-vad", punc_model="ct-punc")
    rows: list[Row] = []
    for p, ref in zip(wavs, TEXTS):
        t0 = time.monotonic()
        try:
            res = model.generate(input=str(p))
            hyp = ""
            if isinstance(res, list) and res and isinstance(res[0], dict):
                hyp = str(res[0].get("text") or "")
            dt = (time.monotonic() - t0) * 1000
            rows.append(Row(text=ref, hyp=hyp, cer=_cer(ref, hyp), latency_ms=dt, ok=True))
        except Exception as exc:
            dt = (time.monotonic() - t0) * 1000
            rows.append(Row(text=ref, hyp="", cer=1.0, latency_ms=dt, ok=False, error=str(exc)))
    return rows


def run_qwen(wavs: list[Path], model_id: str) -> tuple[list[Row], str | None]:
    try:
        from qwen_asr import Qwen3ASRModel
        import torch
    except Exception as exc:
        return [], f"import_error:{exc}"

    try:
        model = Qwen3ASRModel.from_pretrained(
            model_id,
            dtype=torch.float32,
            device_map="cpu",
            max_inference_batch_size=1,
            max_new_tokens=256,
        )
    except Exception as exc:
        return [], f"load_error:{exc}"

    rows: list[Row] = []
    for p, ref in zip(wavs, TEXTS):
        t0 = time.monotonic()
        try:
            out = model.transcribe(audio=str(p), language="Chinese")
            hyp = ""
            if isinstance(out, list) and out:
                hyp = str(getattr(out[0], "text", "") or "")
            dt = (time.monotonic() - t0) * 1000
            rows.append(Row(text=ref, hyp=hyp, cer=_cer(ref, hyp), latency_ms=dt, ok=True))
        except Exception as exc:
            dt = (time.monotonic() - t0) * 1000
            rows.append(Row(text=ref, hyp="", cer=1.0, latency_ms=dt, ok=False, error=str(exc)))
    return rows, None


def summarize(rows: list[Row]) -> dict:
    if not rows:
        return {"count": 0, "ok_rate": 0.0, "avg_cer": 1.0, "avg_ms": 0.0, "p95_ms": 0.0}
    ms = [float(r.latency_ms) for r in rows]
    ok_rate = sum(1 for r in rows if r.ok) / len(rows)
    avg_cer = sum(float(r.cer) for r in rows) / len(rows)
    avg_ms = sum(ms) / len(ms)
    p95_ms = sorted(ms)[max(0, int(len(ms) * 0.95) - 1)]
    return {
        "count": len(rows),
        "ok_rate": round(ok_rate, 3),
        "avg_cer": round(avg_cer, 4),
        "avg_ms": round(avg_ms, 1),
        "p95_ms": round(p95_ms, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qwen-model", default="Qwen/Qwen3-ASR-0.6B")
    ap.add_argument("--voice", default="Ting-Ting")
    args = ap.parse_args()

    work = Path("/tmp/kage_asr_ab")
    work.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i, text in enumerate(TEXTS, 1):
        p = work / f"sample_{i:02d}.wav"
        _gen_audio(text, p, voice=str(args.voice))
        wavs.append(p)

    fun_rows = run_funasr(wavs)
    q_rows, q_err = run_qwen(wavs, model_id=str(args.qwen_model))

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dataset": {"count": len(TEXTS), "texts": TEXTS},
        "funasr_paraformer": {
            "summary": summarize(fun_rows),
            "rows": [r.__dict__ for r in fun_rows],
        },
        "qwen_asr": {
            "model": str(args.qwen_model),
            "error": q_err,
            "summary": summarize(q_rows),
            "rows": [r.__dict__ for r in q_rows],
        },
        "recommendation": "KEEP_FUNASR",
        "reason": "qwen_unavailable",
    }

    if not q_err and q_rows:
        a = report["funasr_paraformer"]["summary"]
        b = report["qwen_asr"]["summary"]
        cer_gain = float(a["avg_cer"]) - float(b["avg_cer"])
        lat_reg = (float(b["avg_ms"]) / max(1e-6, float(a["avg_ms"]))) - 1.0
        if cer_gain >= 0.02 and lat_reg <= 0.2:
            report["recommendation"] = "SWITCH_OR_HYBRID_QWEN"
            report["reason"] = "better_accuracy_within_latency_budget"
        else:
            report["recommendation"] = "KEEP_FUNASR"
            report["reason"] = "qwen_not_better_under_latency_budget"
        report["delta"] = {
            "cer_gain": round(cer_gain, 4),
            "latency_regression_ratio": round(lat_reg, 4),
        }

    out = Path("/Users/wenbo/Kage/docs/benchmarks/latest_asr_ab_benchmark.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    print(f"saved={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
