"""The daemon that runs must be the one the service manager supervises.

Regression: `cs --setup` spawned its own detached daemon even with a
LaunchAgent installed. That daemon took the pidfile, launchd's own job then
exited 0 and — by design, since KeepAlive is `SuccessfulExit: false` — stood
down for good. The daemon stayed up with nothing watching it, while
`cs daemon install` had promised a restart on crash, and `cs doctor` printed
a green ✓ next to "launchd state: not running".
"""
import pytest

from claude_statusbar import service as svc


def test_adopt_is_a_noop_without_an_installed_service(monkeypatch):
    monkeypatch.setattr(svc, "is_installed", lambda: False)
    ok, msg = svc.adopt_running_daemon()
    assert ok is False
    assert "no service installed" in msg


def test_adopt_is_a_noop_when_already_supervised(monkeypatch):
    monkeypatch.setattr(svc, "is_installed", lambda: True)
    monkeypatch.setattr(svc, "is_supervising", lambda: True)
    called = []
    monkeypatch.setattr(svc, "_macos_kickstart",
                        lambda: called.append(1) or (True, "kicked"))
    ok, msg = svc.adopt_running_daemon()
    assert ok is True and "already supervised" in msg
    assert called == [], "must not bounce a healthy supervised daemon"


def test_adopt_kickstarts_an_idle_launchd_job(monkeypatch):
    monkeypatch.setattr(svc, "is_installed", lambda: True)
    monkeypatch.setattr(svc, "is_supervising", lambda: False)
    monkeypatch.setattr(svc, "_platform", lambda: "macos")
    calls = []

    def fake_launchctl(*args):
        calls.append(args)
        return 0, "", ""

    monkeypatch.setattr(svc, "_launchctl", fake_launchctl)
    ok, msg = svc.adopt_running_daemon()

    assert ok is True
    assert calls and calls[0][0] == "kickstart" and calls[0][1] == "-k"


def test_supervising_is_false_when_launchd_job_is_idle(monkeypatch):
    monkeypatch.setattr(svc, "_platform", lambda: "macos")
    monkeypatch.setattr(
        svc, "_macos_status",
        lambda: (True, "installed (/x.plist), launchd state: not running"))
    assert svc.is_supervising() is False


def test_supervising_is_true_when_launchd_runs_the_job(monkeypatch):
    monkeypatch.setattr(svc, "_platform", lambda: "macos")
    monkeypatch.setattr(
        svc, "_macos_status",
        lambda: (True, "installed (/x.plist), launchd state: running"))
    assert svc.is_supervising() is True
