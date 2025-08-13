#!/usr/bin/env python3
# file: text_overlay.py
from __future__ import annotations
from typing import Dict, Tuple, Optional
import pathlib
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageChops

# --- font preload --------------------------------------------------------

_SYSTEM_FONT_DIRS = [
    # Windows
    pathlib.Path("C:/Windows/Fonts"),
    # macOS
    pathlib.Path("/System/Library/Fonts"),
    pathlib.Path("/Library/Fonts"),
    pathlib.Path.home() / "Library/Fonts",
    # Linux common
    pathlib.Path("/usr/share/fonts"), pathlib.Path("/usr/local/share/fonts"), pathlib.Path.home() / ".fonts",
]

_STYLE_TOKENS = {
    'bold italic': 'Bold Italic', 'italic bold': 'Bold Italic', 'black italic': 'Bold Italic',
    'bold': 'Bold', 'italic': 'Italic', 'oblique': 'Italic', 'regular': 'Regular', 'book': 'Regular', 'roman': 'Regular'
}


def _scan_font_dir(base: pathlib.Path) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    try:
        it = base.rglob("*") if base.is_dir() else []
    except Exception:
        it = []
    for p in it:
        if p.suffix.lower() not in (".ttf", ".otf", ".ttc"):
            continue
        name = p.stem.replace('_', ' ').replace('-', ' ')
        low = name.lower()
        fam = name; style = 'Regular'
        for tok, norm in _STYLE_TOKENS.items():
            if low.endswith(' ' + tok):
                fam = name[:-(len(tok)+1)]; style = norm; break
        fam = fam.strip()
        out.setdefault(fam, {})[style] = str(p)
    return out


def preload_fonts() -> Dict[str, Dict[str, str]]:
    """Best-effort system font preload. Returns {family: {style: path}}.
    Fallback to PIL's default font if nothing is found.
    """
    out: Dict[str, Dict[str, str]] = {}
    for d in _SYSTEM_FONT_DIRS:
        if d.exists():
            m = _scan_font_dir(d)
            for fam, styles in m.items():
                out.setdefault(fam, {}).update(styles)
    return out


# --- model ---------------------------------------------------------------

class TextOverlay:
    """Holds text style and transform state."""
    def __init__(self) -> None:
        # switches
        self.enabled: bool = True
        self.child_enabled: bool = True

        # content
        self.text: str = "N123AB"
        self.font_family: str = ""
        self.font_style: str = "Regular"
        self.font_size_px: int = 120

        # colors
        self.fill_hex: str = "#ffffff"
        self.stroke_hex: str = "#000000"
        self.stroke_width: int = 6
        self.stroke_gap: int = 0  # gap between fill and stroke
        self.stroke_offset_x: int = 0
        self.stroke_offset_y: int = 0

        # transforms
        self.scale: float = 1.0
        self.rotation_deg: float = 0.0
        self.parent_mirror_h: bool = False
        self.child_mirror_h: bool = True  # default child mirrored

        # positions (normalized 0..1, interpreted as text anchor center)
        self.pos_norm: Tuple[float, float] = (0.5, 0.5)
        self.child_pos_norm: Tuple[float, float] = (0.5, 0.5)

        # child base rotation (180) and opposite rotation to parent
        self.child_base_deg: float = 180.0


# --- rendering helpers ---------------------------------------------------

def _load_font(font_map: Dict[str, Dict[str, str]], family: str, style: str, size_px: int) -> ImageFont.FreeTypeFont:
    path = None
    if family and family in font_map:
        st = style if style in font_map[family] else ("Regular" if "Regular" in font_map[family] else next(iter(font_map[family].keys())))
        path = font_map[family].get(st)
    if path is None:
        # fallback: try DejaVu
        for fam in ("DejaVu Sans", "Arial", "Liberation Sans"):
            if fam in font_map:
                path = font_map[fam].get("Regular") or next(iter(font_map[fam].values()))
                break
    if path is None:
        # last resort
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size=size_px)
    except Exception:
        return ImageFont.load_default()


def _text_mask(text: str, font: ImageFont.ImageFont) -> Image.Image:
    if not text:
        return Image.new("L", (1, 1), 0)
    # Measure
    bbox = font.getbbox(text, anchor=None)
    w = max(1, bbox[2] - bbox[0])
    h = max(1, bbox[3] - bbox[1])
    im = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(im)
    d.text((-bbox[0], -bbox[1]), text, font=font, fill=255)
    return im


