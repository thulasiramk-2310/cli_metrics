#!/usr/bin/env python3
"""
SysDash CLI Dashboard
Real-time terminal-based system monitoring using rich library
"""

import math
import platform
import sys
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


class TrendGraph:
    """A braille line graph that sizes itself to whatever space rich gives it.

    The previous graph was hardcoded to 70x10 and drawn into whatever panel
    height happened to be left over, so most of it was clipped away and the
    rest was padding. Braille cells pack 2x4 dots per character, so the same
    panel now carries eight times the detail.
    """

    # Bit mask of each braille dot, indexed as _DOTS[column][row] in a 2x4 cell.
    _DOTS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

    def __init__(self, series: list, scale: float = 100.0):
        # series: [(label, data, colour), ...]
        self.series = series
        self.scale = scale

    def __rich_console__(self, console, options):
        width = max(8, options.max_width)
        height = options.height or 12
        count = len(self.series) or 1
        # Each series gets a caption line; the rest of the height is split evenly.
        # A single braille row still resolves four levels, so in a short panel it
        # is better to shrink every plot than to clip the last series away.
        plot_height = max(1, (height - count) // count)
        budget = height

        for label, data, colour in self.series:
            if budget <= 1:
                break
            latest = data[-1] if data else 0.0
            peak = max(data) if data else 0.0
            caption = Text(no_wrap=True, overflow="crop")
            caption.append(f"{label} ", style=f"bold {colour}")
            caption.append(f"now {latest:5.1f}%   peak {peak:5.1f}%", style="dim")
            yield caption
            budget -= 1
            for line in self._plot(data, width, min(plot_height, budget)):
                yield line
                budget -= 1

    def _plot(self, data: list, width: int, height: int):
        """Render one series as braille rows, newest sample at the right edge."""
        dot_width, dot_height = width * 2, height * 4
        cells = [[0] * width for _ in range(height)]

        previous = None
        for x in range(dot_width):
            index = len(data) - dot_width + x
            if index < 0:
                # Not enough history yet: leave the left of the graph empty
                # rather than smearing the oldest sample across it.
                continue
            value = min(max(data[index], 0.0), self.scale)
            y = int((1 - value / self.scale) * (dot_height - 1))
            # Join to the previous column so steep changes stay a continuous line.
            span = range(min(previous, y), max(previous, y) + 1) if previous is not None else (y,)
            for fill in span:
                cells[fill // 4][x // 2] |= self._DOTS[x % 2][fill % 4]
            previous = y

        for row, cell_row in enumerate(cells):
            # Colour by height so a spike reads as red without extra work.
            band = 1 - row / max(1, height - 1)
            style = "red" if band > 0.75 else "yellow" if band > 0.5 else "green"
            yield Text(
                "".join(chr(0x2800 + cell) for cell in cell_row),
                style=style, no_wrap=True, overflow="crop",
            )


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

        # Enumerating every process costs ~2s and dominates a refresh, so it runs
        # on its own slower cadence and the bars keep updating in between.
        self.process_interval = 3.0
        self._last_process_sample = 0.0
        self._cached_processes = []
        
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

    @staticmethod
    def _core_columns(count: int) -> int:
        """Wrap the core grid so a many-thread CPU still fits a normal panel."""
        if count > 12:
            return 4
        if count > 4:
            return 2
        return 1

    def _make_slot(self, name: str) -> Layout:
        """Give the metrics panel exactly the height its rows need.

        Splitting the column evenly starved it: on a 16-thread CPU only two
        cores fitted, and the graph was left with too little room to read.
        """
        if name != "metrics":
            return Layout(name=name, ratio=1)

        rows = (1 if self.show_cpu else 0) + (2 if self.show_memory else 0)
        if self.show_cpu:
            cores = psutil.cpu_count() or 1
            rows += math.ceil(cores / self._core_columns(cores))
        return Layout(name=name, size=rows + 4)

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
        """Create footer panel"""
        footer_text = Text()
        footer_text.append("Press ", style="dim")
        footer_text.append("Ctrl+C", style="bold red")
        footer_text.append(" to exit", style="dim")
        footer_text.append(" | ", style="dim")
        footer_text.append(f"Update: {self.update_interval}s", style="dim")
        
        return Panel(footer_text, style="dim white on black")
    
    def create_cpu_memory_panel(self, metrics: dict) -> Panel:
        """Create CPU and Memory metrics panel"""
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
        table.add_column("Metric", style="cyan", width=15)
        table.add_column("Value", justify="right")
        table.add_column("Bar", width=30)
        
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
                    "Pagefile" if platform.system() == "Windows" else "Swap",
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

    def _create_core_grid(self, per_core: list) -> Table:
        """Lay per-core usage out in columns, htop style.

        One row per core overflows the panel on any machine with more than a
        handful of threads, so wrap into columns instead of hiding cores.
        """
        columns = self._core_columns(len(per_core))
        bar_width = 8 if columns >= 4 else 10
        grid = Table.grid(padding=(0, 1))
        for _ in range(columns):
            grid.add_column(no_wrap=True)

        cells = []
        for index, usage in enumerate(per_core):
            color = self._get_color_for_value(usage)
            bar = self._create_bar(usage, 100, color, width=bar_width)
            cells.append(f"[cyan]{index:>2}[/] {bar}")

        # Pad the final row so the grid stays rectangular.
        if len(cells) % columns:
            cells.extend([""] * (columns - len(cells) % columns))

        for start in range(0, len(cells), columns):
            grid.add_row(*cells[start:start + columns])

        return grid
    
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
        table.add_column("Mount", style="cyan", width=12)
        table.add_column("Used", justify="right", width=12)
        table.add_column("Usage", width=20)
        
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
        
        for proc in metrics['processes'][:10]:
            cpu_color = self._get_color_for_value(proc['cpu'])
            mem_color = self._get_color_for_value(proc['memory'])
            
            table.add_row(
                str(proc['pid']),
                proc['name'][:20],
                f"[{cpu_color}]{proc['cpu']:.1f}%[/]",
                f"[{mem_color}]{proc['memory']:.1f}%[/]"
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
        now = time.monotonic()
        sample_processes = (
            self.show_processes
            and now - self._last_process_sample >= self.process_interval
        )
        metrics = self.collector.collect_all(
            per_nic=False, include_processes=sample_processes
        )

        if not metrics:
            layout["header"].update(Panel("[red]Error collecting metrics[/]"))
            return

        if sample_processes:
            self._cached_processes = metrics["processes"]
            self._last_process_sample = now
        else:
            metrics["processes"] = self._cached_processes

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

    def run(self):
        """Run the dashboard"""
        layout = self.make_layout()
        
        try:
            with Live(layout, console=self.console, screen=True, refresh_per_second=4) as live:
                while True:
                    self.update_dashboard(layout)
                    time.sleep(self.update_interval)
                    
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Dashboard stopped by user[/]")
        except Exception as e:
            self.console.print(f"\n[red]Error: {e}[/]")
            raise


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
