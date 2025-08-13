#!/usr/bin/env python3
# file: text_overlay.py
from __future__ import annotations
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
import os, sys, pathlib
from PIL import Image, ImageOps, ImageDraw, ImageFont, ImageChops, ImageColor

@dataclass
class TextOverlay:
    enabled: bool = False
    text: str = "Sample Text"
    font_family: str = ""
    font_style: str = "Regular"
    font_size_px: int = 72
    scale: float = 1.0
    rotation_deg: float = 0.0
    pos_norm: Tuple[float, float] = (0.5, 0.5)
    fill_hex: str = "#ffffff"
    stroke_hex: str = "#000000"
    stroke_width: int = 0
    stroke_gap: int = 0
    stroke_offset_x: int = 0
    stroke_offset_y: int = 0
    parent_mirror_h: bool = False
    child_enabled: bool = False
    child_pos_norm: Tuple[float, float] = (0.5, 0.5)
    child_mirror_h: bool = False


def preload_fonts() -> Optional[Dict[str, Dict[str, str]]]:
    mapping: Dict[str, Dict[str, str]] = {}
    def add_family(family: str, candidates: Dict[str, list[str]]):
        fam_map: Dict[str, str] = {}
        for style, paths in candidates.items():
            for p in paths:
                if pathlib.Path(p).exists():
                    fam_map[style] = p
                    break
        if fam_map:
            mapping[family] = fam_map

    if sys.platform.startswith("win"):
        fonts = pathlib.Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        add_family("Arial", {
            "Regular": [str(fonts / "arial.ttf")],
            "Bold": [str(fonts / "arialbd.ttf")],
            "Italic": [str(fonts / "ariali.ttf")],
            "Bold Italic": [str(fonts / "arialbi.ttf")],
        })
        add_family("Segoe UI", {
            "Regular": [str(fonts / "segoeui.ttf")],
            "Bold": [str(fonts / "segoeuib.ttf")],
            "Italic": [str(fonts / "segoeuii.ttf")],
            "Bold Italic": [str(fonts / "segoeuiz.ttf"), str(fonts / "segoeuib.ttf")],
        })
    elif sys.platform == "darwin":
        lib = pathlib.Path("/Library/Fonts")
        syslib = pathlib.Path("/System/Library/Fonts")
        add_family("Arial", {
            "Regular": [str(lib / "Arial.ttf")],
            "Bold": [str(lib / "Arial Bold.ttf")],
            "Italic": [str(lib / "Arial Italic.ttf")],
            "Bold Italic": [str(lib / "Arial Bold Italic.ttf")],
        })
        add_family("Helvetica", {
            "Regular": [str(syslib / "Helvetica.ttc")],
            "Bold": [str(syslib / "Helvetica.ttc")],
            "Italic": [str(syslib / "Helvetica.ttc")],
            "Bold Italic": [str(syslib / "Helvetica.ttc")],
        })
    else:
        dj = pathlib.Path("/usr/share/fonts/truetype/dejavu")
        lib = pathlib.Path("/usr/share/fonts/truetype/liberation")
        add_family("DejaVu Sans", {
            "Regular": [str(dj / "DejaVuSans.ttf")],
            "Bold": [str(dj / "DejaVuSans-Bold.ttf")],
            "Italic": [str(dj / "DejaVuSans-Oblique.ttf")],
            "Bold Italic": [str(dj / "DejaVuSans-BoldOblique.ttf")],
        })
        add_family("Liberation Sans", {
            "Regular": [str(lib / "LiberationSans-Regular.ttf")],
            "Bold": [str(lib / "LiberationSans-Bold.ttf")],
            "Italic": [str(lib / "LiberationSans-Italic.ttf")],
            "Bold Italic": [str(lib / "LiberationSans-BoldItalic.ttf")],
        })
    return mapping or None


