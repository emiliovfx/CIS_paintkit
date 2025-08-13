#!/usr/bin/env python3
# file: app.py
from __future__ import annotations
import os, pathlib, tkinter as tk
from typing import Optional, Tuple, Dict
from tkinter import ttk, filedialog, messagebox, colorchooser
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
        self.title("Albedo + Dual‑Mask HSV Editor + Text Overlay")
        self.geometry("1480x980"); self.minsize(1200, 820)

        self._images = None
        self._preview_size = (1024, 1024)
        self._preview_photo: Optional[ImageTk.PhotoImage] = None
        self._debounce_job = None

        # zoom / pan / preview cache
        self._zoom_var = tk.DoubleVar(value=1.0)
        self._last_full_composite: Optional[Image.Image] = None
        self._last_preview_img_size: Optional[Tuple[int, int]] = None
        self._last_preview_padding: Tuple[int, int] = (0, 0)
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

        # paths & status
        self.albedo_path_var = tk.StringVar(); self.mask1_path_var = tk.StringVar(); self.mask2_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Open albedo to auto‑load masks…")

        self._build_ui()

    # UI ------------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)
        ttk.Label(top, text="Albedo:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.albedo_path_var, width=68).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Open…", command=self.open_albedo).grid(row=0, column=2)
        top.columnconfigure(1, weight=1)

        self.nb = ttk.Notebook(self); self.nb.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=(0, 10))
        for key, label in (("M1_R","Mask1 - Red"),("M1_G","Mask1 - Green"),("M1_B","Mask1 - Blue")):
            self._ensure_tab(key, label)
        ttab = ttk.Frame(self.nb); self._build_text_tab(ttab); self.nb.add(ttab, text="Text")

        btns = ttk.Frame(self); btns.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), pady=(0, 10))
        ttk.Button(btns, text="Reset All", command=self.reset_all).pack(anchor="w", pady=(4, 6))
        ttk.Button(btns, text="Save…", command=self.save_output).pack(anchor="w")
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
        tvar = tk.StringVar(value=to.text); ttk.Entry(parent, textvariable=tvar, width=40).grid(row=1, column=1, sticky="ew", **pad)
        tvar.trace_add("write", lambda *_: (setattr(to, "text", tvar.get()), self._schedule_preview()))

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

        ttk.Label(parent, text="Font size (px)").grid(row=4, column=0, sticky="w", **pad)
        sz = tk.IntVar(value=to.font_size_px); ttk.Spinbox(parent, from_=6, to=512, textvariable=sz, width=7, command=lambda: self._on_size_change(sz)).grid(row=4, column=1, sticky="w", **pad)
        sz.trace_add("write", lambda *_: self._on_size_change(sz))

        ttk.Label(parent, text="Fill").grid(row=5, column=0, sticky="w", **pad)
        self.fill_chip = tk.Label(parent, text=" ", width=4, relief="groove", bg=to.fill_hex); self.fill_chip.grid(row=5, column=1, sticky="w", **pad)
        self.fill_chip.bind("<Button-1>", lambda _e: self._pick_fill())

        ttk.Label(parent, text="Stroke").grid(row=6, column=0, sticky="w", **pad)
        self.stroke_chip = tk.Label(parent, text=" ", width=4, relief="groove", bg=to.stroke_hex); self.stroke_chip.grid(row=6, column=1, sticky="w", **pad)
        self.stroke_chip.bind("<Button-1>", lambda _e: self._pick_stroke())

        ttk.Label(parent, text="Stroke width (px)").grid(row=7, column=0, sticky="w", **pad)
        sw = tk.IntVar(value=to.stroke_width); ttk.Spinbox(parent, from_=0, to=50, textvariable=sw, width=7, command=lambda: self._on_sw_change(sw)).grid(row=7, column=1, sticky="w", **pad)
        sw.trace_add("write", lambda *_: self._on_sw_change(sw))

        ttk.Label(parent, text="Stroke gap (px)").grid(row=8, column=0, sticky="w", **pad)
        sg = tk.IntVar(value=getattr(to, 'stroke_gap', 0)); ttk.Spinbox(parent, from_=0, to=50, textvariable=sg, width=7, command=lambda: self._on_gap(sg)).grid(row=8, column=1, sticky="w", **pad)
        sg.trace_add("write", lambda *_: self._on_gap(sg))

        ttk.Label(parent, text="Scale").grid(row=9, column=0, sticky="w", **pad)
        sc = tk.DoubleVar(value=to.scale); ttk.Scale(parent, from_=0.1, to=5.0, orient=tk.HORIZONTAL, variable=sc, command=lambda _=None: self._on_scale(sc)).grid(row=9, column=1, sticky="ew", **pad)
        ttk.Spinbox(parent, from_=0.1, to=5.0, increment=0.05, textvariable=sc, width=7, command=lambda: self._on_scale(sc)).grid(row=9, column=2, sticky="w", **pad)
        sc.trace_add("write", lambda *_: self._on_scale(sc)); self._scale_var = sc

        ttk.Label(parent, text="Rotation (°)").grid(row=10, column=0, sticky="w", **pad)
        rt = tk.DoubleVar(value=to.rotation_deg); ttk.Scale(parent, from_=-180, to=180, orient=tk.HORIZONTAL, variable=rt, command=lambda _=None: self._on_rot(rt)).grid(row=10, column=1, sticky="ew", **pad)
        ttk.Spinbox(parent, from_=-180, to=180, increment=1, textvariable=rt, width=7, command=lambda: self._on_rot(rt)).grid(row=10, column=2, sticky="w", **pad)
        rt.trace_add("write", lambda *_: self._on_rot(rt)); self._rot_var = rt

        ttk.Button(parent, text="Center Parent", command=self._center_text_parent).grid(row=11, column=0, sticky="w", **pad)
        ttk.Button(parent, text="Center Child", command=self._center_text_child).grid(row=11, column=1, sticky="w", **pad)

        mp = tk.BooleanVar(value=to.parent_mirror_h); ttk.Checkbutton(parent, text="Mirror parent (H)", variable=mp, command=lambda: (setattr(to,"parent_mirror_h", mp.get()), self._schedule_preview())).grid(row=12, column=0, sticky="w", **pad)
        mc = tk.BooleanVar(value=to.child_mirror_h); ttk.Checkbutton(parent, text="Mirror child (H)", variable=mc, command=lambda: (setattr(to,"child_mirror_h", mc.get()), self._schedule_preview())).grid(row=12, column=1, sticky="w", **pad)

        ttk.Label(parent, text="Stroke offset X").grid(row=13, column=0, sticky="w", **pad)
        sox = tk.IntVar(value=to.stroke_offset_x); ttk.Spinbox(parent, from_=-200, to=200, textvariable=sox, width=7, command=lambda: self._on_sox(sox)).grid(row=13, column=1, sticky="w", **pad)
        sox.trace_add("write", lambda *_: self._on_sox(sox))
        ttk.Label(parent, text="Stroke offset Y").grid(row=14, column=0, sticky="w", **pad)
        soy = tk.IntVar(value=to.stroke_offset_y); ttk.Spinbox(parent, from_=-200, to=200, textvariable=soy, width=7, command=lambda: self._on_soy(soy)).grid(row=14, column=1, sticky="w", **pad)
        soy.trace_add("write", lambda *_: self._on_soy(soy))

        parent.columnconfigure(1, weight=1)

    # text handlers -------------------------------------------------------
    def _on_font_change(self):
        fam = self.font_combo.get(); self.text_overlay.font_family = fam
        styles = sorted(self.font_map[fam].keys()) if (self.font_map and fam in self.font_map) else ["Regular"]
        self.style_combo.configure(values=styles)
        pick = self.text_overlay.font_style if self.text_overlay.font_style in styles else ("Regular" if "Regular" in styles else styles[0])
        self.style_combo.set(pick); self.text_overlay.font_style = pick
        self._schedule_preview()

    def _on_style_change(self): self.text_overlay.font_style = self.style_combo.get() or "Regular"; self._schedule_preview()
    def _on_size_change(self, var): self.text_overlay.font_size_px = max(1, int(var.get())); self._schedule_preview()
    def _on_sw_change(self, var): self.text_overlay.stroke_width = max(0, int(var.get())); self._schedule_preview()
    def _on_gap(self, var): self.text_overlay.stroke_gap = max(0, int(var.get())); self._schedule_preview()
    def _on_scale(self, var): self.text_overlay.scale = max(0.05, float(var.get())); self._schedule_preview()
    def _on_rot(self, var): self.text_overlay.rotation_deg = float(var.get()); self._schedule_preview()
    def _on_sox(self, var): self.text_overlay.stroke_offset_x = int(var.get()); self._schedule_preview()
    def _on_soy(self, var): self.text_overlay.stroke_offset_y = int(var.get()); self._schedule_preview()

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
        z = max(0.05, min(2.0, float(z))); self._zoom_var.set(z); self._on_zoom_change();
        try: self.status_var.set(f"Zoom: {int(z*100)}%")
        except Exception: pass

    # file actions --------------------------------------------------------
    def _find_related_mask(self, albedo_path: str, token: str) -> Optional[str]:
        p = pathlib.Path(albedo_path); base, suffix, parent = p.stem, p.suffix, p.parent
        cand = parent / f"{base}_{token}{suffix}";
        if cand.exists(): return str(cand)
        target = f"{base}_{token}".casefold()
        try:
            for f in parent.iterdir():
                if f.is_file() and f.suffix.lower() == suffix.lower() and f.stem.casefold() == target:
                    return str(f)
        except Exception: pass
        return None

    def open_albedo(self):
        p = filedialog.askopenfilename(title="Open Albedo PNG", filetypes=PNG_FT)
        if not p: return
        self.albedo_path_var.set(p); self.mask1_path_var.set(""); self.mask2_path_var.set("")
        m1 = self._find_related_mask(p, "PK1"); m2 = self._find_related_mask(p, "PK2")
        if m1: self.mask1_path_var.set(m1)
        if m2: self.mask2_path_var.set(m2)
        self._try_load_all()
        if not m1: self.status_var.set("Albedo loaded. Related Mask 1 not found (expected _PK1).")

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
            keys = list(weights.keys()); hue = {k: self.channels[k].hue.get() for k in keys}; sat = {k: self.channels[k].sat.get() for k in keys}; val = {k: self.channels[k].val.get() for k in keys}
            out_full = apply_hsv_adjust_multi(full.convert("RGB"), weights, hue, sat, val)
            out_full, self._bbox_parent, self._bbox_child = compose_text(out_full, self.text_overlay, self.font_map)
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
        if not self.text_overlay.enabled or not self._show_sel.get(): return
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
        if not self.text_overlay.enabled: return
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
        if not (self.text_overlay.enabled and self._drag_active): return
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
        if not self.text_overlay.enabled: return
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
        if not self.text_overlay.enabled: return
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

    # saving --------------------------------------------------------------
    def save_output(self):
        if not self._images:
            messagebox.showwarning("Missing images", "Load an albedo and Mask 1 first."); return
        folder = filedialog.askdirectory(title="Select destination folder")
        if not folder: return
        out_path = pathlib.Path(folder) / self._images['albedo_path'].name
        if out_path.exists():
            if not messagebox.askyesno("Overwrite?", f"{out_path}\nalready exists. Overwrite?"): return
        self.status_var.set("Saving…"); self.update_idletasks()
        try:
            full = self._images['albedo_full']
            weights = self._build_weights(full.size)
            keys = list(weights.keys()); hue = {k: self.channels[k].hue.get() for k in keys}; sat = {k: self.channels[k].sat.get() for k in keys}; val = {k: self.channels[k].val.get() for k in keys}
            out = apply_hsv_adjust_multi(full.convert("RGB"), weights, hue, sat, val)
            out, _, _ = compose_text(out, self.text_overlay, self.font_map)
            paste_alpha(out, self._images['albedo_alpha']).save(out_path, format="PNG")
            self.status_var.set(f"Saved: {out_path}"); messagebox.showinfo("Saved", f"Output written to:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Save error", str(e)); self.status_var.set("Save failed.")

if __name__ == "__main__":
    App().mainloop()
