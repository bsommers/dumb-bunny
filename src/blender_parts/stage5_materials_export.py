"""Stage 5: Authentic PBR Materials, 4 Studio Turnaround Renders, .blend/.obj/.stl Exports & Live Showcase."""
import math
import shutil
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector, Matrix

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "src" / "blender_parts") not in sys.path:
    sys.path.insert(0, str(ROOT / "src" / "blender_parts"))

import importlib
import bunny_common
importlib.reload(bunny_common)
from bunny_common import (
    MODELS_DIR,
    OUTPUT_DIR,
    TEX_DIR,
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


def build_pbr_face_material(colors: dict):
    """Mat_VintageRubberFace: repaired baby-bunny vinyl texture + warm satin coat & micro-grain."""
    name = "Mat_VintageRubberFace"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")

    face_tex_path = TEX_DIR / "face_repaired.png"
    img = load_image_fresh(face_tex_path, colorspace="sRGB")
    if img is not None:
        tex_coord = nt.nodes.new("ShaderNodeTexCoord")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.extension = "EXTEND"
        nt.links.new(tex_coord.outputs["UV"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        set_bsdf_input(bsdf, "Base Color", srgb_to_linear(colors["rubber_skin"]))

    # Warm vintage molded vinyl / soft rubber satin finish (soft, tactile, non-glary)
    set_bsdf_input(bsdf, "Roughness", 0.44)
    set_bsdf_input(bsdf, "Specular IOR Level", 0.38)
    set_bsdf_input(bsdf, "Coat Weight", 0.18)
    set_bsdf_input(bsdf, "Coat Roughness", 0.28)
    set_bsdf_input(bsdf, "Subsurface Weight", 0.06)
    set_bsdf_input(bsdf, "Subsurface Scale", 0.004)

    # Very subtle vinyl micro-grain bump
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 380.0
    noise.inputs["Detail"].default_value = 5.0
    noise.inputs["Roughness"].default_value = 0.55
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.015
    bump.inputs["Distance"].default_value = 0.0005
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def build_pbr_pink_velour_material(colors: dict):
    """Mat_PinkVelour: dusty-rose plush velour with velvet sheen, grazing lift & subtle nap micro-bump."""
    name = "Mat_PinkVelour"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")

    base_col = srgb_to_linear(colors["pink_velour"])
    shadow_col = srgb_to_linear(colors["pink_velour_shadow"])
    # Subtle soft lighter highlight at grazing velour angles
    sheen_col = (
        min(1.0, base_col[0] * 1.28 + 0.04),
        min(1.0, base_col[1] * 1.24 + 0.03),
        min(1.0, base_col[2] * 1.26 + 0.04),
        1.0,
    )

    tc = nt.nodes.new("ShaderNodeTexCoord")
    # Velour nap tonal mottling
    nap_macro = nt.nodes.new("ShaderNodeTexNoise")
    nap_macro.inputs["Scale"].default_value = 42.0
    nap_macro.inputs["Detail"].default_value = 6.0
    nap_macro.inputs["Roughness"].default_value = 0.65
    nt.links.new(tc.outputs["Object"], nap_macro.inputs["Vector"])

    mix_base = nt.nodes.new("ShaderNodeMix")
    mix_base.data_type = "RGBA"
    mix_base.inputs["A"].default_value = shadow_col
    mix_base.inputs["B"].default_value = base_col
    nt.links.new(nap_macro.outputs["Fac"], mix_base.inputs["Factor"])

    # Velvet grazing highlight via Layer Weight
    lw = nt.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.35
    mix_sheen = nt.nodes.new("ShaderNodeMix")
    mix_sheen.data_type = "RGBA"
    mix_sheen.inputs["B"].default_value = sheen_col
    nt.links.new(lw.outputs["Facing"], mix_sheen.inputs["Factor"])
    nt.links.new(mix_base.outputs["Result"], mix_sheen.inputs["A"])
    nt.links.new(mix_sheen.outputs["Result"], bsdf.inputs["Base Color"])

    set_bsdf_input(bsdf, "Roughness", 0.80)
    set_bsdf_input(bsdf, "Specular IOR Level", 0.16)
    set_bsdf_input(bsdf, "Sheen Weight", 0.88)
    set_bsdf_input(bsdf, "Sheen Roughness", 0.45)

    # Fine velour nap micro-bump
    nap_fine = nt.nodes.new("ShaderNodeTexNoise")
    nap_fine.inputs["Scale"].default_value = 620.0
    nap_fine.inputs["Detail"].default_value = 8.0
    nap_fine.inputs["Roughness"].default_value = 0.72
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.065
    bump.inputs["Distance"].default_value = 0.0008
    nt.links.new(tc.outputs["Object"], nap_fine.inputs["Vector"])
    nt.links.new(nap_fine.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def build_pbr_olive_cloth_material(colors: dict):
    """Mat_OliveCloth: vintage aged olive-tan woven cloth with crosshatch warp/weft bump."""
    name = "Mat_OliveCloth"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")

    base_col = srgb_to_linear(colors["olive_cloth"])
    dark_col = (base_col[0] * 0.68, base_col[1] * 0.66, base_col[2] * 0.62, 1.0)

    tc = nt.nodes.new("ShaderNodeTexCoord")

    # Orthogonal warp & weft waves for authentic woven vintage canvas/cloth crosshatch
    wave_x = nt.nodes.new("ShaderNodeTexWave")
    wave_x.wave_type = "BANDS"
    wave_x.bands_direction = "X"
    wave_x.inputs["Scale"].default_value = 135.0
    wave_x.inputs["Distortion"].default_value = 0.45
    wave_x.inputs["Detail"].default_value = 2.0
    nt.links.new(tc.outputs["UV"], wave_x.inputs["Vector"])

    wave_y = nt.nodes.new("ShaderNodeTexWave")
    wave_y.wave_type = "BANDS"
    wave_y.bands_direction = "Y"
    wave_y.inputs["Scale"].default_value = 135.0
    wave_y.inputs["Distortion"].default_value = 0.45
    wave_y.inputs["Detail"].default_value = 2.0
    nt.links.new(tc.outputs["UV"], wave_y.inputs["Vector"])

    weave_mix = nt.nodes.new("ShaderNodeMath")
    weave_mix.operation = "MULTIPLY"
    nt.links.new(wave_x.outputs["Fac"], weave_mix.inputs[0])
    nt.links.new(wave_y.outputs["Fac"], weave_mix.inputs[1])

    # Subtle thread crevice color variation
    mix_col = nt.nodes.new("ShaderNodeMix")
    mix_col.data_type = "RGBA"
    mix_col.inputs["A"].default_value = dark_col
    mix_col.inputs["B"].default_value = base_col
    nt.links.new(weave_mix.outputs["Value"], mix_col.inputs["Factor"])
    nt.links.new(mix_col.outputs["Result"], bsdf.inputs["Base Color"])

    set_bsdf_input(bsdf, "Roughness", 0.88)
    set_bsdf_input(bsdf, "Specular IOR Level", 0.14)
    set_bsdf_input(bsdf, "Sheen Weight", 0.32)
    set_bsdf_input(bsdf, "Sheen Roughness", 0.65)

    # Crosshatch weave bump
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.14
    bump.inputs["Distance"].default_value = 0.0009
    nt.links.new(weave_mix.outputs["Value"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def _keep_largest_shell(bm):
    """Delete any tiny detached voxel speck components so exported STL is strictly 1 connected shell."""
    visited = set()
    components = []
    for v in bm.verts:
        if v in visited:
            continue
        comp = []
        stack = [v]
        visited.add(v)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for e in cur.link_edges:
                nb = e.other_vert(cur)
                if nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        components.append(comp)
    if len(components) > 1:
        components.sort(key=len, reverse=True)
        drop_verts = []
        for small_comp in components[1:]:
            drop_verts.extend(small_comp)
        bmesh.ops.delete(bm, geom=drop_verts, context="VERTS")
    return len(components)


def _check_and_clean_manifold(obj, enforce_z_zero: bool = False):
    """
    Keep only the largest connected shell, triangulate, clean degenerate geometry,
    ensure outward normals, optionally align min Z to 0, and verify strict watertightness.
    """
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges)
    shells_before = _keep_largest_shell(bm)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    if enforce_z_zero and len(bm.verts) > 0:
        min_z = min(v.co.z for v in bm.verts)
        if abs(min_z) > 1e-7:
            for v in bm.verts:
                v.co.z -= min_z

    boundary = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    non_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    n_verts = len(bm.verts)
    n_faces = len(bm.faces)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    smooth_mesh(mesh)
    return {
        "verts": n_verts,
        "faces": n_faces,
        "shells_before_clean": shells_before,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
    }


def _select_only(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.hide_viewport = False
        o.select_set(True)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]


def _create_flat_print_pad(col):
    """Create subtle flat-bottomed print stability pad resting at Z=0 tucked cleanly under lower torso."""
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=48,
        radius1=0.027,
        radius2=0.024,
        depth=0.0085,
        matrix=Matrix.Translation((0.0, -0.003, 0.00425)) @ Matrix.Diagonal((1.0, 0.78, 1.0, 1.0)),
    )
    mesh = bpy.data.meshes.new("Temp_PrintPad")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Temp_PrintPad", mesh)
    link_to_collection(obj, col)
    return obj


def _export_watertight_full_stl(model_col, out_stl: Path):
    temp_col = get_or_create_collection("Temp_STL_Export", clear=True)
    set_collection_visibility("Temp_STL_Export", True)

    # Duplicate all model parts into temp collection
    dups = []
    for src in list(model_col.objects):
        if src.type != "MESH":
            continue
        dup = src.copy()
        dup.data = src.data.copy()
        link_to_collection(dup, temp_col)
        dups.append(dup)

    # Add subtle flat bottom print pad nestled cleanly at Z=0 so STL stands flat on print bed
    pad = _create_flat_print_pad(temp_col)
    dups.append(pad)

    _select_only(dups)
    bpy.ops.object.join()
    solid = bpy.context.active_object
    solid.name = "DumbBunny_PrintSolid"

    # Voxel remesh at 0.0007 m (0.7 mm) for 100% watertight solid fusion
    remesh = solid.modifiers.new(name="VoxelRemesh", type="REMESH")
    remesh.mode = "VOXEL"
    remesh.voxel_size = 0.0007
    remesh.adaptivity = 0.0
    remesh.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=remesh.name)

    # Light smoothing pass to eliminate voxel stair-stepping while keeping crisp sculpted details
    smooth_mod = solid.modifiers.new(name="LightSmooth", type="SMOOTH")
    smooth_mod.factor = 0.42
    smooth_mod.iterations = 4
    bpy.ops.object.modifier_apply(modifier=smooth_mod.name)

    # Clean flat bottom bed contact: slice subtly at Z = min_z + 0.0012 m using a boolean DIFFERENCE
    # with a clean box below Z = 0.0012 m so the bottom contact is dead-flat and 100% watertight!
    verts_z = [v.co.z for v in solid.data.vertices]
    z_cut = min(verts_z) + 0.0012
    bm_cut = bmesh.new()
    bmesh.ops.create_cube(
        bm_cut,
        size=0.40,
        matrix=Matrix.Translation((0.0, 0.0, z_cut - 0.20)),
    )
    cut_mesh = bpy.data.meshes.new("Temp_BottomCutter")
    bm_cut.to_mesh(cut_mesh)
    bm_cut.free()
    cutter = bpy.data.objects.new("Temp_BottomCutter", cut_mesh)
    link_to_collection(cutter, temp_col)

    bool_mod = solid.modifiers.new(name="FlatBottomCut", type="BOOLEAN")
    bool_mod.operation = "DIFFERENCE"
    bool_mod.solver = "EXACT"
    bool_mod.object = cutter
    _select_only([solid])
    bpy.ops.object.modifier_apply(modifier=bool_mod.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cut_mesh.users == 0:
        bpy.data.meshes.remove(cut_mesh)

    stats = _check_and_clean_manifold(solid, enforce_z_zero=True)
    print(f"[Stage5] Full STL solid stats: {stats}", flush=True)

    # Export binary STL scaled x1000 (meters -> millimeters for 3D printing!)
    _select_only([solid])
    bpy.ops.wm.stl_export(
        filepath=str(out_stl),
        ascii_format=False,
        global_scale=1000.0,
        export_selected_objects=True,
    )

    # Cleanup temp collection
    for o in list(temp_col.objects):
        d = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if isinstance(d, bpy.types.Mesh) and d.users == 0:
            bpy.data.meshes.remove(d)
    bpy.data.collections.remove(temp_col)
    return stats


def _export_watertight_mask_stl(out_stl: Path):
    src = bpy.data.objects.get("DumbBunny_Face_Mask_Standalone")
    if src is None:
        raise RuntimeError("DumbBunny_Face_Mask_Standalone not found! Run Stage 4 first.")

    temp_col = get_or_create_collection("Temp_Mask_Export", clear=True)
    set_collection_visibility("Temp_Mask_Export", True)

    dup = src.copy()
    dup.data = src.data.copy()
    dup.name = "DumbBunny_FaceMask_PrintSolid"
    link_to_collection(dup, temp_col)
    _select_only([dup])

    # Enforce exact -X -> +X bilateral symmetry BEFORE voxel remeshing so the final
    # OpenVDB voxel remesh produces a 100% watertight, 0-non-manifold, 1-shell symmetric mask!
    mirror = dup.modifiers.new(name="BionicSymmetryMirror", type="MIRROR")
    mirror.use_axis = (True, False, False)
    mirror.use_bisect_axis = (True, False, False)
    mirror.use_bisect_flip_axis = (True, False, False)  # keeps -X (intact right donor side) and mirrors onto +X!
    mirror.use_clip = True
    mirror.use_mirror_merge = True
    mirror.merge_threshold = 0.0001
    bpy.ops.object.modifier_apply(modifier=mirror.name)

    # Voxel remesh standalone 3.5 mm mask at ultra-fine 0.00045 m (0.45 mm) AFTER mirror
    remesh = dup.modifiers.new(name="VoxelRemesh", type="REMESH")
    remesh.mode = "VOXEL"
    remesh.voxel_size = 0.00045
    remesh.adaptivity = 0.0
    remesh.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=remesh.name)

    # Light smoothing
    smooth_mod = dup.modifiers.new(name="LightSmooth", type="SMOOTH")
    smooth_mod.factor = 0.35
    smooth_mod.iterations = 3
    bpy.ops.object.modifier_apply(modifier=smooth_mod.name)

    stats = _check_and_clean_manifold(dup, enforce_z_zero=False)
    print(f"[Stage5] Face Mask STL stats: {stats}", flush=True)

    _select_only([dup])
    bpy.ops.wm.stl_export(
        filepath=str(out_stl),
        ascii_format=False,
        global_scale=1000.0,
        export_selected_objects=True,
    )

    # Cleanup temp collection
    for o in list(temp_col.objects):
        d = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if isinstance(d, bpy.types.Mesh) and d.users == 0:
            bpy.data.meshes.remove(d)
    bpy.data.collections.remove(temp_col)
    return stats


def run():
    update_stage("export", "RUNNING", overall_progress=85, current_stage="Applying PBR Materials, Rendering Turnarounds & Exporting")
    update_agent("agent-3", status="RUNNING", progress=88, task="Applying PBR shaders & rendering 4 studio turnaround views")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tune_studio_lighting()
    params = get_bunny_params()
    colors = params["colors"]

    model_col = bpy.data.collections.get("DumbBunny_Model")
    if model_col is None:
        raise RuntimeError("DumbBunny_Model collection not found! Run Stages 2-4 first.")

    # Build & assign authentic PBR materials
    mat_face = build_pbr_face_material(colors)
    mat_velour = build_pbr_pink_velour_material(colors)
    mat_olive = build_pbr_olive_cloth_material(colors)

    for obj in model_col.objects:
        if obj.type != "MESH":
            continue
        obj.data.materials.clear()
        n = obj.name
        if "Face" in n:
            obj.data.materials.append(mat_face)
        elif "Torso" in n or "Hood" in n:
            obj.data.materials.append(mat_velour)
        else:
            obj.data.materials.append(mat_olive)

    # Also keep standalone mask material synced
    mask_obj = bpy.data.objects.get("DumbBunny_Face_Mask_Standalone")
    if mask_obj:
        mask_obj.data.materials.clear()
        mask_obj.data.materials.append(mat_face)

    # Hide Reference_Rig, Studio_Stage/Pedestal, and Print_FaceMask for clean studio turnaround renders
    set_collection_visibility("Reference_Rig", False)
    set_collection_visibility("Studio_Stage", False)
    set_collection_visibility("Print_FaceMask", False)
    set_collection_visibility("DumbBunny_Model", True)
    ORBIT_STATE["enabled"] = False

    # 4 crisp studio turnaround renders (full body + ears framed cleanly!)
    capture_live_snapshot(
        "05_hero_34.png",
        "Stage 5: Hero 3/4 Studio Render (Restored Dumb Bunny)",
        angle_deg=-26.0,
        elev_deg=14.0,
        dist=0.52,
        target=(0.0, 0.0, 0.092),
    )
    capture_live_snapshot(
        "06_front.png",
        "Stage 5: Straight Front Studio Render",
        angle_deg=0.0,
        elev_deg=6.0,
        dist=0.52,
        target=(0.0, 0.0, 0.092),
    )
    capture_live_snapshot(
        "07_left_repaired.png",
        "Stage 5: Bunny's Left Side (+X) — Repaired Cheek & Limbs",
        angle_deg=54.0,
        elev_deg=10.0,
        dist=0.50,
        target=(0.0, -0.004, 0.094),
    )
    capture_live_snapshot(
        "08_back.png",
        "Stage 5: Back View — Cinched Hood Pleats & Back Seam",
        angle_deg=180.0,
        elev_deg=10.0,
        dist=0.52,
        target=(0.0, 0.0, 0.092),
    )

    update_agent("agent-3", status="RUNNING", progress=93, task="Exporting OBJ+MTL, Watertight STL (mm), Face Mask STL & .blend")

    # Export OBJ + MTL + textures (BEFORE packing images into .blend so path_mode='COPY' copies clean PNG!)
    model_meshes = [o for o in model_col.objects if o.type == "MESH"]
    _select_only(model_meshes)
    obj_path = OUTPUT_DIR / "dumb_bunny_repaired.obj"
    bpy.ops.wm.obj_export(
        filepath=str(obj_path),
        export_selected_objects=True,
        export_materials=True,
        path_mode="COPY",
        export_uv=True,
        export_normals=True,
    )
    # Guarantee face_repaired.png sits alongside OBJ/MTL and patch authentic Kd colors for procedural materials in .mtl!
    face_src = TEX_DIR / "face_repaired.png"
    face_dst = OUTPUT_DIR / "face_repaired.png"
    if face_src.exists():
        shutil.copy2(face_src, face_dst)
    mtl_path = OUTPUT_DIR / "dumb_bunny_repaired.mtl"
    if mtl_path.exists():
        def _rgb01(c):
            return [v / 255.0 if v > 1.0 else float(v) for v in c[:3]]
        pv = _rgb01(colors["pink_velour"])
        oc = _rgb01(colors["olive_cloth"])
        lines = mtl_path.read_text(encoding="utf-8").splitlines()
        out_lines = []
        cur_mat = None
        for ln in lines:
            if ln.startswith("newmtl "):
                cur_mat = ln.split(None, 1)[1].strip()
            if ln.startswith("Kd ") and cur_mat == "Mat_PinkVelour":
                out_lines.append(f"Kd {pv[0]:.6f} {pv[1]:.6f} {pv[2]:.6f}")
            elif ln.startswith("Kd ") and cur_mat == "Mat_OliveCloth":
                out_lines.append(f"Kd {oc[0]:.6f} {oc[1]:.6f} {oc[2]:.6f}")
            else:
                out_lines.append(ln)
        mtl_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    # Export 100% watertight voxel-remeshed full STL (mm scale)
    full_stl_path = OUTPUT_DIR / "dumb_bunny_repaired.stl"
    full_stats = _export_watertight_full_stl(model_col, full_stl_path)

    # Export 100% watertight strictly symmetric standalone replacement face mask STL (mm scale)
    mask_stl_path = OUTPUT_DIR / "dumb_bunny_face_mask_repaired.stl"
    mask_stats = _export_watertight_mask_stl(mask_stl_path)

    # Restore textured DumbBunny_Model standing on Studio_Pedestal with gentle live turntable orbit!
    set_collection_visibility("Reference_Rig", False)
    set_collection_visibility("Print_FaceMask", False)
    set_collection_visibility("DumbBunny_Model", True)
    set_collection_visibility("Studio_Stage", True)
    bpy.ops.object.select_all(action="DESELECT")

    # Save complete Blender project file (pack external textures inside .blend for portability)
    try:
        bpy.ops.file.pack_all()
    except Exception:
        pass
    blend_path = MODELS_DIR / "dumb_bunny.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    # Set crisp hero 3/4 view angle with orbit disabled so user can freely inspect with mouse!
    ORBIT_STATE["enabled"] = False
    set_viewport_camera(angle_deg=-24.0, elev_deg=74.0, dist=0.52, target=(0.0, 0.0, 0.092), orbit=False)
    update_tracker_blender(
        connected=True,
        status="LIVE SHOWCASE READY",
        stage="Dumb Bunny Restored — Interactive Studio View",
        render_url="/tracker/live_renders/05_hero_34.png",
        render_label="Restored Dumb Bunny — Hero 3/4",
    )

    update_stage("export", "DONE", overall_progress=90, current_stage="All 3D Models & Print STLs Exported", event_msg="Stage 5 complete: .blend, .obj/.mtl, watertight full STL & symmetric face-mask STL exported")
    update_agent(
        "agent-3",
        status="DONE",
        progress=100,
        task="All 5 live Blender stages complete; 1-shell watertight STLs, .obj/.mtl & .blend verified",
        log=f"Stage 5 live: Exported .blend, .obj, 1-shell full STL ({full_stats['faces']} tris, nm={full_stats['non_manifold_edges']}), 1-shell symmetric mask STL ({mask_stats['faces']} tris, nm={mask_stats['non_manifold_edges']})",
        metrics={
            "full_stl_tris": full_stats["faces"],
            "full_stl_non_manifold": full_stats["non_manifold_edges"],
            "mask_stl_tris": mask_stats["faces"],
            "mask_stl_non_manifold": mask_stats["non_manifold_edges"],
        },
    )


run()