def resolve_font(font_map: Optional[Dict[str, Dict[str, str]]], family: str, style: str, px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        if font_map and family in font_map:
            style_map = font_map[family]
            path = style_map.get(style) or style_map.get("Regular") or next(iter(style_map.values()))
            return ImageFont.truetype(path, size=px)
        return ImageFont.truetype("arial.ttf", size=px) if os.name == "nt" else ImageFont.load_default()
    except Exception:
        try:
            return ImageFont.truetype("arial.ttf", size=px) if os.name == "nt" else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()


def render_text_bitmap(text: str, font: ImageFont.ImageFont, stroke_w: int, fill_hex: str, stroke_hex: str, dx: int, dy: int, gap: int) -> Image.Image:
    dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=max(0, stroke_w + max(0, gap)))
    w = max(1, bbox[2] - bbox[0])
    h = max(1, bbox[3] - bbox[1])

    # Build ring mask = (stroke_w + gap) outline MINUS (gap) outline
    big = Image.new("L", (w, h), 0)
    bdraw = ImageDraw.Draw(big)
    bdraw.text((-bbox[0], -bbox[1]), text, font=font, fill=255,
               stroke_width=max(0, stroke_w + max(0, gap)), stroke_fill=255)

    small = Image.new("L", (w, h), 0)
    sdraw = ImageDraw.Draw(small)
    if gap > 0:
        sdraw.text((-bbox[0], -bbox[1]), text, font=font, fill=255,
                   stroke_width=max(0, gap), stroke_fill=255)
    else:
        # no gap ⇒ only the fill area
        sdraw.text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    ring = ImageChops.subtract(big, small)

    # Colorize ring to stroke color
    rgb = ImageColor.getrgb(stroke_hex)
    color_img = Image.new("RGBA", (w, h), (rgb[0], rgb[1], rgb[2], 255))
    stroke_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    stroke_layer = Image.composite(color_img, stroke_layer, ring)

    # Fill layer
    fill_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fdraw = ImageDraw.Draw(fill_layer)
    fdraw.text((-bbox[0], -bbox[1]), text, font=font, fill=fill_hex)

    # Composite with offset stroke to leave a gap from the fill
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if stroke_w > 0:
        out.alpha_composite(stroke_layer, dest=(int(dx), int(dy)))
    out.alpha_composite(fill_layer, dest=(0, 0))
    return out


def render_text_masks(text: str, font: ImageFont.ImageFont, stroke_w: int, _fill_hex: str, _stroke_hex: str, gap: int) -> tuple[Image.Image, Image.Image, tuple[int,int,int,int]]:
    """Return (stroke_mask, fill_mask, bbox) as 8-bit L images.
    Stroke mask is a ring: outline at width (stroke_w + gap) minus outline at width (gap).
    Colors are ignored here; we colorize after transforms to avoid AA halos.
    """
    # Measure with the outer outline to ensure enough canvas
    dummy = Image.new("L", (1, 1), 0)
    d = ImageDraw.Draw(dummy)
    outer_w = max(0, int(stroke_w) + max(0, int(gap)))
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=outer_w)
    w = max(1, bbox[2] - bbox[0])
    h = max(1, bbox[3] - bbox[1])

    # Fill mask (no stroke)
    fill_mask = Image.new("L", (w, h), 0)
    df = ImageDraw.Draw(fill_mask)
    df.text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    # Outer outline mask
    outer = Image.new("L", (w, h), 0)
    do = ImageDraw.Draw(outer)
    if outer_w > 0:
        do.text((-bbox[0], -bbox[1]), text, font=font, fill=255, stroke_width=outer_w, stroke_fill=255)
    else:
        # No stroke + no gap => no ring
        do.text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    # Inner outline mask (gap)
    inner = Image.new("L", (w, h), 0)
    di = ImageDraw.Draw(inner)
    gap_w = max(0, int(gap))
    if gap_w > 0:
        di.text((-bbox[0], -bbox[1]), text, font=font, fill=255, stroke_width=gap_w, stroke_fill=255)
    else:
        # When gap==0, inner == fill area only
        di.text((-bbox[0], -bbox[1]), text, font=font, fill=255)

    # Ring = outer - inner (clamped at 0)
    stroke_mask = ImageChops.subtract(outer, inner)

    return stroke_mask, fill_mask, bbox


