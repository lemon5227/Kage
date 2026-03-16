#!/usr/bin/env python3
"""Benchmark common no-key weather providers.

Outputs JSON to docs/benchmarks/latest_weather_provider_benchmark.json.
"""

from __future__ import annotations

import json
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path


USER_AGENT = "Kage/1.0"


def _resolve_coords(city: str) -> tuple[float, float] | None:
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": city, "count": 1, "language": "zh", "format": "json"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    rows = data.get("results") or []
    if not rows:
        return None
    r0 = rows[0]
    lat = r0.get("latitude")
    lon = r0.get("longitude")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def _call_open_meteo(city: str) -> str:
    coords = _resolve_coords(city)
    if not coords:
        return ""
    lat, lon = coords
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
        }
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    cw = data.get("current_weather") or {}
    t = cw.get("temperature")
    return f"ok:{t}"


def _call_wttr(city: str) -> str:
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    cc = (data.get("current_condition") or [{}])[0]
    t = cc.get("temp_C")
    return f"ok:{t}"


def _call_metno(city: str) -> str:
    coords = _resolve_coords(city)
    if not coords:
        return ""
    lat, lon = coords
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?" + urllib.parse.urlencode(
        {"lat": lat, "lon": lon}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Kage/1.0 (kage assistant)"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    ts = ((data.get("properties") or {}).get("timeseries") or [])
    if not ts:
        return ""
    details = (((ts[0].get("data") or {}).get("instant") or {}).get("details") or {})
    t = details.get("air_temperature")
    return f"ok:{t}"


def _bench_provider(name: str, fn, city: str, rounds: int = 5) -> dict:
    latencies = []
    ok = 0
    errors = []
    for _ in range(rounds):
        t0 = time.monotonic()
        try:
            out = fn(city)
            dt = (time.monotonic() - t0) * 1000
            latencies.append(round(dt, 1))
            if out:
                ok += 1
            else:
                errors.append("empty")
        except Exception as exc:
            dt = (time.monotonic() - t0) * 1000
            latencies.append(round(dt, 1))
            errors.append(type(exc).__name__)
    median = statistics.median(latencies) if latencies else 0.0
    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
    return {
        "provider": name,
        "city": city,
        "rounds": rounds,
        "ok_rate": round(ok / max(1, rounds), 3),
        "median_ms": round(float(median), 1),
        "p95_ms": round(float(p95), 1),
        "samples_ms": latencies,
        "errors": errors,
    }


def main() -> int:
    providers = {
        "open_meteo": _call_open_meteo,
        "wttr": _call_wttr,
        "metno": _call_metno,
    }
    cities = ["Nice", "Shanghai"]

    rows = []
    for city in cities:
        for name, fn in providers.items():
            rows.append(_bench_provider(name, fn, city, rounds=5))

    by_provider: dict[str, list[dict]] = {}
    for r in rows:
        by_provider.setdefault(r["provider"], []).append(r)

    ranking = []
    for name, rs in by_provider.items():
        med = statistics.mean([float(x["median_ms"]) for x in rs]) if rs else 0.0
        ok = statistics.mean([float(x["ok_rate"]) for x in rs]) if rs else 0.0
        ranking.append({"provider": name, "avg_median_ms": round(med, 1), "avg_ok_rate": round(ok, 3)})
    ranking.sort(key=lambda x: (-(x["avg_ok_rate"]), x["avg_median_ms"]))

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "providers": list(providers.keys()),
        "cities": cities,
        "results": rows,
        "ranking": ranking,
        "recommended_top2": [r["provider"] for r in ranking[:2]],
    }

    out_dir = Path("/Users/wenbo/Kage/docs/benchmarks")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest_weather_provider_benchmark.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"top2": out["recommended_top2"], "ranking": ranking}, ensure_ascii=False))
    print(f"saved={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
