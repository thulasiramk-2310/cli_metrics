#!/usr/bin/env python3
"""
SysDash CLI Dashboard
Real-time terminal-based system monitoring using rich library
"""

import os
import platform
import sys
import threading
import time
from datetime import datetime
from typing import Optional

import psutil

from rich.console import Console, Group
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .collector import MetricsCollector, format_uptime
from .keys import DOWN, UP, key_reader


def swap_label(system: str) -> str:
    """What to call the swap row.

    Windows reports the pagefile (commit limit minus physical RAM), which Task
    Manager never calls swap. Takes the platform as an argument so both branches
    are testable on either OS.
    """
    return "Pagefile" if system == "Windows" else "Swap"


def privilege_name(os_name: str) -> str:
    """The name of the elevation a user needs to kill someone else's process."""
    return "Administrator" if os_name == "nt" else "sudo"


# Killing these takes the machine down with them.
PROTECTED_PIDS = frozenset({0, 1, 4})
PROTECTED_NAMES = frozenset({
    "System", "System Idle Process", "Registry", "Memory Compression",
    "kernel_task", "systemd", "init", "launchd",
})


class TrendGraph:
    """The original block line graph, sized to the space rich actually gives it.

    The drawing style is unchanged -- a solid line over a dotted field, coloured
    by trend, autoscaled between the window's own min and max. Only the sizing
    differs: it was hardcoded to 70x10 and drawn into whatever panel height was
    left over, so most of it was clipped away and the Memory series never
    appeared at all.
    """

    def __init__(self, series: list):
        # series: [(label, data, colour), ...]
        self.series = series

    def __rich_console__(self, console, options):
        width = max(8, options.max_width)
        height = options.height or 12
        count = len(self.series) or 1
        # One caption line per series; the rest of the height is split evenly.
        # Floor of one row: in a short panel every series should still draw
        # something rather than the last one silently disappearing.
        plot_height = max(1, (height - count) // count)
        budget = height

        for label, data, colour in self.series:
            if budget <= 1:
                break
            low, high = min(data), max(data)
            caption = Text(no_wrap=True, overflow="crop")
            caption.append(f"{label} ", style=f"bold {colour}")
            caption.append(f"Max: {high:.1f}%   Min: {low:.1f}%", style="dim")
            yield caption
            budget -= 1
            for line in self._plot(data, width, min(plot_height, budget)):
                yield line
                budget -= 1

    def _plot(self, data: list, width: int, height: int):
        """Draw one series, connecting samples with a solid line."""
        low, high = min(data), max(data)
        value_range = high - low if high != low else 1

        grid = [[None] * width for _ in range(height)]

        previous = None
        for x in range(width):
            # Stretch a short history across the panel, subsample a long one.
            step = len(data) / width if len(data) > width else 1
            index = min(int(x * step), len(data) - 1)

            y = int((1 - (data[index] - low) / value_range) * (height - 1))
            y = max(0, min(height - 1, y))

            if index == 0:
                colour = "cyan"
            elif data[index] > data[index - 1]:
                colour = "red"       # climbing - higher load
            elif data[index] < data[index - 1]:
                colour = "green"     # falling - recovering
            else:
                colour = "yellow"

            if previous is None:
                grid[y][x] = colour
            else:
                # Join to the previous column so steep changes stay continuous.
                for fill in range(min(previous, y), max(previous, y) + 1):
                    grid[fill][x] = colour
            previous = y

        for row in grid:
            line = Text(no_wrap=True, overflow="crop")
            for colour in row:
                if colour:
                    line.append("█", style=colour)
                else:
                    line.append("·", style="dim")
            yield line


class CoreGrid:
    """Per-core usage bars, in as many columns as the panel is wide enough for.

    Column count used to depend only on how many cores the CPU had, so a 16
    thread machine kept four columns even in a 60 column terminal and every
    cell was truncated to "0 ░░░░...". Deciding at render time means a
    resize is handled without rebuilding anything.
    """

    def __init__(self, per_core: list, colour_for):
        self.per_core = per_core
        self.colour_for = colour_for

    def __rich_console__(self, console, options):
        width = options.max_width
        # "15 " + bar + " 100%" plus a column of padding.
        for columns in (4, 3, 2, 1):
            bar_width = 8 if columns >= 3 else 10
            if columns == 1 or columns * (bar_width + 9) <= width:
                break

        cells = []
        for index, usage in enumerate(self.per_core):
            colour = self.colour_for(usage)
            filled = int(usage / 100 * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            cell = Text(no_wrap=True, overflow="crop")
            cell.append(f"{index:>2} ", style="cyan")
            cell.append(bar, style=colour)
            cell.append(f" {usage:>3.0f}%")
            cells.append(cell)

        for start in range(0, len(cells), columns):
            row = Text(no_wrap=True, overflow="crop")
            for cell in cells[start:start + columns]:
                row.append_text(cell)
                row.append(" ")
            yield row


class CLIDashboard:
    """Terminal-based dashboard using rich"""
    
    def __init__(self, hostname: Optional[str] = None, update_interval: float = 1.0, 
                 show_cpu: bool = True, show_memory: bool = True, show_disk: bool = True, 
                 show_network: bool = True, show_processes: bool = True):
        """
        Initialize the CLI dashboard
        
        Args:
            hostname: Custom hostname
            update_interval: Update interval in seconds
            show_cpu: Show CPU metrics
            show_memory: Show memory metrics
            show_disk: Show disk metrics
            show_network: Show network metrics
            show_processes: Show process list
        """
        self.console = Console()
        self.collector = MetricsCollector(hostname=hostname)
        self.update_interval = update_interval
        self.start_time = time.time()
        self.show_cpu = show_cpu
        self.show_memory = show_memory
        self.show_disk = show_disk
        self.show_network = show_network
        self.show_processes = show_processes
        
        # History for graphs (store last 60 data points)
        self.cpu_history = []
        self.memory_history = []
        self.network_sent_history = []
        self.network_recv_history = []
        self.max_history = 60

        # Enumerating every process costs ~2s and would stall the input loop, so
        # it runs on a background thread and the bars keep updating in between.
        self.process_interval = 3.0
        self._cached_processes = []
        self._process_lock = threading.Lock()
        self._sampler = None

        # Interactive state
        self.running = True
        self.selected = 0
        self.show_help = False
        self.pending_kill = None
        self.status = ""
        self._status_expiry = 0.0
        
    def _ensure_process_sampler(self):
        """Start the background process sampler once, on first use."""
        if self._sampler is not None:
            return

        def sample():
            while self.running:
                try:
                    processes = self.collector.get_process_metrics(limit=30)
                except psutil.Error:
                    processes = []
                with self._process_lock:
                    self._cached_processes = processes
                time.sleep(self.process_interval)

        self._sampler = threading.Thread(target=sample, daemon=True)
        self._sampler.start()

    def _set_status(self, message: str, seconds: float = 4.0):
        self.status = message
        self._status_expiry = time.monotonic() + seconds

    def make_layout(self) -> Layout:
        """Create the dashboard layout"""
        layout = Layout(name="root")

        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )

        # Wide panels stack on the left, narrow ones on the right.
        left_sections = []
        if self.show_cpu or self.show_memory:
            left_sections.extend(["metrics", "graph"])
        if self.show_processes:
            left_sections.append("processes")

        right_sections = []
        if self.show_disk:
            right_sections.append("disk")
        if self.show_network:
            right_sections.append("network")

        if not left_sections and not right_sections:
            layout["main"].update(
                Panel("[yellow]No metrics selected. Use flags to enable metrics.[/]")
            )
        elif left_sections and right_sections:
            layout["main"].split_row(
                Layout(name="left", ratio=2),
                Layout(name="right", ratio=1),
            )
            layout["left"].split(*[self._make_slot(name) for name in left_sections])
            layout["right"].split(*[self._make_slot(name) for name in right_sections])
        else:
            sections = left_sections or right_sections
            layout["main"].split(*[self._make_slot(name) for name in sections])

        return layout

    # Share of the column each panel gets. Ratios rather than fixed heights:
    # a fixed size cannot shrink, so on a short terminal the metrics panel used
    # to eat over half the screen and leave the graph and process list empty.
    SLOT_RATIOS = {"metrics": 3, "graph": 2, "processes": 2}

    def _make_slot(self, name: str) -> Layout:
        """Proportional slot, so every panel survives a resize."""
        return Layout(
            name=name, ratio=self.SLOT_RATIOS.get(name, 1), minimum_size=3
        )

    def create_header(self, metrics: dict) -> Panel:
        """Create header panel"""
        uptime_str = format_uptime(metrics["system"]["uptime_seconds"])

        header_text = Text()
        header_text.append("SysDash CLI", style="bold cyan")
        header_text.append(" | ", style="dim")
        header_text.append(f"Host: {self.collector.hostname}", style="bold green")
        header_text.append(" | ", style="dim")
        header_text.append(f"Up time: {uptime_str}", style="yellow")
        header_text.append(" | ", style="dim")
        header_text.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="blue")
        
        return Panel(header_text, style="bold white on blue", box=box.DOUBLE)
    
    def create_footer(self) -> Panel:
        """Create footer panel: hotkeys, or whatever needs saying right now."""
        text = Text()

        if self.pending_kill:
            name, pid = self.pending_kill
            text.append(f" Kill {name} ({pid})? ", style="bold white on red")
            for key, label in (("y", " terminate  "), ("K", " force kill  "), ("n", " cancel")):
                text.append(f"  {key}", style="bold")
                text.append(label, style="dim")
        elif self.status:
            text.append(self.status, style="bold yellow")
        else:
            for key, label in (
                ("h", "help"), ("1", "cpu"), ("2", "mem"), ("3", "disk"),
                ("4", "net"), ("5", "proc"), ("↑↓", "select"),
                ("k", "kill"), ("q", "quit"),
            ):
                text.append(f" {key}", style="bold cyan")
                text.append(f" {label} ", style="dim")

        return Panel(text, style="dim white on black")

    def create_help_panel(self) -> Panel:
        """Full-screen key reference, toggled with h."""
        table = Table(show_header=False, box=None, padding=(0, 3))
        table.add_column(style="bold cyan", justify="right")
        table.add_column()
        for key, description in (
            ("h  ?", "Show or hide this help"),
            ("1", "Toggle CPU metrics"),
            ("2", "Toggle memory metrics"),
            ("3", "Toggle disk metrics"),
            ("4", "Toggle network metrics"),
            ("5", "Toggle the process list"),
            ("↑  ↓", "Move the selection in the process list"),
            ("k", "Kill the selected process (asks first)"),
            ("y", "Confirm: terminate, letting the process clean up"),
            ("K", "Confirm: force kill, no cleanup"),
            ("n  Esc", "Cancel a pending kill"),
            ("q", "Quit"),
        ):
            table.add_row(key, description)

        privilege = privilege_name(os.name)
        note = Text(
            "\nKilling a process owned by another user needs " + privilege + ".",
            style="dim",
        )
        return Panel(
            Group(table, note), title="[bold]SysDash — Keys",
            border_style="cyan", box=box.ROUNDED,
        )
    
    def create_cpu_memory_panel(self, metrics: dict) -> Panel:
        """Create CPU and Memory metrics panel"""
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=15)
        # no_wrap: in a narrower terminal the value would otherwise fold onto a
        # second line and push the core grid out of the panel.
        table.add_column("Value", justify="right", no_wrap=True)
        table.add_column("Bar", width=26, no_wrap=True)

        # Only show CPU if enabled
        if self.show_cpu:
            # CPU
            cpu_total = metrics['cpu']['total']
            cpu_color = self._get_color_for_value(cpu_total)
            cpu_bar = self._create_bar(cpu_total, 100, cpu_color)
            table.add_row(
                "CPU",
                f"{cpu_total:.1f}%",
                cpu_bar
            )
        
        # Only show Memory if enabled
        if self.show_memory:
            # Memory
            mem_percent = metrics['memory']['percent']
            mem_color = self._get_color_for_value(mem_percent)
            mem_bar = self._create_bar(mem_percent, 100, mem_color)
            mem_used_gb = metrics['memory']['used'] / (1024**3)
            mem_total_gb = metrics['memory']['total'] / (1024**3)
            table.add_row(
                "Memory",
                f"{mem_percent:.1f}% ({mem_used_gb:.1f}/{mem_total_gb:.1f} GB)",
                mem_bar
            )
            
            # Swap. On Windows psutil reports the pagefile (commit limit minus
            # physical RAM), which Task Manager never calls "swap"; and a machine
            # with zram or no swap at all reports 0, where the row is just noise.
            swap = metrics['memory']['swap']
            if swap['total'] > 0:
                swap_percent = swap['percent']
                swap_color = self._get_color_for_value(swap_percent)
                swap_bar = self._create_bar(swap_percent, 100, swap_color)
                swap_used_gb = swap['used'] / (1024**3)
                swap_total_gb = swap['total'] / (1024**3)
                table.add_row(
                    swap_label(platform.system()),
                    f"{swap_percent:.1f}% ({swap_used_gb:.1f}/{swap_total_gb:.1f} GB)",
                    swap_bar
                )
        
        title = []
        if self.show_cpu:
            title.append("CPU")
        if self.show_memory:
            title.append("Memory")
        title_str = " & ".join(title) if title else "Metrics"

        body = [table]
        if self.show_cpu:
            body.append(self._create_core_grid(metrics['cpu']['per_core']))

        return Panel(
            Group(*body), title=f"[bold]{title_str}", border_style="green", box=box.ROUNDED
        )

    def _create_core_grid(self, per_core: list) -> "CoreGrid":
        """Per-core bars, wrapped into however many columns currently fit."""
        return CoreGrid(per_core, self._get_color_for_value)
    
    def create_graph_panel(self, metrics: dict) -> Panel:
        """Create a dedicated panel for graphs"""
        series = []
        if self.show_cpu and len(self.cpu_history) > 1:
            series.append(("CPU", self.cpu_history, "cyan"))
        if self.show_memory and len(self.memory_history) > 1:
            series.append(("Memory", self.memory_history, "magenta"))

        body = TrendGraph(series) if series else "[dim]Collecting data for graphs...[/]"
        return Panel(body, title="[bold]Usage Trends", border_style="yellow", box=box.ROUNDED)

    def create_disk_panel(self, metrics: dict) -> Panel:
        """Create disk usage panel"""
        table = Table(show_header=True, box=box.SIMPLE_HEAD, padding=(0, 1))
        # no_wrap throughout: in the narrow right-hand column the usage bar
        # otherwise folds its percentage onto a line of its own.
        table.add_column("Mount", style="cyan", width=12, no_wrap=True)
        table.add_column("Used", justify="right", width=12, no_wrap=True)
        table.add_column("Usage", width=20, no_wrap=True)
        
        for partition in metrics['disk']['partitions'][:5]:  # Show first 5 partitions
            usage = partition['percent']
            color = self._get_color_for_value(usage)
            bar = self._create_bar(usage, 100, color)
            
            used_gb = partition['used'] / (1024**3)
            total_gb = partition['total'] / (1024**3)
            
            table.add_row(
                partition['mountpoint'][:12],
                f"{used_gb:.0f}/{total_gb:.0f}GB",
                bar
            )
        
        # Disk I/O
        disk_io = metrics['disk']['io']
        read_mb = disk_io['read_rate'] / (1024**2)
        write_mb = disk_io['write_rate'] / (1024**2)
        
        table.add_row("", "", "")
        table.add_row("[bold]I/O Rates", "", "")
        table.add_row("  Read", f"{read_mb:.2f} MB/s", "")
        table.add_row("  Write", f"{write_mb:.2f} MB/s", "")
        
        return Panel(table, title="[bold]Disk Usage", border_style="yellow", box=box.ROUNDED)
    
    def create_network_panel(self, metrics: dict) -> Panel:
        """Create network statistics panel"""
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=15)
        table.add_column("Value", justify="right")
        
        net = metrics['network']
        
        # Rates
        sent_kb = net['bytes_sent_rate'] / 1024
        recv_kb = net['bytes_recv_rate'] / 1024
        
        table.add_row("[bold]Current Rates", "")
        table.add_row("  Upload", f"{sent_kb:.1f} KB/s")
        table.add_row("  Download", f"{recv_kb:.1f} KB/s")
        
        # Totals
        sent_gb = net['bytes_sent'] / (1024**3)
        recv_gb = net['bytes_recv'] / (1024**3)
        
        table.add_row("", "")
        table.add_row("[bold]Total Transfer", "")
        table.add_row("  Sent", f"{sent_gb:.2f} GB")
        table.add_row("  Received", f"{recv_gb:.2f} GB")
        
        # Packets
        table.add_row("", "")
        table.add_row("[bold]Packets", "")
        table.add_row("  Sent", f"{net['packets_sent']:,}")
        table.add_row("  Received", f"{net['packets_recv']:,}")
        
        return Panel(table, title="[bold]Network", border_style="blue", box=box.ROUNDED)
    
    def create_processes_panel(self, metrics: dict) -> Panel:
        """Create top processes panel"""
        table = Table(show_header=True, box=box.SIMPLE_HEAD, padding=(0, 1))
        table.add_column("PID", style="dim", width=8)
        table.add_column("Name", style="cyan", width=20)
        table.add_column("CPU", justify="right", width=8)
        table.add_column("Mem", justify="right", width=8)
        
        visible = metrics['processes'][:10]
        for index, proc in enumerate(visible):
            cpu_color = self._get_color_for_value(proc['cpu'])
            mem_color = self._get_color_for_value(proc['memory'])
            # The selected row is what k acts on, so it has to be obvious.
            row_style = "reverse bold" if index == self.selected else ""

            table.add_row(
                str(proc['pid']),
                proc['name'][:20],
                f"[{cpu_color}]{proc['cpu']:.1f}%[/]",
                f"[{mem_color}]{proc['memory']:.1f}%[/]",
                style=row_style,
            )

        return Panel(table, title="[bold]Top Processes", border_style="magenta", box=box.ROUNDED)
    
    def _get_color_for_value(self, value: float) -> str:
        """Get color based on value threshold"""
        if value < 50:
            return "green"
        elif value < 75:
            return "yellow"
        elif value < 90:
            return "orange3"
        else:
            return "red"
    
    def _create_bar(self, value: float, max_value: float, color: str, width: int = 20) -> str:
        """Create a text-based progress bar"""
        filled = int((value / max_value) * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{color}]{bar}[/] {value:.0f}%"
    
    def update_dashboard(self, layout: Layout):
        """Update all dashboard panels"""
        if self.show_processes:
            self._ensure_process_sampler()

        # Processes come from the background sampler, never from this call --
        # enumerating them inline would stall the loop for seconds at a time.
        metrics = self.collector.collect_all(per_nic=False, include_processes=False)

        if not metrics:
            layout["header"].update(Panel("[red]Error collecting metrics[/]"))
            return

        with self._process_lock:
            metrics["processes"] = list(self._cached_processes)

        self.selected = max(0, min(self.selected, len(metrics["processes"][:10]) - 1))
        if self.status and time.monotonic() > self._status_expiry:
            self.status = ""

        if self.show_cpu:
            self.cpu_history.append(metrics["cpu"]["total"])
            if len(self.cpu_history) > self.max_history:
                self.cpu_history.pop(0)

        if self.show_memory:
            self.memory_history.append(metrics["memory"]["percent"])
            if len(self.memory_history) > self.max_history:
                self.memory_history.pop(0)

        layout["header"].update(self.create_header(metrics))
        layout["footer"].update(self.create_footer())

        # Every enabled panel has a named slot from make_layout, so these
        # lookups cannot fail -- a KeyError here is a real bug worth surfacing.
        if self.show_cpu or self.show_memory:
            layout["metrics"].update(self.create_cpu_memory_panel(metrics))
            layout["graph"].update(self.create_graph_panel(metrics))
        if self.show_disk:
            layout["disk"].update(self.create_disk_panel(metrics))
        if self.show_network:
            layout["network"].update(self.create_network_panel(metrics))
        if self.show_processes:
            layout["processes"].update(self.create_processes_panel(metrics))

    def _selected_process(self):
        """The process the cursor is on, or None if the list is empty."""
        with self._process_lock:
            visible = self._cached_processes[:10]
        if not visible or not 0 <= self.selected < len(visible):
            return None
        return visible[self.selected]

    def _request_kill(self):
        """Stage a kill for confirmation, refusing the ones that would hurt."""
        proc = self._selected_process()
        if proc is None:
            self._set_status("No process selected")
            return

        pid, name = proc["pid"], proc["name"]
        if pid in PROTECTED_PIDS or name in PROTECTED_NAMES:
            self._set_status(f"Refusing to kill {name} ({pid}) - system process")
        elif pid == os.getpid():
            self._set_status("Refusing to kill sysdash itself - press q to quit")
        else:
            self.pending_kill = (name, pid)

    def _confirm_kill(self, force: bool):
        """Carry out the staged kill. terminate() unless force, which uses kill()."""
        if not self.pending_kill:
            return
        name, pid = self.pending_kill
        self.pending_kill = None

        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
            else:
                proc.terminate()
        except psutil.NoSuchProcess:
            self._set_status(f"{name} ({pid}) had already exited")
        except psutil.AccessDenied:
            privilege = privilege_name(os.name)
            self._set_status(f"Permission denied for {name} ({pid}) - run as {privilege}")
        except psutil.Error as exc:
            self._set_status(f"Could not kill {name} ({pid}): {exc}")
        else:
            verb = "Force killed" if force else "Terminated"
            self._set_status(f"{verb} {name} ({pid})")

    def handle_key(self, key: str) -> bool:
        """Act on a keypress. Returns True when the layout must be rebuilt."""
        # A pending confirmation swallows every other key.
        if self.pending_kill:
            if key == "y":
                self._confirm_kill(force=False)
            elif key == "K":
                self._confirm_kill(force=True)
            else:
                self.pending_kill = None
                self._set_status("Kill cancelled")
            return False

        if key in ("q", "Q"):
            self.running = False
        elif key in ("h", "H", "?"):
            self.show_help = not self.show_help
        elif key == UP:
            self.selected = max(0, self.selected - 1)
        elif key == DOWN:
            self.selected = min(9, self.selected + 1)
        elif key in ("k", "K"):
            self._request_kill()
        elif key in "12345":
            attribute = {
                "1": "show_cpu", "2": "show_memory", "3": "show_disk",
                "4": "show_network", "5": "show_processes",
            }[key]
            enabled = not getattr(self, attribute)
            setattr(self, attribute, enabled)
            # Say what happened: a panel silently vanishing reads as a bug.
            label = {"1": "CPU", "2": "Memory", "3": "Disk", "4": "Network",
                     "5": "Processes"}[key]
            self._set_status(
                f"{label} shown" if enabled else f"{label} hidden - press {key} to show"
            )
            return True

        return False

    def run(self):
        """Run the dashboard"""
        layout = self.make_layout()
        self.running = True

        try:
            with key_reader() as keys, Live(
                layout, console=self.console, screen=True, refresh_per_second=8
            ) as live:
                next_refresh = 0.0
                while self.running:
                    now = time.monotonic()
                    if now >= next_refresh:
                        self.update_dashboard(layout)
                        next_refresh = now + self.update_interval

                    key = keys.get()
                    if key is not None:
                        if self.handle_key(key):
                            layout = self.make_layout()
                            self.update_dashboard(layout)
                        live.update(self.create_help_panel() if self.show_help else layout)

                    # Poll far faster than the refresh so keys feel immediate.
                    time.sleep(0.02)

        except KeyboardInterrupt:
            self.console.print("\n[yellow]Dashboard stopped by user[/]")
        except Exception as e:
            self.console.print(f"\n[red]Error: {e}[/]")
            raise
        finally:
            self.running = False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="SysDash CLI - Terminal-based system monitoring dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings (all metrics)
  python cli.py
  
  # Show only CPU metrics
  python cli.py --cpu-only
  
  # Show only disk metrics
  python cli.py --disk-only
  
  # Show CPU and disk only
  python cli.py --no-memory --no-network --no-processes
  
  # Show everything except processes
  python cli.py --no-processes
  
  # Update every 0.5 seconds
  python cli.py --interval 0.5
  
  # Custom hostname
  python cli.py --hostname production-server-01
        """
    )
    
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Update interval in seconds (default: 1.0)"
    )
    
    parser.add_argument(
        "--hostname",
        type=str,
        default=None,
        help="Custom hostname (default: system hostname)"
    )
    
    # Metric selection arguments
    parser.add_argument(
        "--cpu-only",
        action="store_true",
        help="Show only CPU metrics"
    )
    
    parser.add_argument(
        "--memory-only",
        action="store_true",
        help="Show only memory metrics"
    )
    
    parser.add_argument(
        "--disk-only",
        action="store_true",
        help="Show only disk metrics"
    )
    
    parser.add_argument(
        "--network-only",
        action="store_true",
        help="Show only network metrics"
    )
    
    parser.add_argument(
        "--processes-only",
        action="store_true",
        help="Show only process list"
    )
    
    parser.add_argument(
        "--no-cpu",
        action="store_true",
        help="Hide CPU metrics"
    )
    
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Hide memory metrics"
    )
    
    parser.add_argument(
        "--no-disk",
        action="store_true",
        help="Hide disk metrics"
    )
    
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Hide network metrics"
    )
    
    parser.add_argument(
        "--no-processes",
        action="store_true",
        help="Hide process list"
    )
    
    args = parser.parse_args()
    
    # Validate interval
    if args.interval < 0.1:
        print("Error: Interval must be at least 0.1 seconds")
        sys.exit(1)
    
    # Determine which metrics to show
    show_cpu = True
    show_memory = True
    show_disk = True
    show_network = True
    show_processes = True
    
    # Handle "only" flags
    if args.cpu_only:
        show_cpu = True
        show_memory = show_disk = show_network = show_processes = False
    elif args.memory_only:
        show_memory = True
        show_cpu = show_disk = show_network = show_processes = False
    elif args.disk_only:
        show_disk = True
        show_cpu = show_memory = show_network = show_processes = False
    elif args.network_only:
        show_network = True
        show_cpu = show_memory = show_disk = show_processes = False
    elif args.processes_only:
        show_processes = True
        show_cpu = show_memory = show_disk = show_network = False
    else:
        # Handle "no" flags
        if args.no_cpu:
            show_cpu = False
        if args.no_memory:
            show_memory = False
        if args.no_disk:
            show_disk = False
        if args.no_network:
            show_network = False
        if args.no_processes:
            show_processes = False
    
    # Create and run dashboard
    dashboard = CLIDashboard(
        hostname=args.hostname,
        update_interval=args.interval,
        show_cpu=show_cpu,
        show_memory=show_memory,
        show_disk=show_disk,
        show_network=show_network,
        show_processes=show_processes
    )
    
    dashboard.run()


if __name__ == "__main__":
    main()
