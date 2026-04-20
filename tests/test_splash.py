"""Unit tests for observal_cli.splash — Task 6."""

from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from observal_cli.splash import COMPACT_BANNER, print_splash


# ---------------------------------------------------------------------------
# 6.1 / 6.2: Full art printed when width >= 80
# ---------------------------------------------------------------------------


def test_full_art_printed_when_width_ge_80():
    """Full splash art is printed when console width >= 80."""
    fake_art = "== DRAGON ART ==\nline2\n"

    mock_traversable = MagicMock()
    mock_traversable.joinpath.return_value.read_text.return_value = fake_art

    with patch("observal_cli.splash.files", return_value=mock_traversable):
        buf = io.StringIO()
        console = Console(file=buf, width=120, color_system=None)
        print_splash(console)

    output = buf.getvalue()
    assert "DRAGON ART" in output


# ---------------------------------------------------------------------------
# 6.3: Compact fallback printed when width < 80
# ---------------------------------------------------------------------------


def test_compact_fallback_when_width_lt_80():
    """Compact banner is printed when console width < 80."""
    fake_art = "== DRAGON ART ==\nline2\n"

    mock_traversable = MagicMock()
    mock_traversable.joinpath.return_value.read_text.return_value = fake_art

    with patch("observal_cli.splash.files", return_value=mock_traversable):
        buf = io.StringIO()
        console = Console(file=buf, width=60, color_system=None)
        print_splash(console)

    output = buf.getvalue()
    # The compact banner contains block-letter art
    assert "█▀█" in output
    # Full art should NOT appear
    assert "DRAGON ART" not in output


# ---------------------------------------------------------------------------
# 6.4: No exception raised when asset is missing
# ---------------------------------------------------------------------------


def test_no_exception_when_asset_missing():
    """print_splash does not raise when splash.txt is missing."""
    mock_traversable = MagicMock()
    mock_traversable.joinpath.return_value.read_text.side_effect = FileNotFoundError(
        "splash.txt not found"
    )

    with patch("observal_cli.splash.files", return_value=mock_traversable):
        buf = io.StringIO()
        console = Console(file=buf, width=120, color_system=None)
        # Should not raise
        print_splash(console)

    # Nothing printed
    assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# 6.5: Debug log emitted when asset is missing
# ---------------------------------------------------------------------------


def test_debug_log_emitted_when_asset_missing(caplog):
    """A debug log is emitted when splash.txt cannot be loaded."""
    mock_traversable = MagicMock()
    mock_traversable.joinpath.return_value.read_text.side_effect = FileNotFoundError(
        "splash.txt not found"
    )

    with patch("observal_cli.splash.files", return_value=mock_traversable):
        buf = io.StringIO()
        console = Console(file=buf, width=120, color_system=None)

        with caplog.at_level(logging.DEBUG, logger="observal_cli.splash"):
            print_splash(console)

    assert any("Could not load splash art" in record.message for record in caplog.records)
