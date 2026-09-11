"""Shared fixtures.

Every test renders against a fixed metrics dict rather than live psutil data --
snapshots of real CPU readings would differ on every run and on every machine.
"""

import io
import re
import os

import psutil
import pytest

from rich.console import Console


@pytest.fixture(autouse=True)
def no_process_priming(request, monkeypatch):
    """Stop MetricsCollector walking every process on construction.

    The constructor primes psutil's per-process CPU counters, which costs about
    two seconds a call. Tests supply their own process lists, so it is dead
    weight that made the suite take a minute.

    Tests marked ``real_psutil`` opt out, so the priming path itself stays
    covered rather than being stubbed away everywhere.
    """
    if "real_psutil" in request.keywords:
        return
    monkeypatch.setattr(psutil, "process_iter", lambda *args, **kwargs: iter(()))


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Pin the header clock so snapshots are reproducible."""
    import datetime as datetime_module

    import sysdash.cli

    fixed = datetime_module.datetime(2026, 1, 1, 12, 30, 45)

    class FrozenDateTime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(sysdash.cli, "datetime", FrozenDateTime)


@pytest.fixture(autouse=True)
def fixed_platform(monkeypatch):
    """Pin the platform so snapshots match on Windows and Linux CI alike.

    The dashboard says "Pagefile" on Windows and "Swap" elsewhere, so an
    unpinned render would produce two different snapshots for the same code.

    Only platform.system is pinned here. os.name must be left alone: pathlib
    reads it to choose PosixPath over WindowsPath, so patching it globally makes
    any later path operation raise UnsupportedOperation on Windows. The help
    panel's sudo/Administrator wording is pinned in its own test instead.
    """
    import sysdash.cli

    monkeypatch.setattr(sysdash.cli.platform, "system", lambda: "Linux")

# A history shape with a clear rise and fall, so a graph regression is visible.
CPU_HISTORY = [5.0, 12.0, 30.0, 55.0, 80.0, 62.0, 41.0, 25.0, 14.0, 8.0] * 3
MEMORY_HISTORY = [70.0, 72.0, 75.0, 79.0, 84.0, 81.0, 77.0, 74.0, 72.0, 71.0] * 3

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _rich_version():
    from importlib.metadata import version

    return f"rich {version('rich')}"


def make_metrics():
    """A complete metrics dict with stable values."""
    return {
        "timestamp": "2026-01-01T00:00:00",
        "hostname": "testhost",
        "cpu": {
            "total": 25.0,
            "per_core": [10.0, 20.0, 30.0, 40.0, 25.0, 15.0, 35.0, 45.0,
                         5.0, 50.0, 22.0, 18.0, 33.0, 27.0, 11.0, 9.0],
            "cores": 16,
            "frequency": {"current": 2400.0, "min": 400.0, "max": 4200.0},
            "load_avg": [0.5, 0.6, 0.7],
        },
        "memory": {
            "total": 16 * 1024 ** 3,
            "available": 4 * 1024 ** 3,
            "used": 12 * 1024 ** 3,
            "free": 4 * 1024 ** 3,
            "percent": 75.0,
            "swap": {
                "total": 8 * 1024 ** 3,
                "used": 1 * 1024 ** 3,
                "free": 7 * 1024 ** 3,
                "percent": 12.5,
            },
        },
        "disk": {
            "partitions": [
                {"device": "/dev/nvme0n1p2", "mountpoint": "/", "fstype": "ext4",
                 "total": 500 * 1024 ** 3, "used": 300 * 1024 ** 3,
                 "free": 200 * 1024 ** 3, "percent": 60.0},
                {"device": "/dev/nvme0n1p1", "mountpoint": "/boot", "fstype": "vfat",
                 "total": 1 * 1024 ** 3, "used": 200 * 1024 ** 2,
                 "free": 824 * 1024 ** 2, "percent": 20.0},
            ],
            "io": {
                "read_bytes": 1024 ** 3, "write_bytes": 2 * 1024 ** 3,
                "read_rate": 5 * 1024 ** 2, "write_rate": 3 * 1024 ** 2,
                "read_count": 1000, "write_count": 2000,
            },
        },
        "network": {
            "bytes_sent": 1024 ** 3,
            "bytes_recv": 2 * 1024 ** 3,
            "bytes_sent_rate": 50 * 1024,
            "bytes_recv_rate": 120 * 1024,
            "packets_sent": 123456,
            "packets_recv": 654321,
            "interfaces": {},
        },
        "gpu": None,
        "processes": [
            {"pid": 1000 + n, "name": f"process-{n}.bin",
             "cpu": 50.0 - n * 4, "memory": 10.0 - n * 0.5, "user": "tester"}
            for n in range(10)
        ],
        "system": {
            "hostname": "testhost",
            "platform": "Linux",
            "boot_time": "2026-01-01T00:00:00",
            "uptime_seconds": 93784.0,          # 1:02:03:04
            "timestamp": "2026-01-01T00:00:00",
        },
    }


@pytest.fixture
def metrics_factory():
    """Hand tests the metrics builder.

    Exposed as a fixture rather than imported: tests/ has no __init__.py, so
    "from tests.conftest import ..." only resolves when the repository root
    happens to be on sys.path, which it is not under CI.
    """
    return make_metrics


@pytest.fixture
def make_dashboard():
    """Build a CLIDashboard wired to fixed metrics, with no background threads."""
    from sysdash.cli import CLIDashboard
    from sysdash.glyphs import UNICODE_GLYPHS

    def build(**flags):
        # The header renders collector.hostname, which otherwise falls back to
        # socket.gethostname() and bakes this machine's name into every
        # snapshot. Pin it so they compare equal on any runner.
        flags.setdefault("hostname", "testhost")
        dashboard = CLIDashboard(**flags)
        metrics = make_metrics()

        # Pin the glyph set. It is otherwise chosen from the ambient stdout, so
        # a runner with no locale set would quietly swap every bar for ASCII
        # and fail every snapshot for a reason that has nothing to do with the
        # layout. The ASCII path has its own tests.
        dashboard.glyphs = UNICODE_GLYPHS

        dashboard.collector.collect_all = lambda **kwargs: make_metrics()
        # A truthy sentinel makes _ensure_process_sampler a no-op, so no thread
        # starts and the process list stays fixed.
        dashboard._sampler = "disabled"
        dashboard._cached_processes = metrics["processes"]
        dashboard.cpu_history = list(CPU_HISTORY)
        dashboard.memory_history = list(MEMORY_HISTORY)
        return dashboard

    return build


@pytest.fixture
def render():
    """Render a renderable at a fixed size and return plain text, no ANSI."""

    def do(renderable, width=110, height=32):
        console = Console(
            file=io.StringIO(), width=width, height=height,
            force_terminal=True, legacy_windows=False, color_system="truecolor",
        )
        console.print(renderable)
        text = ANSI.sub("", console.file.getvalue())
        return "\n".join(line.rstrip() for line in text.splitlines())

    return do


@pytest.fixture
def snapshot(request):
    """Compare against tests/snapshots/<name>.txt.

    Set SYSDASH_UPDATE_SNAPSHOTS=1 to rewrite them after an intentional change.
    """
    directory = os.path.join(os.path.dirname(__file__), "snapshots")

    def check(name, text):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{name}.txt")

        if os.environ.get("SYSDASH_UPDATE_SNAPSHOTS") or not os.path.exists(path):
            with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            if not os.environ.get("SYSDASH_UPDATE_SNAPSHOTS"):
                pytest.skip(f"created new snapshot {name}; re-run to check it")
            return

        with io.open(path, encoding="utf-8") as handle:
            expected = handle.read()
        assert text == expected, (
            f"render changed for {name!r}. Either the layout regressed, or rich "
            f"changed how it draws (installed: {_rich_version()}). If the new "
            f"output is correct, re-run with SYSDASH_UPDATE_SNAPSHOTS=1 and "
            f"commit the snapshot."
        )

    return check
