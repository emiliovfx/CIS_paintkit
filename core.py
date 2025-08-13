#!/usr/bin/env python3
# file: core.py
from __future__ import annotations
from typing import Dict, Optional, Tuple
import pathlib
import numpy as np
from PIL import Image

# --- image I/O -----------------------------------------------------------

def load_albedo(path: pathlib.Path) -> Tuple[Image.Image, Image.Image]:
    """Load PNG preserving alpha. Returns (RGB, A) as separate images.
    RGB is the color channels; A is a single-channel 8-bit alpha.
    """
    im = Image.open(path).convert("RGBA")
    r, g, b, a = im.split()
    rgb = Image.merge("RGB", (r, g, b))
    return rgb, a


def load_mask_rgb(path: Optional[pathlib.Path], size: Tuple[int, int]) -> Optional[Image.Image]:
    """Load mask as RGB (ignore alpha), resized to *size* using bilinear.
    Returns None if *path* is None.
    """
    if path is None:
        return None
    im = Image.open(path).convert("RGB")
    if im.size != size:
        im = im.resize(size, Image.BILINEAR)
    return im


def paste_alpha(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Merge RGB and A back to RGBA."""
    if rgb.mode != "RGB":
        rgb = rgb.convert("RGB")
    if alpha.mode != "L":
        alpha = alpha.convert("L")
    if rgb.size != alpha.size:
        alpha = alpha.resize(rgb.size, Image.BILINEAR)
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, alpha))


# --- color math ----------------------------------------------------------

def _rgb_to_hsv_np(rgb: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized RGB->HSV for arrays in 0..1.
    Returns h in 0..1, s in 0..1, v in 0..1.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.max(rgb, axis=-1)
    minc = np.min(rgb, axis=-1)
    v = maxc
    delta = maxc - minc
    s = np.where(maxc == 0, 0.0, delta / np.maximum(maxc, 1e-8))

    # Hue computation
    # Avoid division by zero using where with delta>0
    rc = (maxc - r) / np.maximum(delta, 1e-8)
    gc = (maxc - g) / np.maximum(delta, 1e-8)
    bc = (maxc - b) / np.maximum(delta, 1e-8)

    h = np.zeros_like(maxc)
    cond = (maxc == r)
    h = np.where(cond, (bc - gc), h)
    cond = (maxc == g)
    h = np.where(cond, 2.0 + (rc - bc), h)
    cond = (maxc == b)
    h = np.where(cond, 4.0 + (gc - rc), h)
    h = (h / 6.0) % 1.0
    h = np.where(delta == 0, 0.0, h)
    return h, s, v


def _hsv_to_rgb_np(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vectorized HSV->RGB for arrays in 0..1. Returns array shape (...,3)."""
    i = np.floor(h * 6.0).astype(int)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    i_mod = i % 6
    r = np.choose(i_mod, [v, q, p, p, t, v])
    g = np.choose(i_mod, [t, v, v, q, p, p])
    b = np.choose(i_mod, [p, p, t, v, v, q])
    rgb = np.stack([r, g, b], axis=-1)
    return np.clip(rgb, 0.0, 1.0)


def apply_hsv_adjust_multi(
    image_rgb: Image.Image,
    weights: Dict[str, np.ndarray],
    hue_deg: Dict[str, float],
    sat_pct: Dict[str, float],
    val_pct: Dict[str, float],
) -> Image.Image:
    """Apply weighted HSV adjustments.

    * image_rgb: RGB image
    * weights: mapping key->mask array (float32 0..1), all same size as image
    * hue_deg, sat_pct, val_pct: per-key adjustment values

    For each pixel, we compute a weighted average of adjustments from all
    provided masks. If the sum of weights is 0, no change is applied.
    """
    arr = np.asarray(image_rgb.convert("RGB"), dtype=np.float32) / 255.0
    h, s, v = _rgb_to_hsv_np(arr)

    # Broadcast masks to 2D
    total_w = np.zeros(arr.shape[:2], dtype=np.float32)
    dh = np.zeros_like(total_w)
    ds = np.zeros_like(total_w)
    dv = np.zeros_like(total_w)

    for k, w in weights.items():
        if w is None:
            continue
        w2 = w.astype(np.float32)
        total_w += w2
        dh += w2 * float(hue_deg.get(k, 0.0))
        ds += w2 * float(sat_pct.get(k, 0.0))
        dv += w2 * float(val_pct.get(k, 0.0))

    nz = total_w > 1e-6
    if np.any(nz):
        dh[nz] = dh[nz] / total_w[nz]
        ds[nz] = ds[nz] / total_w[nz]
        dv[nz] = dv[nz] / total_w[nz]

        # Apply: hue in degrees, sat/val in percent scale
        h[nz] = (h[nz] + (dh[nz] / 360.0)) % 1.0
        s[nz] = np.clip(s[nz] * (1.0 + ds[nz] / 100.0), 0.0, 1.0)
        v[nz] = np.clip(v[nz] * (1.0 + dv[nz] / 100.0), 0.0, 1.0)

    rgb = _hsv_to_rgb_np(h, s, v)
    out = Image.fromarray((rgb * 255.0 + 0.5).astype(np.uint8), mode="RGB")
    return out