def _stroke_from_mask(mask: Image.Image, width: int) -> Image.Image:
    if width <= 0:
        return Image.new("L", mask.size, 0)
    # approximate dilate by repeated MaxFilter
    k = max(1, int(width))
    rad = max(1, 2 * k + 1)
    out = mask
    for _ in range(k):
        out = out.filter(ImageFilter.MaxFilter(size=3))
    return out


def _erode_mask(mask: Image.Image, pixels: int) -> Image.Image:
    if pixels <= 0:
        return mask
    out = mask
    for _ in range(pixels):
        out = out.filter(ImageFilter.MinFilter(size=3))
    return out


def _apply_transform(im: Image.Image, scale: float, rotation_deg: float, mirror_h: bool) -> Image.Image:
    if mirror_h:
        im = ImageOps.mirror(im)
    if abs(scale - 1.0) > 1e-6:
        w = max(1, int(round(im.width * scale)))
        h = max(1, int(round(im.height * scale)))
        im = im.resize((w, h), Image.LANCZOS)
    if abs(rotation_deg) > 1e-6:
        im = im.rotate(rotation_deg, resample=Image.BICUBIC, expand=True)
    return im

def _dilate(mask: Image.Image, radius: int) -> Image.Image:
    """Morphological dilation of an 8-bit mask using a square kernel."""
    if radius <= 0:
        return mask.copy()
    from PIL import ImageFilter  # local import to avoid global changes
    size = radius * 2 + 1  # must be odd
    return mask.filter(ImageFilter.MaxFilter(size))
def render_text_masks(
    text: str,
    font: ImageFont.ImageFont,
    stroke_w: int,
    _fill_hex: str,
    _stroke_hex: str,
    gap: int,
) -> tuple[Image.Image, Image.Image, tuple[int, int, int, int]]:
    """
    Return (stroke_mask, fill_mask, bbox) as 8-bit L images.

    stroke_mask is computed as: dilate(fill, gap + stroke_w) - dilate(fill, gap)
    which guarantees the gap sits OUTSIDE the fill boundary (no inward bite).
    """
    # Measure tight bbox using the glyph only (no stroke)
    dummy = Image.new("L", (1, 1), 0)
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    w = max(1, bbox[2] - bbox[0])
    h = max(1, bbox[3] - bbox[1])

    # Fill mask (anti-aliased glyph)
    fill_mask = Image.new("L", (w, h), 0)
    df = ImageDraw.Draw(fill_mask)
    df.text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    gap = max(0, int(gap))
    stroke_w = max(0, int(stroke_w))

    if stroke_w == 0:
        # No stroke: empty ring
        stroke_mask = Image.new("L", (w, h), 0)
        return stroke_mask, fill_mask, bbox

    # Outside-only ring by dilating the fill mask
    outer = _dilate(fill_mask, gap + stroke_w)
    inner = _dilate(fill_mask, gap)
    stroke_mask = ImageChops.subtract(outer, inner)

    return stroke_mask, fill_mask, bbox


def _paste_mask_color(base: Image.Image, mask: Image.Image, color_hex: str, offset_xy: Tuple[int,int]=(0,0)) -> None:
    if mask.getbbox() is None:
        return
    col = Image.new("RGBA", mask.size, _hex_to_rgba(color_hex))
    if offset_xy != (0, 0):
        canvas = Image.new("L", base.size, 0)
        canvas.paste(mask, box=offset_xy)
        base.paste(col, offset_xy, mask)
    else:
        base.paste(col, (0, 0), mask)


def _hex_to_rgba(hexstr: str) -> Tuple[int, int, int, int]:
    hs = hexstr.strip()
    if hs.startswith('#'):
        hs = hs[1:]
    if len(hs) == 6:
        r = int(hs[0:2], 16); g = int(hs[2:4], 16); b = int(hs[4:6], 16)
        return (r, g, b, 255)
    if len(hs) == 8:
        r = int(hs[0:2], 16); g = int(hs[2:4], 16); b = int(hs[4:6], 16); a = int(hs[6:8], 16)
        return (r, g, b, a)
    return (255, 255, 255, 255)


