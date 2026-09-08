"""Collector tests: the metric maths, and the Linux filesystem filtering."""

import collections

import psutil
import pytest

from sysdash.collector import MetricsCollector, format_uptime


FakePart = collections.namedtuple("FakePart", "device mountpoint fstype opts")
FakeUsage = collections.namedtuple("FakeUsage", "total used free percent")


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0:00:00"),
        (59, "0:00:59"),
        (3661, "1:01:01"),
        (86400, "1:00:00:00"),
        (93784, "1:02:03:04"),
        (911045, "10:13:04:05"),
    ],
)
def test_format_uptime(seconds, expected):
    """Days only appear once there is at least one, matching Task Manager."""
    assert format_uptime(seconds) == expected


def test_cpu_total_matches_per_core(monkeypatch):
    """total must be the mean of per_core: they used to be sampled separately."""
    monkeypatch.setattr(psutil, "cpu_percent", lambda **kw: [10.0, 20.0, 30.0, 40.0])
    monkeypatch.setattr(psutil, "cpu_freq", lambda: None)
    monkeypatch.setattr(psutil, "cpu_count", lambda: 4)

    metrics = MetricsCollector.get_cpu_metrics(object.__new__(MetricsCollector))
    assert metrics["total"] == pytest.approx(25.0)
    assert metrics["per_core"] == [10.0, 20.0, 30.0, 40.0]


def test_cpu_total_survives_empty_per_core(monkeypatch):
    """An empty reading must not raise ZeroDivisionError."""
    monkeypatch.setattr(psutil, "cpu_percent", lambda **kw: [])
    monkeypatch.setattr(psutil, "cpu_freq", lambda: None)
    monkeypatch.setattr(psutil, "cpu_count", lambda: 0)

    metrics = MetricsCollector.get_cpu_metrics(object.__new__(MetricsCollector))
    assert metrics["total"] == 0.0


def _disk_setup(monkeypatch, partitions, usages):
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=False: partitions)

    def disk_usage(mountpoint):
        result = usages[mountpoint]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(psutil, "disk_usage", disk_usage)
    monkeypatch.setattr(psutil, "disk_io_counters", lambda: None)


def test_disk_filters_a_dual_boot_linux_box(monkeypatch):
    """Loop mounts and tmpfs must not crowd the real partitions off the panel."""
    partitions = [
        FakePart("/dev/loop0", "/snap/core/1", "squashfs", "ro"),
        FakePart("/dev/loop1", "/snap/code/2", "squashfs", "ro"),
        FakePart("tmpfs", "/run", "tmpfs", "rw"),
        FakePart("/dev/nvme0n1p3", "/windows", "ntfs", "rw"),
        FakePart("/dev/nvme0n1p2", "/", "ext4", "rw"),
        FakePart("/dev/nvme0n1p1", "/boot/efi", "vfat", "rw"),
    ]
    usages = {
        "/snap/core/1": FakeUsage(100 * 1024 ** 2, 100 * 1024 ** 2, 0, 100.0),
        "/snap/code/2": FakeUsage(100 * 1024 ** 2, 100 * 1024 ** 2, 0, 100.0),
        "/run": FakeUsage(8 * 1024 ** 3, 1024 ** 2, 8 * 1024 ** 3, 0.1),
        "/windows": FakeUsage(900 * 1024 ** 3, 500 * 1024 ** 3, 400 * 1024 ** 3, 55.0),
        "/": FakeUsage(400 * 1024 ** 3, 200 * 1024 ** 3, 200 * 1024 ** 3, 50.0),
        "/boot/efi": FakeUsage(1024 ** 3, 100 * 1024 ** 2, 900 * 1024 ** 2, 10.0),
    }
    _disk_setup(monkeypatch, partitions, usages)

    collector = object.__new__(MetricsCollector)
    collector.last_disk_time = 0.0
    collector.last_disk_io = None
    mounts = [p["mountpoint"] for p in collector.get_disk_metrics()["partitions"]]

    assert "/snap/core/1" not in mounts and "/snap/code/2" not in mounts
    assert "/run" not in mounts
    # Root first: on a dual-boot box Windows must never outrank it.
    assert mounts[0] == "/"
    assert "/windows" in mounts and "/boot/efi" in mounts


