"""Stage 2: Live Sculpt of DumbBunny_Torso & DumbBunny_Hood (plush velour onesie & cinched hood)."""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "src" / "blender_parts") not in sys.path:
    sys.path.insert(0, str(ROOT / "src" / "blender_parts"))

import importlib
import bunny_common
importlib.reload(bunny_common)
from bunny_common import (
    create_mesh_object,
    get_bunny_params,
    get_or_create_collection,
    set_bsdf_input,
    srgb_to_linear,
    tune_studio_lighting,
)
from tracker_util import update_agent, update_stage


def _smoothstep(edge0, edge1, x):
    if edge1 == edge0:
        return 0.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _gauss(x, mu, sigma):
    d = (x - mu) / max(1e-6, sigma)
    return math.exp(-0.5 * d * d)


def _preview_velour_mat(colors):
    name = "Mat_PinkVelour"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_bsdf_input(bsdf, "Base Color", srgb_to_linear(colors["pink_velour"]))
    set_bsdf_input(bsdf, "Roughness", 0.78)
    set_bsdf_input(bsdf, "Specular IOR Level", 0.18)
    set_bsdf_input(bsdf, "Sheen Weight", 0.75)
    set_bsdf_input(bsdf, "Sheen Roughness", 0.55)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def build_torso(params, col):
    tp = params["torso"]
    z_bot = tp["z_bottom"]
    z_top = tp["z_top"]
    max_rx = tp["max_rx"]
    max_ry_f = tp["max_ry_front"]
    max_ry_b = tp["max_ry_back"]
    neck_rx = tp["neck_rx"]
    neck_ry = tp["neck_ry"]
    base_cy = tp["center_y"]

    n_rings = 96
    n_seg = 128

    verts = []
    uvs = []

    # Bottom pole
    verts.append((0.0, base_cy + 0.002, z_bot))
    uvs.append((0.5, 0.0))

    for i in range(1, n_rings):
        # Smooth cosine-biased spacing so poles are dense and smooth
        u_lin = i / n_rings
        t = 0.5 - 0.5 * math.cos(math.pi * u_lin)
        z = z_bot + t * (z_top - z_bot)

        # Base pear/bean plush torso envelope
        if t < 0.18:
            # Rounded plush bottom seat
            k = math.sin((t / 0.18) * (math.pi * 0.5)) ** 0.72
            rx = max_rx * (0.28 + 0.68 * k)
            ry_f = max_ry_f * (0.28 + 0.66 * k)
            ry_b = max_ry_b * (0.30 + 0.68 * k)
        elif t < 0.62:
            # Plump belly & hips peaking around t=0.40
            s = (t - 0.18) / 0.44
            swell = 0.96 + 0.07 * math.sin(math.pi * s)
            rx = max_rx * swell
            ry_f = max_ry_f * (0.94 + 0.09 * math.sin(math.pi * s))
            ry_b = max_ry_b * (0.98 + 0.06 * math.sin(math.pi * s))
        elif t < 0.93:
            # Smooth taper up through chest/shoulders into cinched neck
            s = (t - 0.62) / 0.31
            ease = s * s * (3.0 - 2.0 * s)
            rx = max_rx * 0.96 * (1.0 - ease) + neck_rx * ease
            ry_f = max_ry_f * 0.94 * (1.0 - ease) + neck_ry * ease
            ry_b = max_ry_b * 0.98 * (1.0 - ease) + neck_ry * ease
        else:
            # Close smoothly inside the hood neck core
            s = (t - 0.93) / 0.07
            cap = math.cos(s * math.pi * 0.5) ** 0.7
            rx = neck_rx * cap
            ry_f = neck_ry * cap
            ry_b = neck_ry * cap

        # Spine S-curve offset in Y (plump lower-mid back, slightly forward chest/neck)
        cy = base_cy + 0.0055 * math.sin(math.pi * t) - 0.004 * _smoothstep(0.65, 0.95, t)

        # Slight plush pinch right under neck collar
        neck_pinch = 1.0 - 0.06 * _gauss(t, 0.89, 0.045)
        rx *= neck_pinch
        ry_f *= neck_pinch
        ry_b *= neck_pinch

        for j in range(n_seg):
            # theta = 0 is Front (-Y), +pi/2 is Bunny's Left (+X), pi is Back (+Y), -pi/2 is Bunny's Right (-X)
            theta = (2.0 * math.pi * j) / n_seg
            sin_t = math.sin(theta)
            cos_t = math.cos(theta)

            # Asymmetric front vs back radius
            ry = ry_f if cos_t >= 0.0 else ry_b
            # Smooth blend across side equator
            blend_fb = 0.5 + 0.5 * math.tanh(cos_t * 3.0)
            ry = ry_b * (1.0 - blend_fb) + ry_f * blend_fb

            x = rx * sin_t
            y = cy - ry * cos_t

            # --- Sculpted Vintage Velour Drapery Details ---
            front_mask = _smoothstep(-0.15, 0.55, cos_t)
            back_mask = _smoothstep(-0.15, 0.55, -cos_t)
            side_mask = _smoothstep(0.45, 0.92, abs(sin_t))
            mid_z_mask = _smoothstep(0.05, 0.16, t) * (1.0 - _smoothstep(0.86, 0.95, t))

            drape = 0.0

            # 1. Signature diagonal front belly wrap fold (smooth lush velour tuck, never jagged)
            x_norm = sin_t
            diag_coord = (t - 0.63) + 0.27 * x_norm
            diag_ridge = 0.0032 * _gauss(diag_coord, 0.048, 0.062)
            diag_crease = -0.0022 * _gauss(diag_coord, -0.018, 0.048)
            drape += front_mask * mid_z_mask * (diag_ridge + diag_crease)

            # 2. Lower front hem gathers between the two chubby feet
            low_front = front_mask * _smoothstep(0.05, 0.16, t) * (1.0 - _smoothstep(0.38, 0.56, t))
            hem_pleats = (
                0.0028 * math.sin(4.5 * theta + 1.4 * t - 0.3)
                + 0.0015 * math.cos(7.5 * theta - 2.0 * t)
            )
            # Soft upturned hem lip near bunny's lower right side (-X) like in front_preview.png
            hem_lip = 0.0028 * _gauss(theta + 0.52, 0.0, 0.26) * _gauss(t, 0.22, 0.095)
            drape += low_front * hem_pleats + front_mask * hem_lip

            # 3. Cozy side waist fabric folds (seen in right_side.png & back.png)
            waist_folds = (
                0.0018 * math.sin(18.0 * t + 1.5 * sin_t) * _gauss(t, 0.44, 0.12)
                + 0.0012 * math.cos(24.0 * t - 2.0 * cos_t) * _gauss(t, 0.34, 0.10)
            )
            drape += side_mask * mid_z_mask * waist_folds

            # 4. Back upper center hand-stitched seam (matching back.png)
            seam_angle = ((theta - math.pi + math.pi) % (2.0 * math.pi)) - math.pi  # 0 at back (+Y)
            seam_off = seam_angle + 0.10 * (t - 0.72)
            seam_z = _smoothstep(0.55, 0.64, t) * (1.0 - _smoothstep(0.84, 0.91, t))
            seam_groove = -0.0016 * _gauss(seam_off, 0.0, 0.045)
            seam_pucker = 0.0010 * (_gauss(seam_off, 0.085, 0.04) + _gauss(seam_off, -0.085, 0.04)) * (0.65 + 0.35 * math.sin(70.0 * t))
            drape += back_mask * seam_z * (seam_groove + seam_pucker)

            # 5. Subtle organic plush batting fullness (gentle broad undulation)
            drape += mid_z_mask * (0.0009 * math.sin(3.0 * theta + 5.0 * t) + 0.0006 * math.cos(4.0 * theta - 6.0 * t))

            # Apply radial displacement cleanly outward from centerline
            dx = x
            dy = y - cy
            r_xy = math.hypot(dx, dy)
            if r_xy > 1e-6:
                x += (dx / r_xy) * drape
                y += (dy / r_xy) * drape

            verts.append((x, y, z))
            uvs.append((j / n_seg, t))

    # Top pole
    verts.append((0.0, base_cy, z_top))
    uvs.append((0.5, 1.0))

    faces = []
    # Bottom cap fan
    for j in range(n_seg):
        jn = (j + 1) % n_seg
        faces.append((0, 1 + jn, 1 + j))

    # Quad rings
    for i in range(n_rings - 2):
        r0 = 1 + i * n_seg
        r1 = 1 + (i + 1) * n_seg
        for j in range(n_seg):
            jn = (j + 1) % n_seg
            faces.append((r0 + j, r0 + jn, r1 + jn, r1 + j))

    # Top cap fan
    top_idx = len(verts) - 1
    last_ring = 1 + (n_rings - 2) * n_seg
    for j in range(n_seg):
        jn = (j + 1) % n_seg
        faces.append((last_ring + j, last_ring + jn, top_idx))

    obj = create_mesh_object("DumbBunny_Torso", verts, faces, col, uvs=uvs)
    return obj


