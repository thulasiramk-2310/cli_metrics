"""Dashboard tests: layout shape, snapshot renders, hotkeys and the kill path."""

import os

import psutil
import pytest

from sysdash.keys import DOWN, UP


def slot_names(layout):
    """Every named slot in a layout tree."""
    names = []

    def walk(node):
        if node.name:
            names.append(node.name)
        for child in node.children:
            walk(child)

    walk(layout)
    return names


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "flags, expected",
    [
        ({}, {"metrics", "graph", "processes", "disk", "network"}),
        (dict(show_memory=False, show_disk=False, show_network=False,
              show_processes=False), {"metrics", "graph"}),
        (dict(show_cpu=False, show_memory=False, show_network=False,
              show_processes=False), {"disk"}),
        (dict(show_processes=False), {"metrics", "graph", "disk", "network"}),
    ],
)
def test_every_enabled_panel_gets_a_named_slot(make_dashboard, flags, expected):
    """update_dashboard indexes these by name; a missing slot is a KeyError."""
    dashboard = make_dashboard(**flags)
    names = set(slot_names(dashboard.make_layout()))

    assert expected <= names


def test_cpu_only_still_gets_a_graph_slot(make_dashboard):
    """The graph used to exist only when three or more panels were enabled."""
    dashboard = make_dashboard(
        show_memory=False, show_disk=False, show_network=False, show_processes=False
    )
    assert "graph" in slot_names(dashboard.make_layout())


def test_no_panels_enabled_renders_a_message(make_dashboard, render):
    dashboard = make_dashboard(
        show_cpu=False, show_memory=False, show_disk=False,
        show_network=False, show_processes=False,
    )
    layout = dashboard.make_layout()
    dashboard.update_dashboard(layout)

    assert "No metrics selected" in render(layout)


def test_update_dashboard_does_not_swallow_errors(make_dashboard):
    """Panel errors used to be hidden behind a bare except."""
    dashboard = make_dashboard()
    layout = dashboard.make_layout()

    def explode(metrics):
        raise RuntimeError("boom")

    dashboard.create_disk_panel = explode
    with pytest.raises(RuntimeError, match="boom"):
        dashboard.update_dashboard(layout)


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------

@pytest.mark.parametrize("width", [80, 110, 200])
def test_full_dashboard_snapshot(make_dashboard, render, snapshot, width):
    """Catches layout regressions -- the value-wrapping bug showed up at 110."""
    dashboard = make_dashboard()
    layout = dashboard.make_layout()
    dashboard.update_dashboard(layout)

    snapshot(f"dashboard_{width}", render(layout, width=width, height=34))


@pytest.mark.parametrize("width", [80, 110, 200])
def test_metric_values_never_wrap(make_dashboard, render, width):
    """A wrapped value pushes the core grid out of the panel."""
    dashboard = make_dashboard()
    layout = dashboard.make_layout()
    dashboard.update_dashboard(layout)
    text = render(layout, width=width, height=34)

    # A wrap left an orphan "(x/y GB)" fragment on its own line.
    for line in text.splitlines():
        stripped = line.strip().strip("│").strip()
        assert not stripped.startswith("("), f"value wrapped at width {width}: {line!r}"


def test_all_cores_are_rendered(make_dashboard, render):
    """The panel used to hard-cap at the first eight cores."""
    dashboard = make_dashboard()
    layout = dashboard.make_layout()
    dashboard.update_dashboard(layout)
    text = render(layout, width=200, height=40)

    for index in range(16):
        assert f"{index:>2} " in text or f" {index} " in text


def test_help_panel_snapshot(make_dashboard, render, snapshot, monkeypatch):
    """Pin the privilege wording here rather than globally: patching os.name
    for the whole suite breaks pathlib on Windows."""
    import sysdash.cli

    monkeypatch.setattr(sysdash.cli, "privilege_name", lambda os_name: "sudo")
    dashboard = make_dashboard()
    snapshot("help_panel", render(dashboard.create_help_panel(), width=78, height=20))


# --------------------------------------------------------------------------
# Hotkeys
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key, attribute, label",
    [("1", "show_cpu", "CPU"), ("2", "show_memory", "Memory"),
     ("3", "show_disk", "Disk"), ("4", "show_network", "Network"),
     ("5", "show_processes", "Processes")],
)
def test_number_keys_toggle_and_report(make_dashboard, key, attribute, label):
    dashboard = make_dashboard()
    assert getattr(dashboard, attribute) is True

    assert dashboard.handle_key(key) is True, "toggling must rebuild the layout"
    assert getattr(dashboard, attribute) is False
    assert label in dashboard.status and "press" in dashboard.status

    dashboard.handle_key(key)
    assert getattr(dashboard, attribute) is True
    assert dashboard.status == f"{label} shown"


def test_quit_stops_the_loop(make_dashboard):
    dashboard = make_dashboard()
    dashboard.handle_key("q")
    assert dashboard.running is False


def test_help_toggles(make_dashboard):
    dashboard = make_dashboard()
    dashboard.handle_key("h")
    assert dashboard.show_help is True
    dashboard.handle_key("h")
    assert dashboard.show_help is False


