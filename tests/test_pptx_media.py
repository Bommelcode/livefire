"""Tests voor `livefire.engines.powerpoint.extract_slide_media`.

Bouwt een minimale .pptx-achtige ZIP-structuur op met embedded audio +
video onder ``ppt/media/`` plus per-slide ``slideN.xml.rels``-bestanden,
en verifieert dat de extractor de juiste media uitpakt en mapt naar de
juiste slide-nummers — inclusief de timing-tree-interpretatie
(autoplay/click, loop, delay, volume). Volledig PowerPoint-loos."""

from __future__ import annotations

import zipfile
from pathlib import Path

from livefire.engines.powerpoint import extract_slide_media, SlideMedia


_RELS_NS = (
    'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
)
_PRES_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_AUDIO_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio"
)
_VIDEO_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/video"
)


def _rels_xml(*entries: tuple[str, str, str]) -> str:
    """Bouw een Relationships-XML uit (id, rel_type, target)-tuples."""
    items = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
        for rid, rtype, target in entries
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><Relationships {_RELS_NS}>{items}</Relationships>'


def _make_pptx_with_media(
    path: Path,
    slide_rels: dict[int, list[tuple[str, str, str]]],
    media_files: dict[str, bytes],
    slide_xmls: dict[int, str] | None = None,
) -> None:
    """Schrijf een fake .pptx met de gegeven slides + media-blobs.

    ``slide_rels`` mapt slide-nummer → lijst (Id, Type, Target).
    ``media_files`` mapt zip-pad (bv. ``"ppt/media/foo.mp3"``) → bytes.
    ``slide_xmls`` (optioneel) mapt slide-nummer → custom slideN.xml-
    body. Niet-vermelde slides krijgen een placeholder-XML die geen
    timing-tree bevat (zodat tests die zich niet om timing bekommeren
    zonder boilerplate kunnen draaien).
    """
    slide_xmls = slide_xmls or {}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("ppt/presentation.xml", "<presentation/>")
        for slide_num, rels in slide_rels.items():
            body = slide_xmls.get(slide_num, f"<sld nr='{slide_num}'/>")
            zf.writestr(f"ppt/slides/slide{slide_num}.xml", body)
            zf.writestr(
                f"ppt/slides/_rels/slide{slide_num}.xml.rels",
                _rels_xml(*rels),
            )
        for zip_path, blob in media_files.items():
            zf.writestr(zip_path, blob)


def _slide_with_pic_audio(
    spid: str,
    rid: str,
    *,
    timing_inner: str,
) -> str:
    """Slide-body met een ``<p:pic>`` die naar ``rid`` linkt en een
    timing-tree die ``timing_inner`` als kinderen onder ``<p:tnLst>``
    bevat. Helper voor tests die specifieke timing-patronen willen
    valideren."""
    return f'''<?xml version="1.0"?>
<p:sld xmlns:p="{_PRES_NS}" xmlns:r="{_DOC_REL_NS}">
  <p:cSld><p:spTree>
    <p:pic>
      <p:nvPicPr>
        <p:cNvPr id="{spid}" name="Media"/>
        <p:cNvPicPr/>
        <p:nvPr><p:audioFile r:link="{rid}"/></p:nvPr>
      </p:nvPicPr>
    </p:pic>
  </p:spTree></p:cSld>
  <p:timing><p:tnLst>{timing_inner}</p:tnLst></p:timing>
</p:sld>'''


# ---- basis: extractie + filtering ------------------------------------------

