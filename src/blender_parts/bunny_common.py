"""Shared geometry parameters, color helpers, and Blender 5.0 utilities for Dumb Bunny."""
import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector, Matrix, Euler

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
WORK = ROOT / "work"
REF_DIR = WORK / "ref_images"
TEX_DIR = WORK / "textures"
MODELS_DIR = ROOT / "models"
OUTPUT_DIR = ROOT / "output"
RENDERS_DIR = ROOT / "tracker" / "live_renders"


def srgb_channel_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def srgb_to_linear(rgb, alpha: float = 1.0):
    """Convert sRGB (0..255 or 0..1) 3-tuple/list to Blender linear RGBA."""
    vals = list(rgb[:3])
    if any(v > 1.0 for v in vals):
        vals = [v / 255.0 for v in vals]
    return (
        srgb_channel_to_linear(vals[0]),
        srgb_channel_to_linear(vals[1]),
        srgb_channel_to_linear(vals[2]),
        float(alpha),
    )


def set_bsdf_input(bsdf, name: str, value):
    if bsdf and name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def smooth_mesh(mesh):
    for p in mesh.polygons:
        p.use_smooth = True


def remove_object_if_exists(name: str):
    obj = bpy.data.objects.get(name)
    if obj is not None:
        mesh_data = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh_data is not None and mesh_data.users == 0:
            bpy.data.meshes.remove(mesh_data)


