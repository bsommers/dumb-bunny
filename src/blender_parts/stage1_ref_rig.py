"""Stage 1: Build 4-View Orthographic Reference Rig & Studio Pedestal live in Blender."""
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "src" / "blender_parts") not in sys.path:
    sys.path.insert(0, str(ROOT / "src" / "blender_parts"))

import importlib
import bunny_common
importlib.reload(bunny_common)
from bunny_common import (
    REF_DIR,
    get_bunny_params,
    get_or_create_collection,
    link_to_collection,
    load_image_fresh,
    remove_object_if_exists,
    set_bsdf_input,
    smooth_mesh,
    set_collection_visibility,
    tune_studio_lighting,
)
from tracker_util import update_agent, update_stage


def _make_pedestal_material():
    name = "Mat_StudioPedestal"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    set_bsdf_input(bsdf, "Base Color", (0.045, 0.058, 0.088, 1.0))
    set_bsdf_input(bsdf, "Metallic", 0.55)
    set_bsdf_input(bsdf, "Roughness", 0.28)
    set_bsdf_input(bsdf, "Coat Weight", 0.35)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _make_ring_material():
    name = "Mat_PedestalRing"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.18, 0.78, 0.98, 1.0)
    em.inputs["Strength"].default_value = 2.4
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def _make_ref_plane_material(name: str, img_path: Path, alpha_val: float = 0.52):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = True
    if hasattr(mat, "blend_method"):
        try:
            mat.blend_method = "BLEND"
        except Exception:
            pass
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    tex = nt.nodes.new("ShaderNodeTexImage")
    img = load_image_fresh(img_path, colorspace="sRGB")
    if img is not None:
        tex.image = img
    tex.extension = "CLIP"

    # Unlit-clean emission mixed with Transparent BSDF by (image.alpha * alpha_val),
    # and forced 100% transparent on Backfacing side so opposite planes NEVER block the camera!
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.92
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])

    transp = nt.nodes.new("ShaderNodeBsdfTransparent")

    # Front-side opacity = tex.Alpha * alpha_val
    mul_alpha = nt.nodes.new("ShaderNodeMath")
    mul_alpha.operation = "MULTIPLY"
    mul_alpha.inputs[1].default_value = alpha_val
    nt.links.new(tex.outputs["Alpha"], mul_alpha.inputs[0])

    # Backfacing -> 0.0 opacity (100% invisible from behind!)
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    inv_back = nt.nodes.new("ShaderNodeMath")
    inv_back.operation = "SUBTRACT"
    inv_back.inputs[0].default_value = 1.0
    nt.links.new(geom.outputs["Backfacing"], inv_back.inputs[1])

    final_alpha = nt.nodes.new("ShaderNodeMath")
    final_alpha.operation = "MULTIPLY"
    nt.links.new(mul_alpha.outputs["Value"], final_alpha.inputs[0])
    nt.links.new(inv_back.outputs["Value"], final_alpha.inputs[1])

    mix_shader = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(final_alpha.outputs["Value"], mix_shader.inputs["Fac"])
    nt.links.new(transp.outputs["BSDF"], mix_shader.inputs[1])
    nt.links.new(em.outputs["Emission"], mix_shader.inputs[2])

    nt.links.new(mix_shader.outputs["Shader"], out.inputs["Surface"])
    return mat, img


def _build_pedestal(col):
    remove_object_if_exists("Studio_Pedestal")
    bm = bmesh.new()
    # Main beveled turntable disc with top surface exactly at Z = 0.0
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=72,
        radius1=0.098,
        radius2=0.095,
        depth=0.012,
        matrix=Matrix.Translation((0.0, 0.0, -0.006)),
    )
    mesh = bpy.data.meshes.new("Studio_Pedestal")
    bm.to_mesh(mesh)
    bm.free()
    smooth_mesh(mesh)
    obj = bpy.data.objects.new("Studio_Pedestal", mesh)
    link_to_collection(obj, col)
    obj.data.materials.append(_make_pedestal_material())

    # Subtle glowing calibration ring around outer bevel
    remove_object_if_exists("Studio_Pedestal_Ring")
    bm_r = bmesh.new()
    segs = 72
    r_in, r_out = 0.091, 0.0935
    z_ring = 0.00025
    verts_in = [bm_r.verts.new((r_in * math.cos(2 * math.pi * i / segs), r_in * math.sin(2 * math.pi * i / segs), z_ring)) for i in range(segs)]
    verts_out = [bm_r.verts.new((r_out * math.cos(2 * math.pi * i / segs), r_out * math.sin(2 * math.pi * i / segs), z_ring)) for i in range(segs)]
    for i in range(segs):
        j = (i + 1) % segs
        bm_r.faces.new((verts_in[i], verts_out[i], verts_out[j], verts_in[j]))
    mesh_r = bpy.data.meshes.new("Studio_Pedestal_Ring")
    bm_r.to_mesh(mesh_r)
    bm_r.free()
    ring_obj = bpy.data.objects.new("Studio_Pedestal_Ring", mesh_r)
    link_to_collection(ring_obj, col)
    ring_obj.data.materials.append(_make_ring_material())
    return obj


