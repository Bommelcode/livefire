"""Tests voor de Image-cue (v0.4.1) en de ImageEngine."""

from __future__ import annotations

from livefire.cues import Cue, CueType


def test_image_cue_type_in_all() -> None:
    assert CueType.IMAGE == "Image"
    assert CueType.IMAGE in CueType.ALL


def test_image_cue_default_fields() -> None:
    c = Cue(cue_type=CueType.IMAGE)
    assert c.image_output_screen == 0
    assert c.image_fade_in == 0.0
    assert c.image_fade_out == 0.0
    assert c.file_path == ""


def test_image_cue_roundtrip() -> None:
    c = Cue(
        cue_type=CueType.IMAGE,
        cue_number="3",
        name="Slide 1",
        file_path="/tmp/slide_001.png",
        image_output_screen=2,
        image_fade_in=0.5,
        image_fade_out=0.25,
        duration=8.0,
    )
    d = c.to_dict()
    c2 = Cue.from_dict(d)
    assert c2.cue_type == CueType.IMAGE
    assert c2.file_path == "/tmp/slide_001.png"
    assert c2.image_output_screen == 2
    assert c2.image_fade_in == 0.5
    assert c2.image_fade_out == 0.25
    assert c2.duration == 8.0
    assert c2.name == "Slide 1"


def test_image_cue_legacy_workspace_compat() -> None:
    """Een v0.4.0-workspace zonder image_*-velden moet zonder fout laden;
    de defaults vullen ontbrekende keys aan."""
    legacy_dict = {
        "id": "abc",
        "cue_number": "1",
        "cue_type": "Image",
        "name": "X",
        "file_path": "/x.png",
        # geen image_output_screen, image_fade_in, image_fade_out
    }
    c = Cue.from_dict(legacy_dict)
    assert c.cue_type == CueType.IMAGE
    assert c.image_output_screen == 0
    assert c.image_fade_in == 0.0
    assert c.image_fade_out == 0.0


def test_image_engine_construction(qt_app) -> None:
    """De ImageEngine moet zonder audio-/video-/COM-dependencies opstarten,
    en is_playing/get_remaining moeten zinnig terugvallen op None/False voor
    onbekende cues."""
    from livefire.engines.image import ImageEngine
    eng = ImageEngine()
    assert eng.available is True
    assert eng.is_playing("does-not-exist") is False
    assert eng.get_remaining("does-not-exist") is None
    # stop_cue op iets onbekends mag niet crashen
    eng.stop_cue("does-not-exist")
    eng.stop_all()
    eng.shutdown()


def test_image_engine_play_missing_file(qt_app) -> None:
    """Niet-bestaand pad → (False, foutmelding)."""
    from livefire.engines.image import ImageEngine
    eng = ImageEngine()
    ok, err = eng.play("cue1", "/nonexistent/path/foo.png")
    assert ok is False
    assert err  # niet-lege foutstring
    eng.shutdown()


def _write_tiny_png(path) -> None:
    """Schrijf een geldige 1×1 PNG via Qt zelf — vermijdt het handmatig
    samenstellen van PNG-bytes en de bijbehorende CRC-foutgevoeligheid."""
    from PyQt6.QtGui import QImage
    from PyQt6.QtCore import Qt
    img = QImage(1, 1, QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.black)
    assert img.save(str(path), "PNG"), f"Kon PNG niet schrijven: {path}"


def test_image_engine_play_and_stop_roundtrip(qt_app, tmp_path) -> None:
    """Echte play() + stop_cue() lifecycle met een minimale PNG. Verifieert
    dat geen exceptions optreden en dat de engine state schoon eindigt."""
    from livefire.engines.image import ImageEngine

    png = tmp_path / "tiny.png"
    _write_tiny_png(png)

    eng = ImageEngine()
    ok, err = eng.play("c1", str(png), screen_index=0)
    assert ok, err
    assert eng.is_playing("c1")

    eng.stop_cue("c1")  # geen fade → meteen sluiten via _finalize_close
    qt_app.processEvents()
    # Na hard-stop is c1 niet meer actief
    assert not eng.is_playing("c1")
    eng.shutdown()


def test_image_engine_hard_replace_no_fade_in(qt_app, tmp_path) -> None:
    """Tweede image-cue zonder fade-in op zelfde scherm sluit de eerste
    direct (geen onnodige resources voor onzichtbare prev)."""
    from livefire.engines.image import ImageEngine
    png = tmp_path / "x.png"
    _write_tiny_png(png)

    eng = ImageEngine()
    eng.play("a", str(png), screen_index=0, fade_in=0.0)
    assert eng.is_playing("a")
    eng.play("b", str(png), screen_index=0, fade_in=0.0)
    qt_app.processEvents()
    assert not eng.is_playing("a"), "harde cut moet a meteen sluiten"
    assert eng.is_playing("b")
    eng.stop_all()
    qt_app.processEvents()
    eng.shutdown()