def test_extract_audio_per_slide(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    rels = {1: [("rId1", _AUDIO_REL_TYPE, "../media/applause.wav")]}
    _make_pptx_with_media(pptx, rels, {"ppt/media/applause.wav": b"FAKEWAV"})

    out = tmp_path / "deck_slides"
    result = extract_slide_media(str(pptx), str(out))

    assert set(result.keys()) == {1}
    assert len(result[1]) == 1
    media = result[1][0]
    assert isinstance(media, SlideMedia)
    assert media.kind == "audio"
    assert Path(media.path).read_bytes() == b"FAKEWAV"
    assert Path(media.path).name == "applause.wav"
    assert Path(media.path).parent == out / "media"


def test_extract_video_per_slide(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    rels = {2: [("rId1", _VIDEO_REL_TYPE, "../media/intro.mp4")]}
    _make_pptx_with_media(pptx, rels, {"ppt/media/intro.mp4": b"FAKEMP4"})

    out = tmp_path / "deck_slides"
    result = extract_slide_media(str(pptx), str(out))

    assert list(result.keys()) == [2]
    media = result[2][0]
    assert media.kind == "video"
    assert Path(media.path).read_bytes() == b"FAKEMP4"


def test_extract_skips_external_links(tmp_path: Path) -> None:
    """TargetMode='External' = link, niet embedded — niet uitpakken."""
    pptx = tmp_path / "deck.pptx"
    with zipfile.ZipFile(pptx, "w") as zf:
        zf.writestr("ppt/slides/slide1.xml", "<sld/>")
        zf.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            f'<?xml version="1.0"?><Relationships {_RELS_NS}>'
            '<Relationship Id="rId1" '
            f'Type="{_AUDIO_REL_TYPE}" '
            'Target="C:/movies/song.mp3" TargetMode="External"/>'
            '</Relationships>',
        )

    out = tmp_path / "deck_slides"
    assert extract_slide_media(str(pptx), str(out)) == {}
    assert not (out / "media").exists()


def test_extract_dedupes_shared_media(tmp_path: Path) -> None:
    """Hetzelfde mediabestand op meerdere slides wordt één keer uitgepakt
    en op iedere slide gerefereerd."""
    pptx = tmp_path / "deck.pptx"
    rels = {
        1: [("rId1", _AUDIO_REL_TYPE, "../media/sting.wav")],
        2: [("rId1", _AUDIO_REL_TYPE, "../media/sting.wav")],
    }
    _make_pptx_with_media(pptx, rels, {"ppt/media/sting.wav": b"STING"})

    out = tmp_path / "deck_slides"
    result = extract_slide_media(str(pptx), str(out))

    assert set(result.keys()) == {1, 2}
    assert result[1][0].path == result[2][0].path
    files = list((out / "media").iterdir())
    assert len(files) == 1


def test_extract_multiple_media_one_slide_sorted_by_rid(tmp_path: Path) -> None:
    """Volgorde binnen een slide volgt de numerieke rId-suffix (rId2 < rId10)."""
    pptx = tmp_path / "deck.pptx"
    rels = {
        1: [
            ("rId10", _AUDIO_REL_TYPE, "../media/laatste.wav"),
            ("rId2", _VIDEO_REL_TYPE, "../media/eerste.mp4"),
            ("rId3", _AUDIO_REL_TYPE, "../media/tweede.mp3"),
        ],
    }
    media = {
        "ppt/media/eerste.mp4": b"V1",
        "ppt/media/tweede.mp3": b"A2",
        "ppt/media/laatste.wav": b"A3",
    }
    _make_pptx_with_media(pptx, rels, media)

    out = tmp_path / "deck_slides"
    result = extract_slide_media(str(pptx), str(out))

    names = [Path(m.path).name for m in result[1]]
    assert names == ["eerste.mp4", "tweede.mp3", "laatste.wav"]
    kinds = [m.kind for m in result[1]]
    assert kinds == ["video", "audio", "audio"]


def test_extract_skips_unknown_extensions(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    rels = {
        1: [
            ("rId1", _AUDIO_REL_TYPE, "../media/foo.xyz"),
            ("rId2", _AUDIO_REL_TYPE, "../media/bar.wav"),
        ],
    }
    media = {"ppt/media/foo.xyz": b"???", "ppt/media/bar.wav": b"WAV"}
    _make_pptx_with_media(pptx, rels, media)

    out = tmp_path / "deck_slides"
    result = extract_slide_media(str(pptx), str(out))

    assert len(result[1]) == 1
    assert Path(result[1][0].path).name == "bar.wav"


def test_extract_legacy_ppt_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "old.ppt"
    f.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")
    out = tmp_path / "out"
    assert extract_slide_media(str(f), str(out)) == {}


def test_extract_corrupt_pptx_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "stuk.pptx"
    f.write_bytes(b"dit is geen zip")
    out = tmp_path / "out"
    assert extract_slide_media(str(f), str(out)) == {}


def test_extract_no_media_returns_empty(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(pptx, {1: [], 2: []}, {})

    out = tmp_path / "deck_slides"
    assert extract_slide_media(str(pptx), str(out)) == {}
    assert not (out / "media").exists()


def test_extract_ignores_dangling_relationships(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    rels = {1: [("rId1", _AUDIO_REL_TYPE, "../media/missing.mp3")]}
    _make_pptx_with_media(pptx, rels, media_files={})

    out = tmp_path / "deck_slides"
    assert extract_slide_media(str(pptx), str(out)) == {}


# ---- defaults wanneer er geen timing-tree is ------------------------------

def test_default_meta_when_no_timing(tmp_path: Path) -> None:
    """Slides zonder ``<p:timing>``-tree krijgen veilige defaults
    (trigger=click, geen loop, geen delay, volume=1.0)."""
    pptx = tmp_path / "deck.pptx"
    rels = {1: [("rId1", _AUDIO_REL_TYPE, "../media/x.wav")]}
    _make_pptx_with_media(pptx, rels, {"ppt/media/x.wav": b"X"})

    result = extract_slide_media(str(pptx), str(tmp_path / "out"))
    m = result[1][0]
    assert m.trigger == "click"
    assert m.loop is False
    assert m.delay_s == 0.0
    assert m.volume == 1.0


# ---- timing-tree: trigger ---------------------------------------------------

def test_audio_outside_mainseq_with_zero_delay_is_auto(tmp_path: Path) -> None:
    """Audio buiten de mainSeq met ``delay="0"`` = slide-soundtrack die
    autoplay't."""
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode>
            <p:cTn id="2"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/song.wav")]},
        {"ppt/media/song.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.trigger == "auto"


def test_audio_inside_mainseq_is_click(tmp_path: Path) -> None:
    """Audio onder een ``<p:cTn nodeType="mainSeq">`` zit in de
    animatie-step-sequence en wacht op een operator-klik."""
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:seq><p:cTn id="2" nodeType="mainSeq"><p:childTnLst>
          <p:audio>
            <p:cMediaNode>
              <p:cTn id="3"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>
              <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
            </p:cMediaNode>
          </p:audio>
        </p:childTnLst></p:cTn></p:seq>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/clip.wav")]},
        {"ppt/media/clip.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.trigger == "click"


def test_audio_with_indefinite_delay_is_click(tmp_path: Path) -> None:
    """``delay="indefinite"`` = wacht op een externe trigger ⇒ click."""
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode>
            <p:cTn id="2"><p:stCondLst><p:cond delay="indefinite"/></p:stCondLst></p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/clip.wav")]},
        {"ppt/media/clip.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.trigger == "click"


# ---- timing-tree: delay -----------------------------------------------------

def test_audio_with_delay_in_ms(tmp_path: Path) -> None:
    """``delay="2000"`` (ms in PowerPoint-eenheden) → ``delay_s = 2.0``."""
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode>
            <p:cTn id="2"><p:stCondLst><p:cond delay="2000"/></p:stCondLst></p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/clip.wav")]},
        {"ppt/media/clip.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.delay_s == 2.0
    assert m.trigger == "auto"


# ---- timing-tree: loop ------------------------------------------------------

def test_audio_with_repeat_indefinite_is_loop(tmp_path: Path) -> None:
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode>
            <p:cTn id="2" repeatCount="indefinite">
              <p:stCondLst><p:cond delay="0"/></p:stCondLst>
            </p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/loop.wav")]},
        {"ppt/media/loop.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.loop is True


def test_audio_without_repeat_is_not_loop(tmp_path: Path) -> None:
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode>
            <p:cTn id="2"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/once.wav")]},
        {"ppt/media/once.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.loop is False


# ---- timing-tree: volume ----------------------------------------------------

def test_audio_volume_attribute_parsed(tmp_path: Path) -> None:
    """``cMediaNode/@vol="50000"`` (uint, 100000 = 100%) → volume 0.5."""
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode vol="50000">
            <p:cTn id="2"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/half.wav")]},
        {"ppt/media/half.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.volume == 0.5


def test_audio_mute_attribute_zeros_volume(tmp_path: Path) -> None:
    timing = '''
      <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
        <p:audio>
          <p:cMediaNode mute="1">
            <p:cTn id="2"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>
            <p:tgtEl><p:spTgt spid="100"/></p:tgtEl>
          </p:cMediaNode>
        </p:audio>
      </p:childTnLst></p:cTn></p:par>'''
    slide_xml = _slide_with_pic_audio("100", "rId1", timing_inner=timing)
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/mute.wav")]},
        {"ppt/media/mute.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.volume == 0.0


# ---- timing-tree: directe sndTgt ------------------------------------------

def test_direct_sndtgt_pattern(tmp_path: Path) -> None:
    """``<p:sndTgt r:embed="rIdN"/>`` direct in de timing-tree zonder
    bijbehorende shape — extractor moet 'm via dat patroon nog steeds
    matchen."""
    slide_xml = f'''<?xml version="1.0"?>
<p:sld xmlns:p="{_PRES_NS}" xmlns:r="{_DOC_REL_NS}">
  <p:cSld><p:spTree/></p:cSld>
  <p:timing><p:tnLst>
    <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
      <p:audio>
        <p:cMediaNode vol="80000">
          <p:cTn id="2" repeatCount="indefinite">
            <p:stCondLst><p:cond delay="0"/></p:stCondLst>
          </p:cTn>
          <p:tgtEl><p:sndTgt r:embed="rId1"/></p:tgtEl>
        </p:cMediaNode>
      </p:audio>
    </p:childTnLst></p:cTn></p:par>
  </p:tnLst></p:timing>
</p:sld>'''
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _AUDIO_REL_TYPE, "../media/direct.wav")]},
        {"ppt/media/direct.wav": b"X"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.trigger == "auto"
    assert m.loop is True
    assert m.volume == 0.8


# ---- timing-tree: video via spid -------------------------------------------

def test_video_via_spid_lookup(tmp_path: Path) -> None:
    """Video met de standaard moderne layout: ``<p:pic>`` met
    ``<p:videoFile r:link>`` in slide-body, in timing aangesproken via
    ``<p:spTgt spid="...">``."""
    slide_xml = f'''<?xml version="1.0"?>
<p:sld xmlns:p="{_PRES_NS}" xmlns:r="{_DOC_REL_NS}">
  <p:cSld><p:spTree>
    <p:pic>
      <p:nvPicPr>
        <p:cNvPr id="42" name="Video"/>
        <p:cNvPicPr/>
        <p:nvPr><p:videoFile r:link="rId1"/></p:nvPr>
      </p:nvPicPr>
    </p:pic>
  </p:spTree></p:cSld>
  <p:timing><p:tnLst>
    <p:par><p:cTn id="1" nodeType="tmRoot"><p:childTnLst>
      <p:video>
        <p:cMediaNode>
          <p:cTn id="2"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>
          <p:tgtEl><p:spTgt spid="42"/></p:tgtEl>
        </p:cMediaNode>
      </p:video>
    </p:childTnLst></p:cTn></p:par>
  </p:tnLst></p:timing>
</p:sld>'''
    pptx = tmp_path / "deck.pptx"
    _make_pptx_with_media(
        pptx,
        {1: [("rId1", _VIDEO_REL_TYPE, "../media/clip.mp4")]},
        {"ppt/media/clip.mp4": b"V"},
        slide_xmls={1: slide_xml},
    )

    m = extract_slide_media(str(pptx), str(tmp_path / "out"))[1][0]
    assert m.kind == "video"
    assert m.trigger == "auto"
