"""Genereer een set witte glyphs voor Stream Deck buttons (Companion).

Output: 144x144 PNG met transparante achtergrond. Dropt in Companion's
Image Library zodat je ze met de Image-picker op presets kunt zetten.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 144
WHITE = (255, 255, 255, 255)
RED = (217, 83, 79, 255)  # match style.ERR
W = SIZE
# Wordt door _lock_body gebruikt; default = WHITE, rode variant override't.
_LOCK_FILL = WHITE


def _new() -> Image.Image:
    return Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))


def _ctx(img: Image.Image) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(img)


# ---- shape primitives ---------------------------------------------------


def play_triangle(d: ImageDraw.ImageDraw) -> None:
    # Iets naar rechts geoffset zodat de zwaartekracht visueel klopt.
    pad = 30
    pts = [
        (pad + 12, pad),
        (pad + 12, W - pad),
        (W - pad + 8, W // 2),
    ]
    d.polygon(pts, fill=WHITE)


def square_solid(d: ImageDraw.ImageDraw) -> None:
    pad = 36
    d.rectangle([pad, pad, W - pad, W - pad], fill=WHITE)


def square_with_x(d: ImageDraw.ImageDraw) -> None:
    pad = 30
    d.rectangle([pad, pad, W - pad, W - pad], fill=WHITE)
    # Cut-out X — twee zwarte diagonalen via "transparante" rectangle
    # mask. Simpler: draw zwarte X.
    pad2 = 50
    d.line([pad2, pad2, W - pad2, W - pad2], fill=(0, 0, 0, 0), width=10)
    d.line([pad2, W - pad2, W - pad2, pad2], fill=(0, 0, 0, 0), width=10)


def pause_bars(d: ImageDraw.ImageDraw) -> None:
    pad = 36
    bw = 18
    cx = W // 2
    d.rectangle([cx - 26, pad, cx - 26 + bw, W - pad], fill=WHITE)
    d.rectangle([cx + 26 - bw, pad, cx + 26, W - pad], fill=WHITE)


def chevron_down(d: ImageDraw.ImageDraw) -> None:
    # Twee gestapelde V's (pijl-naar-beneden)
    cx = W // 2
    for y_off in (0, 36):
        pts = [
            (cx - 36, 36 + y_off),
            (cx + 36, 36 + y_off),
            (cx, 72 + y_off),
        ]
        d.polygon(pts, fill=WHITE)


def chevron_up(d: ImageDraw.ImageDraw) -> None:
    cx = W // 2
    for y_off in (0, 36):
        pts = [
            (cx - 36, W - 36 - y_off),
            (cx + 36, W - 36 - y_off),
            (cx, W - 72 - y_off),
        ]
        d.polygon(pts, fill=WHITE)


def fast_forward(d: ImageDraw.ImageDraw) -> None:
    # Twee triangles naast elkaar →→
    pad = 24
    h = (W - 2 * pad) // 2
    cy = W // 2
    for x_off in (0, h):
        pts = [
            (pad + x_off, cy - h),
            (pad + x_off, cy + h),
            (pad + x_off + h, cy),
        ]
        d.polygon(pts, fill=WHITE)


def rewind(d: ImageDraw.ImageDraw) -> None:
    pad = 24
    h = (W - 2 * pad) // 2
    cy = W // 2
    for x_off in (0, h):
        pts = [
            (W - pad - x_off, cy - h),
            (W - pad - x_off, cy + h),
            (W - pad - x_off - h, cy),
        ]
        d.polygon(pts, fill=WHITE)


def speaker(d: ImageDraw.ImageDraw) -> None:
    # Trapezoid + arc-waves
    pad = 24
    cx = 56
    cy = W // 2
    # box
    d.rectangle([pad, cy - 14, cx, cy + 14], fill=WHITE)
    # cone (driehoek)
    d.polygon(
        [(cx, cy - 14), (cx + 30, cy - 36), (cx + 30, cy + 36), (cx, cy + 14)],
        fill=WHITE,
    )
    # waves
    for i, r in enumerate((22, 38)):
        d.arc(
            [cx + 30 - r, cy - r, cx + 30 + r, cy + r],
            start=-45,
            end=45,
            fill=WHITE,
            width=8,
        )


def video_box(d: ImageDraw.ImageDraw) -> None:
    pad = 24
    d.rounded_rectangle(
        [pad, pad + 12, W - pad, W - pad - 12], radius=10, outline=WHITE, width=8,
    )
    # play-tipje
    cx, cy = W // 2, W // 2
    d.polygon(
        [(cx - 16, cy - 18), (cx - 16, cy + 18), (cx + 18, cy)], fill=WHITE,
    )


def image_frame(d: ImageDraw.ImageDraw) -> None:
    pad = 24
    d.rounded_rectangle(
        [pad, pad, W - pad, W - pad], radius=10, outline=WHITE, width=8,
    )
    # zon
    d.ellipse([pad + 14, pad + 14, pad + 36, pad + 36], fill=WHITE)
    # bergen
    pts = [
        (pad + 6, W - pad - 6),
        (pad + 36, W // 2 + 4),
        (W // 2, W - pad - 14),
        (W - pad - 24, W // 2 - 4),
        (W - pad - 6, W - pad - 6),
    ]
    d.polygon(pts, fill=WHITE)


def slide_rect(d: ImageDraw.ImageDraw) -> None:
    # PowerPoint: rounded rect met drie tekst-bullets
    pad = 22
    d.rounded_rectangle(
        [pad, pad + 6, W - pad, W - pad - 6], radius=10, outline=WHITE, width=7,
    )
    cx = W // 2
    for i, y in enumerate((W // 2 - 18, W // 2, W // 2 + 18)):
        # bullet
        d.ellipse([pad + 14, y - 4, pad + 22, y + 4], fill=WHITE)
        # tekstlijn
        d.rectangle([pad + 30, y - 3, W - pad - 14, y + 3], fill=WHITE)


def lightbulb(d: ImageDraw.ImageDraw) -> None:
    # DMX-glyph: gloeilamp met straling
    cx, cy = W // 2, W // 2 - 8
    r = 32
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    # voet
    d.rectangle([cx - 16, cy + r - 4, cx + 16, cy + r + 14], fill=WHITE)
    d.rectangle([cx - 12, cy + r + 14, cx + 12, cy + r + 22], fill=WHITE)
    # straling
    for ang in range(0, 360, 45):
        rad = math.radians(ang)
        x1 = cx + int(math.cos(rad) * (r + 12))
        y1 = cy + int(math.sin(rad) * (r + 12))
        x2 = cx + int(math.cos(rad) * (r + 24))
        y2 = cy + int(math.sin(rad) * (r + 24))
        d.line([x1, y1, x2, y2], fill=WHITE, width=6)


def network_globe(d: ImageDraw.ImageDraw) -> None:
    # Drie expanderende cirkel-segmenten (wifi/zend-icon)
    cx, cy = W // 2, W - 36
    for i, r in enumerate((24, 50, 76)):
        d.arc(
            [cx - r, cy - r, cx + r, cy + r],
            start=200, end=340, fill=WHITE, width=10,
        )
    # punt
    d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=WHITE)


def folder(d: ImageDraw.ImageDraw) -> None:
    # Group-cue glyph: folder
    pad = 22
    # tab
    d.rounded_rectangle(
        [pad, pad + 12, pad + 56, pad + 36], radius=6, fill=WHITE,
    )
    # body
    d.rounded_rectangle(
        [pad, pad + 28, W - pad, W - pad], radius=8, fill=WHITE,
    )
    # uitsparing om de tab te onderscheiden
    d.line(
        [pad + 56, pad + 28, pad + 56, pad + 36], fill=(0, 0, 0, 0), width=4,
    )


def standby_circle(d: ImageDraw.ImageDraw) -> None:
    # Open cirkel (cue-marker), QLab-style
    pad = 24
    d.ellipse([pad, pad, W - pad, W - pad], outline=WHITE, width=10)


def clock(d: ImageDraw.ImageDraw) -> None:
    # Klok met wijzers — staat voor "wait" / "standby"
    pad = 24
    d.ellipse([pad, pad, W - pad, W - pad], outline=WHITE, width=8)
    cx, cy = W // 2, W // 2
    # uren-wijzer (omhoog)
    d.line([cx, cy, cx, cy - 28], fill=WHITE, width=8)
    # minuten-wijzer (naar rechts)
    d.line([cx, cy, cx + 36, cy], fill=WHITE, width=6)


def _draw_bow_closed(d: ImageDraw.ImageDraw, body_top: int) -> None:
    """Tekent een dichte U-bow op de gegeven draw — beide poten landen
    op body_top, top is een halve ring."""
    cx = W // 2
    bracket_outer_r = 30
    bracket_inner_r = 18
    bracket_cy = body_top - 4  # ring-center net boven de body
    outer_box = [
        cx - bracket_outer_r, bracket_cy - bracket_outer_r,
        cx + bracket_outer_r, bracket_cy + bracket_outer_r,
    ]
    inner_box = [
        cx - bracket_inner_r, bracket_cy - bracket_inner_r,
        cx + bracket_inner_r, bracket_cy + bracket_inner_r,
    ]
    d.pieslice(outer_box, start=180, end=360, fill=_LOCK_FILL)
    d.pieslice(inner_box, start=180, end=360, fill=(0, 0, 0, 0))
    # Linker + rechter flank tussen ring-onderkant en body-bovenkant
    d.rectangle(
        [cx - bracket_outer_r, bracket_cy,
         cx - bracket_inner_r, body_top + 2],
        fill=_LOCK_FILL,
    )
    d.rectangle(
        [cx + bracket_inner_r, bracket_cy,
         cx + bracket_outer_r, body_top + 2],
        fill=_LOCK_FILL,
    )


def _lock_body(d: ImageDraw.ImageDraw, *, closed: bool) -> None:
    """Hangslot — body onderaan, beugel bovenop. closed=True = dicht slot;
    closed=False = open slot waarbij de beugel naar links gedraaid is om
    z'n linker-aanhechtpunt (typische open-slot iconografie)."""
    cx = W // 2
    body_top = 70
    body_bottom = W - 24
    body_left = cx - 40
    body_right = cx + 40
    # Body — afgeronde rechthoek
    d.rounded_rectangle(
        [body_left, body_top, body_right, body_bottom],
        radius=10, fill=_LOCK_FILL,
    )
    # Sleutelgat — kleine cirkel + verticale streep — uitgespaard zodat
    # 't gaatje contrasteert tegen de witte body.
    cy_keyhole = body_top + (body_bottom - body_top) // 2 - 4
    d.ellipse(
        [cx - 7, cy_keyhole - 7, cx + 7, cy_keyhole + 7],
        fill=(0, 0, 0, 0),
    )
    d.rectangle(
        [cx - 3, cy_keyhole, cx + 3, cy_keyhole + 18],
        fill=(0, 0, 0, 0),
    )
    if closed:
        # Beugel staat in dichte stand op de body.
        _draw_bow_closed(d, body_top)
    else:
        # Beugel naar links gedraaid om z'n linker-aanhechtpunt — typische
        # open-slot iconografie. We tekenen de gesloten bow op een
        # transparant sub-canvas, roteren dat met PIL.Image.rotate() rond
        # 't aanhechtpunt, en composieten 't terug op de hoofd-image.
        # `d._image` is de onderliggende PIL.Image van deze ImageDraw —
        # daar pasten we de geroteerde bow op.
        bow_canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        bow_draw = ImageDraw.Draw(bow_canvas)
        _draw_bow_closed(bow_draw, body_top)
        # Pivot: linker-flank van de bow waar 'ie 't body raakt.
        bracket_outer_r = 30
        bracket_inner_r = 18
        pivot_x = cx - (bracket_outer_r + bracket_inner_r) // 2
        pivot_y = body_top
        # 50° CCW = duidelijk "open" zonder dat 'ie 't canvas uitsteekt.
        rotated = bow_canvas.rotate(
            50, center=(pivot_x, pivot_y), resample=Image.BICUBIC,
        )
        d._image.alpha_composite(rotated)


