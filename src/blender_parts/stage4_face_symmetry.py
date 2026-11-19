"""Stage 4: Live Crack Diagnostic Overlay + Strict Right-to-Left Bionic Symmetric Face Sculpt."""
import math
import sys
from pathlib import Path

import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix, Euler

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "src" / "blender_parts") not in sys.path:
    sys.path.insert(0, str(ROOT / "src" / "blender_parts"))

import importlib
import bunny_common
importlib.reload(bunny_common)
from bunny_common import (
    TEX_DIR,
    create_mesh_object,
    get_bunny_params,
    get_or_create_collection,
    link_to_collection,
    load_image_fresh,
    remove_object_if_exists,
    set_bsdf_input,
    set_collection_visibility,
    smooth_mesh,
    srgb_to_linear,
    tune_studio_lighting,
)
from tracker_util import update_agent, update_stage


def _gauss(x, mu, sigma):
    d = (x - mu) / max(1e-6, sigma)
    return math.exp(-0.5 * d * d)


def _gauss2(x, y, mx, my, sx, sy):
    dx = (x - mx) / max(1e-6, sx)
    dy = (y - my) / max(1e-6, sy)
    return math.exp(-0.5 * (dx * dx + dy * dy))


def _smoothstep(e0, e1, x):
    if e1 == e0:
        return 0.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def _parse_face_blueprint(bp: dict) -> dict:
    """
    Extract UV mapping window and normalized facial landmark coordinates from
    work/face_blueprint.json (with robust key lookup & clean anatomical defaults).
    Coordinates in face-oval space:
      ox in [-1, 1] (-1 = bunny right / image left, +1 = bunny left / image right)
      oz in [-1, 1] (-1 = chin / image bottom, +1 = top forehead / image top)
    Blender UV space: u in [0, 1] left->right, v in [0, 1] bottom->top.
    """
    cfg = {
        # UV oval center & half-extents inside face_repaired.png (in Blender UV: v=0 bottom, v=1 top)
        "u_center": 0.50,
        "v_center": 0.50,
        "u_radius": 0.448,
        "v_radius": 0.456,
        # Default landmark positions in face-oval space (abs_ox, oz)
        "eye_ax": 0.629,
        "eye_z": 0.039,
        "nose_z": -0.136,
        "muzzle_ax": 0.214,
        "muzzle_z": -0.390,
        "cheek_ax": 0.658,
        "cheek_z": -0.377,
        "chin_z": -0.785,
    }

    if not isinstance(bp, dict) or not bp:
        return cfg

    # Helper to convert image-normalized (x_norm 0..1 left->right, y_norm 0..1 top->bottom) to Blender UV (u, v)
    def img_to_uv(x_n, y_n):
        return float(x_n), 1.0 - float(y_n)

    lms = bp.get("landmarks_normalized") or bp.get("landmarks_norm") or bp.get("landmarks_uv") or bp.get("landmarks") or {}
    is_uv = "landmarks_uv" in bp

    # Check explicit UV oval / face bounds in blueprint (including nested landmarks_normalized.face_oval)
    bounds = (
        (lms.get("face_oval") if isinstance(lms, dict) else None)
        or bp.get("face_oval_uv")
        or bp.get("uv_bounds")
        or bp.get("face_bounds")
        or bp.get("oval")
        or {}
    )
    if isinstance(bounds, dict):
        if "u_min" in bounds and "u_max" in bounds:
            cfg["u_center"] = 0.5 * (float(bounds["u_min"]) + float(bounds["u_max"]))
            cfg["u_radius"] = 0.5 * abs(float(bounds["u_max"]) - float(bounds["u_min"]))
        elif "cx" in bounds and "rx" in bounds:
            cfg["u_center"] = float(bounds["cx"])
            cfg["u_radius"] = float(bounds["rx"])
        elif "x_min" in bounds and "x_max" in bounds:
            cfg["u_center"] = 0.5 * (float(bounds["x_min"]) + float(bounds["x_max"]))
            cfg["u_radius"] = 0.5 * abs(float(bounds["x_max"]) - float(bounds["x_min"]))

        if "v_min" in bounds and "v_max" in bounds:
            cfg["v_center"] = 0.5 * (float(bounds["v_min"]) + float(bounds["v_max"]))
            cfg["v_radius"] = 0.5 * abs(float(bounds["v_max"]) - float(bounds["v_min"]))
        elif "cy" in bounds and "ry" in bounds:
            cy = float(bounds["cy"])
            cfg["v_center"] = 1.0 - cy if bounds.get("origin", "top_left") != "bottom_left" else cy
            cfg["v_radius"] = float(bounds["ry"])
        elif "y_min" in bounds and "y_max" in bounds:
            y0, y1 = float(bounds["y_min"]), float(bounds["y_max"])
            cfg["v_center"] = 1.0 - 0.5 * (y0 + y1)
            cfg["v_radius"] = 0.5 * abs(y1 - y0)

    # Give a subtle +4% UV margin so outer eye corners & eyelashes sit comfortably inside the pink hood rim
    cfg["u_radius"] = max(0.24, min(0.49, cfg["u_radius"] * 1.04))
    cfg["v_radius"] = max(0.24, min(0.49, cfg["v_radius"] * 1.03))

    if isinstance(lms, dict):
        def _get_pt(keys):
            for k in keys:
                val = lms.get(k)
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    x, y = float(val[0]), float(val[1])
                    if x > 1.5 or y > 1.5:
                        sz = bp.get("texture_resolution") or bp.get("texture_size") or bp.get("image_size") or [1024, 1024]
                        w = float(sz[0] if isinstance(sz, (list, tuple)) else sz)
                        h = float(sz[1] if isinstance(sz, (list, tuple)) else sz)
                        x, y = x / max(1.0, w), y / max(1.0, h)
                    return (x, y) if is_uv else img_to_uv(x, y)
                if isinstance(val, dict) and "x" in val and "y" in val:
                    x, y = float(val["x"]), float(val["y"])
                    return (x, y) if is_uv else img_to_uv(x, y)
                if isinstance(val, dict) and "u" in val and "v" in val:
                    return float(val["u"]), float(val["v"])
            return None

        def uv_to_oval(u, v):
            ox = (u - cfg["u_center"]) / max(1e-5, cfg["u_radius"])
            oz = (v - cfg["v_center"]) / max(1e-5, cfg["v_radius"])
            return ox, oz

        eye_pt = _get_pt(["left_eye_center", "right_eye_center", "right_eye", "eye_right", "eye_r", "intact_eye"])
        if eye_pt is not None:
            ox, oz = uv_to_oval(*eye_pt)
            if 0.18 <= abs(ox) <= 0.80 and -0.25 <= oz <= 0.35:
                cfg["eye_ax"] = abs(ox)
                cfg["eye_z"] = oz

        nose = _get_pt(["nose_tip", "nose", "button_nose"])
        if nose is not None:
            _, oz = uv_to_oval(*nose)
            if -0.35 <= oz <= 0.15:
                cfg["nose_z"] = oz

        muz = _get_pt(["left_muzzle_pad", "right_muzzle_pad", "muzzle_right", "right_muzzle", "muzzle_pad_r", "muzzle"])
        if muz is not None:
            ox, oz = uv_to_oval(*muz)
            if 0.08 <= abs(ox) <= 0.45 and -0.60 <= oz <= -0.05:
                cfg["muzzle_ax"] = abs(ox)
                cfg["muzzle_z"] = oz

        cheek = _get_pt(["left_cheek", "right_cheek", "cheek_right", "cheek_r"])
        if cheek is not None:
            ox, oz = uv_to_oval(*cheek)
            if 0.32 <= abs(ox) <= 0.85 and -0.62 <= oz <= 0.0:
                cfg["cheek_ax"] = abs(ox)
                cfg["cheek_z"] = oz

        chin = _get_pt(["chin_center", "chin"])
        if chin is not None:
            _, oz = uv_to_oval(*chin)
            if -0.95 <= oz <= -0.45:
                cfg["chin_z"] = oz

    return cfg


