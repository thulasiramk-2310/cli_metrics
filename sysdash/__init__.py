"""
SysDash - Real-time terminal-based system monitoring dashboard
"""

__version__ = "1.0.6"
__author__ = "Thulasiram K"
__all__ = ["MetricsCollector", "CLIDashboard", "MiniDashboard", "format_uptime"]

_LAZY = {
    "MetricsCollector": ".collector",
    "format_uptime": ".collector",
    "CLIDashboard": ".cli",
    "MiniDashboard": ".cli_mini",
}


def __getattr__(name):
    """Import submodules on demand so `sysdash-mini` does not pull in `rich`."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    return getattr(import_module(module, __name__), name)


def __dir__():
    return sorted(__all__)
