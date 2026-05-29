"""
Weather Service — multi-provider weather queries with caching.

Providers (tried in order):
1. wttr.in (simple, no API key)
2. Open-Meteo (detailed, no API key)
3. MET Norway (compact, no API key)

Design:
- Accepts a CacheProtocol for dependency injection (can use KageServer._fast_cache)
- All network calls have timeouts
- Graceful fallback chain
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class CacheProtocol(Protocol):
    """Minimal cache interface for weather service."""

    def get(self, key: str, ttl: int) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


# WMO weather code → Chinese description
_WMO_DESC: dict[int, str] = {
    0: "晴", 1: "多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    95: "雷阵雨",
}

_HEADERS = {"User-Agent": "Kage/1.0"}


def _wmo_desc(code: int | None) -> str:
    return _WMO_DESC.get(code, "天气") if code is not None else "天气"


def _fetch_json(url: str, timeout: int = 3) -> dict | None:
    """Fetch JSON from URL with error handling."""
    try:
        req = Request(url, headers=_HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


def resolve_coords(
    city: str, cache: CacheProtocol | None = None
) -> tuple[float, float, str] | None:
    """Resolve city name to (lat, lon, display_name) using Open-Meteo geocoding."""
    name = str(city or "").strip()
    if not name:
        return None

    cache_key = f"weather_coords:{name.lower()}"
    if cache:
        cached = cache.get(cache_key, ttl=86400)
        if cached:
            try:
                o = json.loads(cached)
                return (float(o["lat"]), float(o["lon"]), o.get("name", name))
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

    url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urlencode({"name": name, "count": 1, "language": "zh", "format": "json"})
    )
    data = _fetch_json(url)
    if not data:
        return None

    results = data.get("results") or []
    if not results:
        return None

    r0 = results[0]
    lat, lon = r0.get("latitude"), r0.get("longitude")
    if lat is None or lon is None:
        return None

    disp = r0.get("name") or name
    out = {"lat": lat, "lon": lon, "name": disp}
    if cache:
        cache.set(cache_key, json.dumps(out, ensure_ascii=False))

    return (float(lat), float(lon), str(disp))


def fetch_open_meteo(
    city: str, day_offset: int = 0, cache: CacheProtocol | None = None
) -> str:
    """Open-Meteo provider: current weather + daily high/low."""
    coords = resolve_coords(city, cache)
    if not coords:
        return ""
    lat, lon, disp = coords

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urlencode({
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
        })
    )
    data = _fetch_json(url)
    if not data:
        return ""

    cw = data.get("current_weather") or {}
    temp = cw.get("temperature")
    code = cw.get("weathercode")
    if temp is None:
        return ""

    desc = _wmo_desc(int(code) if code is not None else None)
    try:
        t = int(round(float(temp)))
    except (ValueError, TypeError):
        t = temp

    when = "明天" if int(day_offset or 0) == 1 else "今天"

    daily = data.get("daily") or {}
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    dcode = daily.get("weather_code") or []
    idx = 1 if int(day_offset or 0) == 1 else 0

    hi = tmax[idx] if isinstance(tmax, list) and len(tmax) > idx else None
    lo = tmin[idx] if isinstance(tmin, list) and len(tmin) > idx else None
    dc = dcode[idx] if isinstance(dcode, list) and len(dcode) > idx else code
    ddesc = _wmo_desc(int(dc) if dc is not None else None)

    if hi is not None and lo is not None:
        try:
            hi_v = int(round(float(hi)))
            lo_v = int(round(float(lo)))
            return f"{disp}{when}，{ddesc}，气温{lo_v}到{hi_v}度，当前{t}度。"
        except (ValueError, TypeError):
            pass
    return f"{disp}{when}，{ddesc}，当前{t}度。"


def fetch_metno(
    city: str, cache: CacheProtocol | None = None
) -> str:
    """MET Norway provider: compact current temperature."""
    coords = resolve_coords(city, cache)
    if not coords:
        return ""
    lat, lon, disp = coords

    url = (
        "https://api.met.no/weatherapi/locationforecast/2.0/compact?"
        + urlencode({"lat": lat, "lon": lon})
    )
    headers = {"User-Agent": "Kage/1.0 (kage assistant)"}
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return ""

    ts = ((data.get("properties") or {}).get("timeseries") or [])
    if not ts:
        return ""
    first = ts[0] if isinstance(ts[0], dict) else {}
    details = (((first.get("data") or {}).get("instant") or {}).get("details") or {})
    temp = details.get("air_temperature")
    if temp is None:
        return ""
    try:
        t = int(round(float(temp)))
    except (ValueError, TypeError):
        t = temp
    return f"{disp}今天，当前约{t}度。"


def fetch_wttr(city: str) -> str:
    """wttr.in provider: simple format 3."""
    from urllib.parse import quote
    url = f"https://wttr.in/{quote(city)}?format=3"
    try:
        req = Request(url, headers=_HEADERS)
        with urlopen(req, timeout=5) as resp:
            return (resp.read().decode("utf-8", errors="replace") or "").strip()
    except Exception:
        return ""


class WeatherService:
    """High-level weather service with provider fallback chain."""

    def __init__(self, cache: CacheProtocol | None = None):
        self._cache = cache

    def get_weather(self, city: str) -> str:
        """Get weather for a city, trying multiple providers with caching."""
        cache_key = f"weather:{city.lower()}"
        cached = self._cache_get(cache_key, ttl=1800)
        if cached:
            return cached

        # Provider 1: wttr.in
        weather = fetch_wttr(city)
        if weather:
            self._cache_set(cache_key, weather)
            return weather

        # Provider 2: Open-Meteo
        try:
            alt = fetch_open_meteo(city, cache=self._cache)
            if alt:
                self._cache_set(cache_key, alt)
                return alt
        except Exception:
            pass

        # Fallback: stale cache
        stale = self._cache_get(cache_key, ttl=86400)
        return stale or "天气查询超时了，等会儿再试。"

    def get_local_city(self) -> str:
        """Detect local city from IP geolocation."""
        cached = self._cache_get("local_city", ttl=86400)
        if cached:
            return cached
        try:
            req = Request("https://ipinfo.io/city", headers=_HEADERS)
            with urlopen(req, timeout=4) as resp:
                city = (resp.read().decode("utf-8", errors="replace") or "").strip()
        except Exception:
            city = ""
        if city:
            self._cache_set("local_city", city)
        return city

    def _cache_get(self, key: str, ttl: int) -> str | None:
        if self._cache:
            return self._cache.get(key, ttl)
        return None

    def _cache_set(self, key: str, value: str) -> None:
        if self._cache:
            self._cache.set(key, value)


# ============================================================================
# City name normalization for weather APIs
# ============================================================================

_CITY_MAPPING: dict[str, str] = {
    "尼斯": "Nice",
    "上海": "Shanghai",
    "北京": "Beijing",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "成都": "Chengdu",
    "武汉": "Wuhan",
    "重庆": "Chongqing",
    "西安": "Xi'an",
    "天津": "Tianjin",
    "香港": "Hong Kong",
    "澳门": "Macau",
    "台北": "Taipei",
}


def normalize_city_for_weather(city: str) -> str:
    """Normalize Chinese city name to English for weather API."""
    c = str(city or "").strip()
    return _CITY_MAPPING.get(c, c or "Shanghai")
