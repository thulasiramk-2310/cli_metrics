#!/usr/bin/env python3
"""
SysDash diagnostic - run this on the machine where the numbers look wrong:

    python3 scripts/diagnose.py

It prints what psutil reports next to what the system tools report, so the
discrepancy can be identified instead of guessed at. Paste the whole output.
"""

import os
import platform
import shutil
import subprocess
import sys
import warnings


def sh(cmd):
    """Run a shell command, returning its output or a short failure note."""
    exe = cmd.split()[0]
    if shutil.which(exe) is None:
        return f"<{exe} not installed>"
    try:
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        ).stdout.strip() or "<no output>"
    except subprocess.SubprocessError as exc:
        return f"<failed: {exc}>"


def gb(n):
    return f"{n / 1024 ** 3:8.2f} GiB"


def header(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main():
    caught = []
    warnings.simplefilter("always")

    header("ENVIRONMENT")
    import psutil

    print(f"  platform      : {platform.platform()}")
    print(f"  python        : {sys.version.split()[0]}")
    print(f"  psutil        : {psutil.__version__}")
    print(f"  kernel        : {sh('uname -r')}")
    # Single quotes inside: sh() already runs through a shell, and with double
    # quotes that outer shell expanded $PRETTY_NAME itself -- to nothing --
    # before the inner one ever sourced the file. Every report said "<no
    # output>" for the one field that identifies the distro.
    distro = sh("sh -c '. /etc/os-release 2>/dev/null && echo $PRETTY_NAME'")
    print(f"  distro        : {distro}")
    print(f"  container/imm : ostree={os.path.exists('/run/ostree-booted')} "
          f"composefs={os.path.exists('/run/composefs')} "
          f"docker={os.path.exists('/.dockerenv')}")
    print(f"  root fs ro    : {sh('findmnt -no OPTIONS /') }")

    header("MEMORY - psutil vs the kernel")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        caught.extend(w)

    print("  psutil.virtual_memory():")
    for field in mem._fields:
        print(f"    {field:<12} {gb(getattr(mem, field)) if field != 'percent' else f'{mem.percent:8.1f} %'}")
    print(f"\n  sysdash would display: {mem.percent:.1f}%  "
          f"({mem.used / 1024**3:.1f}/{mem.total / 1024**3:.1f} GB)")
    print(f"  consistency check    : used/total = {mem.used / mem.total * 100:.1f}%  "
          f"vs percent = {mem.percent:.1f}%  "
          f"-> {'MATCH' if abs(mem.used / mem.total * 100 - mem.percent) < 1 else 'MISMATCH <<<<'}")

    print(f"\n  psutil.swap_memory(): total={gb(swap.total)} used={gb(swap.used)} pct={swap.percent}")
    print(f"\n  $ free -h\n{sh('free -h')}")
    print("\n  /proc/meminfo (key lines):")
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.split(":")[0] in ("MemTotal", "MemFree", "MemAvailable",
                                          "Buffers", "Cached", "SReclaimable",
                                          "Shmem", "SwapTotal", "SwapFree"):
                    print("    " + line.rstrip())
    except OSError as exc:
        print(f"    <unavailable: {exc}>")

    header("DISK - what the panel will show")
    print("  psutil.disk_partitions(all=False):")
    for part in psutil.disk_partitions(all=False):
        try:
            use = psutil.disk_usage(part.mountpoint)
            size = f"{gb(use.total)} used={use.percent:5.1f}%"
        except OSError as exc:
            size = f"<{type(exc).__name__}: {exc}>"
        print(f"    {part.device:<28} {part.mountpoint:<24} {part.fstype:<10} {size}")

    try:
        from sysdash.collector import MetricsCollector
        print("\n  after sysdash filtering (what the panel actually renders):")
        for part in MetricsCollector().get_disk_metrics()["partitions"]:
            print(f"    {part['device']:<28} {part['mountpoint']:<24} "
                  f"{part['fstype']:<10} {gb(part['total'])} used={part['percent']:5.1f}%")
    except ImportError as exc:
        print(f"\n  <sysdash not importable from here: {exc}>")

    print(f"\n  $ df -h -x tmpfs -x devtmpfs\n{sh('df -h -x tmpfs -x devtmpfs')}")

    header("CPU")
    print(f"  logical cores : {psutil.cpu_count()}   physical: {psutil.cpu_count(logical=False)}")
    per_core = psutil.cpu_percent(interval=0.3, percpu=True)
    print(f"  per-core (%)  : {[round(c, 1) for c in per_core]}")
    print(f"  derived total : {sum(per_core) / len(per_core):.1f}%")
    try:
        print(f"  load average  : {[round(x, 2) for x in psutil.getloadavg()]}")
    except (OSError, AttributeError) as exc:
        print(f"  load average  : <unavailable: {exc}>")
    try:
        temps = psutil.sensors_temperatures()
        print(f"  sensors       : {list(temps) or '<none exposed>'}")
    except (AttributeError, OSError) as exc:
        print(f"  sensors       : <unavailable: {exc}>")

    header("WARNINGS RAISED BY PSUTIL")
    if caught:
        for w in caught:
            print(f"  {w.category.__name__}: {w.message}")
        print("\n  ^ these print over the live dashboard and corrupt it.")
    else:
        print("  none")

    print("\nDone - please paste everything above.\n")


if __name__ == "__main__":
    main()
