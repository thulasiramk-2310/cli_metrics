"""Mini dashboard tests: the plain-text renderer and its sampling clock."""

import io
import sys

import pytest

from sysdash.cli_mini import MiniDashboard


@pytest.fixture
def mini(metrics_factory, monkeypatch):
    """A MiniDashboard wired to fixed metrics, recording what it collected."""
    dashboard = MiniDashboard(hostname="testhost")
    calls = []

    def collect_all(per_nic=True, include_processes=True):
        calls.append({"per_nic": per_nic, "include_processes": include_processes})
        metrics = metrics_factory()
        if not include_processes:
            metrics["processes"] = []
        return metrics

    dashboard.collector.collect_all = collect_all
    dashboard.calls = calls
    monkeypatch.setattr(dashboard, "clear_screen", lambda: None)
    return dashboard


def capture(dashboard):
    """Render once and return what was printed."""
    buffer = io.StringIO()
    stdout, sys.stdout = sys.stdout, buffer
    try:
        dashboard.render()
    finally:
        sys.stdout = stdout
    return buffer.getvalue()


@pytest.mark.parametrize(
    "needle",
    ["SYSDASH CLI MINI", "testhost", "1:02:03:04", "CPU USAGE", "MEMORY",
     "DISK", "NETWORK", "TOP PROCESSES"],
)
def test_render_includes_every_section(mini, needle):
    assert needle in capture(mini)


def test_processes_are_not_re_enumerated_every_frame(mini, monkeypatch):
    """Walking every process costs ~2s, far more than the 1s refresh allows.

    The first frame samples them; frames inside process_interval reuse the list
    rather than paying that cost again.
    """
    clock = [1000.0]
    monkeypatch.setattr("sysdash.cli_mini.time.monotonic", lambda: clock[0])

    capture(mini)
    assert [call["include_processes"] for call in mini.calls] == [True]

    clock[0] += 1.0
    output = capture(mini)
    assert [call["include_processes"] for call in mini.calls] == [True, False]
    # The cached list is still on screen, not blanked out.
    assert "process-0.bin" in output


def test_processes_are_resampled_once_the_interval_passes(mini, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("sysdash.cli_mini.time.monotonic", lambda: clock[0])

    capture(mini)
    clock[0] += mini.process_interval + 0.1
    capture(mini)

    assert [call["include_processes"] for call in mini.calls] == [True, True]


def test_per_nic_stats_are_skipped(mini):
    """Nothing here renders per-interface counters, so do not pay for them."""
    capture(mini)
    assert mini.calls[0]["per_nic"] is False


def test_a_failed_collection_is_reported(mini):
    mini.collector.collect_all = lambda **kwargs: {}
    assert "Error collecting metrics" in capture(mini)


def test_clear_screen_spawns_no_subprocess(monkeypatch):
    """It used to shell out to cls/clear on every single frame."""
    import sysdash.cli_mini as module

    monkeypatch.setattr(module.os, "name", "posix")
    monkeypatch.setattr(
        module.os, "system", lambda cmd: pytest.fail("must not shell out")
    )

    dashboard = MiniDashboard.__new__(MiniDashboard)
    dashboard._vt_enabled = False

    buffer = io.StringIO()
    stdout, sys.stdout = sys.stdout, buffer
    try:
        dashboard.clear_screen()
    finally:
        sys.stdout = stdout

    assert buffer.getvalue() == "\x1b[H\x1b[J"


def test_windows_enables_virtual_terminal_once(monkeypatch):
    """The no-op os.system call turns on VT processing, so do it once, not daily."""
    import sysdash.cli_mini as module

    calls = []
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.os, "system", lambda cmd: calls.append(cmd))

    dashboard = MiniDashboard.__new__(MiniDashboard)
    dashboard._vt_enabled = False

    stdout, sys.stdout = sys.stdout, io.StringIO()
    try:
        dashboard.clear_screen()
        dashboard.clear_screen()
    finally:
        sys.stdout = stdout

    assert calls == [""]


@pytest.mark.parametrize(
    "value, expected",
    [(0, "0.00 B"), (1536, "1.50 KB"), (5 * 1024 ** 2, "5.00 MB"),
     (2 * 1024 ** 3, "2.00 GB"), (3 * 1024 ** 4, "3.00 TB")],
)
def test_format_bytes(value, expected):
    dashboard = MiniDashboard.__new__(MiniDashboard)
    assert dashboard.format_bytes(value) == expected


def test_create_bar_is_full_width_at_100_percent():
    dashboard = MiniDashboard.__new__(MiniDashboard)
    assert dashboard.create_bar(100, width=10) == "█" * 10 + " 100.0%"
    assert dashboard.create_bar(0, width=10) == "░" * 10 + " 0.0%"
