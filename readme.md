# CIS PaintKit

Albedo + Dual‑Mask HSV Editor with interactive Text Overlay (Tkinter/Pillow).

## Features

- **Automatic mask discovery**: when you open `Name.png` (albedo), the app auto‑loads `Name_PK1.png` and `Name_PK2.png` if present.
- **Per‑channel HSV**: independent Hue/Saturation/Brightness per mask channel: `M1_R/G/B` and (if present) `M2_R/G/B`.
- **Live 1024×1024 preview** of the full‑resolution image with **zoom**/**pan**.
- **Text overlay**: system fonts, styles (Regular/Bold/Italic/Bold Italic), color chips for fill/stroke, stroke width, **stroke gap** (offset from fill), stroke offset X/Y, mirroring, child text (mirrored & 180° baseline) that shares scale/rotation but can be positioned separately.
- **Accurate save**: final PNG saved at original resolution and preserves source alpha.

## Requirements

Install Python 3.9+ and these packages:

```txt
Pillow>=10.0.0,<11
numpy>=1.23
```

> Tkinter ships with most Python distributions (Windows/macOS installers, many Linux packages). If you’re missing it on Linux, install your distro’s `tk` package.

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Run

```bash
python app.py
```

## Packaging (PyInstaller)

```bash
pyinstaller --noconfirm --onefile --windowed \
  --name CIS-PaintKit \
  --collect-all PIL \
  app.py
```

Result is in `dist/`.

---

## GUI: Commands & Shortcuts

**Open albedo**

- Click **Open…** and select `Name.png`. The app will search in the same folder for `Name_PK1.png` and `Name_PK2.png`.

**Adjust colors**

- Use tabs `M1_R`, `M1_G`, `M1_B` (and `M2_*` if present) to set **Hue (°)**, **Saturation (%)**, **Brightness (%)**.
- **Invert mask** flips the selected channel (useful for switching affected areas).

**Preview controls**

- **Zoom**: `Ctrl + Mouse Wheel` (or the Zoom slider on the left).
- **Pan**: Middle‑mouse drag **or** `Space + Left‑drag`.
- **Show selection**: toggles red/yellow selection rectangles.

**Text overlay tab**

- **Enable text overlay**: master toggle.
- **Enable mirrored child**: adds a second text that’s baseline‑mirrored (180°) and rotates opposite to the parent.
- **Edit text**: type in the text field.
- **Font family & Style**: pick from preloaded families and their styles.
- **Size (px)** and **Scale**: pixel size + live scale control.
- **Rotation (°)**: rotate parent text. Child text rotates to `180° − rotation`.
- **Fill / Stroke chips**: click the colored chips to open color pickers.
- **Stroke width (px)**: outline thickness.
- **Stroke gap (px)**: creates a gap between fill and stroke (anti‑halo rendering).
- **Stroke offset X/Y**: shifts the stroke layer relative to the fill.
- **Center Parent / Center Child**: re‑center positions on the image.

**Text interactions**

- **Move text**: click inside the red (active) selection rectangle and **drag**.
- **Choose active item**: click inside **Parent** or **Child** selection rectangle to make it active (red). The other shows in yellow.
- **Rotate on the fly**: `Shift + Mouse Wheel` (over the preview) rotates the active text.
- **Scale on the fly**: `Mouse Wheel` (without Ctrl/Shift) scales the active text.

**Save**

- Click **Save…**, choose a destination folder. The file is saved as the **same name** as the albedo (`Name.png`).

---

## Tips & Notes

- If `Mask 2` channels are all empty, the `M2_*` tabs stay hidden.
- `Reset All` restores mask sliders and re‑centers text with rotation=0 and scale=1.
- On high‑DPI displays, use the zoom slider or `Ctrl + Wheel` for a comfortable view; panning works at any zoom.
- Fonts: We preload common families (Arial/Segoe UI on Windows, Helvetica/Arial on macOS, DejaVu/Liberation on Linux). Extend `preload_fonts()` if you need custom faces.

## Troubleshooting

- **Mouse wheel doesn’t zoom**: ensure the app window has focus (click the preview first). On Linux touchpads, try two‑finger scroll; some desktops report it via Button‑4/5 which is handled.
- **Fonts/styles missing**: verify the family exists on your OS; otherwise update `preload_fonts()` with the file paths.
- **No masks found**: ensure files are named `Name_PK1.png` and `Name_PK2.png` alongside the albedo.

## License

MIT (add your preferred license here).

