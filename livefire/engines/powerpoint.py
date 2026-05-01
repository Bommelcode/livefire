"""PowerPoint-engine via COM-besturing.

Scope MVP:
- Eén actieve presentatie tegelijk (open + slideshow)
- Acties: open, next-slide, previous-slide, goto-slide, close
- Audio + video + animaties + transities + hyperlinks blijven werken want
  PowerPoint blijft de daadwerkelijke speler; liveFire is alleen de
  cue-trigger.

Vereist: Windows + Microsoft PowerPoint geïnstalleerd. Engine degradeert
gracefully op machines zonder Office (alle calls return False met een
duidelijke foutmelding).
"""

from __future__ import annotations

import ctypes
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from .registry import EngineStatus, register


# ---- pure-Python helpers (geen PowerPoint of pywin32 nodig) ---------------

def is_com_available() -> bool:
    """True wanneer pywin32 + PowerPoint COM bruikbaar zijn op deze
    machine. Gebruikt door de PPT-import-dialog om de slides-optie
    al-dan-niet aan te bieden."""
    return _COM_OK


def count_slides(file_path: str) -> int | None:
    """Tel het aantal slides in een .pptx/.pptm zonder PowerPoint te starten.

    .pptx en .pptm zijn ZIP-archieven volgens de OpenXML-spec; iedere slide
    heeft een eigen ``ppt/slides/slideN.xml``. Tellen gaat dus puur via
    zipfile + filtering. Voor het legacy binary ``.ppt``-formaat geven we
    ``None`` terug — dat zou pywin32 + COM vereisen, en daar willen we niet
    op vertrouwen tijdens een drag-drop (PowerPoint zou starten alleen om te
    tellen).

    Edge: het aantal fysieke slides kan in zeldzame gevallen afwijken van
    het aantal slides in slideshow-volgorde (verborgen slides, custom shows).
    Voor de import-flow gebruiken we het fysieke aantal — dat is wat
    ``Slide.GotoSlide(N)`` indexeert.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in {".pptx", ".pptm"}:
        return None
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            return sum(
                1
                for name in zf.namelist()
                if name.startswith("ppt/slides/slide")
                and name.endswith(".xml")
                and "/_rels/" not in name
            )
    except (zipfile.BadZipFile, OSError, KeyError):
        return None


# Audio/video-extensies zoals PowerPoint ze typisch in ppt/media/ embed.
# Houd dit lijstje liever te ruim dan te krap — onbekende extensies komen
# als losse cue terug en falen dan netjes in de eigen engine.
_PPT_AUDIO_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".m4a", ".wma", ".aac", ".aiff", ".aif",
    ".ogg", ".flac", ".mid", ".midi",
})
_PPT_VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".wmv", ".avi", ".mkv", ".webm", ".m4v",
})

_RELS_NAME_RE = re.compile(r"^ppt/slides/_rels/slide(\d+)\.xml\.rels$")
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_PRES_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_RID_RE = re.compile(r"^rId(\d+)$")
_INDEFINITE = ("indefinite", "infinite", "infinity")


@dataclass(frozen=True)
class SlideMedia:
    """Embedded media-referentie op een PowerPoint-slide.

    Velden zijn pure data — de import-flow vertaalt ze naar Cue-velden:

    * ``trigger`` — ``"auto"`` betekent: media start zodra de slide
      verschijnt; vertaalt naar ``ContinueMode.AUTO_CONTINUE`` op de
      vorige cue. ``"click"`` betekent: media wacht op een GO van de
      operator (PowerPoint's animatie-step in mainSeq, of een
      ``delay="indefinite"`` start-conditie).
    * ``delay_s`` — extra wachttijd vóór playback start; vertaalt naar
      ``Cue.pre_wait``.
    * ``loop`` — ``repeatCount="indefinite"`` in de timing-tree;
      vertaalt naar ``Cue.loops = 0``.
    * ``volume`` — lineair 0..1 (uit ``cMediaNode/@vol``, mute-attr);
      door de import-flow omgerekend naar dB voor ``Cue.volume_db``.
    """

    path: str
    kind: str           # "audio" of "video"
    trigger: str = "click"   # "auto" of "click"
    delay_s: float = 0.0
    loop: bool = False
    volume: float = 1.0


def _resolve_zip_target(base_dir: str, target: str) -> str:
    """Resolve een ZIP-relatieve ``Target`` tov ``base_dir``.

    Voorbeeld: een slide-rels heeft ``base_dir='ppt/slides'`` en een
    relationship-target ``'../media/foo.mp3'`` → ``'ppt/media/foo.mp3'``.
    """
    parts = base_dir.split("/")
    for chunk in target.replace("\\", "/").split("/"):
        if chunk in ("", "."):
            continue
        if chunk == "..":
            if parts:
                parts.pop()
            continue
        parts.append(chunk)
    return "/".join(parts)


def _rid_numeric_key(rid: str) -> tuple[int, int, str]:
    """Sorteer rId-strings op de numerieke suffix.

    PowerPoint nummert insertion-order via ``rId1``, ``rId2``... String-
    sortering werkt niet (``rId10`` zou vóór ``rId2`` komen) — ontleed
    daarom expliciet de numerieke suffix."""
    m = _RID_RE.match(rid)
    if m:
        return (0, int(m.group(1)), rid)
    return (1, 0, rid)


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    """ElementTree heeft geen parent-pointer; bouw 'm zelf op zodat we
    omhoog kunnen lopen vanaf een gevonden timing-target."""
    return {child: parent for parent in root.iter() for child in parent}


def _walk_ancestors(elem: ET.Element, parent_map: dict[ET.Element, ET.Element]):
    """Yield voorouders van ``elem`` (exclusief ``elem`` zelf)."""
    while elem in parent_map:
        elem = parent_map[elem]
        yield elem


def _meta_from_timing_target(
    target: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> dict:
    """Walk omhoog vanaf een ``<p:sndTgt>`` of ``<p:spTgt>`` en lees de
    timing-eigenschappen.

    De relevante ``<p:cTn>`` is in PowerPoint-XML een **sibling** van
    het target (beide zijn child van ``<p:cMediaNode>``), niet een
    voorouder. Vandaar dat we volume/mute én cTn-attributen plukken zodra
    we de eerste ``<p:cMediaNode>``-voorouder zien. Het oplopen daarna
    dient enkel om de ``mainSeq``-context te detecteren (= operator-
    klik-step).
    """
    p = f"{{{_PRES_NS}}}"

    delay_s = 0.0
    loop = False
    volume = 1.0
    indefinite_start = False
    in_main_seq = False
    found_cmedia = False

    for ancestor in _walk_ancestors(target, parent_map):
        tag = ancestor.tag

        if not found_cmedia and tag == f"{p}cMediaNode":
            found_cmedia = True
            vol_attr = ancestor.get("vol")
            if vol_attr is not None:
                try:
                    pct = int(vol_attr) / 100000.0
                    volume = max(0.0, min(1.0, pct))
                except ValueError:
                    pass
            if ancestor.get("mute") in ("1", "true"):
                volume = 0.0

            # cTn is een sibling van target — pak 'm via cMediaNode.find().
            ctn = ancestor.find(f"{p}cTn")
            if ctn is not None:
                rc = ctn.get("repeatCount", "")
                if rc.strip().lower() in _INDEFINITE:
                    loop = True
                cond = ctn.find(f"{p}stCondLst/{p}cond")
                if cond is not None:
                    d = cond.get("delay", "")
                    if d.strip().lower() in _INDEFINITE:
                        indefinite_start = True
                    else:
                        try:
                            ms = int(d)
                            if ms > 0:
                                delay_s = ms / 1000.0
                        except ValueError:
                            pass

        if tag == f"{p}cTn" and ancestor.get("nodeType") == "mainSeq":
            in_main_seq = True

    # Trigger-bepaling:
    #   * Media binnen mainSeq → click (operator stept door animaties).
    #   * Media met expliciete delay="indefinite" → click (wacht-op-trigger).
    #   * Anders → auto (slide-soundtrack-stijl, start bij slide-load).
    trigger = "click" if (in_main_seq or indefinite_start) else "auto"

    return {
        "trigger": trigger,
        "delay_s": delay_s,
        "loop": loop,
        "volume": volume,
    }


def _scan_shape_for_media_rid(
    shape: ET.Element, nv_path: str,
) -> tuple[str, str] | None:
    """Voor een ``<p:sp>`` of ``<p:pic>``: lees ``(spid, rid)`` als de
    shape een ``<p:videoFile>`` of ``<p:audioFile>`` heeft. ``nv_path``
    is het tag-pad naar de nv-property-container (``p:nvSpPr`` of
    ``p:nvPicPr``)."""
    p = f"{{{_PRES_NS}}}"
    r = f"{{{_DOC_REL_NS}}}"

    cnv = shape.find(f"{nv_path}/{p}cNvPr")
    if cnv is None:
        return None
    spid = cnv.get("id", "")
    if not spid:
        return None
    nvpr = shape.find(f"{nv_path}/{p}nvPr")
    if nvpr is None:
        return None
    for tag_name in ("videoFile", "audioFile"):
        file_el = nvpr.find(f"{p}{tag_name}")
        if file_el is None:
            continue
        rid = file_el.get(f"{r}link") or file_el.get(f"{r}embed")
        if rid:
            return spid, rid
    return None


def _extract_slide_timing_meta(slide_xml: bytes) -> dict[str, dict]:
    """Map iedere media-rId in deze slide naar een timing-meta-dict.

    Twee patronen worden herkend:

    A. **Direct** — ``<p:sndTgt r:embed="rIdN"/>`` in de timing-tree.
       Dit zie je vaak voor audio-cues die met QuickTime/Sound-objecten
       geplaatst zijn.

    B. **Via shape-spid** — ``<p:spTgt spid="X"/>`` in de timing-tree,
       waarbij shape ``X`` in ``<p:cSld>`` een ``<p:videoFile>`` of
       ``<p:audioFile>`` met ``r:link``/``r:embed`` heeft. Dit is het
       gangbare patroon in moderne PowerPoint-bestanden.
    """
    try:
        root = ET.fromstring(slide_xml)
    except ET.ParseError:
        return {}

    parent_map = _build_parent_map(root)
    p = f"{{{_PRES_NS}}}"
    r = f"{{{_DOC_REL_NS}}}"

    result: dict[str, dict] = {}

    # Pattern A — direct sndTgt in timing
    for tgt in root.iter(f"{p}sndTgt"):
        rid = tgt.get(f"{r}embed") or tgt.get(f"{r}link") or ""
        if rid and rid not in result:
            result[rid] = _meta_from_timing_target(tgt, parent_map)

    # Pattern B — spid lookup via shape-tree
    spid_to_rid: dict[str, str] = {}
    for shape in root.iter(f"{p}sp"):
        found = _scan_shape_for_media_rid(shape, f"{p}nvSpPr")
        if found:
            spid_to_rid[found[0]] = found[1]
    for shape in root.iter(f"{p}pic"):
        found = _scan_shape_for_media_rid(shape, f"{p}nvPicPr")
        if found:
            spid_to_rid[found[0]] = found[1]

    for sp_tgt in root.iter(f"{p}spTgt"):
        spid = sp_tgt.get("spid", "")
        rid = spid_to_rid.get(spid)
        if not rid or rid in result:
            continue
        result[rid] = _meta_from_timing_target(sp_tgt, parent_map)

    return result


def extract_slide_media(
    file_path: str, output_dir: str,
) -> dict[int, list[SlideMedia]]:
    """Pak embedded audio + video uit een .pptx/.pptm uit per slide.

    Voor iedere media-referentie wordt waar mogelijk de PowerPoint
    timing-tree geïnterpreteerd: trigger (autoplay vs. wacht-op-klik),
    start-delay, loop-flag en volume. Niet-detecteerbare velden
    krijgen veilige defaults (trigger=click, delay=0, loop=False,
    volume=1.0).

    Returns ``{slide_number: [SlideMedia, ...]}``. Externe links
    (``TargetMode="External"``), niet-(.pptx/.pptm)-bestanden en
    bestanden die niet als ZIP openen leveren een lege dict.

    Output-layout: bestanden gaan naar
    ``output_dir/media/<oorspronkelijke_naam>``. Komt hetzelfde
    media-bestand op meerdere slides voor, dan pakken we 'm één keer
    uit en mappen we hetzelfde pad naar iedere slide.
    """
    ext = Path(file_path).suffix.lower()
    if ext not in {".pptx", ".pptm"}:
        return {}

    out_dir = Path(output_dir)
    media_dir = out_dir / "media"
    result: dict[int, list[SlideMedia]] = {}

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            namelist = set(zf.namelist())
            extracted: dict[str, str] = {}  # zip-pad → uitgepakt-pad
            used_dests: set[Path] = set()  # voor basename-collision dedup

            for name in sorted(namelist):
                m = _RELS_NAME_RE.match(name)
                if not m:
                    continue
                slide_num = int(m.group(1))

                # Lees rels — geeft rId → (zip_path, kind)
                try:
                    rels_xml = zf.read(name)
                    rels_root = ET.fromstring(rels_xml)
                except (KeyError, ET.ParseError):
                    continue

                rid_map: dict[str, tuple[str, str]] = {}
                for rel in rels_root.findall(f"{{{_RELS_NS}}}Relationship"):
                    if rel.get("TargetMode") == "External":
                        continue
                    rid = rel.get("Id", "")
                    target = rel.get("Target", "")
                    if not (rid and target):
                        continue
                    target_path = _resolve_zip_target("ppt/slides", target)
                    if target_path not in namelist:
                        continue
                    target_ext = Path(target_path).suffix.lower()
                    if target_ext in _PPT_AUDIO_EXTS:
                        kind = "audio"
                    elif target_ext in _PPT_VIDEO_EXTS:
                        kind = "video"
                    else:
                        continue
                    rid_map[rid] = (target_path, kind)

                if not rid_map:
                    continue

                # Lees slide-XML voor timing-metadata
                slide_path = f"ppt/slides/slide{slide_num}.xml"
                timing_meta: dict[str, dict] = {}
                if slide_path in namelist:
                    try:
                        slide_xml = zf.read(slide_path)
                        timing_meta = _extract_slide_timing_meta(slide_xml)
                    except KeyError:
                        pass

                for rid in sorted(rid_map.keys(), key=_rid_numeric_key):
                    target_path, kind = rid_map[rid]

                    out_path = extracted.get(target_path)
                    if out_path is None:
                        try:
                            media_dir.mkdir(parents=True, exist_ok=True)
                        except OSError:
                            continue
                        # Disambig: twee verschillende ZIP-paden kunnen
                        # dezelfde basename hebben (bv. ppt/embeddings/
                        # audio1.mp3 + ppt/media/audio1.mp3). Anders
                        # overschrijft de tweede de eerste op disk en
                        # spelen beide cues dezelfde verkeerde audio af.
                        base_name = Path(target_path).name
                        dest = media_dir / base_name
                        if dest in used_dests:
                            stem = Path(base_name).stem
                            suffix = Path(base_name).suffix
                            for n in range(1, 10000):
                                candidate = media_dir / f"{stem}_{n}{suffix}"
                                if candidate not in used_dests:
                                    dest = candidate
                                    break
                        try:
                            with zf.open(target_path) as src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        except (KeyError, OSError):
                            continue
                        out_path = str(dest)
                        extracted[target_path] = out_path
                        used_dests.add(dest)

                    meta = timing_meta.get(rid, {})
                    result.setdefault(slide_num, []).append(SlideMedia(
                        path=out_path,
                        kind=kind,
                        trigger=meta.get("trigger", "click"),
                        delay_s=meta.get("delay_s", 0.0),
                        loop=meta.get("loop", False),
                        volume=meta.get("volume", 1.0),
                    ))
    except (zipfile.BadZipFile, OSError):
        return {}

    return result


def export_slides_to_png(
    file_path: str,
    output_dir: str,
    max_dim: int = 1920,
    progress_callback=None,
) -> tuple[bool, list[str], str]:
    """Exporteer iedere slide naar een PNG via PowerPoint COM.

    Vereist Windows + Microsoft PowerPoint geïnstalleerd. Op andere
    platforms of zonder pywin32 retourneert deze functie ``(False, [],
    "...")``.

    Resolutie wordt aspect-correct bepaald op basis van
    ``Presentation.PageSetup.SlideWidth/SlideHeight`` (PowerPoint-points).
    De langste zijde wordt geschaald naar ``max_dim`` (default 1920); de
    andere zijde volgt evenredig. Zo blijven 4:3 en 16:9 presentaties
    onvervormd.

    Bestandsnamen volgen ``slide_001.png``, ``slide_002.png``, ... — drie
    cijfers padding zodat alfabetische sortering met natuurlijke volgorde
    overeenkomt tot 999 slides.

    `progress_callback(current, total)` (optioneel) wordt aangeroepen na
    iedere geslaagde slide-export, zodat een UI een progressbar kan
    bijwerken. Geeft het callback ``True`` terug, dan wordt de export
    afgebroken (cancel-knop).

    Returnt ``(ok, list_of_paths, error_message)``.
    """
    if not _COM_OK:
        return False, [], _COM_ERR or "PowerPoint COM niet beschikbaar"

    src = Path(file_path)
    if not src.is_file():
        return False, [], f"Bestand niet gevonden: {src}"

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, [], f"Kon output-folder niet aanmaken ({out_dir}): {e}"

    try:
        pythoncom.CoInitialize()
    except Exception:
        pass

    app = None
    presentation = None
    we_started_app = False
    try:
        try:
            app = win32com.client.GetActiveObject("PowerPoint.Application")
        except Exception:
            app = win32com.client.Dispatch("PowerPoint.Application")
            we_started_app = True
        # PowerPoint vereist Visible=True voor de meeste COM-operaties.
        # Een onzichtbare instance accepteert geen Presentations.Open.
        try:
            app.Visible = True
        except Exception:
            pass

        try:
            presentation = app.Presentations.Open(
                str(src.resolve()),
                ReadOnly=True,
                Untitled=False,
                WithWindow=False,
            )
        except Exception:
            # Sommige PowerPoint-versies/-paths weigeren WithWindow=False;
            # val terug op WithWindow=True (we zien 'm dan kort flitsen).
            try:
                presentation = app.Presentations.Open(str(src.resolve()))
            except Exception as e:
                return False, [], f"Kon presentatie niet openen: {e}"

        # Minimaliseer eventueel het editor-window zodat de gebruiker geen
        # PowerPoint-UI ziet flitsen tijdens export.
        try:
            for i in range(1, presentation.Windows.Count + 1):
                presentation.Windows(i).WindowState = _PP_WINDOW_MINIMIZED
        except Exception:
            pass

        slide_count = int(presentation.Slides.Count)
        if slide_count <= 0:
            return False, [], "Presentatie bevat geen slides"

        # Aspect-correcte target-dims via PageSetup.
        # SlideWidth/Height zijn in points (1 pt = 1/72 inch); we hebben
        # alleen de verhouding nodig.
        try:
            slide_w = float(presentation.PageSetup.SlideWidth)
            slide_h = float(presentation.PageSetup.SlideHeight)
        except Exception:
            slide_w, slide_h = 1280.0, 720.0  # 16:9 fallback
        if slide_w <= 0 or slide_h <= 0:
            slide_w, slide_h = 1280.0, 720.0
        if slide_w >= slide_h:
            target_w = int(max_dim)
            target_h = max(1, int(round(max_dim * slide_h / slide_w)))
        else:
            target_h = int(max_dim)
            target_w = max(1, int(round(max_dim * slide_w / slide_h)))

        paths: list[str] = []
        for i in range(1, slide_count + 1):
            target = out_dir / f"slide_{i:03d}.png"
            try:
                presentation.Slides(i).Export(
                    str(target), "PNG", target_w, target_h
                )
            except Exception as e:
                return False, paths, f"Export van slide {i} mislukt: {e}"
            paths.append(str(target))
            if progress_callback is not None:
                cancelled = bool(progress_callback(i, slide_count))
                if cancelled:
                    return False, paths, "Geannuleerd"

        return True, paths, ""
    finally:
        if presentation is not None:
            try:
                # Markeer als 'opgeslagen' zodat Close() nooit een save-
                # prompt triggert. Slide.Export modificeert het document
                # niet, maar PowerPoint kan om interne redenen toch een
                # 'modified' flag zetten — defensief afvangen.
                presentation.Saved = True
            except Exception:
                pass
            try:
                presentation.Close()
            except Exception:
                pass
        if app is not None and we_started_app:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# Optionele dependency — engine werkt degraded zonder.
_COM_OK = False
_COM_ERR = ""
if sys.platform == "win32":
    try:
        import win32com.client  # type: ignore[import-not-found]
        import pythoncom  # type: ignore[import-not-found]
        _COM_OK = True
    except Exception as _e:
        _COM_ERR = f"pywin32 niet geladen: {_e}"
else:
    _COM_ERR = "PowerPoint COM is alleen beschikbaar op Windows"


# COM-constanten die we anders dynamisch zouden moeten ophalen.
_PP_SHOW_TYPE_KIOSK = 1   # ppShowTypeKiosk — slideshow blijft draaien
_PP_SLIDE_SHOW_DONE = 5   # ppSlideShowDone
_PP_WINDOW_MINIMIZED = 2  # ppWindowMinimized — verbergt de editor-window


class PowerPointEngine(QObject):
    """Beheert één PowerPoint Application + actieve Presentation."""

    presentation_opened = pyqtSignal(str)   # file_path
    presentation_closed = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._app = None        # PowerPoint.Application (COM)
        self._presentation = None
        self._current_path: str = ""
        # Of we PowerPoint zelf hebben gestart (en dus mogen quitten bij
        # shutdown). Als de gebruiker PowerPoint al open had hebben we de
        # bestaande instance overgenomen — niet stiekem afsluiten.
        self._we_started_app = False

    @property
    def available(self) -> bool:
        return _COM_OK

    # ---- public API --------------------------------------------------------

    def open(self, file_path: str) -> tuple[bool, str]:
        """Open een .pptx en start direct de slideshow."""
        if not _COM_OK:
            return False, _COM_ERR
        path = Path(file_path)
        if not path.is_file():
            return False, f"Bestand niet gevonden: {path}"

        try:
            # COM moet per thread geïnitialiseerd worden; doe het hier zodat
            # de Qt-hoofdthread klaar is om PowerPoint te besturen.
            pythoncom.CoInitialize()
        except Exception:
            pass

        # Sluit eventuele vorige presentatie van ons.
        self._close_presentation_if_any()

        try:
            if self._app is None:
                # GetActiveObject gebruikt een lopende PowerPoint als die er
                # is, anders Dispatch() start 'm. We onthouden of we 'm zelf
                # opstartten zodat we niet abrupt iemands geopende slides
                # afsluiten.
                try:
                    self._app = win32com.client.GetActiveObject(
                        "PowerPoint.Application"
                    )
                    self._we_started_app = False
                except Exception:
                    self._app = win32com.client.Dispatch(
                        "PowerPoint.Application"
                    )
                    self._we_started_app = True
                self._app.Visible = True
        except Exception as e:
            return False, f"Kon PowerPoint niet starten: {e}"

        # Open zonder readonly-flag: sommige presentaties (Protected View,
        # buiten Trusted Locations, OneDrive-streams) weigeren read-only en
        # gooien dan een -2147352567 / "PowerPoint could not open the file".
        # WithWindow=True zorgt dat de slideshow z'n eigen fullscreen-venster
        # krijgt; PowerPoint kiest zelf het juiste output-scherm.
        full_path = str(path.resolve())
        try:
            self._presentation = self._app.Presentations.Open(full_path)
        except Exception as e:
            return False, f"Kon presentatie niet openen: {e}"

        # Minimaliseer de editor-window meteen — de slideshow draait straks
        # in een eigen fullscreen window dat hier los van staat. Anders zie
        # je de PowerPoint-UI achter de slideshow.
        try:
            for i in range(1, self._presentation.Windows.Count + 1):
                self._presentation.Windows(i).WindowState = _PP_WINDOW_MINIMIZED
        except Exception:
            pass

        try:
            settings = self._presentation.SlideShowSettings
            settings.ShowType = _PP_SHOW_TYPE_KIOSK
            slideshow_window = settings.Run()
        except Exception as e:
            return False, f"Kon slideshow niet starten: {e}"

        # PowerPoint slideshow opent vaak achter onze Qt-mainwindow (zeker
        # na een fullscreen video-cue). We forceren 'm naar voren via:
        #   1. Hef Windows' foreground-lock op (ASFW_ANY = -1)
        #   2. Activeer PowerPoint op COM-niveau
        #   3. Activate() op de SlideShowWindow zelf
        #   4. Win32 SetForegroundWindow + SwitchToThisWindow op de HWND,
        #      met een Alt-keystroke om de focus-token vrij te geven.
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
        try:
            self._app.Activate()
        except Exception:
            pass

        # Geef PowerPoint even tijd om de slideshow daadwerkelijk te
        # tonen voordat we de HWND opvragen — anders is HWND nog 0.
        hwnd = 0
        for _ in range(20):  # ~1 s
            try:
                hwnd = int(slideshow_window.HWND)
            except Exception:
                hwnd = 0
            if hwnd:
                break
            time.sleep(0.05)

        try:
            slideshow_window.Activate()
        except Exception:
            pass

        if hwnd:
            try:
                user32 = ctypes.windll.user32
                # VK_MENU = 0x12 ; KEYEVENTF_KEYUP = 0x02
                user32.keybd_event(0x12, 0, 0, 0)
                user32.keybd_event(0x12, 0, 0x02, 0)
                user32.SetForegroundWindow(hwnd)
                # SwitchToThisWindow is undocumented maar betrouwbaar voor
                # cross-process focus na een net-getoonde window.
                user32.SwitchToThisWindow(hwnd, True)
                user32.BringWindowToTop(hwnd)
            except Exception:
                pass

        self._current_path = str(path)
        self.presentation_opened.emit(self._current_path)
        return True, ""

    def next_slide(self) -> tuple[bool, str]:
        view = self._slideshow_view()
        if view is None:
            return False, "Geen actieve slideshow"
        try:
            view.Next()
            return True, ""
        except Exception as e:
            return False, f"Volgende slide mislukt: {e}"

    def previous_slide(self) -> tuple[bool, str]:
        view = self._slideshow_view()
        if view is None:
            return False, "Geen actieve slideshow"
        try:
            view.Previous()
            return True, ""
        except Exception as e:
            return False, f"Vorige slide mislukt: {e}"

    def goto_slide(self, slide_number: int) -> tuple[bool, str]:
        view = self._slideshow_view()
        if view is None:
            return False, "Geen actieve slideshow"
        if slide_number < 1:
            return False, "Slide-nummer moet ≥ 1 zijn"
        try:
            view.GotoSlide(int(slide_number))
            return True, ""
        except Exception as e:
            return False, f"Goto slide mislukt: {e}"

    def close(self) -> tuple[bool, str]:
        """Stop de slideshow en sluit de presentatie."""
        self._close_presentation_if_any()
        return True, ""

    def is_slideshow_active(self) -> bool:
        return self._slideshow_view() is not None

    def shutdown(self) -> None:
        self._close_presentation_if_any()
        if self._app is not None and self._we_started_app:
            try:
                self._app.Quit()
            except Exception:
                pass
        self._app = None
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    # ---- intern ------------------------------------------------------------

    def _slideshow_view(self):
        if self._presentation is None:
            return None
        try:
            window = self._presentation.SlideShowWindow
        except Exception:
            return None
        if window is None:
            return None
        try:
            view = window.View
        except Exception:
            return None
        # Als de slideshow al gedaan is, geeft View.State 5 (Done) terug.
        try:
            if int(view.State) == _PP_SLIDE_SHOW_DONE:
                return None
        except Exception:
            pass
        return view

    def _close_presentation_if_any(self) -> None:
        if self._presentation is None:
            return
        # End slideshow als die nog draait.
        try:
            window = self._presentation.SlideShowWindow
            if window is not None:
                window.View.Exit()
        except Exception:
            pass
        try:
            self._presentation.Close()
        except Exception:
            pass
        self._presentation = None
        self._current_path = ""
        # Minimaliseer de PowerPoint Application zelf zodat de (nu lege)
        # editor niet over een volgende video- of presentatie-cue blijft
        # staan. We laten 'm wel draaien — een volgende Open is dan snel.
        if self._app is not None:
            try:
                self._app.WindowState = _PP_WINDOW_MINIMIZED
            except Exception:
                pass
        self.presentation_closed.emit()


# ---- status-registratie ----------------------------------------------------

def register_status(engine: PowerPointEngine | None = None) -> None:
    if not _COM_OK:
        register(EngineStatus(
            name="PowerPoint (COM)",
            available=False,
            detail=_COM_ERR or "pywin32 niet geladen",
            short="ppt",
        ))
        return
    register(EngineStatus(
        name="PowerPoint (COM)",
        available=True,
        detail="pywin32 + COM beschikbaar (vereist Microsoft PowerPoint)",
        short="ppt",
    ))
