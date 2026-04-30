"""Tests voor de crash-handler.

Focus: install_handlers vervangt sys.excepthook + threading.excepthook,
geschreven log bevat traceback + APP_VERSION, dialog-callback wordt
aangeroepen bij een gevangen exception, en uninstall zet alles terug.

We willen de écht hooks niet permanent gemodificeerd achterlaten —
elke test installeert + uninstalleert in een try/finally."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from livefire import crash as crash_mod


@pytest.fixture
def temp_log_dir(tmp_path: Path, monkeypatch) -> Path:
    """Verhuis crash-logs naar een tmp-folder zodat we niet in de echte
    AppData schrijven en tests achter elkaar geen log-trash opbouwen."""
    monkeypatch.setattr(crash_mod, "crash_log_dir", lambda: tmp_path)
    return tmp_path


def test_install_replaces_sys_excepthook(temp_log_dir: Path) -> None:
    original = sys.excepthook
    try:
        crash_mod.install_handlers()
        assert sys.excepthook is not original
    finally:
        crash_mod.uninstall_handlers()
    assert sys.excepthook is sys.__excepthook__


def test_uninstall_restores_threading_excepthook(temp_log_dir: Path) -> None:
    crash_mod.install_handlers()
    crash_mod.uninstall_handlers()
    assert threading.excepthook is threading.__excepthook__


def test_excepthook_writes_log(temp_log_dir: Path) -> None:
    crash_mod.install_handlers()
    try:
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        logs = list(temp_log_dir.glob("crash-*.log"))
        assert len(logs) == 1
        contents = logs[0].read_text(encoding="utf-8")
        # Header met versie + Python-versie aanwezig
        from livefire import APP_VERSION
        assert APP_VERSION in contents
        # Traceback met de exception-naam aanwezig
        assert "RuntimeError" in contents
        assert "boom" in contents
    finally:
        crash_mod.uninstall_handlers()


def test_excepthook_passes_keyboardinterrupt_through(
    temp_log_dir: Path, monkeypatch
) -> None:
    """Ctrl+C in dev-mode mag niet gelogd worden — de Python-default-
    handler moet doorgaan zodat de gebruiker z'n proces gewoon kan
    afbreken."""
    called = {"n": 0}

    def fake_default(*args):
        called["n"] += 1

    monkeypatch.setattr(sys, "__excepthook__", fake_default)
    crash_mod.install_handlers()
    try:
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            sys.excepthook(*sys.exc_info())
        assert called["n"] == 1
        # Geen log geschreven voor KeyboardInterrupt.
        assert list(temp_log_dir.glob("crash-*.log")) == []
    finally:
        crash_mod.uninstall_handlers()


def test_dialog_callback_invoked(temp_log_dir: Path) -> None:
    received: list[tuple[str, Path]] = []

    def cb(summary: str, log_path: Path) -> None:
        received.append((summary, log_path))

    crash_mod.install_handlers(dialog_callback=cb)
    try:
        try:
            raise ValueError("nope")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        assert len(received) == 1
        summary, log_path = received[0]
        assert "ValueError" in summary
        assert "nope" in summary
        assert log_path.is_file()
    finally:
        crash_mod.uninstall_handlers()


def test_dialog_callback_failure_does_not_propagate(temp_log_dir: Path) -> None:
    """Als de dialog-callback zelf crasht, mag dat de excepthook niet
    omzeep helpen — anders veroorzaakt de crash-handler ironisch genoeg
    een nieuwe crash."""

    def bad_cb(summary, log_path):
        raise RuntimeError("dialog itself blew up")

    crash_mod.install_handlers(dialog_callback=bad_cb)
    try:
        try:
            raise IndexError("orig")
        except IndexError:
            # Mag niet raisen — als het fout gaat, faalt deze regel.
            sys.excepthook(*sys.exc_info())
    finally:
        crash_mod.uninstall_handlers()


def test_thread_excepthook_writes_log(temp_log_dir: Path) -> None:
    crash_mod.install_handlers()
    try:
        def boom():
            raise RuntimeError("thread-boom")

        t = threading.Thread(target=boom, name="test-worker")
        t.start()
        t.join(timeout=2.0)
        logs = list(temp_log_dir.glob("crash-*.log"))
        assert any("thread-boom" in p.read_text(encoding="utf-8") for p in logs)
    finally:
        crash_mod.uninstall_handlers()
