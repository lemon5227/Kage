import json


def test_system_control_volume_mute_monkeypatch(monkeypatch):
    from core import system_control as sc

    calls = []

    def fake_run(cmd, timeout=15):
        calls.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(sc, "_run", fake_run)

    out = json.loads(sc.system_control("volume", "mute"))
    assert out["success"] is True
    assert any(c[0] == "osascript" for c in calls)


def test_system_control_wifi_uses_networksetup(monkeypatch):
    from core import system_control as sc

    calls = []

    def fake_run(cmd, timeout=15):
        calls.append(cmd)
        if cmd[:2] == ["networksetup", "-listallhardwareports"]:
            return 0, "Hardware Port: Wi-Fi\nDevice: en9\n", ""
        if cmd[:2] == ["shortcuts", "run"]:
            return 1, "", "no shortcut"
        return 0, "", ""

    monkeypatch.setattr(sc, "_run", fake_run)

    out = json.loads(sc.system_control("wifi", "on"))
    assert out["success"] is True
    assert ["networksetup", "-setairportpower", "en9", "on"] in calls