def build_hood(params, col):
    """
    Construct a closed, watertight plush pink velour hood wrapping over the top, back,
    and sides of Dumb Bunny's head, with:
    - Rolled face-framing collar overlapping the rubber face mask perimeter cleanly
    - Deep cinched radial pleats at the back & lower sides of the neck
    - Soft recessed interior core tucked cleanly behind the rubber face mask
    """
    hp = params["head"]
    fp = params["face"]
    cx, cy, cz = hp["center"]
    rx_h = hp["rx"]
    ry_b = hp["ry_back"]
    rz_h = hp["rz"]
    neck_z = hp["neck_z"]

    # Face opening dimensions (slightly tighter than face outer rim so hood snugly overlaps mask!)
    face_rx = fp["rx"] * 0.945
    face_rz = fp["rz"] * 0.955
    face_cy = fp["center"][1]
    face_cz = fp["center"][2]

    n_phi = 72     # polar angle from front center (-Y) to back (+Y)
    n_alpha = 96   # azimuth around face opening (0 = top +Z, pi/2 = +X, pi = bottom -Z)

    phi_rim = 0.345 * math.pi  # angular boundary where rolled hood collar hugs face rim

    verts = []
    uvs = []

    # Front interior pole (tucked cleanly behind face mask so hood is a closed solid core)
    verts.append((0.0, face_cy + 0.004, face_cz))
    uvs.append((0.5, 0.0))

    for i in range(1, n_phi):
        u_lin = i / n_phi
        # Concentrate resolution around the face-framing rolled collar and neck pleats
        phi = u_lin * math.pi

        for j in range(n_alpha):
            alpha = (2.0 * math.pi * j) / n_alpha
            sin_a = math.sin(alpha)  # +1 on bunny left (+X), -1 on bunny right (-X)
            cos_a = math.cos(alpha)  # +1 on top crown (+Z), -1 on bottom chin/neck (-Z)

            if phi < phi_rim:
                # Interior recessed backing behind the rubber face mask (never pokes through face!)
                s = phi / phi_rim  # 0 at center, 1 at collar rim
                # Smooth oval profile matching face opening
                r_x = face_rx * math.sin(s * math.pi * 0.5)
                r_z = face_rz * math.sin(s * math.pi * 0.5)
                x = r_x * sin_a
                z = face_cz + r_z * cos_a
                # Keep recessed behind face mask surface (+Y direction) then curve forward to collar lip
                y = (face_cy + 0.004) * (1.0 - s * s) + (face_cy - 0.004) * (s * s)
            else:
                # Outer plush pink velour hood wrapping over forehead, sides, cheeks, neck & back
                s = (phi - phi_rim) / (math.pi - phi_rim)  # 0 at face rim, 1 at back pole (+Y)

                # Base spherical angle mapped from rim to back
                ang = phi_rim + s * (math.pi - phi_rim)
                sin_p = math.sin(ang)
                cos_p = math.cos(ang)

                # Interpolate smoothly from face-opening oval to plump outer hood shell
                shell_blend = _smoothstep(0.0, 0.22, s)
                cur_rx = face_rx * (1.0 - shell_blend) + rx_h * shell_blend
                cur_rz = face_rz * (1.0 - shell_blend) + rz_h * shell_blend

                # Base coordinates
                x = cur_rx * sin_p * sin_a / max(0.88, math.sin(phi_rim) * (1.0 - shell_blend) + shell_blend)
                z = cz + cur_rz * sin_p * cos_a / max(0.88, math.sin(phi_rim) * (1.0 - shell_blend) + shell_blend)

                # Smooth Y progression from face collar rim (-Y) around to plump back of hood (+Y)
                y_rim = face_cy - 0.004
                y_sphere = cy - (hp["ry_front"] if cos_p > 0 else ry_b) * cos_p
                y = y_rim * (1.0 - _smoothstep(0.0, 0.16, s)) + y_sphere * _smoothstep(0.0, 0.16, s)

                # 1. Soft organic velour face-framing hood edge (gentle cloth rim with subtle gathers, NOT a rigid donut!)
                rim_ripple = 1.0 + 0.16 * math.sin(7.0 * alpha + 0.4) + 0.10 * math.cos(11.0 * alpha)
                collar_bump = 0.0024 * _gauss(s, 0.06, 0.055) * rim_ripple
                # Slightly fuller soft hood overhang along sides & lower cheeks, gentler over forehead
                side_cheek_bias = 0.72 + 0.38 * (sin_a * sin_a)
                # Cute little rolled velour corner-curl near lower cheeks/jaw (like front_preview.png)
                jaw_curl = 0.0032 * _gauss(abs(alpha - math.pi), 0.54, 0.18) * _gauss(s, 0.085, 0.045)

                # Push collar gently outward & slightly forward (-Y) so it hugs the rubber mask rim organically
                rad_xz = math.hypot(x, z - cz)
                if rad_xz > 1e-6:
                    x += (x / rad_xz) * (collar_bump * side_cheek_bias + jaw_curl)
                    z += ((z - cz) / rad_xz) * (collar_bump * side_cheek_bias)
                y -= 0.0022 * _gauss(s, 0.048, 0.046) * side_cheek_bias

                # 2. Chin / lower-neck cinching & smooth vertical neck pleats (ZERO back-pole star pinch!)
                # Keep upper/mid back dome silky smooth; concentrate gathers strictly in lower neck band (z < neck_z + 0.024)
                low_mask = _smoothstep(-0.18, -0.78, cos_a) * _smoothstep(0.14, 0.34, s) * (1.0 - _smoothstep(0.68, 0.86, s))
                neck_pull = low_mask * 0.0048
                z -= neck_pull
                # Cinch radial pinch near bottom neck
                near_neck = _smoothstep(cz - 0.006, neck_z + 0.004, z)
                pinch_factor = 1.0 - 0.14 * near_neck * _smoothstep(0.18, 0.55, s) * (1.0 - _smoothstep(0.74, 0.90, s))
                x *= pinch_factor
                if z < neck_z:
                    z = neck_z + 0.25 * (z - neck_z)

                # Sculpt natural vertical gathered velour pleats strictly around the lower cinched neck rim!
                # Driven by horizontal angle around neck (atan2(x, y - cy)) so folds run vertically down into neck, never pinching at back pole!
                neck_ang = math.atan2(x - cx, (y - cy) + 1e-6)
                neck_band = (
                    _smoothstep(cz - 0.004, neck_z + 0.009, z)
                    * _smoothstep(0.22, 0.42, s)
                    * (1.0 - _smoothstep(0.62, 0.78, s))
                )
                pleat_wave = (
                    0.0020 * math.sin(11.0 * neck_ang)
                    + 0.0011 * math.cos(17.0 * neck_ang + 0.8)
                )
                total_pleat = neck_band * pleat_wave

                v_out = Vector((x - cx, y - cy, z - cz))
                if v_out.length > 1e-6:
                    v_dir = v_out.normalized()
                    x += v_dir.x * total_pleat
                    y += v_dir.y * total_pleat
                    z += v_dir.z * (total_pleat * 0.35)

                # 3. Soft vintage crown dome fullness (smooth pear-rounded back like back.png)
                crown_mask = _smoothstep(0.30, 0.92, cos_a) * _smoothstep(0.20, 0.55, s) * (1.0 - _smoothstep(0.80, 0.96, s))
                z += 0.0026 * crown_mask
                soft_fold = 0.00055 * math.sin(4.0 * alpha + 3.0 * s) * _smoothstep(0.25, 0.55, s) * (1.0 - _smoothstep(0.68, 0.84, s))
                if v_out.length > 1e-6:
                    v_dir = v_out.normalized()
                    x += v_dir.x * soft_fold
                    y += v_dir.y * soft_fold
                    z += v_dir.z * soft_fold

            verts.append((x, y, z))
            uvs.append((j / n_alpha, i / n_phi))

    # Back pole (+Y)
    verts.append((cx, cy + ry_b, cz))
    uvs.append((0.5, 1.0))

    faces = []
    # Front interior pole fan
    for j in range(n_alpha):
        jn = (j + 1) % n_alpha
        faces.append((0, 1 + j, 1 + jn))

    # Quad rings
    for i in range(n_phi - 2):
        r0 = 1 + i * n_alpha
        r1 = 1 + (i + 1) * n_alpha
        for j in range(n_alpha):
            jn = (j + 1) % n_alpha
            faces.append((r0 + j, r1 + j, r1 + jn, r0 + jn))

    # Back pole fan
    back_idx = len(verts) - 1
    last_ring = 1 + (n_phi - 2) * n_alpha
    for j in range(n_alpha):
        jn = (j + 1) % n_alpha
        faces.append((last_ring + j, back_idx, last_ring + jn))

    obj = create_mesh_object("DumbBunny_Hood", verts, faces, col, uvs=uvs)
    return obj