def _bbox_at(pos: Tuple[int,int], w: int, h: int) -> Tuple[int,int,int,int]:
    x, y = pos
    return (x - w // 2, y - h // 2, x + (w - w // 2), y + (h - h // 2))


def compose_text(base_rgb: Image.Image, to: TextOverlay, font_map: Dict[str, Dict[str, str]]):
    """Draw text(s) into an RGB image. Returns (RGB, bbox_parent, bbox_child).
    BBoxes are in image coordinates of the returned image.
    """
    if base_rgb.mode != "RGB":
        base_rgb = base_rgb.convert("RGB")

    W, H = base_rgb.size
    out = base_rgb.convert("RGBA")

    # prepare font
    font = _load_font(font_map, to.font_family, to.font_style, max(1, int(to.font_size_px)))

    bbox_parent = None
    bbox_child = None

    if to.enabled and to.text:
        s_mask, f_mask, _ = render_text_masks(to.text, font, to.stroke_width, to.fill_hex, to.stroke_hex, to.stroke_gap)
        # transform parent
        parent = Image.new("RGBA", (max(1, s_mask.width), max(1, s_mask.height)), (0, 0, 0, 0))
        # draw stroke then fill
        stroke_rgba = Image.new("RGBA", s_mask.size, _hex_to_rgba(to.stroke_hex))
        fill_rgba = Image.new("RGBA", f_mask.size, _hex_to_rgba(to.fill_hex))
        # stroke first (no offset), then fill with offset
        parent = parent.copy()
        parent.paste(stroke_rgba, (0, 0), mask=s_mask)
        if to.stroke_offset_x or to.stroke_offset_y:
            tmp = Image.new("RGBA", parent.size, (0,0,0,0))
            tmp.paste(fill_rgba, (to.stroke_offset_x, to.stroke_offset_y), mask=f_mask)
            parent = Image.alpha_composite(parent, tmp)
        else:
            parent.paste(fill_rgba, (0, 0), mask=f_mask)

        parent = _apply_transform(parent, to.scale, to.rotation_deg, to.parent_mirror_h)

        # position parent (centered at pos_norm)
        cx = int(round(to.pos_norm[0] * W))
        cy = int(round(to.pos_norm[1] * H))
        pb = _bbox_at((cx, cy), parent.width, parent.height)
        out.alpha_composite(parent, dest=(pb[0], pb[1]))
        bbox_parent = (pb[0], pb[1], pb[0] + parent.width, pb[1] + parent.height)

    if to.child_enabled and to.text:
        # re-use masks to keep identical glyph rasterization
        if 's_mask' not in locals():
            s_mask, f_mask, _ = render_text_masks(to.text, font, to.stroke_width, to.fill_hex, to.stroke_hex, to.stroke_gap)
        child = Image.new("RGBA", (max(1, s_mask.width), max(1, s_mask.height)), (0, 0, 0, 0))
        stroke_rgba = Image.new("RGBA", s_mask.size, _hex_to_rgba(to.stroke_hex))
        fill_rgba = Image.new("RGBA", f_mask.size, _hex_to_rgba(to.fill_hex))
        child.paste(stroke_rgba, (0, 0), mask=s_mask)
        if to.stroke_offset_x or to.stroke_offset_y:
            tmp = Image.new("RGBA", child.size, (0,0,0,0))
            tmp.paste(fill_rgba, (to.stroke_offset_x, to.stroke_offset_y), mask=f_mask)
            child = Image.alpha_composite(child, tmp)
        else:
            child.paste(fill_rgba, (0, 0), mask=f_mask)

        # child: default 180° base, then opposite to parent
        child_rot = (to.child_base_deg - to.rotation_deg) % 360.0
        child = _apply_transform(child, to.scale, child_rot, to.child_mirror_h)

        cx = int(round(to.child_pos_norm[0] * W))
        cy = int(round(to.child_pos_norm[1] * H))
        cb = _bbox_at((cx, cy), child.width, child.height)
        out.alpha_composite(child, dest=(cb[0], cb[1]))
        bbox_child = (cb[0], cb[1], cb[0] + child.width, cb[1] + child.height)

    return out.convert("RGB"), bbox_parent, bbox_child
