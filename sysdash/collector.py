

import psutil
import time
import socket
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Optional dependency for backend integration
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# A library must not configure the root logger -- that is the application's
# job, and doing it here also writes INFO lines over the live dashboard.
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# Filesystems that duplicate real storage or report meaningless sizes. Without
# this the disk panel on Linux fills up with snap/flatpak loop mounts, tmpfs and
# the pseudo-filesystems, pushing the real partitions off the panel.
PSEUDO_FSTYPES = frozenset({
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs",
    "devpts", "devtmpfs", "efivarfs", "fusectl", "hugetlbfs", "mqueue", "proc",
    "pstore", "ramfs", "securityfs", "squashfs", "sysfs", "tmpfs", "tracefs",
})


def format_uptime(seconds: float) -> str:
    """Format uptime the way Windows Task Manager does (d:hh:mm:ss)."""
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days > 0:
        return f"{days}:{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours}:{minutes:02d}:{secs:02d}"


class MetricsCollector:
    """Collects system metrics using psutil"""
    
    def __init__(self, hostname: Optional[str] = None):
        """
        Initialize the metrics collector
        
        Args:
            hostname: Custom hostname (defaults to system hostname)
        """
        self.hostname = hostname or socket.gethostname()

        now = time.time()
        self.last_net_io = psutil.net_io_counters()
        self.last_disk_io = psutil.disk_io_counters()
        self.last_net_time = now
        self.last_disk_time = now

        # Both CPU readings are deltas against the previous call, so take a
        # baseline now; without it the first sample would read 0%.
        psutil.cpu_percent(interval=None, percpu=True)
        for _ in psutil.process_iter(['cpu_percent']):
            pass

        logger.info(f"Initialized MetricsCollector for host: {self.hostname}")
    
    def get_cpu_metrics(self) -> Dict:
        """Collect CPU metrics"""
        # interval=None measures since the previous call instead of sleeping, so
        # a refresh no longer blocks for 100ms and the UI stays responsive to
        # keypresses. Calls closer together than a few hundred ms read as noise.
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        cpu_freq = psutil.cpu_freq()
        cpu_count = psutil.cpu_count()

        return {
            "total": sum(per_core) / len(per_core) if per_core else 0.0,
            "per_core": per_core,
            "cores": cpu_count,
            "frequency": {
                "current": cpu_freq.current if cpu_freq else 0,
                "min": cpu_freq.min if cpu_freq else 0,
                "max": cpu_freq.max if cpu_freq else 0
            },
            "load_avg": list(psutil.getloadavg()) if hasattr(psutil, 'getloadavg') else [0, 0, 0]
        }
    
    def get_memory_metrics(self) -> Dict:
        """Collect memory metrics"""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            "total": mem.total,
            "available": mem.available,
            "used": mem.used,
            "free": mem.free,
            "percent": mem.percent,
            "swap": {
                "total": swap.total,
                "used": swap.used,
                "free": swap.free,
                "percent": swap.percent
            }
        }
    
    def get_disk_metrics(self) -> Dict:
        """Collect disk metrics"""
        current_time = time.time()
        time_delta = current_time - self.last_disk_time
        
        # Disk usage
        partitions = []
        seen_devices = set()
        for partition in psutil.disk_partitions(all=False):
            fstype = (partition.fstype or "").lower()
            is_root = partition.mountpoint == "/"

            # The root filesystem is always kept, even when it is an overlay or
            # composefs image as on immutable distros (ArkaOS, Silverblue) --
            # otherwise the panel shows every partition except the one that matters.
            if not is_root:
                if fstype in PSEUDO_FSTYPES or fstype.startswith("fuse."):
                    continue
                # snap/flatpak loop mounts re-report storage already counted
                if partition.device.startswith("/dev/loop"):
                    continue
                # bind mounts and subvolumes report the same device repeatedly
                if partition.device in seen_devices:
                    continue

            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except OSError:
                # Unreadable mount: no permission, or an empty optical/removable
                # drive, which raises a plain OSError (WinError 21) on Windows.
                continue

            seen_devices.add(partition.device)
            partitions.append({
                "device": partition.device,
                "mountpoint": partition.mountpoint,
                "fstype": partition.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent
            })

        # Root first, then largest: on a dual-boot box the Windows partition must
        # never outrank "/" for the handful of slots the panel actually shows.
        partitions.sort(key=lambda part: (part["mountpoint"] != "/", -part["total"]))
        
        # Disk I/O
        current_disk_io = psutil.disk_io_counters()
        if current_disk_io and self.last_disk_io and time_delta > 0:
            read_rate = (current_disk_io.read_bytes - self.last_disk_io.read_bytes) / time_delta
            write_rate = (current_disk_io.write_bytes - self.last_disk_io.write_bytes) / time_delta
        else:
            read_rate = 0
            write_rate = 0
        
        self.last_disk_io = current_disk_io
        self.last_disk_time = current_time
        
        return {
            "partitions": partitions,
            "io": {
                "read_bytes": current_disk_io.read_bytes if current_disk_io else 0,
                "write_bytes": current_disk_io.write_bytes if current_disk_io else 0,
                "read_rate": read_rate,
                "write_rate": write_rate,
                "read_count": current_disk_io.read_count if current_disk_io else 0,
                "write_count": current_disk_io.write_count if current_disk_io else 0
            }
        }
    
    def get_network_metrics(self, per_nic: bool = True) -> Dict:
        """Collect network metrics"""
        current_time = time.time()
        time_delta = current_time - self.last_net_time
        
        current_net_io = psutil.net_io_counters()
        
        # Calculate rates
        if self.last_net_io and time_delta > 0:
            bytes_sent_rate = (current_net_io.bytes_sent - self.last_net_io.bytes_sent) / time_delta
            bytes_recv_rate = (current_net_io.bytes_recv - self.last_net_io.bytes_recv) / time_delta
        else:
            bytes_sent_rate = 0
            bytes_recv_rate = 0
        
        self.last_net_io = current_net_io
        self.last_net_time = current_time
        
        # Per-interface stats are only consumed by MetricsSender; the dashboards
        # never render them, so let callers skip the work.
        interfaces = {}
        if per_nic:
            for interface, stats in psutil.net_io_counters(pernic=True).items():
                interfaces[interface] = {
                    "bytes_sent": stats.bytes_sent,
                    "bytes_recv": stats.bytes_recv,
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                    "errin": stats.errin,
                    "errout": stats.errout,
                    "dropin": stats.dropin,
                    "dropout": stats.dropout
                }
        
        return {
            "bytes_sent": current_net_io.bytes_sent,
            "bytes_recv": current_net_io.bytes_recv,
            "bytes_sent_rate": bytes_sent_rate,
            "bytes_recv_rate": bytes_recv_rate,
            "packets_sent": current_net_io.packets_sent,
            "packets_recv": current_net_io.packets_recv,
            "interfaces": interfaces
        }
    
    def get_gpu_metrics(self) -> Optional[Dict]:
        """GPU metrics, which are not collected yet.

        None rather than a dict of zeros: nothing here reads a GPU, and a
        consumer cannot tell "no GPU support" from "an idle GPU at 0%" once the
        zeros are recorded as if they were real readings.

        To implement, plug in py3nvml (NVIDIA), pyadl (AMD) or GPUtil and return
        usage, temperature and memory from it.
        """
        return None
    
    def get_process_metrics(self, limit: int = 10, include_username: bool = False) -> List[Dict]:
        """
        Collect top processes by CPU and memory usage

        Args:
            limit: Number of top processes to return
            include_username: Resolve the owning user. Off by default because it
                opens a token per process (~360ms for 380 processes on Windows)
                and neither dashboard renders it.
        """
        attrs = ['pid', 'name', 'cpu_percent', 'memory_percent']
        if include_username:
            attrs.append('username')

        processes = []
        for proc in psutil.process_iter(attrs):
            try:
                pinfo = proc.info
                processes.append({
                    "pid": pinfo['pid'],
                    "name": pinfo['name'],
                    "cpu": pinfo['cpu_percent'] or 0,
                    "memory": pinfo['memory_percent'] or 0,
                    "user": pinfo.get('username') or "unknown"
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        # Sort by CPU usage and return top N
        processes.sort(key=lambda x: x['cpu'], reverse=True)
        return processes[:limit]
    
    def get_system_info(self) -> Dict:
        """Collect general system information"""
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time
        
        # Get platform name
        import platform as platform_module
        platform_name = platform_module.system()  # Windows, Linux, Darwin, etc.
        
        return {
            "hostname": self.hostname,
            "platform": platform_name,
            "boot_time": datetime.fromtimestamp(boot_time).isoformat(),
            "uptime_seconds": uptime_seconds,
            "timestamp": datetime.now().isoformat()
        }
    
    def collect_all(self, per_nic: bool = True, include_processes: bool = True) -> Dict:
        """Collect all metrics and return as JSON-serializable dict"""
        try:
            metrics = {
                "timestamp": datetime.now().isoformat(),
                "hostname": self.hostname,
                "cpu": self.get_cpu_metrics(),
                "memory": self.get_memory_metrics(),
                "disk": self.get_disk_metrics(),
                "network": self.get_network_metrics(per_nic=per_nic),
                "gpu": self.get_gpu_metrics(),
                "processes": self.get_process_metrics() if include_processes else [],
                "system": self.get_system_info()
            }
            
            logger.debug(f"Collected metrics: CPU={metrics['cpu']['total']:.1f}%, "
                        f"Memory={metrics['memory']['percent']:.1f}%")
            
            return metrics
        except (OSError, psutil.Error) as e:
            logger.error(f"Error collecting metrics: {e}")
            return {}


class MetricsSender:
    """Sends collected metrics to Go backend (requires 'requests' library)"""
    
    def __init__(self, backend_url: str = "http://localhost:8080", timeout: int = 5):
        """
        Initialize the metrics sender
        
        Args:
            backend_url: URL of the Go backend server
            timeout: HTTP request timeout in seconds
        """
        if not HAS_REQUESTS:
            raise ImportError("requests library is required for MetricsSender. Install with: pip install requests")
        self.backend_url = backend_url.rstrip('/')
        self.metrics_endpoint = f"{self.backend_url}/api/metrics"
        self.timeout = timeout
        
        logger.info(f"Initialized MetricsSender for backend: {self.backend_url}")
    
    def send_metrics(self, metrics: Dict) -> bool:
        """
        Send metrics to backend via HTTP POST
        
        Args:
            metrics: Metrics dictionary to send
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.post(
                self.metrics_endpoint,
                json=metrics,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                logger.debug(f"Successfully sent metrics to {self.metrics_endpoint}")
                return True
            else:
                logger.warning(f"Failed to send metrics: HTTP {response.status_code}")
                return False
                
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to backend at {self.backend_url}")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout after {self.timeout}s")
            return False
        except requests.exceptions.RequestException as e:
            # Narrower than a bare Exception: a TypeError from an unserialisable
            # metrics dict is a bug here, not a transport failure to log and
            # shrug off.
            logger.error(f"Error sending metrics: {e}")
            return False
    
    def check_backend_health(self) -> bool:
        """Check if backend is reachable"""
        try:
            response = requests.get(
                f"{self.backend_url}/health",
                timeout=self.timeout
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False


def run_collector(interval: int = 2, backend_url: str = "http://localhost:8080"):
    """
    Main collection loop
    
    Args:
        interval: Collection interval in seconds
        backend_url: URL of the Go backend server
    """
    collector = MetricsCollector()
    sender = MetricsSender(backend_url)
    
    logger.info(f"Starting metrics collection (interval: {interval}s)")
    logger.info(f"Backend URL: {backend_url}")
    
    # Check backend availability
    if not sender.check_backend_health():
        logger.warning("Backend is not available. Metrics will be collected but not sent.")
    
    try:
        while True:
            # Collect metrics
            metrics = collector.collect_all()
            
            if metrics:
                # Send to backend
                sender.send_metrics(metrics)
                
                # Print summary
                print(f"\r[{datetime.now().strftime('%H:%M:%S')}] "
                      f"CPU: {metrics['cpu']['total']:.1f}% | "
                      f"Memory: {metrics['memory']['percent']:.1f}% | "
                      f"Disk I/O: ↑{metrics['disk']['io']['write_rate']/1024/1024:.2f}MB/s "
                      f"↓{metrics['disk']['io']['read_rate']/1024/1024:.2f}MB/s | "
                      f"Network: ↑{metrics['network']['bytes_sent_rate']/1024:.1f}KB/s "
                      f"↓{metrics['network']['bytes_recv_rate']/1024:.1f}KB/s",
                      end='', flush=True)
            
            # Wait for next interval
            time.sleep(interval)
            
    except KeyboardInterrupt:
        logger.info("\nStopping metrics collection...")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="System Metrics Collector")
    parser.add_argument(
        "--interval",
        type=int,
        default=2,
        help="Collection interval in seconds (default: 2)"
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="http://localhost:8080",
        help="Backend server URL (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--hostname",
        type=str,
        default=None,
        help="Custom hostname (default: system hostname)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    run_collector(interval=args.interval, backend_url=args.backend)
