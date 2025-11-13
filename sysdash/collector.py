#!/usr/bin/env python3
"""
System Metrics Collector
Collects real-time system metrics using psutil and sends to Go backend
"""

import psutil
import json
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects system metrics using psutil"""
    
    def __init__(self, hostname: Optional[str] = None):
        """
        Initialize the metrics collector
        
        Args:
            hostname: Custom hostname (defaults to system hostname)
        """
        self.hostname = hostname or socket.gethostname()
        self.last_net_io = psutil.net_io_counters()
        self.last_disk_io = psutil.disk_io_counters()
        self.last_time = time.time()
        
        logger.info(f"Initialized MetricsCollector for host: {self.hostname}")
    
    def get_cpu_metrics(self) -> Dict:
        """Collect CPU metrics"""
        cpu_percent = psutil.cpu_percent(interval=0.1, percpu=True)
        cpu_freq = psutil.cpu_freq()
        cpu_count = psutil.cpu_count()
        
        return {
            "total": psutil.cpu_percent(interval=0.1),
            "per_core": cpu_percent,
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
        time_delta = current_time - self.last_time
        
        # Disk usage
        partitions = []
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                partitions.append({
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "fstype": partition.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent
                })
            except PermissionError:
                continue
        
        # Disk I/O
        current_disk_io = psutil.disk_io_counters()
        if current_disk_io and self.last_disk_io and time_delta > 0:
            read_rate = (current_disk_io.read_bytes - self.last_disk_io.read_bytes) / time_delta
            write_rate = (current_disk_io.write_bytes - self.last_disk_io.write_bytes) / time_delta
        else:
            read_rate = 0
            write_rate = 0
        
        self.last_disk_io = current_disk_io
        
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
    
    def get_network_metrics(self) -> Dict:
        """Collect network metrics"""
        current_time = time.time()
        time_delta = current_time - self.last_time
        
        current_net_io = psutil.net_io_counters()
        
        # Calculate rates
        if self.last_net_io and time_delta > 0:
            bytes_sent_rate = (current_net_io.bytes_sent - self.last_net_io.bytes_sent) / time_delta
            bytes_recv_rate = (current_net_io.bytes_recv - self.last_net_io.bytes_recv) / time_delta
        else:
            bytes_sent_rate = 0
            bytes_recv_rate = 0
        
        self.last_net_io = current_net_io
        self.last_time = current_time
        
        # Get per-interface stats
        interfaces = {}
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
    
    def get_gpu_metrics(self) -> Dict:
        """
        Collect GPU metrics (placeholder)
        For real GPU monitoring, integrate libraries like:
        - py3nvml (NVIDIA)
        - pyadl (AMD)
        - GPUtil
        """
        return {
            "usage": 0,
            "temperature": 0,
            "memory": {
                "total": 0,
                "used": 0,
                "percent": 0
            }
        }
    
    def get_process_metrics(self, limit: int = 10) -> List[Dict]:
        """
        Collect top processes by CPU and memory usage
        
        Args:
            limit: Number of top processes to return
        """
        processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'username']):
            try:
                pinfo = proc.info
                processes.append({
                    "pid": pinfo['pid'],
                    "name": pinfo['name'],
                    "cpu": pinfo['cpu_percent'] or 0,
                    "memory": pinfo['memory_percent'] or 0,
                    "user": pinfo['username'] or "unknown"
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
    
    def collect_all(self) -> Dict:
        """Collect all metrics and return as JSON-serializable dict"""
        try:
            metrics = {
                "timestamp": datetime.now().isoformat(),
                "hostname": self.hostname,
                "cpu": self.get_cpu_metrics(),
                "memory": self.get_memory_metrics(),
                "disk": self.get_disk_metrics(),
                "network": self.get_network_metrics(),
                "gpu": self.get_gpu_metrics(),
                "processes": self.get_process_metrics(),
                "system": self.get_system_info()
            }
            
            logger.debug(f"Collected metrics: CPU={metrics['cpu']['total']:.1f}%, "
                        f"Memory={metrics['memory']['percent']:.1f}%")
            
            return metrics
        except Exception as e:
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
        except Exception as e:
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
        except:
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
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


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
