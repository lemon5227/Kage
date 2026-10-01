"""Real Chromium setup failure must remain in the experiment denominator."""
import asyncio
from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest
pytest.importorskip('playwright.async_api', reason='optional computer-use dependency')
from playwright.async_api import async_playwright


def test_failed_navigation_is_recorded_without_aborting_next_run(tmp_path, monkeypatch):
    from scripts.experiments import browser_efficiency as experiment

    @contextmanager
    def broken_fixture():
        # Chromium really attempts navigation and rejects this unsafe port.
        yield 'http://127.0.0.1:1', {'saved':None,'posts':0}

    monkeypatch.setattr(experiment, 'profile_server', broken_fixture)
    args=SimpleNamespace(output_dir=tmp_path,port=18082)

    async def run():
        async with async_playwright() as p:
            browser=await p.chromium.launch(headless=True)
            try:
                rows=[]
                for arm in ('baseline','optimized'):
                    row=await experiment.recorded_trial(browser,args,arm,0)
                    rows.append(row)
                    recorded=json.loads((tmp_path/f'0-{arm}'/'result.json').read_text())
                    assert recorded==row and row['status']=='failed' and row['score']==0
                    assert row['lifecycle_error'] and 'ERR_UNSAFE_PORT' in row['lifecycle_error']
                    assert not (tmp_path/f'0-{arm}'/'model.jsonl').exists()
                assert len(rows)==2
            finally:
                await browser.close()
    asyncio.run(run())