def _load_heightmap():
    hm_path = TEX_DIR / "face_heightmap_repaired.npy"
    if not hm_path.exists():
        return None
    try:
        arr = np.load(str(hm_path)).astype(np.float32)
        if arr.ndim == 3:
            arr = arr[..., 0]
        if arr.size == 0:
            return None
        # Normalize cleanly to [0, 1]
        lo, hi = float(np.percentile(arr, 2)), float(np.percentile(arr, 98))
        if hi > lo + 1e-6:
            arr = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
        else:
            arr = np.full_like(arr, 0.5)
        return arr
    except Exception:
        return None


def _sample_heightmap_sym(hm, u_sym: float, v: float) -> float:
    """Bilinear sample of heightmap using right-mirrored symmetric U coordinate."""
    if hm is None:
        return 0.0
    h, w = hm.shape
    fx = max(0.0, min(w - 1.001, u_sym * (w - 1)))
    # Blender v=1 is top of image (row 0), v=0 is bottom (row h-1)
    fy = max(0.0, min(h - 1.001, (1.0 - v) * (h - 1)))
    x0, y0 = int(fx), int(fy)
    tx, ty = fx - x0, fy - y0
    v00 = float(hm[y0, x0])
    v10 = float(hm[y0, x0 + 1])
    v01 = float(hm[y0 + 1, x0])
    v11 = float(hm[y0 + 1, x0 + 1])
    val = (v00 * (1 - tx) + v10 * tx) * (1 - ty) + (v01 * (1 - tx) + v11 * tx) * ty
    return val - 0.5  # centered around 0