def test_image_engine_crossfade_replace_with_fade_in(qt_app, tmp_path) -> None:
    """Nieuwe image-cue met fade-in op zelfde scherm laat de vorige
    parallel uitfaden in plaats van 'm hard te sluiten. Beide cues
    zijn even gelijktijdig 'in beheer' bij de engine."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from livefire.engines.image import ImageEngine
    png = tmp_path / "x.png"
    _write_tiny_png(png)

    eng = ImageEngine()
    eng.play("a", str(png), screen_index=0)
    assert eng.is_playing("a")

    eng.play("b", str(png), screen_index=0, fade_in=0.3)
    qt_app.processEvents()
    # Beide moeten in _active zitten — a fadet uit, b fadet in.
    assert eng.is_playing("a"), "a moet blijven leven tijdens crossfade"
    assert eng.is_playing("b")

    # Wacht op het einde van de crossfade.
    loop = QEventLoop()
    QTimer.singleShot(450, loop.quit)
    loop.exec()

    assert not eng.is_playing("a"), "a moet weg zijn na fade-out"
    assert eng.is_playing("b"), "b moet nog leven (geen duration)"
    eng.stop_all()
    qt_app.processEvents()
    eng.shutdown()


def test_image_engine_replace_does_not_disturb_running_fade_out(qt_app, tmp_path) -> None:
    """Als de vorige cue al z'n eigen fade-out heeft ingezet (bv. via
    Stop-cue), mag een nieuwe play() die fade niet overrulen of
    afbreken."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from livefire.engines.image import ImageEngine
    png = tmp_path / "x.png"
    _write_tiny_png(png)

    eng = ImageEngine()
    eng.play("a", str(png), screen_index=0)
    eng.stop_cue("a", fade_out=0.5)  # eigen fade-out van 500ms gestart
    qt_app.processEvents()

    # Onmiddellijk een nieuwe cue starten — a's fade-out moet z'n eigen
    # tempo aanhouden, niet plotseling versneld worden door b's fade-in.
    eng.play("b", str(png), screen_index=0, fade_in=0.05)
    qt_app.processEvents()

    # Beide nog actief — a in 500ms-fade, b in 50ms-fade.
    assert eng.is_playing("a")
    assert eng.is_playing("b")

    # Na 100ms is b z'n korte fade-in voorbij, maar a's lange fade nog niet.
    loop = QEventLoop()
    QTimer.singleShot(120, loop.quit)
    loop.exec()
    assert eng.is_playing("a"), "a's eigen 500ms fade-out mag niet versneld zijn"

    # Na nog eens 500ms is alles voorbij.
    loop = QEventLoop()
    QTimer.singleShot(500, loop.quit)
    loop.exec()
    assert not eng.is_playing("a")
    eng.stop_all()
    qt_app.processEvents()
    eng.shutdown()


def test_image_engine_independent_screens(qt_app, tmp_path) -> None:
    """Image-cues op verschillende screens beïnvloeden elkaar niet."""
    from livefire.engines.image import ImageEngine
    png = tmp_path / "x.png"
    _write_tiny_png(png)

    eng = ImageEngine()
    eng.play("a", str(png), screen_index=0)
    eng.play("b", str(png), screen_index=1)
    assert eng.is_playing("a")
    assert eng.is_playing("b")
    eng.stop_all()
    qt_app.processEvents()
    eng.shutdown()


def test_image_engine_is_playing_during_fade_out(qt_app, tmp_path) -> None:
    """is_playing() moet True blijven tijdens een lopende fade-out, en
    pas False worden zodra ``_finalize_close`` de entry heeft verwijderd.
    Hiermee wordt de controller-tick correct gestuurd: post_wait start
    pas na de fade, niet tijdens.

    Spiegelt het contract van VideoEngine.is_playing()."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from livefire.engines.image import ImageEngine
    png = tmp_path / "x.png"
    _write_tiny_png(png)

    eng = ImageEngine()
    eng.play("c1", str(png), screen_index=0, fade_out=0.0)
    assert eng.is_playing("c1")

    # Start een 300ms fade-out — gedurende die tijd moet is_playing True blijven.
    eng.stop_cue("c1", fade_out=0.3)
    qt_app.processEvents()
    assert eng.is_playing("c1"), "moet True blijven terwijl fade-out loopt"

    # Wacht 100ms — fade nog bezig
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert eng.is_playing("c1"), "moet True blijven na 100ms (fade nog niet klaar)"

    # Wacht tot na de fade
    loop = QEventLoop()
    QTimer.singleShot(400, loop.quit)
    loop.exec()
    assert not eng.is_playing("c1"), "moet False zijn na fade-out compleet"

    eng.shutdown()


def test_controller_fires_image_cue_through_full_lifecycle(qt_app, pro_license, tmp_path) -> None:
    """End-to-end: PlaybackController.fire_cue() voor een IMAGE-cue moet
    via pre_wait → action transitionen, image.play() aanroepen, en bij
    stop_cue() weer netjes stoppen."""
    from PyQt6.QtCore import QEventLoop, QTimer
    from livefire.workspace import Workspace
    from livefire.cues import Cue, CueType
    from livefire.playback import PlaybackController

    png = tmp_path / "slide.png"
    _write_tiny_png(png)

    ws = Workspace()
    cue = Cue(
        cue_type=CueType.IMAGE, cue_number="1", name="Slide 1",
        file_path=str(png),
    )
    ws.add_cue(cue)

    ctrl = PlaybackController(ws)
    try:
        ctrl.fire_cue(cue.id)

        # PlaybackController gebruikt een 20ms QTimer; geef 'm 100ms om
        # pre_wait → action te doorlopen.
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()

        assert ctrl.image.is_playing(cue.id), "image engine moet cue spelen"

        ctrl.stop_cue(cue.id)
        qt_app.processEvents()
        assert not ctrl.image.is_playing(cue.id), "stop_cue moet engine afsluiten"
    finally:
        ctrl.shutdown()
