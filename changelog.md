# Changelog

All notable changes to this project will be documented here.

This project follows the [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) style and uses calendar versions.

## [2025-08-12]
### Added
- **Project split** into modules: `app.py`, `core.py`, `text_overlay.py`.
- **Zoom & Pan**: Ctrl+Mouse Wheel zoom, Middle‑mouse drag pan, Space+Left‑drag pan.
- **Selection overlay**: red (active) / yellow (inactive) marquee boxes that respect pan/zoom.
- **Automatic mask discovery**: load `Name_PK1.png` / `Name_PK2.png` next to `Name.png`.
- **Dynamic M2 tabs**: show `M2_R/G/B` only if the channel contains information.
- **Text overlay controls**: numeric scale/rotation, color chips, font family/style pickers.
- **Mirrored child text**: 180° baseline + opposite rotation, independent position.
- **Stroke gap** option to create a clean separation between fill and stroke.
- **Stroke offset X/Y** to shift outline relative to fill.
- **README.md** and **requirements.txt**.

### Changed
- Preview now renders a **cropped viewport** when zoomed in and scales to 1024×1024 display area.
- Text rendering pipeline uses **mask‑first transforms** (rotate/mirror masks, then colorize) to reduce anti‑aliasing halos.
- Save path dialog writes output with **original filename** to user‑chosen folder.

### Fixed
- Several indentation and f‑string line‑break issues in dialogs.
- Missing `paste_alpha` reference wired up via `core.py`.
- Reset now recenters text instead of hiding it.

## [2025-08-10]
### Added
- **Brightness (Value) slider** alongside Hue/Saturation.
- **Dual mask support**: second mask (`_PK2`) with per‑channel controls.

## [2025-08-08]
### Added
- Initial Tkinter GUI with 1024×1024 preview.
- Per‑channel HSV adjustments for first mask (`_PK1`).
- Basic text overlay with fill/stroke and draggable positioning.

---

## Unreleased / Ideas
- Cursor‑centric zoom (keep point under cursor fixed while zooming).
- Fit/Fill/1:1 quick zoom buttons and zoom percentage readout.
- Snap‑to guides and arrow‑key nudge for text.
- Configurable font search paths & user font folder.
- Unit tests for mask discovery and HSV weighting.