def _eval_face_surface(ox: float, oz: float, fp: dict, lm: dict, hm, apply_crack: bool = False):
    """
    Evaluate 3D coordinates (x, y, z) and UV (u, v) on the molded rubber baby-bunny face.
    When apply_crack=False, relief is STRICTLY a function of abs(ox) and oz ->
    guaranteeing exact machine-precision Right-to-Left Bionic Symmetry!
    """
    cx, cy, cz = fp["center"]
    rx = fp["rx"]
    rz = fp["rz"]
    dome_d = fp["dome_depth"]

    aox = abs(ox)
    r2 = ox * ox + oz * oz
    r = math.sqrt(r2)

    # Planar front UV aligned to face_repaired.png
    u = lm["u_center"] + ox * lm["u_radius"]
    v = lm["v_center"] + oz * lm["v_radius"]
    # Strictly symmetric U for heightmap lookup (mirrors intact right side u <= u_center onto both halves!)
    u_sym = lm["u_center"] - aox * lm["u_radius"]

    # Base classic baby-doll oval dome
    # Slightly narrower chin & rounder baby cheeks contour
    chin_taper = 1.0 - 0.08 * _smoothstep(-0.25, -0.95, oz)
    x = cx + ox * rx * chin_taper
    z = cz + oz * rz

    # Smooth baby dome curvature (front is -Y)
    dome_core = max(0.0, 1.0 - 0.88 * min(1.0, r2))
    y_protrude = dome_d * (dome_core ** 0.56)

    # Fade sculpted anatomy smoothly near the oval boundary (r -> 1) so collar junction is silky smooth
    inner_mask = 1.0 - _smoothstep(0.76, 0.99, r)

    # 1. High domed vintage baby forehead fullness
    forehead = 0.0024 * _gauss2(aox, oz, 0.0, 0.56, 0.55, 0.30)

    # 2. Recessed almond eye sockets + raised upper eyelid + convex eyeball!
    ex, ez = lm["eye_ax"], lm["eye_z"]
    # Slight cute upward-outward slant on the almond socket
    socket = -0.0028 * _gauss2(aox, oz, ex, ez, 0.21, 0.145)
    eyeball = 0.0025 * _gauss2(aox, oz, ex, ez - 0.015, 0.145, 0.105)
    eyelid = 0.0014 * _gauss2(aox, oz, ex, ez + 0.125, 0.18, 0.055)

    # 3. Tiny adorable upturned pink button nose right on midline
    nz = lm["nose_z"]
    nose_bridge = 0.0014 * _gauss2(aox, oz, 0.0, nz + 0.10, 0.10, 0.12)
    nose_tip = 0.0039 * _gauss2(aox, oz, 0.0, nz, 0.115, 0.085)

    # 4. Twin chubby puffed rabbit muzzle / whisker pads + soft sculpted vertical philtrum cleft!
    mx, mz = lm["muzzle_ax"], lm["muzzle_z"]
    muzzle_pads = 0.0038 * _gauss2(aox, oz, mx, mz, 0.175, 0.150)
    philtrum = -0.0016 * _gauss(aox, 0.0, 0.062) * _smoothstep(mz - 0.18, mz - 0.04, oz) * (1.0 - _smoothstep(nz - 0.02, nz + 0.05, oz))

    # 5. Plump pinchable outer baby cheeks below outer eye corners
    ckx, ckz = lm["cheek_ax"], lm["cheek_z"]
    cheeks = 0.0038 * _gauss2(aox, oz, ckx, ckz, 0.25, 0.22)

    # 6. Gentle tucked mouth-dimple under muzzle + smooth healed baby chin
    mouth_tuck = -0.0015 * _gauss2(aox, oz, 0.0, mz - 0.18, 0.16, 0.075)
    chin = 0.0022 * _gauss2(aox, oz, 0.0, lm["chin_z"], 0.30, 0.17)

    relief = forehead + socket + eyeball + eyelid + nose_bridge + nose_tip + muzzle_pads + philtrum + cheeks + mouth_tuck + chin

    # Blend subtle micro-relief from repaired symmetric heightmap (kept gentle & smooth)
    if hm is not None:
        hm_val = _sample_heightmap_sym(hm, u_sym, v)
        relief += 0.0020 * hm_val * inner_mask

    y_protrude += relief * inner_mask

    # Optional diagnostic crack indentation (only used for temporary Stage 4a crack preview!)
    if apply_crack and ox > 0.10:
        # Jagged diagonal fracture across bunny's left (+X) outer eye corner -> cheek -> jaw
        crack_line = (oz + 0.58) - 0.85 * (ox - 0.18) + 0.045 * math.sin(18.0 * ox)
        if oz < 0.18 and oz > -0.82:
            y_protrude -= 0.0042 * _gauss(crack_line, 0.0, 0.065)

    # Front faces -Y; gentle baby head tilt around X
    y = cy - y_protrude

    tilt = math.radians(fp.get("tilt_deg", 4.0))
    dy = y - cy
    dz = z - cz
    y_rot = cy + dy * math.cos(tilt) - dz * math.sin(tilt)
    z_rot = cz + dy * math.sin(tilt) + dz * math.cos(tilt)

    return Vector((x, y_rot, z_rot)), (u, v)


