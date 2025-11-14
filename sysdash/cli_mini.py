#!/usr/bin/env python3
"""
SysDash CLI Mini - Compact terminal monitoring
Simple, lightweight version without rich library
"""

import time
import sys
import os
from datetime import datetime
from .collector import MetricsCollector


class MiniDashboard:
    """Minimal terminal dashboard without external dependencies"""
    
    def __init__(self, hostname=None, interval=1.0):
        self.collector = MetricsCollector(hostname=hostname)
        self.interval = interval
        self.start_time = time.time()
    
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
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
        bar = '█' * filled + '░' * (width - filled)
        return f"{bar} {value:.1f}%"
    
    def render(self):
        """Render the dashboard"""
        metrics = self.collector.collect_all()
        
        if not metrics:
            print("Error collecting metrics")
            return
        
        self.clear_screen()
        
        # Header
        import psutil
        boot_time = psutil.boot_time()
        system_uptime = int(time.time() - boot_time)
        sys_hours = system_uptime // 3600
        sys_minutes = (system_uptime % 3600) // 60
        
        # CPU time
        cpu_times = psutil.cpu_times()
        total_cpu_time = cpu_times.user + cpu_times.system
        cpu_hours = int(total_cpu_time // 3600)
        cpu_minutes = int((total_cpu_time % 3600) // 60)
        
        print("=" * 80)
        print(f"  SYSDASH CLI MINI | {self.collector.hostname} | "
              f"System: {sys_hours}h {sys_minutes}m | CPU Time: {cpu_hours}h {cpu_minutes}m")
        print("=" * 80)
        print()
        
        # CPU
        print("CPU USAGE:")
        cpu = metrics['cpu']['total']
        print(f"  Total: {self.create_bar(cpu)}")
        print(f"  Cores: {metrics['cpu']['cores']} cores")
        
        # Show first 4 cores
        for i, core in enumerate(metrics['cpu']['per_core'][:4]):
            print(f"    Core {i}: {core:>5.1f}%  {'█' * int(core/5)}")
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
        for proc in metrics['processes'][:5]:
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
    
    dashboard = MiniDashboard(hostname=args.hostname, interval=args.interval)
    dashboard.run()


if __name__ == "__main__":
    main()