def test_disk_keeps_an_overlay_root(monkeypatch):
    """Immutable distros (ArkaOS, Silverblue) mount / as overlay/composefs."""
    partitions = [
        FakePart("overlay", "/", "overlay", "ro"),
        FakePart("tmpfs", "/tmp", "tmpfs", "rw"),
    ]
    usages = {
        "/": FakeUsage(200 * 1024 ** 3, 50 * 1024 ** 3, 150 * 1024 ** 3, 25.0),
        "/tmp": FakeUsage(4 * 1024 ** 3, 1024 ** 2, 4 * 1024 ** 3, 0.1),
    }
    _disk_setup(monkeypatch, partitions, usages)

    collector = object.__new__(MetricsCollector)
    collector.last_disk_time = 0.0
    collector.last_disk_io = None
    mounts = [p["mountpoint"] for p in collector.get_disk_metrics()["partitions"]]

    assert mounts == ["/"], "the overlay root must survive the pseudo-fs filter"


def test_disk_skips_unreadable_mounts(monkeypatch):
    """An empty optical drive raises OSError on Windows, not PermissionError."""
    partitions = [
        FakePart("D:\\", "D:\\", "", ""),
        FakePart("C:\\", "C:\\", "NTFS", "rw"),
    ]
    usages = {
        "D:\\": OSError(21, "The device is not ready"),
        "C:\\": FakeUsage(500 * 1024 ** 3, 250 * 1024 ** 3, 250 * 1024 ** 3, 50.0),
    }
    _disk_setup(monkeypatch, partitions, usages)

    collector = object.__new__(MetricsCollector)
    collector.last_disk_time = 0.0
    collector.last_disk_io = None
    mounts = [p["mountpoint"] for p in collector.get_disk_metrics()["partitions"]]

    assert mounts == ["C:\\"]


def test_disk_and_network_keep_separate_clocks():
    """Disk rates used to depend on get_network_metrics having run first."""
    collector = MetricsCollector()
    before = collector.last_net_time
    collector.get_disk_metrics()

    assert collector.last_net_time == before, "disk must not touch the network clock"
    assert collector.last_disk_time > 0


def test_collect_all_can_skip_the_expensive_parts():
    collector = MetricsCollector()
    metrics = collector.collect_all(per_nic=False, include_processes=False)

    assert metrics["processes"] == []
    assert metrics["network"]["interfaces"] == {}
    # The keys stay present so the backend contract does not change shape.
    assert set(metrics) >= {"cpu", "memory", "disk", "network", "processes", "system"}


def test_module_import_does_not_configure_root_logging():
    """A library hijacking the root logger writes over the live dashboard.

    Checked in a subprocess: pytest attaches its own handlers to the root
    logger, so an in-process assertion would always fail.
    """
    import subprocess
    import sys

    script = (
        "import logging, sysdash.collector as c; "
        "print(len(logging.getLogger().handlers), "
        "any(isinstance(h, logging.NullHandler) for h in c.logger.handlers))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    root_handlers, has_null_handler = result.stdout.split()

    assert root_handlers == "0", "importing the collector must not call basicConfig"
    assert has_null_handler == "True"


def test_constructor_takes_a_cpu_baseline(monkeypatch):
    """The constructor must sample cpu_percent to establish a baseline.

    get_cpu_metrics uses interval=None, which measures against the previous
    call. psutil captures its own baseline at import, so a missing constructor
    sample does not show up as a 0% reading -- it shows up as the first reading
    being an average over however long ago psutil was imported, rather than a
    fresh window. That is invisible to a value assertion, so the call itself is
    what gets checked here.
    """
    calls = []
    real_cpu_percent = psutil.cpu_percent

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real_cpu_percent(*args, **kwargs)

    monkeypatch.setattr(psutil, "cpu_percent", spy)
    MetricsCollector()

    assert any(
        call.get("interval") is None and call.get("percpu") for call in calls
    ), "constructor did not prime the per-core CPU baseline"


@pytest.mark.real_psutil
def test_real_construction_produces_a_plausible_reading():
    """Integration smoke test over the path the rest of the suite stubs out.

    Covers the real constructor, including the ~2s process priming, and checks
    the readings that come back are shaped and scaled sensibly.
    """
    import time

    collector = MetricsCollector()

    # Give the sampler something real to measure.
    deadline = time.time() + 0.4
    while time.time() < deadline:
        pass

    metrics = collector.get_cpu_metrics()

    assert len(metrics["per_core"]) == psutil.cpu_count()
    assert all(0.0 <= core <= 100.0 for core in metrics["per_core"])
    assert metrics["total"] == pytest.approx(
        sum(metrics["per_core"]) / len(metrics["per_core"])
    )
    assert metrics["total"] > 0.0, "a busy loop should register as CPU usage"
