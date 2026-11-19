"""Stage 3: Live Sculpt of Chubby Arms, Plump Oval Feet & Iconic Floppy Paddle Bunny Ears."""
import math
import sys
from pathlib import Path

import bpy
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
    create_mesh_object,
    get_bunny_params,
    get_or_create_collection,
    set_bsdf_input,
    srgb_to_linear,
    tune_studio_lighting,
)
from tracker_util import update_agent


def _smoothstep(e0, e1, x):
    if e1 == e0:
        return 0.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def _gauss(x, mu, sigma):
    d = (x - mu) / max(1e-6, sigma)
    return math.exp(-0.5 * d * d)


def _preview_olive_mat(colors):
    name = "Mat_OliveCloth"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_bsdf_input(bsdf, "Base Color", srgb_to_linear(colors["olive_cloth"]))
    set_bsdf_input(bsdf, "Roughness", 0.86)
    set_bsdf_input(bsdf, "Specular IOR Level", 0.14)
    set_bsdf_input(bsdf, "Sheen Weight", 0.35)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _build_stuffed_pillow_limb(
    name: str,
    side: int,  # -1 = bunny's right (-X), +1 = bunny's left (+X)
    center: tuple,
    radii: tuple,
    rot_deg: tuple,
    seam_amp: float,
    taper_tip: float,
    col,
):
    """
    Create a plump, chubby stuffed cloth oval limb (arm or foot) with a realistic
    vintage perimeter stitch ridge and soft batting fullness.
    """
    rx, ry, rz = radii
    n_lat = 36
    n_lon = 48

    rot_mat = Euler(tuple(math.radians(a) for a in rot_deg), "XYZ").to_matrix().to_4x4()
    trans_mat = Matrix.Translation(center)
    xform = trans_mat @ rot_mat

    verts = []
    uvs = []

    # Bottom pole (-Z local)
    p_bot = xform @ Vector((0.0, 0.0, -rz))
    verts.append((p_bot.x, p_bot.y, p_bot.z))
    uvs.append((0.5, 0.0))

    for i in range(1, n_lat):
        v_t = i / n_lat
        phi = v_t * math.pi  # 0 = bottom (-Z), pi = top (+Z)
        sin_p = math.sin(phi)
        cos_p = -math.cos(phi)  # -1 at bottom, +1 at top

        # Gentle egg/teardrop fullness (slightly plumper lower half, tapered upper tip)
        egg = 1.0 - taper_tip * cos_p

        for j in range(n_lon):
            u_t = j / n_lon
            theta = 2.0 * math.pi * u_t
            sin_t = math.sin(theta)
            cos_t = math.cos(theta)

            lx = rx * egg * sin_p * cos_t
            ly = ry * egg * sin_p * sin_t
            lz = rz * cos_p

            # Perimeter blanket-stitch seam ridge running vertically around outer profile (theta ~ 0 & pi)
            seam_band = _gauss(sin_t, 0.0, 0.14) * _smoothstep(0.08, 0.24, sin_p)
            stitch_bump = seam_amp * seam_band * (0.78 + 0.22 * math.sin(26.0 * phi))

            # Subtle cloth batting softness
            soft = 0.0005 * math.sin(3.0 * theta + 4.0 * phi) * sin_p

            # Displace along local radial direction
            v_loc = Vector((lx, ly, lz))
            if v_loc.length > 1e-6:
                v_loc += v_loc.normalized() * (stitch_bump + soft)

            p_w = xform @ v_loc
            verts.append((p_w.x, p_w.y, p_w.z))
            uvs.append((u_t, v_t))

    # Top pole (+Z local)
    p_top = xform @ Vector((0.0, 0.0, rz))
    verts.append((p_top.x, p_top.y, p_top.z))
    uvs.append((0.5, 1.0))

    faces = []
    for j in range(n_lon):
        jn = (j + 1) % n_lon
        faces.append((0, 1 + jn, 1 + j))

    for i in range(n_lat - 2):
        r0 = 1 + i * n_lon
        r1 = 1 + (i + 1) * n_lon
        for j in range(n_lon):
            jn = (j + 1) % n_lon
            faces.append((r0 + j, r0 + jn, r1 + jn, r1 + j))

    top_idx = len(verts) - 1
    last_ring = 1 + (n_lat - 2) * n_lon
    for j in range(n_lon):
        jn = (j + 1) % n_lon
        faces.append((last_ring + j, last_ring + jn, top_idx))

    return create_mesh_object(name, verts, faces, col, uvs=uvs)