def test_selection_moves_and_clamps(make_dashboard):
    dashboard = make_dashboard()
    dashboard.selected = 0

    dashboard.handle_key(UP)
    assert dashboard.selected == 0, "must not move above the first row"

    for _ in range(3):
        dashboard.handle_key(DOWN)
    assert dashboard.selected == 3

    for _ in range(50):
        dashboard.handle_key(DOWN)
    assert dashboard.selected == 9, "must not run past the visible ten"


# --------------------------------------------------------------------------
# Kill
# --------------------------------------------------------------------------

def test_kill_refuses_system_processes(make_dashboard):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": 4, "name": "System", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0
    dashboard.handle_key("k")

    assert dashboard.pending_kill is None
    assert "Refusing" in dashboard.status


def test_kill_refuses_itself(make_dashboard):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": os.getpid(), "name": "python", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0
    dashboard.handle_key("k")

    assert dashboard.pending_kill is None
    assert "sysdash itself" in dashboard.status


def test_kill_asks_before_acting(make_dashboard, monkeypatch):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": 4321, "name": "victim", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0

    calls = []

    class FakeProcess:
        def __init__(self, pid):
            calls.append(pid)

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(psutil, "Process", FakeProcess)

    dashboard.handle_key("k")
    assert dashboard.pending_kill == ("victim", 4321)
    assert calls == [], "nothing may die before confirmation"

    dashboard.handle_key("y")
    assert calls == [4321, "terminate"]
    assert dashboard.pending_kill is None
    assert "Terminated" in dashboard.status


def test_force_kill_uses_kill(make_dashboard, monkeypatch):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": 4321, "name": "victim", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0
    calls = []

    class FakeProcess:
        def __init__(self, pid):
            pass

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(psutil, "Process", FakeProcess)
    dashboard.handle_key("k")
    dashboard.handle_key("K")

    assert calls == ["kill"]
    assert "Force killed" in dashboard.status


def test_kill_can_be_cancelled(make_dashboard, monkeypatch):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": 4321, "name": "victim", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0

    def forbidden(pid):
        raise AssertionError("cancelling must not touch the process")

    monkeypatch.setattr(psutil, "Process", forbidden)
    dashboard.handle_key("k")
    dashboard.handle_key("n")

    assert dashboard.pending_kill is None
    assert "cancelled" in dashboard.status.lower()


def test_permission_denied_names_the_privilege(make_dashboard, monkeypatch):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": 4321, "name": "rootproc", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0

    class Denied:
        def __init__(self, pid):
            pass

        def terminate(self):
            raise psutil.AccessDenied(4321)

    monkeypatch.setattr(psutil, "Process", Denied)
    dashboard.handle_key("k")
    dashboard.handle_key("y")

    expected = "Administrator" if os.name == "nt" else "sudo"
    assert expected in dashboard.status


def test_killing_a_dead_process_is_reported(make_dashboard, monkeypatch):
    dashboard = make_dashboard()
    dashboard._cached_processes = [
        {"pid": 99999, "name": "ghost", "cpu": 0.0, "memory": 0.0}
    ]
    dashboard.selected = 0

    class Gone:
        def __init__(self, pid):
            raise psutil.NoSuchProcess(99999)

    monkeypatch.setattr(psutil, "Process", Gone)
    dashboard.handle_key("k")
    dashboard.handle_key("y")

    assert "already exited" in dashboard.status


# --------------------------------------------------------------------------
# Platform-specific labels
#
# Snapshots are pinned to Linux for determinism, so these branches would
# otherwise have no coverage on any CI leg. Calling the logic directly keeps
# both branches tested on both platforms.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "system, expected",
    [("Windows", "Pagefile"), ("Linux", "Swap"), ("Darwin", "Swap"), ("", "Swap")],
)
def test_swap_label_per_platform(system, expected):
    from sysdash.cli import swap_label

    assert swap_label(system) == expected


@pytest.mark.parametrize(
    "os_name, expected", [("nt", "Administrator"), ("posix", "sudo")]
)
def test_privilege_name_per_platform(os_name, expected):
    from sysdash.cli import privilege_name

    assert privilege_name(os_name) == expected


def test_windows_swap_row_says_pagefile(make_dashboard, render, monkeypatch):
    """The Windows branch end to end, forced on regardless of the host OS."""
    import sysdash.cli

    monkeypatch.setattr(sysdash.cli.platform, "system", lambda: "Windows")
    dashboard = make_dashboard()
    layout = dashboard.make_layout()
    dashboard.update_dashboard(layout)
    text = render(layout, width=200, height=34)

    assert "Pagefile" in text and "Swap" not in text


def test_swap_row_hidden_when_there_is_no_swap(make_dashboard, render):
    """Arch with zram or no swap reports 0; the row is then just noise."""
    from tests.conftest import make_metrics

    def no_swap(**kwargs):
        metrics = make_metrics()
        metrics["memory"]["swap"] = {"total": 0, "used": 0, "free": 0, "percent": 0.0}
        return metrics

    dashboard = make_dashboard()
    dashboard.collector.collect_all = no_swap
    layout = dashboard.make_layout()
    dashboard.update_dashboard(layout)
    text = render(layout, width=200, height=34)

    assert "Swap" not in text and "Pagefile" not in text
