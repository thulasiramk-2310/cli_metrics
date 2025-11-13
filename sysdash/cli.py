#!/usr/bin/env python3
"""
SysDash CLI Dashboard
Real-time terminal-based system monitoring using rich library
"""

import time
import sys
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from .collector import MetricsCollector


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
        
        # For candlestick: store OHLC (Open, High, Low, Close) data
        self.cpu_candles = []  # Each item: {'open', 'high', 'low', 'close'}
        self.memory_candles = []
        self.candle_interval = 5  # Group every 5 data points into one candle
        self.temp_cpu_values = []
        self.temp_memory_values = []
        
    def make_layout(self) -> Layout:
        """Create the dashboard layout"""
        layout = Layout(name="root")
        
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )
        
        # Build dynamic layout based on what's enabled
        sections = []
        
        # Add metrics section if CPU or memory is enabled
        if self.show_cpu or self.show_memory:
            sections.append("metrics")
        
        # Add right panel sections if disk or network is enabled
        if self.show_disk:
            sections.append("disk")
        if self.show_network:
            sections.append("network")
            
        # Add processes if enabled
        if self.show_processes:
            sections.append("processes")
        
        # Create layout based on enabled sections
        if len(sections) == 0:
            layout["main"].update(Panel("[yellow]No metrics selected. Use flags to enable metrics.[/]"))
        elif len(sections) == 1:
            # Single section - just use main layout with the section name
            layout["main"]._name = sections[0]
        elif len(sections) == 2:
            layout["main"].split_row(
                Layout(name=sections[0]),
                Layout(name=sections[1]),
            )
        else:
            # Complex layout with multiple sections
            layout["main"].split_row(
                Layout(name="left", ratio=2),
                Layout(name="right", ratio=1),
            )
            
            left_sections = []
            right_sections = []
            
            if "metrics" in sections:
                left_sections.append("metrics")
            if "processes" in sections:
                left_sections.append("processes")
            if "disk" in sections:
                right_sections.append("disk")
            if "network" in sections:
                right_sections.append("network")
            
            # Add graph section to left
            if self.show_cpu or self.show_memory:
                left_sections.append("graph")
            
            if len(left_sections) == 1:
                layout["left"].update(Layout(name=left_sections[0]))
            elif len(left_sections) > 1:
                layout["left"].split(
                    *[Layout(name=name) for name in left_sections]
                )
            
            if len(right_sections) == 1:
                layout["right"].update(Layout(name=right_sections[0]))
            elif len(right_sections) > 1:
                layout["right"].split(
                    *[Layout(name=name) for name in right_sections]
                )
        
        return layout
    
    def create_header(self) -> Panel:
        """Create header panel"""
        uptime = int(time.time() - self.start_time)
        hours = uptime // 3600
        minutes = (uptime % 3600) // 60
        seconds = uptime % 60
        
        header_text = Text()
        header_text.append("SysDash CLI", style="bold cyan")
        header_text.append(" | ", style="dim")
        header_text.append(f"Host: {self.collector.hostname}", style="bold green")
        header_text.append(" | ", style="dim")
        header_text.append(f"Uptime: {hours:02d}:{minutes:02d}:{seconds:02d}", style="yellow")
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
            
            # Swap
            swap_percent = metrics['memory']['swap']['percent']
            swap_color = self._get_color_for_value(swap_percent)
            swap_bar = self._create_bar(swap_percent, 100, swap_color)
            swap_used_gb = metrics['memory']['swap']['used'] / (1024**3)
            swap_total_gb = metrics['memory']['swap']['total'] / (1024**3)
            table.add_row(
                "Swap",
                f"{swap_percent:.1f}% ({swap_used_gb:.1f}/{swap_total_gb:.1f} GB)",
                swap_bar
            )
        
        # CPU Cores (only if CPU is enabled)
        if self.show_cpu:
            table.add_row("", "", "")  # Spacer
            table.add_row("[bold]CPU Cores", "", "")
            for i, core_usage in enumerate(metrics['cpu']['per_core'][:8]):  # Show first 8 cores
                core_color = self._get_color_for_value(core_usage)
                core_bar = self._create_bar(core_usage, 100, core_color)
                table.add_row(
                    f"  Core {i}",
                    f"{core_usage:.1f}%",
                    core_bar
                )
        
        title = []
        if self.show_cpu:
            title.append("CPU")
        if self.show_memory:
            title.append("Memory")
        title_str = " & ".join(title) if title else "Metrics"
        
        return Panel(table, title=f"[bold]{title_str}", border_style="green", box=box.ROUNDED)
    
    def create_graph_panel(self, metrics: dict) -> Panel:
        """Create a dedicated panel for graphs"""
        table = Table(show_header=False, box=None, padding=(0, 1), expand=True)
        table.add_column("Graph", style="white", no_wrap=False)
        
        # CPU graph
        if self.show_cpu and len(self.cpu_history) > 5:
            table.add_row(Text("📈 CPU Usage Trend", style="bold cyan"))
            graph_lines = self._create_sparkline(self.cpu_history, width=70, height=10)
            for line in graph_lines.split('\n'):
                table.add_row(Text.from_markup(line))
        
        # Memory graph
        if self.show_memory and len(self.memory_history) > 5:
            table.add_row("")  # Spacer
            table.add_row(Text("📊 Memory Usage Trend", style="bold magenta"))
            graph_lines = self._create_sparkline(self.memory_history, width=70, height=10)
            for line in graph_lines.split('\n'):
                table.add_row(Text.from_markup(line))
        
        if table.row_count == 0:
            return Panel("[dim]Collecting data for graphs...[/]", title="[bold]Usage Trends", border_style="yellow", box=box.ROUNDED)
        
        return Panel(table, title="[bold]Usage Trends", border_style="yellow", box=box.ROUNDED)
    
    def create_disk_panel(self, metrics: dict) -> Panel:
        """Create disk usage panel"""
        table = Table(show_header=True, box=box.SIMPLE_HEAD, padding=(0, 1))
        table.add_column("Device", style="cyan", width=12)
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
    
    def _create_candlestick_chart(self, candles: list, width: int = 70, height: int = 12) -> str:
        """Create a candlestick chart like trading platforms"""
        if not candles or len(candles) < 1:
            return "[dim]Collecting data for candlestick chart...[/]"
        
        # Limit to last 5 candles for better visibility
        candles = candles[-5:] if len(candles) > 5 else candles
        
        # Get all values for scaling
        all_values = []
        for c in candles:
            all_values.extend([c['high'], c['low']])
        
        max_val = max(all_values)
        min_val = min(all_values)
        value_range = max_val - min_val if max_val != min_val else 1
        
        # Create 2D grid
        grid = [[' ' for _ in range(width)] for _ in range(height)]
        colors = [[None for _ in range(width)] for _ in range(height)]
        
        # Calculate positions for candles - center them with good spacing
        candle_width = 8  # Fixed width for each candle body
        total_spacing = width - (len(candles) * candle_width)
        spacing = total_spacing // (len(candles) + 1) if len(candles) > 0 else 5
        
        # Draw each candle
        for idx, candle in enumerate(candles):
            x_start = spacing + idx * (candle_width + spacing)
            x_center = x_start + candle_width // 2
            
            if x_start + candle_width >= width:
                break
            
            open_val = candle['open']
            close_val = candle['close']
            high_val = candle['high']
            low_val = candle['low']
            
            # Normalize positions (inverted for display)
            open_y = int((1 - (open_val - min_val) / value_range) * (height - 1))
            close_y = int((1 - (close_val - min_val) / value_range) * (height - 1))
            high_y = int((1 - (high_val - min_val) / value_range) * (height - 1))
            low_y = int((1 - (low_val - min_val) / value_range) * (height - 1))
            
            # Clamp values
            open_y = max(0, min(height - 1, open_y))
            close_y = max(0, min(height - 1, close_y))
            high_y = max(0, min(height - 1, high_y))
            low_y = max(0, min(height - 1, low_y))
            
            # Determine color: green if close > open (bullish), red if close < open (bearish)
            is_bullish = close_val >= open_val
            color = "green" if is_bullish else "red"
            
            # Draw upper wick (high to top of body)
            body_top = min(open_y, close_y)
            for y in range(high_y, body_top):
                if 0 <= y < height:
                    grid[y][x_center] = '│'
                    colors[y][x_center] = color
            
            # Draw body (open to close)
            body_bottom = max(open_y, close_y)
            
            # Ensure body has at least 1 pixel height
            if body_top == body_bottom:
                body_bottom = min(body_top + 1, height - 1)
            
            for y in range(body_top, body_bottom + 1):
                if 0 <= y < height:
                    for dx in range(candle_width):
                        x = x_start + dx
                        if x < width:
                            grid[y][x] = '█'
                            colors[y][x] = color
            
            # Draw lower wick (bottom of body to low)
            for y in range(body_bottom + 1, low_y + 1):
                if 0 <= y < height:
                    grid[y][x_center] = '│'
                    colors[y][x_center] = color
        
        # Build output with colors and Y-axis labels
        lines = []
        for h in range(height):
            # Add Y-axis value label
            y_value = min_val + (1 - h / (height - 1)) * value_range
            y_label = f"{y_value:5.1f}% │ "
            
            line_chars = [y_label]
            for w in range(width):
                char = grid[h][w]
                color = colors[h][w]
                if char != ' ' and color:
                    line_chars.append(f"[{color}]{char}[/]")
                elif char == ' ':
                    line_chars.append(f"[dim]·[/]")
                else:
                    line_chars.append(char)
            lines.append("".join(line_chars))
        
        # Add X-axis
        x_axis = "       └" + "─" * width
        lines.append(x_axis)
        
        # Add legend with better formatting
        legend = f"        [bold]Legend:[/] [green]█ Bullish (Up)[/] [dim]│[/] [red]█ Bearish (Down)[/] [dim]│[/] [dim]│ Wick (High/Low)[/]"
        info = f"        [dim]Showing {len(candles)} candle{'s' if len(candles) > 1 else ''} | Range: {min_val:.1f}% - {max_val:.1f}%[/]"
        
        return "\n".join(lines) + "\n" + legend + "\n" + info
    
    def _create_sparkline(self, data: list, width: int = 60, height: int = 10) -> str:
        """Create a smooth line graph like stock market charts"""
        if not data or len(data) < 2:
            return "No data"
        
        # Normalize data to height
        max_val = max(data)
        min_val = min(data)
        value_range = max_val - min_val if max_val != min_val else 1
        
        # Create 2D grid
        grid = [[' ' for _ in range(width)] for _ in range(height)]
        colors = [[None for _ in range(width)] for _ in range(height)]
        
        # Plot points and connect them with lines
        step = len(data) / width if len(data) > width else 1
        prev_x, prev_y = None, None
        
        for i in range(width):
            data_index = min(int(i * step), len(data) - 1)
            value = data[data_index]
            
            # Normalize to 0-1 range
            normalized = (value - min_val) / value_range
            
            # Convert to height position (inverted for display)
            y = int((1 - normalized) * (height - 1))
            y = max(0, min(height - 1, y))
            
            # Determine color based on trend (reversed: red for up, green for down)
            if data_index > 0:
                if data[data_index] > data[data_index - 1]:
                    color = "red"  # Going up (higher usage - bad)
                elif data[data_index] < data[data_index - 1]:
                    color = "green"  # Going down (lower usage - good)
                else:
                    color = "yellow"  # Flat
            else:
                color = "cyan"
            
            # Draw line from previous point to current
            if prev_x is not None:
                # Bresenham's line algorithm for smooth lines
                x0, y0 = prev_x, prev_y
                x1, y1 = i, y
                
                dx = abs(x1 - x0)
                dy = abs(y1 - y0)
                sx = 1 if x0 < x1 else -1
                sy = 1 if y0 < y1 else -1
                err = dx - dy
                
                cx, cy = x0, y0
                while True:
                    if 0 <= cx < width and 0 <= cy < height:
                        grid[cy][cx] = '█'
                        colors[cy][cx] = color
                    
                    if cx == x1 and cy == y1:
                        break
                    
                    e2 = 2 * err
                    if e2 > -dy:
                        err -= dy
                        cx += sx
                    if e2 < dx:
                        err += dx
                        cy += sy
            else:
                # First point
                grid[y][i] = '█'
                colors[y][i] = color
            
            prev_x, prev_y = i, y
        
        # Build output with colors
        lines = []
        for h in range(height):
            line_chars = []
            for w in range(width):
                char = grid[h][w]
                color = colors[h][w]
                if char == '█' and color:
                    line_chars.append(f"[{color}]{char}[/]")
                elif char == ' ':
                    line_chars.append(f"[dim]·[/]")
                else:
                    line_chars.append(char)
            lines.append("".join(line_chars))
        
        # Add axis info
        header = f"[bold]Max: {max_val:.1f}%[/]"
        footer = f"[bold]Min: {min_val:.1f}%[/]"
        
        return header + "\n" + "\n".join(lines) + "\n" + footer
    
    def _create_bar(self, value: float, max_value: float, color: str, width: int = 20) -> str:
        """Create a text-based progress bar"""
        filled = int((value / max_value) * width)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{color}]{bar}[/] {value:.0f}%"
    
    def update_dashboard(self, layout: Layout):
        """Update all dashboard panels"""
        try:
            metrics = self.collector.collect_all()
            
            if not metrics:
                layout["header"].update(Panel("[red]Error collecting metrics[/]"))
                return
            
            # Update history data
            if self.show_cpu:
                cpu_value = metrics['cpu']['total']
                self.cpu_history.append(cpu_value)
                if len(self.cpu_history) > self.max_history:
                    self.cpu_history.pop(0)
                
                # Build candlestick data
                self.temp_cpu_values.append(cpu_value)
                if len(self.temp_cpu_values) >= self.candle_interval:
                    # Create a new candle
                    candle = {
                        'open': self.temp_cpu_values[0],
                        'high': max(self.temp_cpu_values),
                        'low': min(self.temp_cpu_values),
                        'close': self.temp_cpu_values[-1]
                    }
                    self.cpu_candles.append(candle)
                    self.temp_cpu_values = []
                    
                    # Keep only last 20 candles
                    if len(self.cpu_candles) > 20:
                        self.cpu_candles.pop(0)
            
            if self.show_memory:
                mem_value = metrics['memory']['percent']
                self.memory_history.append(mem_value)
                if len(self.memory_history) > self.max_history:
                    self.memory_history.pop(0)
                
                # Build candlestick data
                self.temp_memory_values.append(mem_value)
                if len(self.temp_memory_values) >= self.candle_interval:
                    candle = {
                        'open': self.temp_memory_values[0],
                        'high': max(self.temp_memory_values),
                        'low': min(self.temp_memory_values),
                        'close': self.temp_memory_values[-1]
                    }
                    self.memory_candles.append(candle)
                    self.temp_memory_values = []
                    
                    if len(self.memory_candles) > 20:
                        self.memory_candles.pop(0)
            
            layout["header"].update(self.create_header())
            layout["footer"].update(self.create_footer())
            
            # Only update panels that are enabled
            if self.show_cpu or self.show_memory:
                try:
                    layout["metrics"].update(self.create_cpu_memory_panel(metrics))
                except KeyError:
                    # If metrics section doesn't exist, try updating main directly
                    try:
                        layout["main"].update(self.create_cpu_memory_panel(metrics))
                    except:
                        pass
                
                # Update graph panel
                try:
                    layout["graph"].update(self.create_graph_panel(metrics))
                except KeyError:
                    pass
                    
            if self.show_disk:
                try:
                    layout["disk"].update(self.create_disk_panel(metrics))
                except KeyError:
                    try:
                        layout["main"].update(self.create_disk_panel(metrics))
                    except:
                        pass
                    
            if self.show_network:
                try:
                    layout["network"].update(self.create_network_panel(metrics))
                except KeyError:
                    try:
                        layout["main"].update(self.create_network_panel(metrics))
                    except:
                        pass
                    
            if self.show_processes:
                try:
                    layout["processes"].update(self.create_processes_panel(metrics))
                except KeyError:
                    try:
                        layout["main"].update(self.create_processes_panel(metrics))
                    except:
                        pass
            
        except Exception as e:
            layout["header"].update(Panel(f"[red]Error: {e}[/]"))
    
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
