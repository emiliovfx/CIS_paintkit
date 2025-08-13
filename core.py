#!/usr/bin/env python3
# file: core.py
from __future__ import annotations
from typing import Optional, Tuple, Dict
import pathlib
from PIL import Image
import numpy as np

# I/O

def load_albedo(path: pathlib.Path) -> tuple[Image.Image, Optional[Image.Image]]:
    img = Image.open(path)
    if img.mode == "RGBA":
        r, g, b, a = img.split()
        return Image.merge("RGB", (r, g, b)), a
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img, None


def load_mask_rgb(path: pathlib.Path, target_size: tuple[int, int]) -> Image.Image:
    m = Image.open(path)
    if m.mode != "RGB":
        m = m.convert("RGB")
    if m.size != target_size:
        m = m.resize(target_size, Image.BILINEAR)
    return m


def paste_alpha(rgb: Image.Image, alpha: Optional[Image.Image]) -> Image.Image:
    if alpha is None:
        return rgb
    if rgb.size != alpha.size:
        alpha = alpha.resize(rgb.size, Image.BILINEAR)
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, alpha))


# HSV adjustments (masked)

def apply_hsv_adjust_multi(
    albedo_rgb: Image.Image,
    weights: Dict[str, np.ndarray],  # keys: "M1_R" etc., values 0..1
    hue_deg: Dict[str, float],
    sat_pct: Dict[str, float],
    val_pct: Dict[str, float],
) -> Image.Image:
    hsv = albedo_rgb.convert("HSV")
    h, s, v = hsv.split()
    h_arr = np.asarray(h, dtype=np.float32)
    s_arr = np.asarray(s, dtype=np.float32)
    v_arr = np.asarray(v, dtype=np.float32)

    hue_shift_255 = np.zeros_like(h_arr, dtype=np.float32)
    s_mult = np.ones_like(s_arr, dtype=np.float32)
    v_mult = np.ones_like(v_arr, dtype=np.float32)

    for key, w in weights.items():
        if w is None:
            continue
        if w.dtype != np.float32:
            w = w.astype(np.float32)
        hue_255 = (float(hue_deg.get(key, 0.0)) / 360.0) * 255.0
        if hue_255:
            hue_shift_255 += w * hue_255
        k_s = float(sat_pct.get(key, 0.0)) / 100.0
        if k_s:
            s_mult *= (1.0 + k_s * w)
        k_v = float(val_pct.get(key, 0.0)) / 100.0
        if k_v:
            v_mult *= (1.0 + k_v * w)

    h_arr = (h_arr + hue_shift_255) % 255.0
    s_arr = np.clip(s_arr * s_mult, 0.0, 255.0)
    v_arr = np.clip(v_arr * v_mult, 0.0, 255.0)

    out_hsv = Image.merge(
        "HSV",
        (
            Image.fromarray(h_arr.astype(np.uint8)),
            Image.fromarray(s_arr.astype(np.uint8)),
            Image.fromarray(v_arr.astype(np.uint8)),
        ),
    )
    return out_hsv.convert("RGB")