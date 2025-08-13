#!/usr/bin/env python3
# file: app.py
from __future__ import annotations
import os
import pathlib
import json
import re
import tkinter as tk
from typing import Optional, Tuple, Dict, List
from tkinter import ttk, filedialog, messagebox, colorchooser, simpledialog
from PIL import Image, ImageTk, ImageDraw
import numpy as np

from core import load_albedo, load_mask_rgb, paste_alpha, apply_hsv_adjust_multi
from text_overlay import TextOverlay, preload_fonts, compose_text

PNG_FT = [["PNG Images", "*.png"], ["All files", "*.*"]]


class ChannelVars:
    def __init__(self) -> None:
        self.hue = tk.DoubleVar(value=0.0)
        self.sat = tk.DoubleVar(value=0.0)
        self.val = tk.DoubleVar(value=0.0)
        self.invert = tk.BooleanVar(value=False)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CIS PaintKit — Livery Builder")
        self.geometry("1480x980"); self.minsize(1200, 820)

        # images / preview cache
        self._images = None
        self._preview_size = (1024, 1024)
        self._preview_photo: Optional[ImageTk.PhotoImage] = None
        self._debounce_job = None
        self._last_full_composite: Optional[Image.Image] = None
        self._last_preview_img_size: Optional[Tuple[int, int]] = None
        self._last_preview_padding: Tuple[int, int] = (0, 0)

        # zoom / pan
        self._zoom_var = tk.DoubleVar(value=1.0)
        self._disp_scale: float = 1.0
        self._show_sel = tk.BooleanVar(value=True)
        self._pan_x = 0
        self._pan_y = 0
        self._panning = False
        self._panning_left = False
        self._pan_start = (0, 0)
        self._pan_at_start = (0, 0)
        self._space_down = False

        # channels & text
        self.channels: Dict[str, ChannelVars] = {k: ChannelVars() for k in ("M1_R","M1_G","M1_B","M2_R","M2_G","M2_B")}
        self.text_overlay = TextOverlay(); self.font_map = preload_fonts()
        self._active_text = "parent"; self._drag_active = False; self._drag_offset = (0.0, 0.0)
        self._bbox_parent = None; self._bbox_child = None
        self._scale_var = None; self._rot_var = None
        self._text_allowed_for_current = True

        # paths & status
        self.status_var = tk.StringVar(value="Auto-scanning Resources/Interior and Resources/Exterior next to this app…")
        self.project_root_var = tk.StringVar()
        self.aircraft_root_var = tk.StringVar()
        self.fonts_dir_var = tk.StringVar()
        # file vars
        self.albedo_path_var = tk.StringVar()
        self.mask1_path_var = tk.StringVar()
        self.mask2_path_var = tk.StringVar()

        # assets & per-asset state
        self.assets: List[dict] = []
        self.asset_states: dict[str, dict] = {}
        self.current_asset_key: Optional[str] = None
        self.asset_combo: Optional[ttk.Combobox] = None
        self.propagate_external_var = tk.BooleanVar(value=True)

        # startup
        self._startup_done = False

        self._build_ui()
        # auto set project root to this script folder and scan
        self._auto_set_project_root_and_scan()
        self.after(200, self._startup_flow)

    # ---------- Safe getters & validators ----------
    def _safe_get_int(self, var, fallback: int) -> int:
        try:
            v = var.get()
            if v in ("", None):
                return fallback
            return int(float(v))
        except Exception:
            return fallback

    def _safe_get_float(self, var, fallback: float) -> float:
        try:
            v = var.get()
            if v in ("", None):
                return fallback
            return float(v)
        except Exception:
            return fallback

    def _validate_int(self, proposed: str) -> bool:
        return proposed == "" or re.fullmatch(r"-?\d+", proposed) is not None

    def _validate_float(self, proposed: str) -> bool:
        return proposed == "" or re.fullmatch(r"-?\d*\.?\d*", proposed) is not None

    # UI ------------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)

        # Project root (paintkit root)
        ttk.Label(top, text="Project Root:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.project_root_var, width=68).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Browse…", command=self._browse_project_root).grid(row=0, column=2)
        ttk.Button(top, text="Scan", command=self._scan_assets).grid(row=0, column=3, padx=(6,0))

        # Aircraft folder (X-Plane aircraft root)
        ttk.Label(top, text="Aircraft Folder:").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.aircraft_root_var, width=68).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Browse…", command=self._browse_aircraft_root).grid(row=1, column=2)

        # Fonts folder (optional project fonts)
        ttk.Label(top, text="Fonts Folder:").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.fonts_dir_var, width=68).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Browse…", command=self._browse_fonts_dir).grid(row=2, column=2)
        ttk.Button(top, text="Load Fonts", command=self._load_fonts_from_dir).grid(row=2, column=3, padx=(6,0))

        # Asset picker
        ttk.Label(top, text="Asset:").grid(row=3, column=0, sticky="w")
        self.asset_combo = ttk.Combobox(top, state="readonly", values=[])
        self.asset_combo.grid(row=3, column=1, sticky="ew", padx=6)
        self.asset_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_asset_change())

        top.columnconfigure(1, weight=1)

        self.nb = ttk.Notebook(self); self.nb.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=(0, 10))
        for key, label in (("M1_R","Mask1 - Red"),("M1_G","Mask1 - Green"),("M1_B","Mask1 - Blue")):
            self._ensure_tab(key, label)
        ttab = ttk.Frame(self.nb); self._build_text_tab(ttab); self.nb.add(ttab, text="Text")

        btns = ttk.Frame(self); btns.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), pady=(0, 10))
        ttk.Button(btns, text="Reset All", command=self.reset_all).pack(anchor="w", pady=(4, 6))
        ttk.Button(btns, text="Build Livery (Save All)", command=self.save_all_assets).pack(anchor="w")
        ttk.Checkbutton(btns, text="Propagate Fuselage → Cowlings & Wings", variable=self.propagate_external_var).pack(anchor="w", pady=(6,0))
        ttk.Label(btns, text="Zoom").pack(anchor="w", pady=(16, 0))
        ttk.Scale(btns, from_=0.05, to=2.0, orient=tk.HORIZONTAL, variable=self._zoom_var, command=lambda _=None: self._on_zoom_change()).pack(anchor="w", fill=tk.X)
        ttk.Checkbutton(btns, text="Show selection", variable=self._show_sel, command=self._on_zoom_change).pack(anchor="w", pady=(4,0))

        pf = ttk.LabelFrame(self, text="Preview (scaled)"); pf.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.preview_label = ttk.Label(pf, anchor="center"); self.preview_label.pack(fill=tk.BOTH, expand=True)
        self.preview_label.bind("<Button-1>", self._on_mouse_down)
        self.preview_label.bind("<B1-Motion>", self._on_mouse_drag)
        self.preview_label.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.preview_label.bind("<MouseWheel>", self._on_mouse_wheel)
        self.preview_label.bind("<Button-4>", self._on_mouse_wheel_linux)
        self.preview_label.bind("<Button-5>", self._on_mouse_wheel_linux)
        # middle-button pan
        self.preview_label.bind("<Button-2>", self._on_pan_start)
        self.preview_label.bind("<B2-Motion>", self._on_pan_drag)
        self.preview_label.bind("<ButtonRelease-2>", self._on_pan_end)
        # space+left pan
        self.bind("<KeyPress-space>", self._on_space_down)
        self.bind("<KeyRelease-space>", self._on_space_up)

        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(side=tk.BOTTOM, fill=tk.X)

    def _build_channel_section(self, parent: tk.Widget, key: str, title: str) -> None:
        pad = {"padx": 8, "pady": 4}; v = self.channels[key]
        ttk.Label(parent, text=title).grid(row=0, column=0, sticky="w", **pad)
        ttk.Label(parent, text="Hue shift (°)").grid(row=1, column=0, sticky="w", **pad)
        ttk.Scale(parent, from_=-180, to=180, orient=tk.HORIZONTAL, variable=v.hue, command=self._on_param_change).grid(row=2, column=0, sticky="ew", **pad)
        ttk.Entry(parent, textvariable=v.hue, width=8).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(parent, text="Saturation scale (%)").grid(row=3, column=0, sticky="w", **pad)
        ttk.Scale(parent, from_=-100, to=100, orient=tk.HORIZONTAL, variable=v.sat, command=self._on_param_change).grid(row=4, column=0, sticky="ew", **pad)
        ttk.Entry(parent, textvariable=v.sat, width=8).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(parent, text="Brightness scale (%)").grid(row=5, column=0, sticky="w", **pad)
        ttk.Scale(parent, from_=-100, to=100, orient=tk.HORIZONTAL, variable=v.val, command=self._on_param_change).grid(row=6, column=0, sticky="ew", **pad)
        ttk.Entry(parent, textvariable=v.val, width=8).grid(row=6, column=1, sticky="w", **pad)
        ttk.Checkbutton(parent, text="Invert mask", variable=v.invert, command=self._schedule_preview).grid(row=7, column=0, sticky="w", **pad)
        parent.columnconfigure(0, weight=1)

    def _ensure_tab(self, key: str, label: str) -> None:
        if not hasattr(self, "tab_frames"): self.tab_frames = {}
        if key in self.tab_frames: return
        frame = ttk.Frame(self.nb); self._build_channel_section(frame, key, label)
        self.nb.add(frame, text=key); self.tab_frames[key] = frame

    def _forget_tab(self, key: str) -> None:
        frame = self.tab_frames.get(key)
        if frame is None: return
        idx = self.nb.index(frame); self.nb.forget(idx); del self.tab_frames[key]

    def _build_text_tab(self, parent: tk.Widget) -> None:
        to = self.text_overlay; pad = {"padx": 8, "pady": 4}
        evar = tk.BooleanVar(value=to.enabled); ttk.Checkbutton(parent, text="Enable text overlay", variable=evar, command=lambda: (setattr(to,"enabled",evar.get()), self._schedule_preview())).grid(row=0, column=0, sticky="w", **pad)
        cvar = tk.BooleanVar(value=to.child_enabled); ttk.Checkbutton(parent, text="Enable mirrored child", variable=cvar, command=lambda: (setattr(to,"child_enabled",cvar.get()), self._schedule_preview())).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(parent, text="Text").grid(row=1, column=0, sticky="w", **pad)
        self._text_var = tk.StringVar(value=to.text); ttk.Entry(parent, textvariable=self._text_var, width=40).grid(row=1, column=1, sticky="ew", **pad)
        self._text_var.trace_add("write", lambda *_: (setattr(to, "text", self._text_var.get()), self._schedule_preview()))

        ttk.Label(parent, text="Font family").grid(row=2, column=0, sticky="w", **pad)
        self.font_combo = ttk.Combobox(parent, state="readonly", values=[]); self.font_combo.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Label(parent, text="Style").grid(row=3, column=0, sticky="w", **pad)
        self.style_combo = ttk.Combobox(parent, state="readonly", values=[]); self.style_combo.grid(row=3, column=1, sticky="ew", **pad)

        fams = sorted(self.font_map.keys()) if self.font_map else []
        self.font_combo.configure(values=fams)
        if fams:
            preferred = next((c for c in ("Arial","DejaVu Sans","Liberation Sans", fams[0]) if c in fams), fams[0])
            self.font_combo.set(preferred)
            styles = sorted(self.font_map[preferred].keys()); self.style_combo.configure(values=styles)
            pick = "Regular" if "Regular" in styles else styles[0]
            self.style_combo.set(pick); to.font_family = preferred; to.font_style = pick

        self.font_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_font_change())
        self.style_combo.bind("<<ComboboxSelected>>", lambda *_: self._on_style_change())

        vcmd_i = (self.register(self._validate_int), "%P")
        vcmd_f = (self.register(self._validate_float), "%P")

        ttk.Label(parent, text="Font size (px)").grid(row=4, column=0, sticky="w", **pad)
        self._var_font_size = tk.IntVar(value=to.font_size_px)
        ttk.Spinbox(parent, from_=6, to=512, textvariable=self._var_font_size, width=7,
                    validate="key", validatecommand=vcmd_i,
                    command=lambda: self._on_size_change(self._var_font_size)).grid(row=4, column=1, sticky="w", **pad)
        self._var_font_size.trace_add("write", lambda *_: self._on_size_change(self._var_font_size))

        ttk.Label(parent, text="Fill").grid(row=5, column=0, sticky="w", **pad)
        self.fill_chip = tk.Label(parent, text=" ", width=4, relief="groove", bg=to.fill_hex); self.fill_chip.grid(row=5, column=1, sticky="w", **pad)
        self.fill_chip.bind("<Button-1>", lambda _e: self._pick_fill())

        ttk.Label(parent, text="Stroke").grid(row=6, column=0, sticky="w", **pad)
        self.stroke_chip = tk.Label(parent, text=" ", width=4, relief="groove", bg=to.stroke_hex); self.stroke_chip.grid(row=6, column=1, sticky="w", **pad)
        self.stroke_chip.bind("<Button-1>", lambda _e: self._pick_stroke())

        ttk.Label(parent, text="Stroke width (px)").grid(row=7, column=0, sticky="w", **pad)
        self._var_sw = tk.IntVar(value=to.stroke_width)
        ttk.Spinbox(parent, from_=0, to=50, textvariable=self._var_sw, width=7,
                    validate="key", validatecommand=vcmd_i,
                    command=lambda: self._on_sw_change(self._var_sw)).grid(row=7, column=1, sticky="w", **pad)
        self._var_sw.trace_add("write", lambda *_: self._on_sw_change(self._var_sw))

        ttk.Label(parent, text="Stroke gap (px)").grid(row=8, column=0, sticky="w", **pad)
        self._var_sg = tk.IntVar(value=getattr(to, 'stroke_gap', 0))
        ttk.Spinbox(parent, from_=0, to=50, textvariable=self._var_sg, width=7,
                    validate="key", validatecommand=vcmd_i,
                    command=lambda: self._on_gap(self._var_sg)).grid(row=8, column=1, sticky="w", **pad)
        self._var_sg.trace_add("write", lambda *_: self._on_gap(self._var_sg))

        ttk.Label(parent, text="Scale").grid(row=9, column=0, sticky="w", **pad)
        self._scale_var = tk.DoubleVar(value=to.scale)
        ttk.Scale(parent, from_=0.1, to=5.0, orient=tk.HORIZONTAL, variable=self._scale_var,
                  command=lambda _=None: self._on_scale(self._scale_var)).grid(row=9, column=1, sticky="ew", **pad)
        ttk.Spinbox(parent, from_=0.1, to=5.0, increment=0.05, textvariable=self._scale_var, width=7,
                    validate="key", validatecommand=vcmd_f,
                    command=lambda: self._on_scale(self._scale_var)).grid(row=9, column=2, sticky="w", **pad)
        self._scale_var.trace_add("write", lambda *_: self._on_scale(self._scale_var))

        ttk.Label(parent, text="Rotation (°)").grid(row=10, column=0, sticky="w", **pad)
        self._rot_var = tk.DoubleVar(value=to.rotation_deg)
        ttk.Scale(parent, from_=-180, to=180, orient=tk.HORIZONTAL, variable=self._rot_var,
                  command=lambda _=None: self._on_rot(self._rot_var)).grid(row=10, column=1, sticky="ew", **pad)
        ttk.Spinbox(parent, from_=-180, to=180, increment=1, textvariable=self._rot_var, width=7,
                    validate="key", validatecommand=vcmd_f,
                    command=lambda: self._on_rot(self._rot_var)).grid(row=10, column=2, sticky="w", **pad)
        self._rot_var.trace_add("write", lambda *_: self._on_rot(self._rot_var))

        ttk.Button(parent, text="Center Parent", command=self._center_text_parent).grid(row=11, column=0, sticky="w", **pad)
        ttk.Button(parent, text="Center Child", command=self._center_text_child).grid(row=11, column=1, sticky="w", **pad)

        self._var_parent_mirror = tk.BooleanVar(value=to.parent_mirror_h)
        ttk.Checkbutton(parent, text="Mirror parent (H)", variable=self._var_parent_mirror,
                        command=lambda: (setattr(to,"parent_mirror_h", self._var_parent_mirror.get()), self._schedule_preview())).grid(row=12, column=0, sticky="w", **pad)
        self._var_child_mirror = tk.BooleanVar(value=to.child_mirror_h)
        ttk.Checkbutton(parent, text="Mirror child (H)", variable=self._var_child_mirror,
                        command=lambda: (setattr(to,"child_mirror_h", self._var_child_mirror.get()), self._schedule_preview())).grid(row=12, column=1, sticky="w", **pad)

        ttk.Label(parent, text="Stroke offset X").grid(row=13, column=0, sticky="w", **pad)
        self._var_sox = tk.IntVar(value=to.stroke_offset_x)
        ttk.Spinbox(parent, from_=-200, to=200, textvariable=self._var_sox, width=7,
                    validate="key", validatecommand=vcmd_i,
                    command=lambda: self._on_sox(self._var_sox)).grid(row=13, column=1, sticky="w", **pad)
        self._var_sox.trace_add("write", lambda *_: self._on_sox(self._var_sox))

        ttk.Label(parent, text="Stroke offset Y").grid(row=14, column=0, sticky="w", **pad)
        self._var_soy = tk.IntVar(value=to.stroke_offset_y)
        ttk.Spinbox(parent, from_=-200, to=200, textvariable=self._var_soy, width=7,
                    validate="key", validatecommand=vcmd_i,
                    command=lambda: self._on_soy(self._var_soy)).grid(row=14, column=1, sticky="w", **pad)
        self._var_soy.trace_add("write", lambda *_: self._on_soy(self._var_soy))

        parent.columnconfigure(1, weight=1)

    # text handlers -------------------------------------------------------
    def _on_font_change(self):
        fam = self.font_combo.get(); self.text_overlay.font_family = fam
        styles = sorted(self.font_map[fam].keys()) if (self.font_map and fam in self.font_map) else ["Regular"]
        self.style_combo.configure(values=styles)
        pick = self.text_overlay.font_style if self.text_overlay.font_style in styles else ("Regular" if "Regular" in styles else styles[0])
        self.style_combo.set(pick); self.text_overlay.font_style = pick
        self._schedule_preview()

    def _on_style_change(self):
        self.text_overlay.font_style = self.style_combo.get() or "Regular"; self._schedule_preview()

    def _on_size_change(self, var):
        cur = getattr(self.text_overlay, "font_size_px", 72)
        self.text_overlay.font_size_px = max(1, self._safe_get_int(var, cur)); self._schedule_preview()

    def _on_sw_change(self, var):
        cur = getattr(self.text_overlay, "stroke_width", 0)
        self.text_overlay.stroke_width = max(0, self._safe_get_int(var, cur)); self._schedule_preview()

    def _on_gap(self, var):
        cur = getattr(self.text_overlay, "stroke_gap", 0)
        self.text_overlay.stroke_gap = max(0, self._safe_get_int(var, cur)); self._schedule_preview()

    def _on_scale(self, var):
        cur = getattr(self.text_overlay, "scale", 1.0)
        self.text_overlay.scale = max(0.05, self._safe_get_float(var, cur)); self._schedule_preview()

    def _on_rot(self, var):
        cur = getattr(self.text_overlay, "rotation_deg", 0.0)
        self.text_overlay.rotation_deg = self._safe_get_float(var, cur); self._schedule_preview()

    def _on_sox(self, var):
        cur = getattr(self.text_overlay, "stroke_offset_x", 0)
        self.text_overlay.stroke_offset_x = self._safe_get_int(var, cur); self._schedule_preview()

    def _on_soy(self, var):
        cur = getattr(self.text_overlay, "stroke_offset_y", 0)
        self.text_overlay.stroke_offset_y = self._safe_get_int(var, cur); self._schedule_preview()

    def _pick_fill(self):
        c = colorchooser.askcolor(color=self.text_overlay.fill_hex, title="Pick fill color")
        if c and c[1]: self.text_overlay.fill_hex = c[1]; self.fill_chip.configure(bg=self.text_overlay.fill_hex); self._schedule_preview()

    def _pick_stroke(self):
        c = colorchooser.askcolor(color=self.text_overlay.stroke_hex, title="Pick stroke color")
        if c and c[1]: self.text_overlay.stroke_hex = c[1]; self.stroke_chip.configure(bg=self.text_overlay.stroke_hex); self._schedule_preview()

    def _center_text_parent(self): self.text_overlay.pos_norm = (0.5, 0.5); self._schedule_preview()
    def _center_text_child(self): self.text_overlay.child_pos_norm = (0.5, 0.5); self._schedule_preview()

    # helpers -------------------------------------------------------------
    def _compute_fit_zoom(self, img_size: Tuple[int, int]) -> float:
        maxw, maxh = self._preview_size; iw, ih = img_size
        return 1.0 if iw <= 0 or ih <= 0 else min(maxw/iw, maxh/ih, 1.0)

    def _set_fit_zoom(self, img_size: Tuple[int, int]) -> None:
        self._zoom_var.set(self._compute_fit_zoom(img_size))

    def _set_zoom(self, z: float) -> None:
        z = max(0.05, min(2.0, float(z))); self._zoom_var.set(z); self._on_zoom_change()
        try: self.status_var.set(f"Zoom: {int(z*100)}%")
        except Exception: pass

    # file actions --------------------------------------------------------
    def _find_related_mask(self, albedo_path: str, token: str) -> Optional[str]:
        p = pathlib.Path(albedo_path); base, suffix, parent = p.stem, p.suffix, p.parent
        cand = parent / f"{base}_{token}{suffix}"
        if cand.exists(): return str(cand)
        target = f"{base}_{token}".casefold()
        try:
            for f in parent.iterdir():
                if f.is_file() and f.suffix.lower() == suffix.lower() and f.stem.casefold() == target:
                    return str(f)
        except Exception: pass
        return None

    def _channel_has_info(self, ch_img: Image.Image) -> bool:
        return bool(np.asarray(ch_img, dtype=np.uint8).any())

    def _update_mask2_tabs(self, mask2_rgb: Optional[Image.Image]) -> None:
        want = {"M2_R": False, "M2_G": False, "M2_B": False}
        if mask2_rgb is not None:
            r,g,b = mask2_rgb.split(); want["M2_R"], want["M2_G"], want["M2_B"] = map(self._channel_has_info, (r,g,b))
        labels = {"M2_R": "Mask2 - Red", "M2_G": "Mask2 - Green", "M2_B": "Mask2 - Blue"}
        for k, present in want.items():
            if present and k not in getattr(self, 'tab_frames', {}): self._ensure_tab(k, labels[k])
            if not present and k in getattr(self, 'tab_frames', {}): self._forget_tab(k)

    def _try_load_all(self) -> None:
        a, m1, m2 = self.albedo_path_var.get().strip(), self.mask1_path_var.get().strip(), self.mask2_path_var.get().strip()
        if not a or not m1: return
        try:
            a_img, a_alpha = load_albedo(pathlib.Path(a))
            m1_img = load_mask_rgb(pathlib.Path(m1), a_img.size)
            m2_img = load_mask_rgb(pathlib.Path(m2), a_img.size) if m2 else None
        except Exception as e:
            messagebox.showerror("Load error", str(e)); return
        self._images = {
            'albedo_path': pathlib.Path(a), 'mask1_path': pathlib.Path(m1), 'mask2_path': pathlib.Path(m2) if m2 else None,
            'albedo_full': a_img, 'mask1_rgb': m1_img, 'mask2_rgb': m2_img, 'albedo_alpha': a_alpha,
        }
        self._update_mask2_tabs(m2_img)
        self.status_var.set(f"Loaded: {os.path.basename(a)} + Mask1({os.path.basename(m1)})" + (f" + Mask2({os.path.basename(m2)})" if m2 else "") + f"  |  {a_img.size[0]}x{a_img.size[1]}")
        self._set_fit_zoom(a_img.size); self._schedule_preview()

    # adjustments & preview ----------------------------------------------
    def reset_all(self):
        for v in self.channels.values(): v.hue.set(0.0); v.sat.set(0.0); v.val.set(0.0); v.invert.set(False)
        to = self.text_overlay; to.pos_norm = (0.5, 0.5); to.child_pos_norm = (0.5, 0.5); to.rotation_deg = 0.0; to.scale = 1.0
        self._schedule_preview()

    def _on_param_change(self, _): self._schedule_preview()

    def _schedule_preview(self):
        if self._debounce_job is not None: self.after_cancel(self._debounce_job)
        self._debounce_job = self.after(60, self.update_preview)

    def _build_weights(self, size: Tuple[int, int]) -> Dict[str, np.ndarray]:
        w: Dict[str, np.ndarray] = {}
        def add(prefix: str, img: Optional[Image.Image]):
            if img is None: return
            r,g,b = (img if img.size == size else img.resize(size, Image.BILINEAR)).split()
            for ch_key, im in zip(("R","G","B"),(r,g,b)):
                key = f"{prefix}_{ch_key}"; arr = np.asarray(im, dtype=np.float32)/255.0
                if self.channels[key].invert.get(): arr = 1.0 - arr
                w[key] = arr
        add("M1", self._images['mask1_rgb']); add("M2", self._images['mask2_rgb'])
        return w

    def update_preview(self):
        self._debounce_job = None
        if not self._images: return
        try:
            full = self._images['albedo_full'].copy()
            weights = self._build_weights(full.size)
            keys = list(weights.keys())
            # Safe reads for channel entries (avoid TclError on empty strings)
            def sget(dv, default=0.0):
                try:
                    v = dv.get()
                    if v in ("", None): return default
                    return float(v)
                except Exception:
                    return default
            hue = {k: sget(self.channels[k].hue, 0.0) for k in keys}
            sat = {k: sget(self.channels[k].sat, 0.0) for k in keys}
            val = {k: sget(self.channels[k].val, 0.0) for k in keys}

            out_full = apply_hsv_adjust_multi(full.convert("RGB"), weights, hue, sat, val)

            # text overlay only on fuselage & wings assets
            if self._text_allowed_for_current:
                out_full, self._bbox_parent, self._bbox_child = compose_text(out_full, self.text_overlay, self.font_map)
            else:
                self._bbox_parent = self._bbox_child = None

            self._last_full_composite = out_full

            # compute display image with pan/zoom
            z = float(self._zoom_var.get() or 1.0); self._disp_scale = max(1e-6, z)
            fit_z = self._compute_fit_zoom(out_full.size)
            if z <= fit_z + 1e-6:
                # whole image fits: reset pan to (0,0)
                self._pan_x = self._pan_y = 0
                disp_w = max(1, int(out_full.width * z))
                disp_h = max(1, int(out_full.height * z))
                disp = out_full.resize((disp_w, disp_h), Image.LANCZOS)
            else:
                # crop viewport from full image using pan
                vw = max(1, int(round(self._preview_size[0] / z)))
                vh = max(1, int(round(self._preview_size[1] / z)))
                max_x = max(0, out_full.width - vw); max_y = max(0, out_full.height - vh)
                self._pan_x = min(max(0, self._pan_x), max_x)
                self._pan_y = min(max(0, self._pan_y), max_y)
                crop = out_full.crop((self._pan_x, self._pan_y, self._pan_x + vw, self._pan_y + vh))
                disp = crop.resize(self._preview_size, Image.LANCZOS)

            self._overlay_selection(disp)
            self._last_preview_img_size = disp.size
            self.after(0, self._update_preview_padding_in_label, disp.size)
            self._preview_photo = ImageTk.PhotoImage(disp); self.preview_label.configure(image=self._preview_photo)
        except Exception as e:
            self.status_var.set(f"Error updating preview: {e}")

    def _update_preview_padding_in_label(self, img_size: Tuple[int, int]):
        lw = max(1, self.preview_label.winfo_width()); lh = max(1, self.preview_label.winfo_height())
        iw, ih = img_size; pad_x = max(0, (lw - iw)//2); pad_y = max(0, (lh - ih)//2); self._last_preview_padding = (pad_x, pad_y)

    def _on_zoom_change(self):
        base = self._last_full_composite
        if base is None:
            self.update_preview(); return
        try:
            z = float(self._zoom_var.get() or 1.0); self._disp_scale = max(1e-6, z)
            fit_z = self._compute_fit_zoom(base.size)
            if z <= fit_z + 1e-6:
                self._pan_x = self._pan_y = 0
                disp = base.resize((max(1, int(base.width * z)), max(1, int(base.height * z))), Image.LANCZOS)
            else:
                vw = max(1, int(round(self._preview_size[0] / z)))
                vh = max(1, int(round(self._preview_size[1] / z)))
                max_x = max(0, base.width - vw); max_y = max(0, base.height - vh)
                self._pan_x = min(max(0, self._pan_x), max_x)
                self._pan_y = min(max(0, self._pan_y), max_y)
                crop = base.crop((self._pan_x, self._pan_y, self._pan_x + vw, self._pan_y + vh))
                disp = crop.resize(self._preview_size, Image.LANCZOS)

            self._overlay_selection(disp)
            self._last_preview_img_size = disp.size
            self.after(0, self._update_preview_padding_in_label, disp.size)
            self._preview_photo = ImageTk.PhotoImage(disp)
            self.preview_label.configure(image=self._preview_photo)
        except Exception as e:
            self.status_var.set(f"Zoom error: {e}")

    # mouse interactions --------------------------------------------------
    def _overlay_selection(self, disp_img: Image.Image) -> None:
        if not (self.text_overlay.enabled and self._show_sel.get() and self._text_allowed_for_current): return
        z = max(self._disp_scale, 1e-6); draw = ImageDraw.Draw(disp_img)
        def sbox(bb):
            if bb is None: return None
            x0,y0,x1,y1 = bb
            # translate by current pan then scale
            x0 = (x0 - self._pan_x) * z; y0 = (y0 - self._pan_y) * z
            x1 = (x1 - self._pan_x) * z; y1 = (y1 - self._pan_y) * z
            return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))
        pb = sbox(self._bbox_parent); cb = sbox(self._bbox_child)
        if pb and (self._active_text != "parent"): draw.rectangle(pb, outline=(255,255,0,255), width=1)
        if cb and (self._active_text != "child"): draw.rectangle(cb, outline=(255,255,0,255), width=1)
        if self._active_text == "parent" and pb: draw.rectangle(pb, outline=(255,0,0,255), width=2)
        if self._active_text == "child" and cb: draw.rectangle(cb, outline=(255,0,0,255), width=2)

    def _label_to_image_coords(self, x: int, y: int):
        if not self._last_preview_img_size or self._last_full_composite is None: return None
        iw, ih = self._last_preview_img_size; pad_x, pad_y = self._last_preview_padding
        xi, yi = x - pad_x, y - pad_y
        if xi < 0 or yi < 0 or xi >= iw or yi >= ih: return None
        z = max(self._disp_scale, 1e-6)
        xf = int(round(self._pan_x + xi / z))
        yf = int(round(self._pan_y + yi / z))
        fw, fh = self._last_full_composite.size
        if xf < 0 or yf < 0 or xf >= fw or yf >= fh: return None
        return (xf, yf)

    def _hit(self, xi: int, yi: int):
        if self._bbox_child is not None:
            x0,y0,x1,y1 = self._bbox_child
            if x0 <= xi < x1 and y0 <= yi < y1: return "child"
        if self._bbox_parent is not None:
            x0,y0,x1,y1 = self._bbox_parent
            if x0 <= xi < x1 and y0 <= yi < y1: return "parent"
        return None

    def _on_mouse_down(self, e):
        # space+left => start pan
        if self._space_down:
            self._panning_left = True
            self._on_pan_start(e)
            return
        if not (self.text_overlay.enabled and self._text_allowed_for_current): return
        pt = self._label_to_image_coords(e.x, e.y)
        if pt is None: return
        xi, yi = pt; hit = self._hit(xi, yi)
        if hit is None: return
        self._active_text = hit; fw, fh = self._last_full_composite.size
        nx, ny = xi/fw, yi/fh; to = self.text_overlay
        ox = nx - (to.pos_norm[0] if hit == "parent" else to.child_pos_norm[0])
        oy = ny - (to.pos_norm[1] if hit == "parent" else to.child_pos_norm[1])
        self._drag_offset = (ox, oy); self._drag_active = True

    def _on_mouse_drag(self, e):
        if self._panning_left:
            self._on_pan_drag(e); return
        if not (self.text_overlay.enabled and self._drag_active and self._text_allowed_for_current): return
        pt = self._label_to_image_coords(e.x, e.y)
        if pt is None: return
        fw, fh = self._last_full_composite.size; nx, ny = pt[0]/fw, pt[1]/fh
        nx = min(1.0, max(0.0, nx - self._drag_offset[0])); ny = min(1.0, max(0.0, ny - self._drag_offset[1]))
        if self._active_text == "child": self.text_overlay.child_pos_norm = (nx, ny)
        else: self.text_overlay.pos_norm = (nx, ny)
        self._schedule_preview()

    def _on_mouse_up(self, _):
        if self._panning_left:
            self._on_pan_end(_)
            self._panning_left = False
            return
        self._drag_active = False

    def _on_mouse_wheel(self, e):
        try: ctrl = bool(e.state & 0x0004)
        except Exception: ctrl = False
        if ctrl:
            factor = 1.1 if getattr(e, 'delta', 0) > 0 else 1/1.1
            self._set_zoom((self._zoom_var.get() or 1.0) * factor); return
        if not (self.text_overlay.enabled and self._text_allowed_for_current): return
        if (e.state & 0x0001):
            delta = 5 if e.delta > 0 else -5
            self.text_overlay.rotation_deg = (self.text_overlay.rotation_deg + delta) % 360
            if self._rot_var is not None: self._rot_var.set(self.text_overlay.rotation_deg)
        else:
            factor = 1.1 if e.delta > 0 else 1/1.1
            self.text_overlay.scale = float(min(5.0, max(0.1, self.text_overlay.scale * factor)))
            if self._scale_var is not None: self._scale_var.set(self.text_overlay.scale)
        self._schedule_preview()

    def _on_mouse_wheel_linux(self, e):
        try: ctrl = bool(e.state & 0x0004)
        except Exception: ctrl = False
        if ctrl:
            factor = 1.1 if e.num == 4 else 1/1.1
            self._set_zoom((self._zoom_var.get() or 1.0) * factor); return
        if not (self.text_overlay.enabled and self._text_allowed_for_current): return
        if (e.state & 0x0001):
            delta = 5 if e.num == 4 else -5
            self.text_overlay.rotation_deg = (self.text_overlay.rotation_deg + delta) % 360
            if self._rot_var is not None: self._rot_var.set(self.text_overlay.rotation_deg)
        else:
            factor = 1.1 if e.num == 4 else 1/1.1
            self.text_overlay.scale = float(min(5.0, max(0.1, self.text_overlay.scale * factor)))
            if self._scale_var is not None: self._scale_var.set(self.text_overlay.scale)
        self._schedule_preview()

    # panning -------------------------------------------------------------
    def _on_pan_start(self, e):
        self.preview_label.focus_set()
        self._panning = True
        self._pan_start = (e.x, e.y)
        self._pan_at_start = (self._pan_x, self._pan_y)
        try: self.preview_label.configure(cursor="fleur")
        except Exception: pass

    def _on_pan_drag(self, e):
        if not self._panning: return
        z = max(self._disp_scale, 1e-6)
        dx = int(round((e.x - self._pan_start[0]) / z))
        dy = int(round((e.y - self._pan_start[1]) / z))
        self._pan_x = self._pan_at_start[0] - dx
        self._pan_y = self._pan_at_start[1] - dy
        # clamp
        base = self._last_full_composite
        if base is not None:
            vw = max(1, int(round(self._preview_size[0] / z)))
            vh = max(1, int(round(self._preview_size[1] / z)))
            max_x = max(0, base.width - vw); max_y = max(0, base.height - vh)
            self._pan_x = min(max(0, self._pan_x), max_x)
            self._pan_y = min(max(0, self._pan_y), max_y)
        self._on_zoom_change()

    def _on_pan_end(self, _):
        self._panning = False
        try: self.preview_label.configure(cursor="")
        except Exception: pass

    def _on_space_down(self, _e):
        self._space_down = True
        try: self.preview_label.configure(cursor="fleur")
        except Exception: pass
    def _on_space_up(self, _e):
        self._space_down = False
        if not self._panning_left:
            try: self.preview_label.configure(cursor="")
            except Exception: pass

    # project scanning -----------------------------------------------------
    def _browse_project_root(self):
        d = filedialog.askdirectory(title="Select PaintKit Project Root (contains Resources)")
        if not d:
            return
        self.project_root_var.set(d)
        self._scan_assets()

    def _browse_aircraft_root(self):
        d = filedialog.askdirectory(title="Select Aircraft Folder (contains 'liveries')")
        if not d:
            return
        self.aircraft_root_var.set(d)

    def _auto_set_project_root_and_scan(self):
        """Default project root to the folder containing this script and scan automatically."""
        default_root = str(pathlib.Path(__file__).resolve().parent)
        if not self.project_root_var.get().strip():
            self.project_root_var.set(default_root)
        try:
            self._scan_assets()
        except Exception as e:
            self.status_var.set(f"Auto-scan failed: {e}")

    def _discover_in_dir(self, base: pathlib.Path, label_prefix: str) -> List[dict]:
        assets: List[dict] = []
        if not base.exists():
            return assets
        for p in base.glob("*.png"):
            stem_low = p.stem.lower()
            # skip masks *_pk<digits>
            if re.search(r"_pk\d+$", stem_low):
                continue
            # skip normals & spinner for now
            if "_nml" in stem_low or "spinner" in stem_low:
                continue
            def rel(token: str) -> Optional[pathlib.Path]:
                cand = p.with_name(f"{p.stem}_{token}{p.suffix}")
                if cand.exists():
                    return cand
                token_low = f"{p.stem}_{token}".lower()
                for q in base.glob("*.png"):
                    if q.stem.lower() == token_low:
                        return q
                return None
            m1 = rel("PK1"); m2 = rel("PK2")
            key = str(p)
            assets.append({'key': key, 'name': f"{label_prefix}: {p.stem}", 'albedo': p, 'm1': m1, 'm2': m2})
        return assets

    def _scan_assets(self):
        root = self.project_root_var.get().strip()
        if not root:
            root = str(pathlib.Path(__file__).resolve().parent)
            self.project_root_var.set(root)
        r = pathlib.Path(root)
        interior = r / "Resources" / "Interior"
        exterior = r / "Resources" / "Exterior"
        found: List[dict] = []
        found += self._discover_in_dir(interior, "Interior")
        found += self._discover_in_dir(exterior, "Exterior")
        if not found:
            messagebox.showwarning("No assets", "No PNG albedos found in Resources/Interior or Resources/Exterior next to the app.")
            return
        self.assets = found
        names = [a['name'] for a in self.assets]
        if self.asset_combo:
            self.asset_combo.configure(values=names)
            # prefer fuselage first if present
            default_idx = 0
            for i, a in enumerate(self.assets):
                if "fuselage" in a["name"].lower():
                    default_idx = i
                    break
            self.asset_combo.set(names[default_idx])
        self._on_asset_change()

    def _capture_channels(self) -> dict:
        vals = {}
        for k, v in self.channels.items():
            # safe read
            try:
                h = float(v.hue.get() or 0.0)
                s = float(v.sat.get() or 0.0)
                b = float(v.val.get() or 0.0)
            except Exception:
                h = s = b = 0.0
            vals[k] = (h, s, b, v.invert.get())
        return vals

    def _apply_channels(self, vals: dict) -> None:
        if not vals:
            return
        for k, v in self.channels.items():
            if k in vals:
                h, s, b, inv = vals[k]
                v.hue.set(h); v.sat.set(s); v.val.set(b); v.invert.set(bool(inv))

    def _capture_text_pos(self) -> dict:
        to = self.text_overlay
        return {'parent': to.pos_norm, 'child': to.child_pos_norm}

    def _apply_text_pos(self, pos: Optional[dict]) -> None:
        if not pos:
            return
        to = self.text_overlay
        if 'parent' in pos:
            to.pos_norm = tuple(pos['parent'])
        if 'child' in pos:
            to.child_pos_norm = tuple(pos['child'])

    # ---- per-asset text props ----
    def _capture_text_props(self) -> dict:
        to = self.text_overlay
        return {
            'enabled': bool(to.enabled),
            'child_enabled': bool(to.child_enabled),
            'text': to.text,
            'family': to.font_family,
            'style': to.font_style,
            'size_px': int(to.font_size_px),
            'scale': float(to.scale),
            'rotation': float(to.rotation_deg),
            'fill': to.fill_hex,
            'stroke': to.stroke_hex,
            'stroke_width': int(to.stroke_width),
            'stroke_gap': int(getattr(to, 'stroke_gap', 0)),
            'stroke_offset': [int(to.stroke_offset_x), int(to.stroke_offset_y)],
            'parent_mirror_h': bool(getattr(to, 'parent_mirror_h', False)),
            'child_mirror_h': bool(getattr(to, 'child_mirror_h', False)),
        }

    def _apply_text_props(self, props: Optional[dict]) -> None:
        if not props:
            return
        to = self.text_overlay
        to.enabled = bool(props.get('enabled', to.enabled))
        to.child_enabled = bool(props.get('child_enabled', to.child_enabled))
        to.text = props.get('text', to.text)
        to.font_family = props.get('family', to.font_family)
        to.font_style = props.get('style', to.font_style)
        to.font_size_px = int(props.get('size_px', to.font_size_px))
        to.scale = float(props.get('scale', to.scale))
        to.rotation_deg = float(props.get('rotation', to.rotation_deg))
        to.fill_hex = props.get('fill', to.fill_hex)
        to.stroke_hex = props.get('stroke', to.stroke_hex)
        to.stroke_width = int(props.get('stroke_width', to.stroke_width))
        to.stroke_gap = int(props.get('stroke_gap', getattr(to, 'stroke_gap', 0)))
        so = props.get('stroke_offset', [to.stroke_offset_x, to.stroke_offset_y])
        if isinstance(so, (list, tuple)) and len(so) == 2:
            to.stroke_offset_x, to.stroke_offset_y = int(so[0]), int(so[1])
        to.parent_mirror_h = bool(props.get('parent_mirror_h', getattr(to, 'parent_mirror_h', False)))
        to.child_mirror_h = bool(props.get('child_mirror_h', getattr(to, 'child_mirror_h', False)))

        # reflect in UI
        if hasattr(self, "font_combo") and self.font_map:
            fam = to.font_family
            if fam not in self.font_map:
                fam = sorted(self.font_map.keys())[0]
                to.font_family = fam
            self.font_combo.set(fam)
            styles = sorted(self.font_map[fam].keys())
            self.style_combo.configure(values=styles)
            st = to.font_style if to.font_style in styles else ("Regular" if "Regular" in styles else styles[0])
            to.font_style = st
            self.style_combo.set(st)

        if hasattr(self, "fill_chip"):
            self.fill_chip.configure(bg=to.fill_hex)
        if hasattr(self, "stroke_chip"):
            self.stroke_chip.configure(bg=to.stroke_hex)

        if hasattr(self, "_var_font_size"): self._var_font_size.set(to.font_size_px)
        if hasattr(self, "_var_sw"): self._var_sw.set(to.stroke_width)
        if hasattr(self, "_var_sg"): self._var_sg.set(getattr(to, 'stroke_gap', 0))
        if hasattr(self, "_var_sox"): self._var_sox.set(to.stroke_offset_x)
        if hasattr(self, "_var_soy"): self._var_soy.set(to.stroke_offset_y)
        if hasattr(self, "_scale_var"): self._scale_var.set(to.scale)
        if hasattr(self, "_rot_var"): self._rot_var.set(to.rotation_deg)
        if hasattr(self, "_text_var"): self._text_var.set(to.text)
        if hasattr(self, "_var_parent_mirror"): self._var_parent_mirror.set(bool(getattr(to, 'parent_mirror_h', False)))
        if hasattr(self, "_var_child_mirror"): self._var_child_mirror.set(bool(getattr(to, 'child_mirror_h', False)))

    def _asset_role(self, asset: dict) -> str:
        n = asset['name'].lower()
        if 'fuselage' in n: return 'FUSELAGE'
        if 'wing' in n: return 'WINGS'
        if 'cowling' in n or 'cowlings' in n: return 'COWLINGS'
        if 'internal' in n or 'interior' in n: return 'INTERNAL'
        return 'OTHER'

    def _on_asset_change(self):
        if not self.assets or not self.asset_combo:
            return
        sel_name = self.asset_combo.get()
        asset = next((a for a in self.assets if a['name'] == sel_name), None)
        if not asset:
            return
        # store previous asset state
        if self.current_asset_key:
            st_prev = self.asset_states.get(self.current_asset_key, {})
            st_prev['channels'] = self._capture_channels()
            st_prev['text_pos'] = self._capture_text_pos()
            st_prev['text_props'] = self._capture_text_props()
            self.asset_states[self.current_asset_key] = st_prev
        # switch
        self.current_asset_key = asset['key']
        self._text_allowed_for_current = self._asset_role(asset) in ('FUSELAGE','WINGS')
        self.albedo_path_var.set(str(asset['albedo']))
        self.mask1_path_var.set(str(asset['m1'] or ''))
        self.mask2_path_var.set(str(asset['m2'] or ''))
        st = self.asset_states.get(self.current_asset_key, {})
        self._apply_channels(st.get('channels', {}))
        self._apply_text_pos(st.get('text_pos', None))
        self._apply_text_props(st.get('text_props', None))
        self._try_load_all()

    # saving --------------------------------------------------------------
    def _ensure_livery_objects_dir(self) -> Optional[pathlib.Path]:
        aircraft = self.aircraft_root_var.get().strip()
        if not aircraft:
            messagebox.showwarning("Missing aircraft folder", "Set the Aircraft Folder first.")
            return None
        tail = (self.text_overlay.text or "").strip()
        if not tail:
            messagebox.showwarning("Missing tailnumber", "Enter the tailnumber text in the Text tab.")
            return None
        safe_tail = "".join(ch if ch.isalnum() or ch in ("_","-"," ") else "_" for ch in tail).strip()
        if not safe_tail:
            messagebox.showwarning("Invalid tailnumber", "Tailnumber contains no valid characters.")
            return None
        out_dir = pathlib.Path(aircraft) / "liveries" / safe_tail / "objects"
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _render_full_for_paths(self, albedo_p: pathlib.Path, m1_p: Optional[pathlib.Path], m2_p: Optional[pathlib.Path], channels_vals: Optional[dict]=None, allow_text: bool=True) -> Image.Image:
        a_img, a_alpha = load_albedo(albedo_p)
        m1_img = load_mask_rgb(m1_p, a_img.size) if m1_p else None
        m2_img = load_mask_rgb(m2_p, a_img.size) if m2_p else None
        def build_weights(size: Tuple[int,int]) -> Dict[str, np.ndarray]:
            w: Dict[str, np.ndarray] = {}
            def add(prefix: str, img: Optional[Image.Image]):
                if img is None:
                    return
                r,g,b = (img if img.size == size else img.resize(size, Image.BILINEAR)).split()
                for ch_key, im in zip(("R","G","B"),(r,g,b)):
                    key = f"{prefix}_{ch_key}"; arr = np.asarray(im, dtype=np.float32)/255.0
                    inv = (channels_vals.get(key, (0,0,0,False))[3] if channels_vals is not None else self.channels[key].invert.get())
                    if inv:
                        arr = 1.0 - arr
                    w[key] = arr
            add("M1", m1_img); add("M2", m2_img)
            return w
        weights = build_weights(a_img.size)
        keys = list(weights.keys())
        # choose values from override or current UI
        hue = {k: (channels_vals.get(k,(0,0,0,False))[0] if channels_vals is not None else self._safe_get_float(self.channels[k].hue, 0.0)) for k in keys}
        sat = {k: (channels_vals.get(k,(0,0,0,False))[1] if channels_vals is not None else self._safe_get_float(self.channels[k].sat, 0.0)) for k in keys}
        val = {k: (channels_vals.get(k,(0,0,0,False))[2] if channels_vals is not None else self._safe_get_float(self.channels[k].val, 0.0)) for k in keys}
        out_rgb = apply_hsv_adjust_multi(a_img.convert("RGB"), weights, hue, sat, val)
        if allow_text:
            out_rgb, _, _ = compose_text(out_rgb, self.text_overlay, self.font_map)
        return paste_alpha(out_rgb, a_alpha)

    def save_all_assets(self):
        if not self.assets:
            messagebox.showwarning("No assets", "Scan a Project Root first.")
            return
        out_dir = self._ensure_livery_objects_dir()
        if out_dir is None:
            return
        self.status_var.set("Saving all assets…"); self.update_idletasks()
        ok = 0; errs = []

        # snapshot current UI text state to restore later
        cur_props = self._capture_text_props()
        cur_pos = self._capture_text_pos()

        fuselage = next((a for a in self.assets if self._asset_role(a) == 'FUSELAGE'), None)
        fuselage_vals = self.asset_states.get(fuselage['key'], {}).get('channels') if fuselage else None

        for a in self.assets:
            try:
                role = self._asset_role(a)
                vals = self.asset_states.get(a['key'], {}).get('channels')
                allow_text = role in ('FUSELAGE','WINGS')

                # propagate HSV only (not text props)
                if self.propagate_external_var.get() and role in ('COWLINGS','WINGS') and fuselage_vals:
                    vals = fuselage_vals

                # apply this asset's text state (props + pos) for rendering
                st = self.asset_states.get(a['key'], {})
                self._apply_text_pos(st.get('text_pos', None))
                self._apply_text_props(st.get('text_props', None))

                final = self._render_full_for_paths(a['albedo'], a.get('m1'), a.get('m2'), vals, allow_text=allow_text)
                out_path = out_dir / a['albedo'].name
                if out_path.exists():
                    if not messagebox.askyesno("Overwrite?", f"{out_path}\nalready exists. Overwrite?"):
                        continue
                final.save(out_path, format="PNG")
                ok += 1
            except Exception as e:
                errs.append(f"{a['name']}: {e}")

        # restore UI text state
        self._apply_text_pos(cur_pos)
        self._apply_text_props(cur_props)

        # write JSON config
        try:
            self._save_livery_config(out_dir)
        except Exception as e:
            errs.append(f"Config save: {e}")

        msg = f"Saved {ok} file(s) to {out_dir}"
        if errs:
            msg += "\nErrors:\n" + "\n".join(errs)
        messagebox.showinfo("Save all", msg)
        self.status_var.set(msg)

    # fonts ---------------------------------------------------------------
    def _browse_fonts_dir(self):
        d = filedialog.askdirectory(title="Select Fonts Folder")
        if d:
            self.fonts_dir_var.set(d)

    def _load_fonts_from_dir(self):
        folder = self.fonts_dir_var.get().strip()
        if not folder:
            messagebox.showwarning("No folder", "Pick a Fonts Folder first.")
            return
        try:
            new_map = self._scan_fonts_dir(pathlib.Path(folder))
            if not new_map:
                messagebox.showinfo("Fonts", "No fonts found in that folder.")
                return
            if not self.font_map:
                self.font_map = new_map
            else:
                for fam, styles in new_map.items():
                    self.font_map.setdefault(fam, {}).update(styles)
            fams = sorted(self.font_map.keys())
            self.font_combo.configure(values=fams)
            if fams and self.font_combo.get() not in fams:
                self.font_combo.set(fams[0]); self._on_font_change()
            messagebox.showinfo("Fonts", f"Loaded {sum(len(v) for v in new_map.values())} styles from {folder}")
        except Exception as e:
            messagebox.showerror("Fonts", str(e))

    def _scan_fonts_dir(self, base: pathlib.Path) -> Dict[str, Dict[str, str]]:
        styles_tokens = {
            'bold italic': 'Bold Italic', 'italic bold': 'Bold Italic',
            'black italic': 'Bold Italic', 'bold': 'Bold', 'italic': 'Italic',
            'oblique': 'Italic', 'regular': 'Regular', 'book': 'Regular', 'roman': 'Regular'
        }
        out: Dict[str, Dict[str, str]] = {}
        for p in base.rglob('*'):
            if p.suffix.lower() not in ('.ttf', '.otf', '.ttc'):
                continue
            name = p.stem.replace('_',' ').replace('-',' ')
            low = name.lower()
            fam = name; style = 'Regular'
            for tok, norm in styles_tokens.items():
                if low.endswith(' ' + tok):
                    fam = name[:-(len(tok)+1)]; style = norm; break
            fam = fam.strip()
            out.setdefault(fam, {}); out[fam][style] = str(p)
        return out

    # livery config -------------------------------------------------------
    def _save_livery_config(self, out_objects_dir: pathlib.Path) -> None:
        """Write livery.json with per-asset channels, text positions, and text properties."""
        # ensure current asset state captured
        if self.current_asset_key:
            st_prev = self.asset_states.get(self.current_asset_key, {})
            st_prev['channels'] = self._capture_channels()
            st_prev['text_pos'] = self._capture_text_pos()
            st_prev['text_props'] = self._capture_text_props()
            self.asset_states[self.current_asset_key] = st_prev

        assets_state: Dict[str, dict] = {}
        for a in self.assets:
            st = self.asset_states.get(a['key'], {})
            assets_state[a['key']] = {
                'name': a['name'],
                'albedo': a['albedo'].name,
                'channels': st.get('channels', {}),
                'text_pos': st.get('text_pos', {'parent': self.text_overlay.pos_norm, 'child': self.text_overlay.child_pos_norm}),
                'text_props': st.get('text_props', self._capture_text_props()),
            }

        data = {
            'project_root': self.project_root_var.get().strip(),
            'aircraft_root': self.aircraft_root_var.get().strip(),
            'tailnumber': (self.text_overlay.text or '').strip(),
            'propagate_fuselage': bool(self.propagate_external_var.get()),
            'fonts_dir': self.fonts_dir_var.get().strip(),
            'assets': assets_state,
        }
        cfg = out_objects_dir.parent / 'livery.json'
        with open(cfg, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def _load_livery_config(self, cfg_path: pathlib.Path) -> None:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.project_root_var.set(data.get('project_root', self.project_root_var.get()))
        self.aircraft_root_var.set(data.get('aircraft_root', self.aircraft_root_var.get()))
        self.propagate_external_var.set(bool(data.get('propagate_fuselage', True)))
        self.fonts_dir_var.set(data.get('fonts_dir', self.fonts_dir_var.get()))

        assets_map: Dict[str, dict] = data.get('assets', {})
        for a in self.assets:
            st = None
            if a['key'] in assets_map:
                st = assets_map[a['key']]
            else:
                by_name = next((v for v in assets_map.values() if v.get('name') == a['name']), None)
                if by_name is None:
                    by_name = next((v for v in assets_map.values() if v.get('albedo') == a['albedo'].name), None)
                st = by_name
            if st:
                self.asset_states[a['key']] = {
                    'channels': st.get('channels', {}),
                    'text_pos': st.get('text_pos', None),
                    'text_props': st.get('text_props', None),
                }

        # apply for currently selected asset
        if self.asset_combo and self.asset_combo.get():
            self._on_asset_change()
        self._schedule_preview()

    # startup -------------------------------------------------------------
    def _startup_flow(self):
        if self._startup_done:
            return
        self._startup_done = True
        # pick aircraft root if not set
        if not self.aircraft_root_var.get().strip():
            self._browse_aircraft_root()
        # create or edit?
        create = messagebox.askyesno("Start", "Create new livery?\nYes = Create new, No = Edit existing")
        if create:
            tail = simpledialog.askstring("Tailnumber", "Enter tailnumber (folder name)")
            if tail:
                self.text_overlay.text = tail.strip()
                out = self._ensure_livery_objects_dir()
                if out is None:
                    return
                self.status_var.set(f"Livery folder ready: {out.parent}")
        else:
            base = pathlib.Path(self.aircraft_root_var.get().strip()) / 'liveries'
            d = filedialog.askdirectory(title="Select existing livery folder", initialdir=str(base) if base.exists() else None)
            if d:
                tail = pathlib.Path(d).name
                self.text_overlay.text = tail
                cfg = pathlib.Path(d) / 'livery.json'
                if cfg.exists():
                    try:
                        self._load_livery_config(cfg)
                    except Exception as e:
                        messagebox.showwarning("Config", f"Failed to load config:\n{e}")


if __name__ == "__main__":
    App().mainloop()