def _build_face_solid_mesh(name: str, fp: dict, lm: dict, hm, col, apply_crack: bool = False):
    """
    Build DumbBunny_Face_Repaired as a closed, strictly bilaterally symmetric solid mesh
    that seats snugly inside the pink velour hood collar with zero gaps.
    """
    n_rings = 56    # concentric rings on front oval (0..n_rings)
    n_flange = 8    # smooth curved back-tuck flange rings closing cleanly inside hood
    n_seg = 128     # multiple of 4 -> exact vertex mirror across X=0!

    cx, cy, cz = fp["center"]

    verts = []
    uvs = []

    # Center front vertex (ox=0, oz=0)
    p0, uv0 = _eval_face_surface(0.0, 0.0, fp, lm, hm, apply_crack=apply_crack)
    verts.append((p0.x, p0.y, p0.z))
    uvs.append(uv0)

    # Concentric oval front rings
    ring_pts = []
    for i in range(1, n_rings + 1):
        # Slightly denser near center & rim
        t = i / n_rings
        r = math.sin(t * math.pi * 0.5) ** 0.92
        cur_ring = []
        for j in range(n_seg):
            ang = 2.0 * math.pi * j / n_seg
            ox = r * math.sin(ang)
            oz = r * math.cos(ang)
            p, uv = _eval_face_surface(ox, oz, fp, lm, hm, apply_crack=apply_crack)
            verts.append((p.x, p.y, p.z))
            uvs.append(uv)
            cur_ring.append((p, uv))
        ring_pts.append(cur_ring)

    # Back tuck flange curving smoothly inward (+Y) and closing inside hood core
    rim_ring = ring_pts[-1]
    back_center = Vector((cx, cy + 0.012, cz))
    for k in range(1, n_flange + 1):
        s = k / n_flange
        # Tuck slightly inward in XZ and backward in +Y so hood collar cleanly embraces mask rim
        shrink = 1.0 - 0.82 * (s * s)
        y_back_off = 0.014 * math.sin(s * math.pi * 0.5)
        for j in range(n_seg):
            p_rim, uv_rim = rim_ring[j]
            px = cx + (p_rim.x - cx) * shrink
            pz = cz + (p_rim.z - cz) * shrink
            py = p_rim.y + y_back_off
            verts.append((px, py, pz))
            uvs.append(uv_rim)

    # Back closure pole
    verts.append((back_center.x, back_center.y + 0.004, back_center.z))
    uvs.append((lm["u_center"], lm["v_center"]))

    total_rings = n_rings + n_flange
    faces = []

    # Front center fan
    for j in range(n_seg):
        jn = (j + 1) % n_seg
        faces.append((0, 1 + jn, 1 + j))

    # Quad rings (front + back flange)
    for i in range(total_rings - 1):
        r0 = 1 + i * n_seg
        r1 = 1 + (i + 1) * n_seg
        for j in range(n_seg):
            jn = (j + 1) % n_seg
            faces.append((r0 + j, r0 + jn, r1 + jn, r1 + j))

    # Back pole fan
    back_idx = len(verts) - 1
    last_ring = 1 + (total_rings - 1) * n_seg
    for j in range(n_seg):
        jn = (j + 1) % n_seg
        faces.append((last_ring + j, last_ring + jn, back_idx))

    return create_mesh_object(name, verts, faces, col, uvs=uvs)


