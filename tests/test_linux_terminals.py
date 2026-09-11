"""Regressions seen on Linux distributions but not on Windows.

Two things bite here and nowhere else: mount paths are long and deeply nested,
and a minimal install or container often leaves the locale unset so Python
picks ASCII for stdout.
"""

import io

import pytest

from sysdash.cli import short_mountpoint
from sysdash.cli_mini import MiniDashboard
from sysdash.glyphs import (
    ASCII_GLYPHS,
    UNICODE_GLYPHS,
    enable_utf8,
    for_stream,
    supports_unicode,
)


class AsciiStream(io.StringIO):
    """A stream whose encoder rejects everything above ASCII."""

    encoding = "ascii"


class StubbornAscii(AsciiStream):
    """An ASCII stream that also refuses to be switched to UTF-8."""

    def reconfigure(self, **kwargs):
        raise ValueError("cannot reconfigure")


class Utf8Stream(io.StringIO):
    """A stream that can encode everything, as a UTF-8 terminal does."""

    encoding = "utf-8"


class Reconfigurable(AsciiStream):
    """An ASCII stream that accepts UTF-8, as a real stdout does."""

    def reconfigure(self, **kwargs):
        if "encoding" in kwargs:
            self.encoding = kwargs["encoding"]


# --- mount paths -----------------------------------------------------------

def test_a_short_mountpoint_is_left_alone():
    assert short_mountpoint("/") == "/"
    assert short_mountpoint("/boot/efi") == "/boot/efi"


@pytest.mark.parametrize(
    "mountpoint",
    [
        "/run/media/ram/Samsung T7 Backup",
        "/media/ram/Seagate Expansion Drive",
        "/mnt/storage/media-library",
    ],
)
def test_a_long_mountpoint_keeps_its_tail(mountpoint):
    """The label at the end is what names the drive, so it must survive."""
    shortened = short_mountpoint(mountpoint)
    assert len(shortened) <= 12
    assert shortened.startswith("…")
    assert mountpoint.endswith(shortened[1:])


def test_two_external_drives_stay_distinguishable():
    """They used to collapse to identical "/run/media/r" rows.

    Linux mounts removable media under a long shared prefix, so truncating from
    the right threw away the only part that differed.
    """
    first = short_mountpoint("/run/media/ram/Samsung T7 Backup")
    second = short_mountpoint("/run/media/ram/Kingston DataTraveler")
    assert first != second


def test_the_ellipsis_follows_the_glyph_set():
    """On an ASCII terminal even the ellipsis has to be ASCII."""
    assert short_mountpoint("/run/media/ram/Backup", ellipsis="~").startswith("~")


# --- encoding --------------------------------------------------------------

def test_a_utf8_stream_gets_the_block_glyphs():
    assert supports_unicode(Utf8Stream()) is True
    assert for_stream(Utf8Stream()) is UNICODE_GLYPHS


def test_an_ascii_stream_gets_the_ascii_glyphs():
    assert supports_unicode(AsciiStream()) is False
    assert for_stream(AsciiStream()) is ASCII_GLYPHS


def test_a_stream_with_no_encoding_is_treated_as_capable():
    """An io.StringIO in a test has no encoder to raise."""
    assert supports_unicode(io.StringIO()) is True


@pytest.mark.parametrize("name", sorted(ASCII_GLYPHS))
def test_every_ascii_glyph_encodes_as_ascii(name):
    assert ASCII_GLYPHS[name].encode("ascii")


def test_the_two_glyph_sets_cover_the_same_names():
    assert set(ASCII_GLYPHS) == set(UNICODE_GLYPHS)


def test_enable_utf8_upgrades_a_reconfigurable_stream():
    """The usual case: the terminal speaks UTF-8, only the locale was missing."""
    stream = Reconfigurable()
    assert enable_utf8(stream) is True
    assert stream.encoding == "utf-8"
    assert for_stream(stream) is UNICODE_GLYPHS


def test_enable_utf8_falls_back_when_the_stream_refuses():
    stream = StubbornAscii()
    assert enable_utf8(stream) is False
    assert for_stream(stream) is ASCII_GLYPHS


def test_enable_utf8_leaves_a_working_stream_alone():
    assert enable_utf8(Utf8Stream()) is True


def test_mini_dashboard_bars_survive_an_ascii_terminal():
    """This raised UnicodeEncodeError and killed the dashboard on frame one."""
    dashboard = MiniDashboard.__new__(MiniDashboard)
    dashboard.glyphs = for_stream(AsciiStream())

    bar = dashboard.create_bar(62.5, width=20)
    bar.encode("ascii")
    assert bar == "#" * 12 + "-" * 8 + " 62.5%"


def test_mini_dashboard_renders_end_to_end_on_an_ascii_terminal(
    metrics_factory, monkeypatch
):
    dashboard = MiniDashboard(hostname="testhost")
    dashboard.glyphs = for_stream(AsciiStream())
    dashboard.collector.collect_all = lambda **kwargs: metrics_factory()
    monkeypatch.setattr(dashboard, "clear_screen", lambda: None)

    buffer = AsciiStream()
    monkeypatch.setattr("sys.stdout", buffer)
    dashboard.render()

    # The encoder is what used to raise, so round-trip the whole frame.
    buffer.getvalue().encode("ascii")
    assert "SYSDASH CLI MINI" in buffer.getvalue()
