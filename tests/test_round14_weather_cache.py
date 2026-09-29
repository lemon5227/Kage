"""Tests for Round 14 ISSUE-2, ISSUE-4, and ISSUE-5:
- ISSUE-2: Event loop non-blocking weather / city calls
- ISSUE-4: Weather service deduplication and delegation
- ISSUE-5: Thread-safety and race condition prevention in _fast_cache
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from core.server import KageServer, _FastCacheAdapter, _FAST_CACHE_MAX
from core.weather_service import WeatherService


@pytest.fixture
def mock_server():
    s = object.__new__(KageServer)
    s._fast_cache = {}
    s._fast_cache_lock = threading.Lock()
    s._weather_service = WeatherService(cache=_FastCacheAdapter(s))
    return s


class TestWeatherDelegationAndNonBlocking:
    def test_weather_delegation_to_weather_service(self, mock_server):
        with patch.object(mock_server.weather_service, "get_weather", return_value="北京：晴 20度") as mock_gw:
            res = mock_server._fetch_weather("北京")
            mock_gw.assert_called_once_with("北京")
            assert res == "北京：晴 20度"

    def test_local_city_delegation(self, mock_server):
        with patch.object(mock_server.weather_service, "get_local_city", return_value="Shanghai") as mock_glc:
            res = mock_server._get_local_city()
            mock_glc.assert_called_once()
            assert res == "Shanghai"

    def test_open_meteo_and_metno_delegation(self, mock_server):
        with patch("core.server.fetch_open_meteo", return_value="晴") as mock_om, \
             patch("core.server.fetch_metno", return_value="多云") as mock_mn, \
             patch("core.server.resolve_coords", return_value=(31.2, 121.5, "上海")) as mock_rc:
            
            res_om = mock_server._fetch_weather_open_meteo("上海", day_offset=1)
            assert res_om == "晴"
            mock_om.assert_called_once()

            res_mn = mock_server._fetch_weather_metno("上海")
            assert res_mn == "多云"
            mock_mn.assert_called_once()

            coords = mock_server._resolve_weather_coords("上海")
            assert coords == (31.2, 121.5, "上海")
            mock_rc.assert_called_once()

    @pytest.mark.anyio
    async def test_async_weather_and_local_city(self, mock_server):
        with patch.object(mock_server.weather_service, "get_weather", return_value="Async Sunny") as mock_gw, \
             patch.object(mock_server.weather_service, "get_local_city", return_value="Async City") as mock_glc:
            
            w = await mock_server._fetch_weather_async("Tokyo")
            c = await mock_server._get_local_city_async()
            assert w == "Async Sunny"
            assert c == "Async City"


class TestFastCacheThreadSafety:
    def test_concurrent_fast_cache_access(self, mock_server):
        """Stress-test concurrent reading, writing, and pruning in _fast_cache to verify no RuntimeError."""
        errors = []
        stop_event = threading.Event()

        def writer():
            try:
                for i in range(500):
                    mock_server._set_fast_cache(f"key_{i % 50}", f"val_{i}")
                    time.sleep(0.0001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(500):
                    mock_server._get_fast_cache(f"key_{i % 50}", ttl=60)
                    time.sleep(0.0001)
            except Exception as e:
                errors.append(e)

        def pruner():
            try:
                # Trigger oversized pruning by rapidly inserting beyond _FAST_CACHE_MAX
                for i in range(300):
                    mock_server._set_fast_cache(f"bulk_key_{i}", f"bulk_val_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=pruner),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Encountered thread safety errors in _fast_cache: {errors}"
        # Cache must remain bounded
        assert len(mock_server._fast_cache) <= _FAST_CACHE_MAX * 1.5
