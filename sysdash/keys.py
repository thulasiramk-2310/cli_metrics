"""Non-blocking single-key input, for the interactive dashboard.

The dashboard cannot use ``input()``: it has to keep redrawing while waiting, so
keys are polled instead. Windows and POSIX have nothing in common here, so each
gets its own reader behind one interface.
"""

import os
import sys

UP = "up"
DOWN = "down"


class _NullReader:
    """Fallback when stdin is not a terminal (pipes, CI, `sysdash | less`)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self):
        return None


class _WindowsReader:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self):
        import msvcrt

        if not msvcrt.kbhit():
            return None
        char = msvcrt.getwch()
        # Arrow keys arrive as a two-character escape sequence.
        if char in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": UP, "P": DOWN}.get(code)
        return char


class _PosixReader:
    def __enter__(self):
        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(self._fd)
        # cbreak rather than raw: keys arrive unbuffered but Ctrl+C still works.
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc_info):
        import termios

        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        return False

    def get(self):
        import select

        if not select.select([self._fd], [], [], 0)[0]:
            return None
        char = os.read(self._fd, 1).decode(errors="ignore")
        if char != "\x1b":
            return char
        # Escape may start an arrow sequence, or be a bare Esc keypress.
        if not select.select([self._fd], [], [], 0.01)[0]:
            return "\x1b"
        sequence = os.read(self._fd, 2).decode(errors="ignore")
        return {"[A": UP, "[B": DOWN}.get(sequence, "\x1b")


def key_reader():
    """Return a context manager yielding an object with a ``get()`` method."""
    if not sys.stdin.isatty():
        return _NullReader()
    if os.name == "nt":
        return _WindowsReader()
    try:
        import termios  # noqa: F401
        import tty  # noqa: F401
    except ImportError:
        return _NullReader()
    return _PosixReader()
