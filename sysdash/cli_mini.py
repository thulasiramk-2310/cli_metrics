#!/usr/bin/env python3
"""
SysDash CLI Mini - Compact terminal monitoring
Simple, lightweight version without rich library
"""

import time
import os
import sys
from .collector import MetricsCollector, format_uptime
from .glyphs import UNICODE_GLYPHS, enable_utf8, for_stream


class MiniDashboard:
    """Minimal terminal dashboard without external dependencies"""
    
    # Enumerating every process costs ~2s, which would swamp a 1s refresh and
    # leave the bars frozen while it ran. Sample the list on its own slower
    # clock and reuse it in between.
    process_interval = 3.0

    # Class default so a bare instance still draws; __init__ picks the set
    # the real stdout can encode.
    glyphs = UNICODE_GLYPHS

    # Read as an attribute rather than os.name directly, so a test can pin
    # the platform on the instance. Patching os.name globally is what the
    # conftest warns against: pathlib reads it to pick PosixPath over
    # WindowsPath, and every later path operation then raises on Windows.
    os_name = os.name

    def __init__(self, hostname=None, interval=1.0):
        self.collector = MetricsCollector(hostname=hostname)
        self.interval = interval
        self.start_time = time.time()
        self._processes = []
        self._next_process_sample = 0.0
        self._vt_enabled = False
        self.glyphs = for_stream(sys.stdout)

    def clear_screen(self):
        """Clear the terminal.

        An escape sequence rather than os.system('cls'/'clear'): that spawned a
        process on every single frame. Homing the cursor before clearing also
        stops the screen flashing between redraws. On Windows one no-op
        os.system call first turns on virtual terminal processing, after which
        the escape works there too.
        """
        if self.os_name == 'nt' and not self._vt_enabled:
            os.system('')
            self._vt_enabled = True
        print("\x1b[H\x1b[J", end="")
    
    def format_bytes(self, bytes_value):
        """Format bytes to human readable"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.2f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.2f} PB"
    
    def create_bar(self, value, max_value=100, width=40):
        """Create ASCII progress bar"""
        filled = int((value / max_value) * width)
        bar = (self.glyphs['full'] * filled
               + self.glyphs['empty'] * (width - filled))
        return f"{bar} {value:.1f}%"
    
    def render(self):
        """Render the dashboard"""
        now = time.monotonic()
        sample_processes = now >= self._next_process_sample
        metrics = self.collector.collect_all(
            per_nic=False, include_processes=sample_processes
        )

        if not metrics:
            print("Error collecting metrics")
            return

        if sample_processes:
            self._processes = metrics['processes']
            self._next_process_sample = now + self.process_interval

        self.clear_screen()
        
        uptime_str = format_uptime(metrics['system']['uptime_seconds'])

        print("=" * 80)
        print(f"  SYSDASH CLI MINI | {self.collector.hostname} | "
              f"Up time: {uptime_str}")
        print("=" * 80)
        print()
        
        # CPU
        print("CPU USAGE:")
        cpu = metrics['cpu']['total']
        print(f"  Total: {self.create_bar(cpu)}")
        print(f"  Cores: {metrics['cpu']['cores']} cores")
        
        # Show first 4 cores
        for i, core in enumerate(metrics['cpu']['per_core'][:4]):
            print(f"    Core {i}: {core:>5.1f}%  "
                  f"{self.glyphs['full'] * int(core / 5)}")
        print()
        
        # Memory
        print("MEMORY:")
        mem = metrics['memory']
        print(f"  RAM:  {self.create_bar(mem['percent'])}")
        print(f"        {self.format_bytes(mem['used'])} / {self.format_bytes(mem['total'])}")
        print(f"  Swap: {self.create_bar(mem['swap']['percent'])}")
        print(f"        {self.format_bytes(mem['swap']['used'])} / {self.format_bytes(mem['swap']['total'])}")
        print()
        
        # Disk
        print("DISK:")
        if metrics['disk']['partitions']:
            partition = metrics['disk']['partitions'][0]
            print(f"  {partition['mountpoint']}: {self.create_bar(partition['percent'])}")
            print(f"        {self.format_bytes(partition['used'])} / {self.format_bytes(partition['total'])}")
        
        disk_io = metrics['disk']['io']
        print(f"  I/O:  Read: {self.format_bytes(disk_io['read_rate'])}/s  "
              f"Write: {self.format_bytes(disk_io['write_rate'])}/s")
        print()
        
        # Network
        print("NETWORK:")
        net = metrics['network']
        print(f"  Upload:   {self.format_bytes(net['bytes_sent_rate'])}/s")
        print(f"  Download: {self.format_bytes(net['bytes_recv_rate'])}/s")
        print(f"  Total Sent:     {self.format_bytes(net['bytes_sent'])}")
        print(f"  Total Received: {self.format_bytes(net['bytes_recv'])}")
        print()
        
        # Top Processes
        print("TOP PROCESSES:")
        print(f"  {'PID':<8} {'Name':<25} {'CPU%':<8} {'Memory%':<8}")
        print("  " + "-" * 50)
        for proc in self._processes[:5]:
            print(f"  {proc['pid']:<8} {proc['name']:<25} "
                  f"{proc['cpu']:<8.1f} {proc['memory']:<8.1f}")
        
        print()
        print("-" * 80)
        print(f"  Press Ctrl+C to exit | Update interval: {self.interval}s")
        print("-" * 80)
    
    def run(self):
        """Run the dashboard"""
        try:
            while True:
                self.render()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            self.clear_screen()
            print("\nDashboard stopped.")
        except Exception as e:
            print(f"\nError: {e}")
            raise


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="SysDash CLI Mini - Compact monitoring")
    parser.add_argument("--interval", type=float, default=1.0, help="Update interval (default: 1.0s)")
    parser.add_argument("--hostname", type=str, default=None, help="Custom hostname")
    
    args = parser.parse_args()

    # An entry point may change stdout; the dashboard itself may not.
    enable_utf8()

    dashboard = MiniDashboard(hostname=args.hostname, interval=args.interval)
    dashboard.run()


if __name__ == "__main__":
    main()