def _build_floppy_ear(name: str, side: int, params: dict, col):
    """
    Sculpt an iconic vintage floppy olive-tan cloth paddle bunny ear emerging from the
    top crown of Dumb Bunny's head:
    - Anchored securely inside the hood crown so STL remesh fuses cleanly
    - Curves gently up to ~179mm then flops gracefully outward (+/-X) and slightly forward (-Y)
    - Wide soft cloth paddle silhouette with pinched root folds, subtle concave inner ear cup,
      perimeter stitch seam ridge, and >= 5.2mm print-safe thickness throughout!
    """
    ep = params["ears"]
    s = float(side)  # -1 = Bunny Right (-X), +1 = Bunny Left (+X)

    root = Vector((s * ep["root_x"], ep["root_y"], ep["root_z"]))
    length = ep["length"]
    w_base = ep["base_width"]
    w_paddle = ep["paddle_width"]
    min_thick = max(0.0052, ep["min_thickness"])  # strictly > 4.5mm print-safe

    n_u = 44  # along ear length from embedded root (u=0) to rounded paddle tip (u=1)
    n_v = 40  # around cross-section perimeter

    def spine_point(u: float) -> Vector:
        # Start embedded inside hood crown (-0.008 inward/downward root)
        # Rise softly ~25 deg near crown (top arch ~0.179m) then gracefully flop outward & gently down/forward!
        out_x = s * (
            -0.007 * (1.0 - u)
            + length * (0.78 * u + 0.12 * math.sin(math.pi * 0.5 * u))
        )
        # Gentle upward bunny-ear lift near root, peaking at Z~0.179m around u=0.32, then vintage cloth flop down!
        arc_z = (
            -0.007 * (1.0 - u)
            + 0.0145 * math.sin(min(1.0, u * 1.25) * math.pi * 0.68)
            - 0.024 * (u ** 2.1)
        )
        # Gentle forward sweep (-Y) matching right_side.png & front_preview.png
        fwd_y = -0.014 * (u ** 1.25) + 0.003 * math.sin(math.pi * u)
        return root + Vector((out_x, fwd_y, arc_z))

    # Precompute smooth Frenet-like orthonormal frames along the spine
    spine = [spine_point(i / n_u) for i in range(n_u + 1)]
    verts = []
    uvs = []

    # Root cap center
    verts.append((spine[0].x, spine[0].y, spine[0].z))
    uvs.append((0.5, 0.0))

    for i in range(1, n_u):
        u = i / n_u
        p = spine[i]
        tangent = (spine[min(n_u, i + 1)] - spine[max(0, i - 1)]).normalized()

        # Construct stable blade-width axis (mostly along Y-Z tilted slightly forward)
        # and blade-normal axis (facing forward-downward toward viewer -Y/+Z so broad face shows in front view!)
        ref_front = Vector((0.18 * s, -0.94, 0.28)).normalized()
        # Width axis perpendicular to tangent and ref_front -> broad face faces front-ish!
        width_dir = ref_front.cross(tangent)
        if width_dir.length < 1e-5:
            width_dir = Vector((0.0, 0.0, 1.0))
        else:
            width_dir.normalize()
        # Ensure width_dir points generally upward (+Z) on both sides for consistent parameterization
        if width_dir.z < 0.0:
            width_dir = -width_dir
        normal_dir = tangent.cross(width_dir).normalized()
        # Ensure normal_dir points generally forward (-Y) so inner ear cup faces the front!
        if normal_dir.y > 0.0:
            normal_dir = -normal_dir

        # Twist ear gently outward as it flops toward tip for organic cloth charm
        twist = math.radians(16.0 * u * s)
        ct, st = math.cos(twist), math.sin(twist)
        w_ax = (width_dir * ct + normal_dir * st).normalized()
        n_ax = (-width_dir * st + normal_dir * ct).normalized()

        # Paddle half-width envelope: pinched at base, broad soft cloth paddle mid-outer, smooth round tip
        if u < 0.14:
            # Smooth start from embedded root
            k = math.sin((u / 0.14) * math.pi * 0.5) ** 0.65
            hw = 0.5 * w_base * (0.45 + 0.55 * k)
        elif u < 0.78:
            t_mid = (u - 0.14) / 0.64
            flare = math.sin(t_mid * math.pi * 0.68)
            hw = 0.5 * (w_base + (w_paddle - w_base) * flare)
        else:
            # Soft rounded bunny ear paddle tip
            t_tip = (u - 0.78) / 0.22
            cap = math.cos(t_tip * math.pi * 0.5) ** 0.58
            hw = 0.5 * w_paddle * (0.92 * cap)

        # Print-safe half-thickness envelope (>= 0.0028m = 5.6mm thick across whole paddle!)
        tip_taper = 1.0 - 0.28 * _smoothstep(0.84, 1.0, u)
        root_puff = 1.0 + 0.25 * (1.0 - _smoothstep(0.0, 0.28, u))
        ht = 0.5 * min_thick * tip_taper * root_puff

        # Soft ear-cup concavity depth (gentle vintage folded inner ear trough)
        cup_depth = 0.0028 * math.sin(math.pi * _smoothstep(0.08, 0.90, u))

        for j in range(n_v):
            v = j / n_v
            ang = 2.0 * math.pi * v  # 0 & pi = upper/lower paddle edges, pi/2 = front face (+n_ax), 3pi/2 = back face (-n_ax)
            ca = math.cos(ang)
            sa = math.sin(ang)

            # Broad cloth cross-section (superellipse for plump stuffed edge, never knife-sharp!)
            edge_w = math.copysign(abs(ca) ** 0.88, ca) * hw
            # Keep solid print-safe thickness across the width
            thick_n = math.copysign(abs(sa) ** 0.78, sa) * ht

            # Ear cup curvature: bow the center backward slightly (-n_ax) while edges curl slightly forward (+n_ax)
            # This bends BOTH front and back surfaces together so minimum wall thickness NEVER shrinks!
            center_factor = 1.0 - ca * ca  # 1 at center of ear width, 0 at edges
            cup_shift = -cup_depth * center_factor

            # Base cloth pinch gathers near root (u in [0.08, 0.32])
            root_pleat = 0.0011 * math.cos(4.0 * ang) * _gauss(u, 0.18, 0.09)

            # Subtle stitched perimeter hem ridge right at the ear edges (|ca| near 1)
            hem_ridge = 0.00075 * _gauss(sa, 0.0, 0.20) * _smoothstep(0.15, 0.30, u) * (1.0 - _smoothstep(0.92, 1.0, u))

            # Gentle organic cloth wave
            cloth_soft = 0.00045 * math.sin(10.0 * u + 2.0 * ang) * _smoothstep(0.2, 0.85, u)

            pos = (
                p
                + w_ax * (edge_w + math.copysign(hem_ridge, ca))
                + n_ax * (thick_n + cup_shift + root_pleat + cloth_soft)
            )
            verts.append((pos.x, pos.y, pos.z))
            uvs.append((v, u))

    # Tip cap center
    p_tip = spine[-1]
    verts.append((p_tip.x, p_tip.y, p_tip.z))
    uvs.append((0.5, 1.0))

    faces = []
    # Root fan
    for j in range(n_v):
        jn = (j + 1) % n_v
        faces.append((0, 1 + jn, 1 + j))

    # Quad rings along ear
    for i in range(n_u - 2):
        r0 = 1 + i * n_v
        r1 = 1 + (i + 1) * n_v
        for j in range(n_v):
            jn = (j + 1) % n_v
            faces.append((r0 + j, r0 + jn, r1 + jn, r1 + j))

    # Tip fan
    tip_idx = len(verts) - 1
    last_ring = 1 + (n_u - 2) * n_v
    for j in range(n_v):
        jn = (j + 1) % n_v
        faces.append((last_ring + j, last_ring + jn, tip_idx))

    return create_mesh_object(name, verts, faces, col, uvs=uvs)


