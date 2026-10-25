"""Decision model client: failure handling (no network: urlopen is replaced in every test)."""
import io
import urllib.error

import pytest

from core import decision_model as dm


@pytest.fixture
def client(monkeypatch, tmp_path):
    cred = tmp_path / 'cloudflare.json'
    cred.write_text('{"account_id": "a", "api_token": "t"}')
    monkeypatch.setattr(dm, 'CREDENTIALS', cred)
    monkeypatch.setattr(dm, '_breaker', {'failures': 0, 'open_until': 0.0, 'quota_day': ''})
    monkeypatch.setattr(dm, 'available', dm._ready)        # conftest turns it off; here we test the real check
    return dm


def _raises(exc):
    def opener(*args, **kwargs):
        raise exc
    return opener


def test_breaker_opens_after_repeated_failures(monkeypatch, client):
    monkeypatch.setattr(dm.urllib.request, 'urlopen', _raises(urllib.error.URLError('down')))
    for _ in range(dm.BREAKER_FAILURES):
        with pytest.raises(dm.DecisionUnavailable):
            dm.ask('s', {'q': {'type': 'noul', 'question': 'x'}})
    assert not dm.available()
    with pytest.raises(dm.DecisionUnavailable, match='paused'):
        dm.ask('s', {'q': {'type': 'noul', 'question': 'x'}})


def test_free_quota_stops_for_the_day(monkeypatch, client):
    error = urllib.error.HTTPError('u', 429, 'limit', {}, io.BytesIO(b'{"code":"FreeUsageLimit"}'))
    monkeypatch.setattr(dm.urllib.request, 'urlopen', _raises(error))
    with pytest.raises(dm.DecisionUnavailable):
        dm.ask('s', {'q': {'type': 'noul', 'question': 'x'}})
    assert dm._breaker['quota_day'] and not dm.available()
