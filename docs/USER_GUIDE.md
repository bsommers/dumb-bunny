# 🕹️ Operation Dumb Bunny — Operator Handbook & 3D Printing Field Manual

> **WELCOME TO THE GRID, USER.**  
> Whether you're here to monitor the OSI Bionic Lab dashboard, tweak Dumb Bunny's plush velour creases live in Blender 5.0, or fire up your 3D printer to materialize a crack-free bionic rabbit — this handbook has your back.  
> *No Scotch tape required.*

---

## 1. Prerequisites

| Component | Recommended Version | Used For |
| :--- | :--- | :--- |
| **macOS / Python** | Python `3.11+` (`numpy`, `scipy`, `Pillow`) | Photogrammetry, facial symmetry repair, QA audit, IPC client & Web Tracker |
| **Blender** | **Blender `5.0.1+`** (`/Applications/Blender.app`) | Live GUI sculpting, PBR showcase & watertight STL/OBJ export |
| **3D Printer Slicer** | PrusaSlicer, Bambu Studio, OrcaSlicer, Cura, or Lychee/Chitubox | Slicing `output/dumb_bunny_repaired.stl` or `dumb_bunny_face_mask_repaired.stl` |

---

## 2. Running the Live Mission Control Tracker

The Mission Control HUD runs locally with zero external dependencies (pure Python standard library backend + vanilla HTML/CSS/JS frontend):

```bash
python3 tracker/server.py 8765
```

Then open **`http://127.0.0.1:8765`** in your browser.

### What You Can Do in the HUD
- **Collapsible Live Gantt Chart (Top Panel):** Inspect exact parallel execution windows across all 4 specialist agents and 7 pipeline stages. Hover over any bar for exact start timestamp, duration, model pill, and active task. Click **Collapse / Expand** (state is persisted in `localStorage`) while keeping elapsed time and lane telemetry visible in the bar.
- **Live Blender Viewport Feed:** Browse every live `1280×800` render captured straight out of the Blender 5.0.1 desktop GUI (`01_ref_rig.png` through `08_back.png`).
- **Facial Symmetry Comparison:** Inspect the aligned damaged intake face, the diagnostic crack-derezzing mask, and the final `99.69%`-symmetric Crisp v3 restoration side-by-side.
- **Download Ready Deliverables:** Click links to inspect generated `.stl`, `.obj`, `.mtl`, and `.blend` files directly via the local server.

> **Tip:** Need a different port? Pass it as the first argument: `python3 tracker/server.py 9000`.

---

## 3. Launching & Driving Blender 5.0 Live (Watch the Bionic Rebuild!)

Unlike headless scripts, Operation Dumb Bunny lets you watch every mesh appear and rotate live inside Blender's desktop viewport.

### Step A — Start Blender with the Live IPC Bridge
```bash
/Applications/Blender.app/Contents/MacOS/Blender --python src/blender_live_bridge.py
```
Wait ~2 seconds for Blender's dark bionic studio viewport (3-point area lights + `LiveStudioCamera`) to initialize.

### Step B — Verify the Grid Handshake
In a second terminal:
```bash
python3 src/blender_ipc_client.py --wait
python3 src/blender_ipc_client.py --ping
# Expected output: {'id': '...', 'ok': True, 'output': 'pong', 'error': None}
```

### Step C — Execute the 5 Sculpt Stages Live
Run them in sequence and watch Dumb Bunny materialize inside Blender (and stream live snapshots to `http://127.0.0.1:8765`!):

```bash
# Stage 1: Mount the 4-view backface-culled orthographic rig & glowing pedestal
python3 src/blender_ipc_client.py src/blender_parts/stage1_ref_rig.py

# Stage 2: Sculpt plush velour torso drapery & cinched hood collar
python3 src/blender_ipc_client.py src/blender_parts/stage2_body_hood.py

# Stage 3: Sculpt chubby olive-tan arms, oval feet & print-safe floppy ears
python3 src/blender_ipc_client.py src/blender_parts/stage3_limbs_ears.py

# Stage 4: Sculpt bionic right-to-left symmetric face & standalone mask shell
python3 src/blender_ipc_client.py src/blender_parts/stage4_face_symmetry.py

# Stage 5: Apply PBR shaders, render 4 turnarounds, save .blend & export OBJ + watertight STLs
python3 src/blender_ipc_client.py src/blender_parts/stage5_materials_export.py
```

### Bonus: Controlling the Live Viewport via Inline IPC
Because `blender_live_bridge.py` accepts `exec_code` payloads, you can pause/resume the live turntable orbit or snap custom angles on the fly:

```bash
python3 -c '
import sys; sys.path.insert(0, "src")
from blender_ipc_client import send_cmd
# Pause auto-orbit so you can inspect manually in Blender GUI
send_cmd({"action": "exec_code", "code": "ORBIT_STATE[\"enabled\"] = False"})
'
```