def _build_standalone_face_mask(name: str, fp: dict, lm: dict, hm, col):
    """
    Build a standalone, 3.5 mm thick, 100% watertight, STRICTLY bilaterally symmetric
    printable replacement face mask shell (`DumbBunny_Face_Mask_Standalone`).
    Every vertex on +X mirrors a vertex on -X to machine precision!
    """
    n_rings = 52
    n_seg = 128  # multiple of 4 -> exact mirror symmetry across X=0!
    thickness = float(fp.get("mask_thickness", 0.0035))  # 3.5 mm

    # Evaluate front surface grid on exact symmetric polar oval
    front_center, uv_center = _eval_face_surface(0.0, 0.0, fp, lm, hm, apply_crack=False)
    front_rings = []
    uv_rings = []
    for i in range(1, n_rings + 1):
        t = i / n_rings
        r = math.sin(t * math.pi * 0.5) ** 0.92
        f_ring = []
        u_ring = []
        for j in range(n_seg):
            ang = 2.0 * math.pi * j / n_seg
            ox = r * math.sin(ang)
            oz = r * math.cos(ang)
            p, uv = _eval_face_surface(ox, oz, fp, lm, hm, apply_crack=False)
            f_ring.append(p)
            u_ring.append(uv)
        front_rings.append(f_ring)
        uv_rings.append(u_ring)

    # Compute exact symmetric inward offset (+Y biased inward normal) for back shell of 3.5 mm mask
    cx, cy, cz = fp["center"]
    shell_ref = Vector((cx, cy + 0.018, cz))

    def inward_offset(p: Vector) -> Vector:
        # Smooth symmetric inward direction toward shell interior (mostly +Y with gentle dome normal)
        d = shell_ref - p
        # Mix pure +Y with radial inward vector so thickness is uniform ~3.5 mm everywhere
        n_in = (Vector((0.0, 0.72, 0.0)) + d.normalized() * 0.28).normalized()
        return p + n_in * thickness

    verts = []
    uvs = []

    # --- Front shell vertices ---
    f_center_idx = 0
    verts.append((front_center.x, front_center.y, front_center.z))
    uvs.append(uv_center)

    f_ring_starts = []
    for i in range(n_rings):
        f_ring_starts.append(len(verts))
        for j in range(n_seg):
            p = front_rings[i][j]
            verts.append((p.x, p.y, p.z))
            uvs.append(uv_rings[i][j])

    # --- Smooth rounded beveled rim (3 intermediate rings between front rim and back rim) ---
    n_bevel = 3
    rim_ring_starts = []
    for b in range(1, n_bevel + 1):
        s = b / (n_bevel + 1)
        # Smooth rounded half-circle bevel bulging subtly outward by 0.4 mm at midpoint
        bulge = 0.00045 * math.sin(s * math.pi)
        rim_ring_starts.append(len(verts))
        for j in range(n_seg):
            pf = front_rings[-1][j]
            pb = inward_offset(pf)
            pm = pf.lerp(pb, s)
            rad = Vector((pf.x - cx, 0.0, pf.z - cz))
            if rad.length > 1e-6:
                pm += rad.normalized() * bulge
            verts.append((pm.x, pm.y, pm.z))
            uvs.append(uv_rings[-1][j])

    # --- Back shell vertices (from outer rim inward to back center) ---
    b_ring_starts = []
    for i in range(n_rings - 1, -1, -1):
        b_ring_starts.append(len(verts))
        for j in range(n_seg):
            pb = inward_offset(front_rings[i][j])
            verts.append((pb.x, pb.y, pb.z))
            uvs.append(uv_rings[i][j])

    b_center_idx = len(verts)
    bc = inward_offset(front_center)
    verts.append((bc.x, bc.y, bc.z))
    uvs.append(uv_center)

    # --- Faces (all connected seamlessly into 100% closed manifold!) ---
    faces = []
    # Front center fan
    for j in range(n_seg):
        jn = (j + 1) % n_seg
        faces.append((f_center_idx, f_ring_starts[0] + jn, f_ring_starts[0] + j))

    # Build ordered sequence of all rings from front inner -> front rim -> bevel -> back rim -> back inner
    all_rings = f_ring_starts + rim_ring_starts + b_ring_starts
    for r_idx in range(len(all_rings) - 1):
        r0 = all_rings[r_idx]
        r1 = all_rings[r_idx + 1]
        for j in range(n_seg):
            jn = (j + 1) % n_seg
            faces.append((r0 + j, r0 + jn, r1 + jn, r1 + j))

    # Back center fan
    last_r = all_rings[-1]
    for j in range(n_seg):
        jn = (j + 1) % n_seg
        faces.append((last_r + j, last_r + jn, b_center_idx))

    return create_mesh_object(name, verts, faces, col, uvs=uvs)