def compose_text(base_rgb: Image.Image, to: TextOverlay, font_map: Optional[Dict[str, Dict[str, str]]]) -> tuple[Image.Image, Optional[Tuple[int,int,int,int]], Optional[Tuple[int,int,int,int]]]:
    if not to.enabled or not to.text.strip():
        return base_rgb, None, None

    img_w, img_h = base_rgb.size
    px = max(1, int(round(to.font_size_px * to.scale)))
    font = resolve_font(font_map, to.font_family, to.font_style, px)

    # Build AA masks once, then transform masks (avoid rotating colored RGBA)
    stroke_w = max(0, int(round(to.stroke_width)))
    gap = max(0, int(round(to.stroke_gap)))
    s_mask, f_mask, bbox = render_text_masks(to.text, font, stroke_w, to.fill_hex, to.stroke_hex, gap)

    # Parent transforms (mirror + rotate)
    pm_s = s_mask
    pm_f = f_mask
    if to.parent_mirror_h:
        pm_s = ImageOps.mirror(pm_s)
        pm_f = ImageOps.mirror(pm_f)
    if abs(to.rotation_deg) > 0.01:
        pm_s = pm_s.rotate(to.rotation_deg, expand=True, resample=Image.BICUBIC)
        pm_f = pm_f.rotate(to.rotation_deg, expand=True, resample=Image.BICUBIC)

    # Child transforms (mirror + opposite rotation around 180° baseline)
    cm_s = cm_f = None
    if to.child_enabled:
        cm_s = s_mask
        cm_f = f_mask
        if to.child_mirror_h:
            cm_s = ImageOps.mirror(cm_s)
            cm_f = ImageOps.mirror(cm_f)
        angle = (180.0 - to.rotation_deg) % 360.0
        cm_s = cm_s.rotate(angle, expand=True, resample=Image.BICUBIC)
        cm_f = cm_f.rotate(angle, expand=True, resample=Image.BICUBIC)

    # Color layers from masks (no color rotation => fewer halos)
    def _rgba_from_mask(mask: Image.Image, hex_color: str) -> Image.Image:
        rgb = ImageColor.getrgb(hex_color)
        solid = Image.new("RGBA", mask.size, (rgb[0], rgb[1], rgb[2], 255))
        out = Image.new("RGBA", mask.size, (0, 0, 0, 0))
        return Image.composite(solid, out, mask)

    parent_fill = _rgba_from_mask(pm_f, to.fill_hex)
    parent_stroke = _rgba_from_mask(pm_s, to.stroke_hex) if to.stroke_width > 0 else None

    child_fill = _rgba_from_mask(cm_f, to.fill_hex) if cm_f is not None else None
    child_stroke = _rgba_from_mask(cm_s, to.stroke_hex) if (cm_s is not None and to.stroke_width > 0) else None

    base_rgba = base_rgb.convert("RGBA")

    # Parent placement
    pcx = int(to.pos_norm[0] * img_w)
    pcy = int(to.pos_norm[1] * img_h)
    px0 = int(pcx - parent_fill.width / 2)
    py0 = int(pcy - parent_fill.height / 2)
    if parent_stroke is not None:
        dx = int(to.stroke_offset_x); dy = int(to.stroke_offset_y)
        base_rgba.alpha_composite(parent_stroke, dest=(px0 + dx, py0 + dy))
    base_rgba.alpha_composite(parent_fill, dest=(px0, py0))
    bbox_parent = (px0, py0, px0 + parent_fill.width, py0 + parent_fill.height)

    # Child placement
    bbox_child = None
    if child_fill is not None:
        ccx = int(to.child_pos_norm[0] * img_w)
        ccy = int(to.child_pos_norm[1] * img_h)
        cx0 = int(ccx - child_fill.width / 2)
        cy0 = int(ccy - child_fill.height / 2)
        if child_stroke is not None:
            dx = int(to.stroke_offset_x); dy = int(to.stroke_offset_y)
            base_rgba.alpha_composite(child_stroke, dest=(cx0 + dx, cy0 + dy))
        base_rgba.alpha_composite(child_fill, dest=(cx0, cy0))
        bbox_child = (cx0, cy0, cx0 + child_fill.width, cy0 + child_fill.height)

    return base_rgba.convert("RGB"), bbox_parent, bbox_child