def lock_closed(d: ImageDraw.ImageDraw) -> None:
    _lock_body(d, closed=True)


def lock_open(d: ImageDraw.ImageDraw) -> None:
    _lock_body(d, closed=False)


def lock_closed_red(d: ImageDraw.ImageDraw) -> None:
    """Rode versie van het dichte slot — gebruikt voor de showtime-knop
    in z'n locked-state. Module-level _LOCK_FILL wordt tijdelijk op
    RED gezet en daarna teruggezet."""
    global _LOCK_FILL
    prev = _LOCK_FILL
    _LOCK_FILL = RED
    try:
        _lock_body(d, closed=True)
    finally:
        _LOCK_FILL = prev


def cart_wall(d: ImageDraw.ImageDraw) -> None:
    # Cart wall: 4x4 grid van afgeronde knoppen, klassieke radio-sting-look.
    # Eén knopje "ingedrukt" (gevuld vs. outline) zodat 't karakter heeft
    # i.p.v. een schaakbord.
    pad = 18
    gap = 6
    grid = 4
    cell = (W - 2 * pad - (grid - 1) * gap) // grid
    radius = 4
    pressed_x, pressed_y = 1, 2  # cellen-coordinaten van 't 'aan'-knopje
    for gy in range(grid):
        for gx in range(grid):
            x0 = pad + gx * (cell + gap)
            y0 = pad + gy * (cell + gap)
            x1 = x0 + cell
            y1 = y0 + cell
            if gx == pressed_x and gy == pressed_y:
                d.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=WHITE)
            else:
                d.rounded_rectangle(
                    [x0, y0, x1, y1], radius=radius, outline=WHITE, width=4,
                )


