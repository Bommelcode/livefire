"""Tests voor `livefire.engines.powerpoint.count_slides`.

Bouwt een minimale .pptx-achtige ZIP-structuur op met N slide-XML-files
en verifieert dat de teller exact dat aantal teruggeeft. Volledig
PowerPoint-loos — werkt cross-platform en zonder pywin32.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from livefire.engines.powerpoint import count_slides


def _make_fake_pptx(path: Path, slide_count: int) -> None:
    """Schrijf een ZIP met `slide_count` slideN.xml-files, plus wat ruis
    die niet meegeteld zou moeten worden (rels, theme, presentation.xml).
    """
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("ppt/presentation.xml", "<presentation/>")
        zf.writestr("ppt/theme/theme1.xml", "<theme/>")
        for i in range(1, slide_count + 1):
            zf.writestr(f"ppt/slides/slide{i}.xml", f"<sld nr='{i}'/>")
            # rels onder _rels/ moeten niet meetellen
            zf.writestr(
                f"ppt/slides/_rels/slide{i}.xml.rels",
                "<Relationships/>",
            )


def test_count_slides_pptx(tmp_path: Path) -> None:
    f = tmp_path / "deck.pptx"
    _make_fake_pptx(f, 7)
    assert count_slides(str(f)) == 7


def test_count_slides_pptm(tmp_path: Path) -> None:
    f = tmp_path / "deck.pptm"
    _make_fake_pptx(f, 3)
    assert count_slides(str(f)) == 3


def test_count_slides_empty_deck(tmp_path: Path) -> None:
    f = tmp_path / "leeg.pptx"
    _make_fake_pptx(f, 0)
    assert count_slides(str(f)) == 0


def test_count_slides_legacy_ppt_returns_none(tmp_path: Path) -> None:
    """.ppt is binary, niet ZIP — geen pure-Python telling mogelijk."""
    f = tmp_path / "old.ppt"
    f.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")  # OLE compound header
    assert count_slides(str(f)) is None


def test_count_slides_corrupt_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "stuk.pptx"
    f.write_bytes(b"dit is geen zip")
    assert count_slides(str(f)) is None


def test_count_slides_unknown_extension_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "foto.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0")
    assert count_slides(str(f)) is None


def test_count_slides_ignores_rels_and_theme(tmp_path: Path) -> None:
    """De teller mag puur de slideN.xml-files tellen, geen rels of theme."""
    f = tmp_path / "deck.pptx"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", "<sld/>")
        zf.writestr("ppt/slides/slide2.xml", "<sld/>")
        # ruis die NIET meegeteld mag worden
        zf.writestr("ppt/slides/_rels/slide1.xml.rels", "<Relationships/>")
        zf.writestr("ppt/slides/_rels/slide2.xml.rels", "<Relationships/>")
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", "<sldLayout/>")
        zf.writestr("ppt/slideMasters/slideMaster1.xml", "<sldMaster/>")
        zf.writestr("ppt/theme/theme1.xml", "<theme/>")
    assert count_slides(str(f)) == 2


def test_is_com_available_returns_bool() -> None:
    from livefire.engines.powerpoint import is_com_available
    assert isinstance(is_com_available(), bool)


def test_export_slides_without_com_returns_error(tmp_path: Path) -> None:
    """Op platforms zonder pywin32 (zoals deze CI / Linux) moet de export
    ``(False, [], <bericht>)`` teruggeven in plaats van te crashen."""
    from livefire.engines.powerpoint import (
        export_slides_to_png, is_com_available,
    )
    if is_com_available():
        pytest.skip("COM beschikbaar — deze test draait alleen op niet-Windows")
    f = tmp_path / "deck.pptx"
    f.write_bytes(b"fake")
    out = tmp_path / "out"
    ok, paths, err = export_slides_to_png(str(f), str(out))
    assert ok is False
    assert paths == []
    assert err  # niet-lege foutmelding