---

## 4. Customizing & Re-Sculpting Dumb Bunny

Want to tweak proportions, regenerate facial textures, or adjust ear flop angles? Every stage is cleanly decoupled:

1. **Re-run 4-View Photogrammetry (`work/measurements.json` & `ortho_*.png`):**
   ```bash
   python3 src/analyze_views.py
   ```
   Edit `TARGET_HEIGHT_M = 0.180` in `src/analyze_views.py` if you want a taller or smaller calibrated scale (e.g., `0.220` for a 220 mm deluxe edition!).
2. **Re-run Facial Symmetry Repair (`work/textures/face_repaired.png` & heightmap):**
   ```bash
   python3 src/repair_face_symmetry.py
   ```
   Inspect `work/textures/face_repaired.png` and `work/face_blueprint.json` to verify symmetry metrics before re-running Stage 4 & Stage 5 in Blender.
3. **Interactive Tweaking in Blender:**
   Open `models/dumb_bunny.blend` directly in Blender 5.0+:
   - `DumbBunny_Model` collection holds the clean, separated, UV-mapped parts (`DumbBunny_Torso`, `DumbBunny_Hood`, `DumbBunny_Arm_R/L`, `DumbBunny_Foot_R/L`, `DumbBunny_Ear_R/L`, `DumbBunny_Face`).
   - `Print_FaceMask` collection holds `DumbBunny_Face_Mask_Standalone` (hidden during studio renders — toggle visibility in the Outliner to inspect).
   - `Reference_Rig` collection holds the 4 calibrated orthographic photo planes (toggle on anytime to cross-check silhouette fidelity!).
   - After editing any mesh, re-run `stage5_materials_export.py` via the bridge (or Blender's Scripting tab) to regenerate the watertight STLs, then run `python3 src/verify_prototype.py` to confirm 0 non-manifold edges!

---

## 5. Inspecting the Exported Deliverables

| File | Format | Intended Use |
| :--- | :---: | :--- |
| `output/dumb_bunny_repaired.stl` | Binary STL (`mm`) | **Primary 3D print** — full 180 mm restored figurine with flat print-bed base |
| `output/dumb_bunny_face_mask_repaired.stl` | Binary STL (`mm`) | **Standalone replacement face mask** — ultra-fine `0.45 mm` remesh, exact bilateral symmetry |
| `output/dumb_bunny_repaired.obj` + `.mtl` + `face_repaired.png` | Wavefront OBJ/MTL | Universal 3D viewer, full-color sandstone/PolyJet printing, AR/VR, Unity/Unreal |
| `models/dumb_bunny.blend` | Blender 5.0 Scene | Master editable project with packed textures, PBR shaders, 3-point lights & ortho rig |

### Running the Automated Mesh & Printability Audit
```bash
python3 src/verify_prototype.py
```
This prints a full pass/fail report and updates `work/qa_report.json` with triangle counts, exact bounding box dimensions (mm), signed volume (cm³), manifold edge counts, and 3D bilateral X-symmetry RMS error.

---

## 6. 🖨️ 3D Printing Field Manual

Both STL exports are already pre-scaled to **millimeters** (`1 unit = 1 mm`) and verified **100% 2-manifold watertight** with **zero boundary edges** and **zero non-manifold edges**.

### Option A: Printing the Full Figurine (`output/dumb_bunny_repaired.stl`)

> **Verified Print Specs (`work/qa_report.json`):** `139.57 × 95.55 × 184.01 mm` · **`358,230` triangles** · **`1` watertight shell** (`0` boundary / `0` non-manifold edges) · **`784.616 cm³`** volume (`605.60 cm²` surface area) · `17.08 MB` binary STL.

Dumb Bunny includes an engineered **flat bottom bed-contact cut (`Z = 0.000 mm`)** so he sits flush on your build plate without rolling, plus thickened floppy paddle ears (`≥ 5.6 mm`) for structural durability.

#### Recommended FDM Settings (PLA / Matte PLA / PETG)
| Setting | Recommendation | Why? |
| :--- | :--- | :--- |
| **Orientation** | Upright (`Z = 0` flat bottom directly on build plate) | Maximizes bed adhesion & keeps face layers crisp and concentric |
| **Layer Height** | **`0.12 mm`** *(or `0.16 mm` adaptive/variable)* | Captures subtle facial eye/muzzle relief and hood pleats cleanly |
| **Wall Loops / Perimeters** | `3` walls (`~1.2 mm` shell) | Strong enough for floppy ears & smooth sanding if painting |
| **Infill** | `15% Gyroid` or `Lightning` (if display-only) | Lightweight, fast print, balanced center of gravity |
| **Supports** | **Tree / Organic Supports** *(Build Plate Only, `30°–35°` threshold)* | Gently supports the undersides of the floppy ears, chin rim, and stubby arms while leaving the front face spotless! |
| **Brim** | Optional `5 mm` outer brim (if using glossy PEI plate) | Extra insurance for tall `180 mm` prints |
| **Filament Pick** | Warm Cream / Matte Beige PLA (for painting) or Silk Dusty Rose | Matte PLA hides layer lines and takes acrylic primer beautifully |

#### Recommended Resin / SLA Settings (Ultra-Crisp Vintage Vinyl Finish!)
| Setting | Recommendation | Why? |
| :--- | :--- | :--- |
| **Orientation** | Tilted **`25°–30°` backward** (face angled upward) | Keeps all support marks on the back velour seam — **zero marks on the face!** |
| **Layer Height** | `0.03 mm` – `0.05 mm` | Museum-grade smooth rubber face & velour micro-folds |
| **Hollowing** | **Recommended!** `2.5 mm` wall thickness + two `4 mm` drain holes in the flat bottom seat | Saves ~65% resin and prevents suction-cup layer shifts |
| **Resin Pick** | ABS-Like Gray/Beige or Tough Matte Resin | Prevents brittle ear tips if Dumb Bunny ever takes another tumble |

---

### Option B: Printing the Standalone Bionic Face Mask (`output/dumb_bunny_face_mask_repaired.stl`)

> **Verified Print Specs (`work/qa_report.json`):** `58.56 × 26.84 × 56.47 mm` · **`124,644` triangles** · **`1` watertight shell** (`0` boundary / `0` non-manifold edges) · **`10.170 cm³`** volume · **`0.0029 mm` bilateral X-symmetry RMS** (`0.005%` of width!) · `5.94 MB` binary STL.

Want to literally perform **Six Million Dollar Man surgery** on a vintage rubber-face plushie — or paint a standalone miniature display mask?

| Printing Mode | Recommended Setup | Pro Tip |
| :--- | :--- | :--- |
| **Resin / SLA (Best Choice!)** | Stand near-vertical (`15°–20°` tilt back), `0.03 mm` layers, medium supports on the concave back only | Produces a glass-smooth vintage vinyl sheen on the front face with zero sanding required! |
| **FDM (0.2 mm or 0.4 mm Nozzle)** | Stand upright or tilt `45°` face-up, `0.08–0.12 mm` layers, tree supports on back | Use **TPU 95A (Soft/Flex)** if you want an authentic squishy rubber-face feel! |

#### Vintage Painting Recipe (Match the Authentic Photogrammetry Swatches!)
Want to hand-paint your printed Dumb Bunny to match the original childhood plushie? Here are the exact sampled colors from `work/measurements.json` & `work/face_blueprint.json`:

| Region | Sampled Hex | Paint / Finishing Note |
| :--- | :---: | :--- |
| **Vintage Rubber Face** | `#AF875E` (Highlight `#C2986B`) | Warm peach-cream acrylic base + **satin varnish** for molded vinyl sheen |
| **Cheek Blush** | `#B98C5D` | Soft dry-brushed warm peach/terracotta on outer baby cheeks |
| **Button Nose** | `#944536` | Muted vintage dusty coral-pink tip |
| **Side-Glancing Eyes** | `#3C6885` (Iris) · `#E2E2E4` (Sclera) · `#16181C` (Lashes) | Gloss varnish drop over the eyes brings the vintage gaze to life! |
| **Hood & Onesie Velour** | `#967274` (Shadow `#6F494E`) | Dusty mauve-rose matte acrylic (or flock powder for real plush texture!) |
| **Arms, Feet & Floppy Ears** | `#856845` | Aged warm olive-tan matte wash to accentuate the blanket-stitch ridges |

---

## 7. Troubleshooting

| Symptom | Quick Fix |
| :--- | :--- |
| **`Timed out waiting for Blender Live Bridge`** | Make sure Blender was launched *without* `-b` (background/headless mode) and with `--python src/blender_live_bridge.py`. Check `work/blender_ipc/outbox/bridge_ready.json`. |
| **Tracker shows stale data or refuses to connect** | Confirm `python3 tracker/server.py 8765` is running and check `curl -s http://127.0.0.1:8765/api/state \| head`. Hard-refresh (`Cmd+Shift+R`) to bypass any browser cache. |
| **STL imports tiny or gigantic in slicer** | Both STLs are exported in **millimeters** (`180 mm` tall). If your slicer asks for units, select **mm** (never meters). |
| **Want to re-verify after manual edits** | Always run `python3 src/verify_prototype.py` — it catches non-manifold edges, inverted normals, or symmetry regressions before you waste filament. |

---

*Happy printing, Program! Return to [README.md](../README.md) or inspect [docs/ARCHITECTURE.md](ARCHITECTURE.md).*
