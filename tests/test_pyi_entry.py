"""Tests for the frozen-binary entry point (packaging/pyi_entry.py).

Not part of the installed package — loaded by path, the way PyInstaller does.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_entry():
    spec = importlib.util.spec_from_file_location(
        "pyi_entry", ROOT / "packaging" / "pyi_entry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def entry():
    return _load_entry()


def test_ca_bundle_is_set_when_unset(entry, monkeypatch):
    # The frozen binary ships libssl but no CA store; without this every HTTPS
    # call fails verification and each call site swallows the error.
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)

    entry._ensure_ca_bundle()

    import os
    path = os.environ.get("SSL_CERT_FILE")
    assert path, "no CA bundle found — certifi and every OS fallback missed"
    assert Path(path).exists()


def test_existing_ssl_cert_file_is_never_overridden(entry, monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/user-chosen-bundle.pem")

    entry._ensure_ca_bundle()

    import os
    assert os.environ["SSL_CERT_FILE"] == "/tmp/user-chosen-bundle.pem"


def test_ssl_cert_dir_also_counts_as_configured(entry, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("SSL_CERT_DIR", "/etc/ssl/certs")

    entry._ensure_ca_bundle()

    import os
    assert "SSL_CERT_FILE" not in os.environ


def test_m_shim_still_routes_only_our_own_modules(entry, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cs", "-m", "pip", "install", "evil"])
    assert entry._run() == 2
    assert "cannot run `-m pip`" in capsys.readouterr().err