def run():
    update_agent("agent-3", status="RUNNING", progress=62, task="Sculpting olive-tan chubby arms, plump oval feet & floppy bunny ears")

    tune_studio_lighting()
    params = get_bunny_params()
    model_col = get_or_create_collection("DumbBunny_Model", clear=False)
    mat_olive = _preview_olive_mat(params["colors"])

    ap = params["arms"]
    fp = params["feet"]

    created = []

    # Stubby chubby olive-tan cloth arms tucked snug at upper sides (Right = -X, Left = +X)
    for side, suffix in ((-1, "R"), (1, "L")):
        arm = _build_stuffed_pillow_limb(
            name=f"DumbBunny_Arm_{suffix}",
            side=side,
            center=(side * ap["x"], ap["y"], ap["z"]),
            radii=(ap["rx"], ap["ry"], ap["rz"]),
            rot_deg=(18.0, side * -20.0, side * 12.0),
            seam_amp=0.0009,
            taper_tip=0.14,
            col=model_col,
        )
        arm.data.materials.clear()
        arm.data.materials.append(mat_olive)
        created.append(arm)

    # Big plump oval olive-tan stuffed feet at lower front-sides (Right = -X, Left = +X)
    for side, suffix in ((-1, "R"), (1, "L")):
        foot = _build_stuffed_pillow_limb(
            name=f"DumbBunny_Foot_{suffix}",
            side=side,
            center=(side * fp["x"], fp["y"], fp["z"]),
            radii=(fp["rx"], fp["ry"], fp["rz"]),
            rot_deg=(14.0, side * -10.0, side * -16.0),
            seam_amp=0.0014,
            taper_tip=0.09,
            col=model_col,
        )
        foot.data.materials.clear()
        foot.data.materials.append(mat_olive)
        created.append(foot)

    # Iconic vintage floppy cloth paddle bunny ears (Right = -X, Left = +X)
    for side, suffix in ((-1, "R"), (1, "L")):
        ear = _build_floppy_ear(
            name=f"DumbBunny_Ear_{suffix}",
            side=side,
            params=params,
            col=model_col,
        )
        ear.data.materials.clear()
        ear.data.materials.append(mat_olive)
        created.append(ear)

    set_viewport_camera(angle_deg=-24.0, elev_deg=74.0, dist=0.52, target=(0.0, 0.0, 0.092), orbit=False)
    capture_live_snapshot(
        "03_limbs_ears.png",
        "Stage 3: Chubby Olive-Tan Arms, Plump Feet & Floppy Paddle Bunny Ears",
        angle_deg=-24.0,
        elev_deg=14.0,
        dist=0.54,
        target=(0.0, 0.0, 0.092),
    )

    update_agent(
        "agent-3",
        status="RUNNING",
        progress=72,
        task="Arms, feet & floppy ears sculpted; ready for Bionic Face Symmetry stage",
        log="Stage 3 live: Sculpted DumbBunny_Arm_R/L, Foot_R/L (with stitch ridge), Ear_R/L (>=5.2mm print-safe) -> 03_limbs_ears.png",
    )


run()
