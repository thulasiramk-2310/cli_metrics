"""Key reader tests: the escape-sequence parsing each platform needs.

The readers are exercised through fake stdin rather than a real terminal, so
the POSIX branch runs on Windows CI and vice versa.
"""

import sys

import pytest

from sysdash.keys import DOWN, UP, _NullReader, _PosixReader, _WindowsReader, key_reader


class FakeStdin:
    """Just enough of stdin for _PosixReader: a descriptor number."""

    def __init__(self, tty=True):
        self._tty = tty

    def isatty(self):
        return self._tty

    def fileno(self):
        return 7


def test_null_reader_never_returns_a_key():
    with _NullReader() as reader:
        assert reader.get() is None


def test_a_pipe_gets_the_null_reader(monkeypatch):
    """`sysdash | less` must not try to put a pipe into cbreak mode."""
    monkeypatch.setattr(sys, "stdin", FakeStdin(tty=False))
    assert isinstance(key_reader(), _NullReader)


@pytest.mark.parametrize(
    "queued, expected",
    [
        (["q"], "q"),
        (["\x00", "H"], UP),
        (["\xe0", "H"], UP),
        (["\x00", "P"], DOWN),
        # A function key shares the two-character prefix but means nothing here.
        (["\x00", "; "], None),
    ],
)
def test_windows_reader_decodes_keys(monkeypatch, queued, expected):
    """Arrow keys arrive as a prefix byte plus a code, plain keys do not."""
    pending = list(queued)
    fake = type(sys)("msvcrt")
    fake.kbhit = lambda: bool(pending)
    fake.getwch = lambda: pending.pop(0)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)

    assert _WindowsReader().get() == expected


def test_windows_reader_returns_none_on_an_empty_buffer(monkeypatch):
    fake = type(sys)("msvcrt")
    fake.kbhit = lambda: False
    fake.getwch = lambda: pytest.fail("must not read when kbhit() is false")
    monkeypatch.setitem(sys.modules, "msvcrt", fake)

    assert _WindowsReader().get() is None


def _posix_reader(monkeypatch, chunks, ready):
    """A _PosixReader whose os.read and select are scripted.

    ``ready`` is consumed one entry per select call, so a test can say "a byte
    is waiting, then nothing is" and drive the escape-versus-arrow decision.
    """
    import select as select_module

    from sysdash import keys as keys_module

    reader = _PosixReader()
    reader._fd = 7

    pending_reads = list(chunks)
    pending_ready = list(ready)

    monkeypatch.setattr(
        keys_module.os, "read", lambda fd, n: pending_reads.pop(0)
    )
    monkeypatch.setattr(
        select_module,
        "select",
        lambda r, w, x, timeout: ([reader._fd] if pending_ready.pop(0) else [], [], []),
    )
    return reader


def test_posix_reader_returns_none_when_nothing_is_waiting(monkeypatch):
    reader = _posix_reader(monkeypatch, chunks=[], ready=[False])
    assert reader.get() is None


def test_posix_reader_returns_a_plain_key(monkeypatch):
    reader = _posix_reader(monkeypatch, chunks=[b"k"], ready=[True])
    assert reader.get() == "k"


@pytest.mark.parametrize("sequence, expected", [(b"[A", UP), (b"[B", DOWN)])
def test_posix_reader_decodes_arrows(monkeypatch, sequence, expected):
    reader = _posix_reader(
        monkeypatch, chunks=[b"\x1b", sequence], ready=[True, True]
    )
    assert reader.get() == expected


def test_posix_reader_passes_a_bare_escape_through(monkeypatch):
    """Esc with nothing behind it cancels a kill, so it must not be swallowed."""
    reader = _posix_reader(monkeypatch, chunks=[b"\x1b"], ready=[True, False])
    assert reader.get() == "\x1b"


def test_posix_reader_ignores_an_unknown_escape_sequence(monkeypatch):
    """Home, PageUp and friends must not be mistaken for an arrow."""
    reader = _posix_reader(
        monkeypatch, chunks=[b"\x1b", b"[5"], ready=[True, True]
    )
    assert reader.get() == "\x1b"
