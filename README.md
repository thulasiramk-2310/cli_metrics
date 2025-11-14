# SysDash - Real-Time System Monitoring Dashboard

Real-time terminal-based system monitoring with beautiful graphs and customizable views.

## Installation

### Option 1: Install from PyPI (using pip)
```bash
pip install git+https://github.com/thulasiramk-2310/cli_metrics.git
```

### Option 2: Run with Docker (Linux only)
```bash
# Pull from Docker Hub
docker pull ram231006/sysdash:latest

# Run on Linux with host system access (requires sudo for some metrics)
sudo docker run -it --rm --pid=host --net=host ram231006/sysdash:latest

# Run the mini dashboard
sudo docker run -it --rm --pid=host --net=host ram231006/sysdash:latest sysdash-mini

# ⚠️ Note: Docker on Windows/macOS shows container metrics, not your actual system.
# For accurate Windows/macOS monitoring, use pip install instead (Option 1 or 3).
# Docker works perfectly on native Linux systems with sudo.
```

### Option 3: Clone and install locally
```bash
git clone https://github.com/thulasiramk-2310/cli_metrics.git
cd cli_metrics
pip install -e .
```

## Quick Start

### Graphical Dashboard (Recommended)
```bash
sysdash
```
Beautiful graphs, colors, and real-time visualizations.

### Simple Text Dashboard
```bash
sysdash-mini
```
Lightweight ASCII version - perfect for SSH sessions and basic terminals.

## Features

### 📊 System Metrics
- ✅ **CPU Metrics**: Total usage, per-core usage, frequency, load average
- ✅ **Memory Metrics**: Total, used, available, free, swap
- ✅ **Disk Metrics**: Partition usage, I/O rates (read/write)
- ✅ **Network Metrics**: Upload/download rates, total transfer, packets
- ✅ **Process Metrics**: Top processes by CPU and memory usage
- ✅ **System Info**: Hostname, uptime, real-time updates

### 📈 Visualizations (sysdash only)
- **Real-time Line Graphs**: Smooth trend lines with color-coded indicators
  - 🔴 Red: CPU/Memory increasing (high load warning)
  - 🟢 Green: CPU/Memory decreasing (optimizing)
- **Progress Bars**: Visual usage indicators for all metrics
- **Live Updates**: Configurable refresh intervals (0.1s - 10s)
- **60-Second History**: Rolling graph showing usage trends

### 🎨 Customizable Views
- **Full Dashboard**: All metrics at once
- **CPU Only**: `--cpu-only`
- **Memory Only**: `--memory-only`
- **Disk Only**: `--disk-only`
- **Network Only**: `--network-only`
- **Processes Only**: `--processes-only`
- **Custom Combinations**: Use `--no-*` flags to hide specific metrics

## Usage

### Graphical Dashboard (sysdash)

```bash
# Full dashboard with graphs (all metrics)
sysdash

# Faster updates (every 0.5 seconds)
sysdash --interval 0.5

# Custom hostname
sysdash --hostname production-server-01
```

### Simple Dashboard (sysdash-mini)

```bash
# Basic text dashboard
sysdash-mini

# Custom interval
sysdash-mini --interval 2

# Custom hostname
sysdash-mini --hostname my-server
```

### Customized Views (sysdash)

```bash
# Show only CPU metrics with graph
sysdash --cpu-only

# Show only disk metrics
sysdash --disk-only

# Show CPU and memory only
sysdash --no-disk --no-network --no-processes

# Show everything except processes
sysdash --no-processes

# CPU only with fast updates
sysdash --cpu-only --interval 0.3
```

## Command-Line Arguments

### sysdash (Graphical Dashboard)

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--interval` | float | 1.0 | Update interval in seconds (min: 0.1) |
| `--hostname` | str | system hostname | Custom hostname identifier |
| `--cpu-only` | flag | false | Show only CPU metrics |
| `--memory-only` | flag | false | Show only memory metrics |
| `--disk-only` | flag | false | Show only disk metrics |
| `--network-only` | flag | false | Show only network metrics |
| `--processes-only` | flag | false | Show only process list |
| `--no-cpu` | flag | false | Hide CPU metrics |
| `--no-memory` | flag | false | Hide memory metrics |
| `--no-disk` | flag | false | Hide disk metrics |
| `--no-network` | flag | false | Hide network metrics |
| `--no-processes` | flag | false | Hide process list |

### sysdash-mini (Simple Dashboard)

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--interval` | float | 1.0 | Update interval in seconds |
| `--hostname` | str | system hostname | Custom hostname identifier |

## Dashboard Layout

### Graphical Dashboard (sysdash)
```
╔════════════════════════════════════════════════════╗
║ SysDash CLI | Host: YourPC | Uptime: 00:05:23     ║
╚════════════════════════════════════════════════════╝
╭──────── CPU & Memory ────────╮╭───── Disk ──────╮
│ CPU:    45.2% ████████░░░░   ││ C:\ 48% Used    │
│ Memory: 68.5% █████████████░ ││ D:\ 30% Used    │
│ Per-Core Usage               ││ I/O Rates       │
╰──────────────────────────────╯╰─────────────────╯
╭──────── Usage Trends ────────╮╭──── Network ────╮
│ 📈 CPU Usage Trend           ││ Up: 125 KB/s    │
│ Max: 85.7%                   ││ Dn: 89 KB/s     │
│ [Line graph]                 ││ Total Transfer  │
│ Min: 12.3%                   ││ Packets         │
╰──────────────────────────────╯╰─────────────────╯
```

### Simple Dashboard (sysdash-mini)
```
=== SysDash Mini ===
Host: YourPC | Uptime: 00:05:23

CPU: 45.2% ████████████░░░░░░░░
Memory: 68.5% █████████████░░░░░░░
Disk C:\ 48% | Network: ↑125 KB/s ↓89 KB/s
```

## Requirements

- Python 3.7+
- psutil 5.9.0+
- rich 13.0.0+ (for sysdash only, not required for sysdash-mini)

## Troubleshooting

**Permission denied errors on Linux?**
- Run with sudo: `sudo sysdash` or `sudo sysdash-mini`
- For Docker: `sudo docker run -it --rm --pid=host --net=host ram231006/sysdash:latest`
- Some system metrics require elevated permissions

**Graph not displaying? (sysdash)**
- Wait 5-10 seconds for data collection
- Graphs need at least 5 data points to render

**Updates too slow/fast?**
- Adjust with `--interval` (recommended: 0.5 - 2.0 seconds)

**Terminal too small?**
- Try `--cpu-only` or other single metric views
- Use `sysdash-mini` for compact display

**Colors not showing?**
- Check if your terminal supports ANSI colors
- Use `sysdash-mini` for basic ASCII output

**SSH/Remote connection issues?**
- Use `sysdash-mini` for better compatibility
- Some terminal emulators may not support Rich features

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License