def _create_ref_plane(name, img_path, fallback_path, loc, rot_z_deg, plane_h, col, flip_u=False):
    remove_object_if_exists(name)
    chosen = img_path if img_path.exists() else fallback_path
    mat, img = _make_ref_plane_material(f"Mat_{name}", chosen, alpha_val=0.45)
    aspect = 0.75
    if img is not None and img.size[1] > 0:
        aspect = img.size[0] / img.size[1]
    plane_w = plane_h * aspect

    hw = plane_w * 0.5
    # Vertical quad in local XZ, Z from 0 to plane_h, facing -Y
    verts = [(-hw, 0.0, 0.0), (hw, 0.0, 0.0), (hw, 0.0, plane_h), (-hw, 0.0, plane_h)]
    faces = [(0, 1, 2, 3)]
    uvs = [(1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (1.0, 1.0)] if flip_u else [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_idx in poly.loop_indices:
            uv_layer.data[loop_idx].uv = uvs[mesh.loops[loop_idx].vertex_index]

    obj = bpy.data.objects.new(name, mesh)
    obj.location = loc
    obj.rotation_euler = (0.0, 0.0, math.radians(rot_z_deg))
    obj.data.materials.append(mat)
    link_to_collection(obj, col)
    return obj


def run():
    update_stage("live_rig", "RUNNING", overall_progress=40, current_stage="Building Blender Live 4-View Reference Rig")
    update_agent("agent-3", status="RUNNING", progress=30, task="Building 4-view orthographic Reference_Rig & Studio_Pedestal")

    tune_studio_lighting()
    params = get_bunny_params()
    h = params["height"]

    # Determine calibrated ortho plate dimensions & Z offset from measurements.json
    meas = params.get("measurements_raw", {})
    plate_h = h * 1.1696
    plane_z_min = -0.01526
    ortho_meta = meas.get("ortho_plates", meas.get("ortho", {}))
    if isinstance(ortho_meta, dict):
        if isinstance(ortho_meta.get("plane_height_m"), (int, float)):
            plate_h = float(ortho_meta["plane_height_m"])
        elif isinstance(ortho_meta.get("plate_height_m"), (int, float)):
            plate_h = float(ortho_meta["plate_height_m"])
        if isinstance(ortho_meta.get("plane_z_min_m"), (int, float)):
            plane_z_min = float(ortho_meta["plane_z_min_m"])

    ref_col = get_or_create_collection("Reference_Rig", clear=True)
    ped_col = get_or_create_collection("Studio_Stage", clear=True)

    _build_pedestal(ped_col)

    dist_plane = 0.140
    # Front plate behind model (+Y) facing -Y so looking from front aligns directly
    _create_ref_plane(
        "RefPlane_Front",
        REF_DIR / "ortho_front.png",
        REF_DIR / "front_preview.png",
        (0.0, dist_plane, plane_z_min),
        0.0,
        plate_h,
        ref_col,
        flip_u=False,
    )
    # Back plate at -Y facing +Y
    _create_ref_plane(
        "RefPlane_Back",
        REF_DIR / "ortho_back.png",
        REF_DIR / "back.png",
        (0.0, -dist_plane, plane_z_min),
        180.0,
        plate_h,
        ref_col,
        flip_u=False,
    )
    # Left side plate (viewed from +X looking -X; front normal = +X; bunny faces image LEFT = -Y)
    _create_ref_plane(
        "RefPlane_Left",
        REF_DIR / "ortho_left.png",
        REF_DIR / "left_side.png",
        (-dist_plane, 0.0, plane_z_min),
        90.0,
        plate_h,
        ref_col,
        flip_u=False,
    )
    # Right side plate (viewed from -X looking +X; front normal = -X; bunny faces image RIGHT = -Y)
    _create_ref_plane(
        "RefPlane_Right",
        REF_DIR / "ortho_right.png",
        REF_DIR / "right_side.png",
        (dist_plane, 0.0, plane_z_min),
        -90.0,
        plate_h,
        ref_col,
        flip_u=False,
    )

    set_collection_visibility("Reference_Rig", True)
    set_collection_visibility("Studio_Stage", True)
    set_collection_visibility("DumbBunny_Model", False)

    set_viewport_camera(angle_deg=-34.0, elev_deg=72.0, dist=0.60, target=(0.0, 0.0, 0.092), orbit=False)
    capture_live_snapshot(
        "01_ref_rig.png",
        "Stage 1: 4-View Orthographic Reference Rig & Studio Pedestal",
        angle_deg=-34.0,
        elev_deg=18.0,
        dist=0.62,
        target=(0.0, 0.0, 0.092),
    )
    set_collection_visibility("DumbBunny_Model", True)

    update_stage("live_rig", "DONE", overall_progress=48, current_stage="4-View Reference Rig Live", event_msg="Stage 1 complete: 4-view orthographic rig & pedestal active in Blender GUI")
    update_agent("agent-3", status="RUNNING", progress=38, task="4-view Reference_Rig complete; ready for Body & Hood sculpt", log="Stage 1 live: 4 ortho reference planes + Studio_Pedestal snapped to 01_ref_rig.png")


run()