def _build_crack_diagnostic_overlay(fp: dict, lm: dict, hm, col):
    """
    Create glowing red diagnostic fracture overlay on the bunny's left (+X) cheek & forehead
    for Stage 4a visual damage inspection before applying Bionic Symmetry Repair.
    """
    remove_object_if_exists("Face_Crack_Diagnostic")

    # Define jagged fracture paths in face-oval (ox, oz) coordinates matching front_face_closeup.png:
    # 1) Major jagged vinyl missing-chunk fracture from outer left eye (+X) down across left cheek & jaw
    # 2) Secondary hairline crack on upper forehead & muzzle cleft
    paths = [
        [
            (0.82, 0.02), (0.76, -0.09), (0.68, -0.22), (0.56, -0.36),
            (0.42, -0.49), (0.26, -0.60), (0.10, -0.66),
        ],
        [
            (0.80, -0.14), (0.74, -0.28), (0.62, -0.44), (0.46, -0.57),
            (0.28, -0.66), (0.14, -0.71),
        ],
        [
            (-0.08, 0.86), (-0.11, 0.68), (-0.12, 0.50), (-0.10, 0.36),
        ],
        [
            (-0.01, -0.20), (-0.02, -0.34), (-0.01, -0.48),
        ],
    ]

    bm = bmesh.new()
    for p_idx, pts in enumerate(paths):
        radius = 0.00085 if p_idx < 2 else 0.00055
        world_pts = []
        for ox, oz in pts:
            p, _ = _eval_face_surface(ox, oz, fp, lm, hm, apply_crack=True)
            # Lift slightly forward (-Y) so diagnostic trace floats crisply over surface
            world_pts.append(p + Vector((0.0, -0.0018, 0.0)))

        # Build segmented red diagnostic tube along fracture curve
        n_sides = 10
        ring_verts = []
        for i, pt in enumerate(world_pts):
            if i == 0:
                tang = (world_pts[1] - pt).normalized()
            elif i == len(world_pts) - 1:
                tang = (pt - world_pts[-2]).normalized()
            else:
                tang = (world_pts[i + 1] - world_pts[i - 1]).normalized()
            up = Vector((0.0, -1.0, 0.0))
            side_v = tang.cross(up)
            if side_v.length < 1e-5:
                side_v = Vector((1.0, 0.0, 0.0))
            else:
                side_v.normalize()
            norm_v = side_v.cross(tang).normalized()
            ring = []
            for k in range(n_sides):
                a = 2.0 * math.pi * k / n_sides
                v_pos = pt + (side_v * math.cos(a) + norm_v * math.sin(a)) * radius
                ring.append(bm.verts.new(v_pos))
            ring_verts.append(ring)

        for i in range(len(ring_verts) - 1):
            r0, r1 = ring_verts[i], ring_verts[i + 1]
            for k in range(n_sides):
                kn = (k + 1) % n_sides
                bm.faces.new((r0[k], r0[kn], r1[kn], r1[k]))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new("Face_Crack_Diagnostic")
    bm.to_mesh(mesh)
    bm.free()
    smooth_mesh(mesh)
    obj = bpy.data.objects.new("Face_Crack_Diagnostic", mesh)
    link_to_collection(obj, col)

    # Vivid glowing red diagnostic shader
    mat = bpy.data.materials.get("Mat_CrackDiagnostic") or bpy.data.materials.new("Mat_CrackDiagnostic")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (1.0, 0.02, 0.03, 1.0)
    em.inputs["Strength"].default_value = 1.45
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    obj.data.materials.append(mat)
    return obj