def run():
    update_stage("sculpt", "RUNNING", overall_progress=55, current_stage="Sculpting Plush Velour Body & Cinched Hood")
    update_agent("agent-3", status="RUNNING", progress=50, task="Sculpting DumbBunny_Torso & DumbBunny_Hood live in Blender")

    tune_studio_lighting()
    params = get_bunny_params()
    model_col = get_or_create_collection("DumbBunny_Model", clear=False)

    torso = build_torso(params, model_col)
    hood = build_hood(params, model_col)

    mat_velour = _preview_velour_mat(params["colors"])
    for obj in (torso, hood):
        obj.data.materials.clear()
        obj.data.materials.append(mat_velour)

    set_viewport_camera(angle_deg=-26.0, elev_deg=74.0, dist=0.52, target=(0.0, 0.0, 0.092), orbit=False)
    capture_live_snapshot(
        "02_body_hood.png",
        "Stage 2: Plush Velour Torso Drapery & Cinched Hood Sculpt",
        angle_deg=-26.0,
        elev_deg=14.0,
        dist=0.54,
        target=(0.0, 0.0, 0.092),
    )

    update_agent("agent-3", status="RUNNING", progress=58, task="Torso & Hood sculpted; ready for Limbs & Floppy Ears", log="Stage 2 live: DumbBunny_Torso (belly drape + back seam) & DumbBunny_Hood (rolled collar + neck pleats) snapped to 02_body_hood.png")


run()
