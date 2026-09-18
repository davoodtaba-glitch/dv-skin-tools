<p align="center">
  <img src="docs/banner.jpg" alt="DV Skin Tools — Maya-style skinning in Blender" width="100%">
</p>

<h1 align="center">DV Skin Tools</h1>

<p align="center">
  <strong>Maya-style multi-influence skinning for Blender weight paint.</strong><br>
  Smooth every bone at once. Bind, mirror, copy, and visualize weights the way character TDs expect.
</p>

<p align="center">
  <img alt="Version" src="https://img.shields.io/badge/version-0.8.30-4F8CFF?style=for-the-badge">
  <img alt="Blender" src="https://img.shields.io/badge/Blender-4.2%2B-F5792A?style=for-the-badge&logo=blender&logoColor=white">
</p>

---

## Install

**Blender 4.2+** (including Blender 5)

1. Download [`dv_skin_tool-0.8.30-protected.zip`](https://github.com/davoodtaba-glitch/dv-skin-tools/releases/latest) from Releases, or the zip in this repository.
2. In Blender: **Edit → Preferences → Get Extensions** (or **Add-ons**) → **Install from Disk**.
3. Choose the zip and enable **DV Skin Tools**.
4. In the 3D Viewport, open the **N** panel → **DV Skin Tools**.

If an older *Skin Tools* or *DV Skin Tools* add-on is installed, remove it first, then restart Blender before installing.

[User Guide (PDF)](DV_Skin_Tools_User_Guide.pdf)

---

## Brush

Weight Paint mode → **Paint** to start a session. The sidebar stays live.

| Mode | What it does |
| --- | --- |
| **Smooth** | Average all influences with neighbors. Close vertices move together. |
| **Sharpen** | Push weights away from the neighbor average. |
| **Stitch** | Blend border vertices toward their partner across a seam gap. |
| **Replace** | Set the active bone to Intensity. |
| **Add** | Add Intensity to the active bone. |
| **Remove** | Subtract Intensity from the active bone. |

**Flood** applies the current mode to the whole mesh, or only the paint mask.

**Ignore Gap** (Replace, Add, Remove, Sharpen): when off, only vertices connected to the hit surface are painted, so a brush over a waist gap does not stamp a disconnected shell. Smooth and Stitch never use this filter.

---

## Author

Davood Taba — [davoodice@gmail.com](mailto:davoodice@gmail.com)