def house(d: ImageDraw.ImageDraw) -> None:
    # Home-glyph: dak (driehoek) + body (rechthoek) + deur (rechthoek-cutout
    # die we als zwart-transparant tekenen). Klassieke home-icon-look.
    cx = W // 2
    # Dak — driehoek bovenaan
    roof_top_y = 22
    roof_base_y = 64
    roof_half_w = 56
    d.polygon(
        [
            (cx - roof_half_w, roof_base_y),
            (cx + roof_half_w, roof_base_y),
            (cx, roof_top_y),
        ],
        fill=WHITE,
    )
    # Body — rechthoek onder het dak (iets smaller dan dak-base zodat
    # 't dak duidelijk overhangt)
    body_left = cx - 44
    body_right = cx + 44
    body_top = 60
    body_bottom = W - 22
    d.rectangle(
        [body_left, body_top, body_right, body_bottom], fill=WHITE,
    )
    # Deur — uitgespaard zodat 't huis 'n eigen silhouet houdt
    door_w = 20
    door_top = W // 2 + 6
    d.rectangle(
        [cx - door_w // 2, door_top, cx + door_w // 2, body_bottom],
        fill=(0, 0, 0, 0),
    )


# ---- runner -------------------------------------------------------------


GLYPHS = [
    ("go", play_triangle),
    ("stop", square_solid),
    ("stop_all", square_with_x),
    ("pause", pause_bars),
    ("next", chevron_down),
    ("prev", chevron_up),
    ("bank_next", fast_forward),
    ("bank_prev", rewind),
    ("audio", speaker),
    ("video", video_box),
    ("image", image_frame),
    ("powerpoint", slide_rect),
    ("dmx", lightbulb),
    ("network", network_globe),
    ("group", folder),
    ("standby", standby_circle),
    ("wait", clock),
    ("home", house),
    ("cart_wall", cart_wall),
    ("lock_closed", lock_closed),
    ("lock_closed_red", lock_closed_red),
    ("lock_open", lock_open),
]


def main() -> None:
    out_dir = Path.home() / "Downloads" / "livefire-glyphs"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in GLYPHS:
        img = _new()
        fn(_ctx(img))
        # Lichte glow onder 't witte glyph zodat 'ie ook op witte
        # achtergrond een rand heeft. Subtiel — alleen 1px expanded.
        img.save(out_dir / f"{name}.png", "PNG")
        print(f"  {name}.png")
    print(f"\n{len(GLYPHS)} glyphs naar {out_dir}")


if __name__ == "__main__":
    main()