def _make_face_preview_mat(name: str, img_path: Path, colors: dict):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")

    img = load_image_fresh(img_path, colorspace="sRGB")
    if img is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.extension = "EXTEND"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        set_bsdf_input(bsdf, "Base Color", srgb_to_linear(colors["rubber_skin"]))

    set_bsdf_input(bsdf, "Roughness", 0.44)
    set_bsdf_input(bsdf, "Specular IOR Level", 0.38)
    set_bsdf_input(bsdf, "Coat Weight", 0.18)
    set_bsdf_input(bsdf, "Coat Roughness", 0.28)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def run():
    update_agent("agent-3", status="RUNNING", progress=76, task="Running Stage 4a crack diagnostic & Stage 4b Bionic Symmetry Face sculpt")

    tune_studio_lighting()
    params = get_bunny_params()
    fp = params["face"]
    lm = _parse_face_blueprint(params.get("blueprint_raw", {}))
    hm = _load_heightmap()

    model_col = get_or_create_collection("DumbBunny_Model", clear=False)
    diag_col = get_or_create_collection("Face_Diagnostic", clear=True)
    mask_col = get_or_create_collection("Print_FaceMask", clear=True)

    # --- Stage 4a: Show damaged face + glowing red crack diagnostic overlay on bunny-left (+X) ---
    dmg_img = TEX_DIR / "face_damaged_aligned.png"
    rep_img = TEX_DIR / "face_repaired.png"
    diag_tex = dmg_img if dmg_img.exists() else rep_img

    dmg_face = _build_face_solid_mesh("DumbBunny_Face_Damaged_Preview", fp, lm, hm, diag_col, apply_crack=True)
    dmg_face.data.materials.append(_make_face_preview_mat("Mat_FaceDamagedPreview", diag_tex, params["colors"]))
    _build_crack_diagnostic_overlay(fp, lm, hm, diag_col)

    # Hide any previous repaired face during 4a diagnostic shot
    old_rep = bpy.data.objects.get("DumbBunny_Face_Repaired")
    if old_rep:
        old_rep.hide_viewport = True
        old_rep.hide_render = True

    set_collection_visibility("Reference_Rig", False)
    set_collection_visibility("Face_Diagnostic", True)
    set_collection_visibility("Print_FaceMask", False)

    face_target = (0.0, fp["center"][1] - 0.012, fp["center"][2])
    set_viewport_camera(angle_deg=18.0, elev_deg=82.0, dist=0.145, target=face_target, orbit=False)
    capture_live_snapshot(
        "04a_crack_detected.png",
        "Stage 4a: Left-Cheek Vinyl Fracture Diagnostic Overlay (+X)",
        angle_deg=18.0,
        elev_deg=7.0,
        dist=0.155,
        target=face_target,
    )

    # --- Stage 4b: Remove diagnostic overlay & build pristine STRICT Right-to-Left Bionic Symmetric Face ---
    set_collection_visibility("Face_Diagnostic", False)
    for obj in list(diag_col.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)

    face_obj = _build_face_solid_mesh("DumbBunny_Face_Repaired", fp, lm, hm, model_col, apply_crack=False)
    mat_face = _make_face_preview_mat("Mat_VintageRubberFace", rep_img, params["colors"])
    face_obj.data.materials.clear()
    face_obj.data.materials.append(mat_face)

    # Create standalone 3.5 mm thickened replacement mask in hidden Print_FaceMask collection
    mask_obj = _build_standalone_face_mask("DumbBunny_Face_Mask_Standalone", fp, lm, hm, mask_col)
    mask_obj.data.materials.clear()
    mask_obj.data.materials.append(mat_face)
    set_collection_visibility("Print_FaceMask", False)

    set_viewport_camera(angle_deg=14.0, elev_deg=82.0, dist=0.145, target=face_target, orbit=False)
    capture_live_snapshot(
        "04b_face_repaired.png",
        "Stage 4b: Right-to-Left Bionic Symmetric Repaired Face Sculpt",
        angle_deg=12.0,
        elev_deg=6.0,
        dist=0.152,
        target=face_target,
    )

    update_stage("sculpt", "DONE", overall_progress=78, current_stage="Bionic Symmetric Face Sculpt Complete", event_msg="Stage 4 complete: Left-cheek crack repaired via strict Right-to-Left Bionic Symmetry")
    update_agent(
        "agent-3",
        status="RUNNING",
        progress=85,
        task="Bionic face & standalone 3.5mm mask built; ready for PBR materials & export",
        log="Stage 4 live: 04a_crack_detected.png & 04b_face_repaired.png snapped; standalone 3.5mm symmetric face mask ready",
    )


run()