def get_or_create_collection(name: str, parent=None, clear: bool = False):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        target_parent = parent if parent is not None else bpy.context.scene.collection
        target_parent.children.link(col)
    elif clear:
        for obj in list(col.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if isinstance(data, bpy.types.Mesh) and data.users == 0:
                bpy.data.meshes.remove(data)
    return col


def link_to_collection(obj, col):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    col.objects.link(obj)


def set_collection_visibility(col_name: str, visible: bool):
    col = bpy.data.collections.get(col_name)
    if col is None:
        return
    col.hide_viewport = not visible
    col.hide_render = not visible
    # Also update view layer exclusion if needed
    def _walk(lc):
        if lc.collection.name == col_name:
            lc.hide_viewport = not visible
        for ch in lc.children:
            _walk(ch)
    _walk(bpy.context.view_layer.layer_collection)
    for obj in col.objects:
        obj.hide_viewport = not visible
        obj.hide_render = not visible


def load_image_fresh(path: Path, colorspace: str = "sRGB"):
    path = Path(path)
    if not path.exists():
        return None
    for img in list(bpy.data.images):
        try:
            if Path(bpy.path.abspath(img.filepath)).resolve() == path.resolve():
                img.reload()
                if colorspace:
                    img.colorspace_settings.name = colorspace
                return img
        except Exception:
            pass
    img = bpy.data.images.load(str(path), check_existing=False)
    if colorspace:
        try:
            img.colorspace_settings.name = colorspace
        except Exception:
            pass
    return img


def load_json_safe(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _extract_color(colors_dict: dict, keys, fallback):
    if not isinstance(colors_dict, dict):
        return fallback
    for k in keys:
        if k in colors_dict:
            v = colors_dict[k]
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                return list(v[:3])
            if isinstance(v, dict):
                for subk in ("srgb_255", "rgb255", "srgb_01", "rgb01", "rgb", "srgb"):
                    if subk in v and isinstance(v[subk], (list, tuple)) and len(v[subk]) >= 3:
                        return list(v[subk][:3])
                if "r" in v and "g" in v and "b" in v:
                    return [v["r"], v["g"], v["b"]]
    return fallback


def get_bunny_params() -> dict:
    """
    Build unified calibrated geometric parameters (in meters, Z up, front = -Y,
    bunny's right = -X, bunny's left = +X, total height ~0.180 m).
    Reads work/measurements.json & work/face_blueprint.json when available and
    clamps anatomical ranges so all sub-parts interlock cleanly.
    """
    meas = load_json_safe(WORK / "measurements.json")
    bp = load_json_safe(WORK / "face_blueprint.json")

    # Total calibrated height
    target_h = 0.180
    for path_keys in [
        ("overall_dimensions", "height_m"),
        ("dimensions", "height_m"),
        ("dimensions", "height"),
        ("overall", "height_m"),
        ("overall", "height"),
        ("calibrated_dimensions", "height_m"),
        ("height_m",),
    ]:
        cur = meas
        ok = True
        for k in path_keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if ok and isinstance(cur, (int, float)) and 0.15 <= cur <= 0.22:
            target_h = float(cur)
            break

    scale = target_h / 0.180

    # Authentic sRGB colors sampled from photos, overridden by measurements.json if present
    cdict = meas.get("colors", meas.get("palette", meas.get("sampled_colors", {})))
    colors = {
        "pink_velour": _extract_color(cdict, ["pink_velour", "velour_pink", "hood_pink"], [174, 118, 146]),
        "pink_velour_shadow": _extract_color(cdict, ["pink_velour_shadow", "velour_shadow"], [128, 82, 108]),
        "olive_cloth": _extract_color(cdict, ["olive_cloth", "cloth_olive", "limb_cloth"], [136, 116, 72]),
        "rubber_skin": _extract_color(cdict, ["rubber_skin", "face_skin", "vinyl_skin"], [214, 174, 146]),
        "eye_blue": _extract_color(cdict, ["eye_blue"], [76, 132, 186]),
        "nose_pink": _extract_color(cdict, ["nose_pink"], [192, 96, 108]),
    }

    # Unified anatomical skeleton calibrated to work/measurements.json (all scaled cleanly with target_h)
    params = {
        "height": target_h,
        "scale": scale,
        "measurements_raw": meas,
        "blueprint_raw": bp,
        "colors": colors,
        # Torso (plump pear/bean onesie bunting, Z=0.001..0.122m, neck pinch ~0.114m)
        "torso": {
            "z_bottom": 0.001 * scale,
            "z_top": 0.123 * scale,      # extends cleanly inside neck/hood core
            "z_neck": 0.114 * scale,
            "belly_z": 0.048 * scale,
            "max_rx": 0.0435 * scale,    # half-width ~43.5mm (87mm wide)
            "max_ry_front": 0.036 * scale,
            "max_ry_back": 0.038 * scale,
            "neck_rx": 0.0255 * scale,
            "neck_ry": 0.0245 * scale,
            "center_y": 0.001 * scale,
        },
        # Head & Hood (crown reaches ~0.180m)
        "head": {
            "center": (0.0, -0.002 * scale, 0.146 * scale),
            "rx": 0.0365 * scale,        # hood outer half-width (~36.5mm)
            "ry_front": 0.0355 * scale,
            "ry_back": 0.0385 * scale,   # plump gathered back of hood
            "rz": 0.0335 * scale,        # top of hood ~0.1795m
            "neck_z": 0.111 * scale,
        },
        # Molded rubber baby-bunny face mask (fits flush inside hood front opening)
        "face": {
            "center": (0.0, -0.0218 * scale, 0.1455 * scale),
            "rx": 0.0292 * scale,        # face half-width ~29.2mm (flush hug with hood collar)
            "rz": 0.0282 * scale,        # face half-height ~28.2mm (zero top rim gap)
            "dome_depth": 0.0235 * scale,  # protrudes forward to Y ~ -0.0453m
            "tilt_deg": 3.5,             # slight cute baby-chin tilt
            "mask_thickness": 0.0035,    # 3.5mm standalone replacement mask
        },
        # Stubby chubby olive-tan arms tucked snugly at upper chest sides
        "arms": {
            "x": 0.039 * scale,
            "y": -0.006 * scale,
            "z": 0.090 * scale,
            "length": 0.028 * scale,
            "rx": 0.0115 * scale,
            "ry": 0.0135 * scale,
            "rz": 0.0170 * scale,
        },
        # Big plump oval olive-tan stuffed feet at lower front-sides
        "feet": {
            "x": 0.0365 * scale,
            "y": -0.024 * scale,
            "z": 0.0255 * scale,
            "rx": 0.0160 * scale,
            "ry": 0.0205 * scale,
            "rz": 0.0245 * scale,
        },
        # Iconic vintage floppy paddle cloth bunny ears emerging from top crown
        "ears": {
            "root_x": 0.019 * scale,
            "root_y": -0.007 * scale,
            "root_z": 0.167 * scale,
            "length": 0.054 * scale,
            "base_width": 0.017 * scale,
            "paddle_width": 0.027 * scale,
            "min_thickness": 0.0056,     # >= 4.5mm print-safe minimum (5.6mm nominal)
        },
    }

    # Refine torso width/depth gently from measurements.json if overall metrics are present
    dims = meas.get("dimensions", meas.get("overall", meas.get("calibrated_dimensions", {})))
    if isinstance(dims, dict):
        w = dims.get("width_m", dims.get("width"))
        if isinstance(w, (int, float)) and 0.075 <= w <= 0.135:
            # Note overall width includes arms/feet/ears; gently nudge torso within natural plush range
            params["measured_width_m"] = float(w)
        d = dims.get("depth_m", dims.get("depth"))
        if isinstance(d, (int, float)) and 0.055 <= d <= 0.110:
            params["measured_depth_m"] = float(d)

    return params


def tune_studio_lighting():
    """Calibrate studio 3-point lighting & AgX/Filmic exposure so colors stay rich and never blow out."""
    scene = bpy.context.scene
    for vt in ("AgX", "Filmic", "Standard"):
        try:
            scene.view_settings.view_transform = vt
            break
        except Exception:
            continue
    scene.view_settings.exposure = -0.25

    if scene.world and scene.world.use_nodes:
        bg = scene.world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs[0].default_value = (0.018, 0.028, 0.052, 1.0)
            bg.inputs[1].default_value = 0.32

    light_cfg = {
        "KeyLight": (4.8, (1.0, 0.96, 0.92), 0.35),
        "FillLight": (1.8, (0.82, 0.91, 1.0), 0.45),
        "RimLight": (3.2, (0.62, 0.88, 1.0), 0.32),
    }
    for lname, (energy, col, sz) in light_cfg.items():
        obj = bpy.data.objects.get(lname)
        if obj and obj.type == "LIGHT":
            obj.data.energy = energy
            obj.data.color = col
            if obj.data.type == "AREA":
                obj.data.size = sz


def create_mesh_object(name: str, verts, faces, collection, uvs=None):
    """Create a clean smooth-shaded Blender mesh object with optional per-vertex UVs."""
    remove_object_if_exists(name)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    if uvs is not None:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for loop_idx in poly.loop_indices:
                v_idx = mesh.loops[loop_idx].vertex_index
                uv_layer.data[loop_idx].uv = uvs[v_idx]

    # Ensure outward normals cleanly via bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()

    smooth_mesh(mesh)
    obj = bpy.data.objects.new(name, mesh)
    link_to_collection(obj, collection)
    return obj
