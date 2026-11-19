#!/usr/bin/env python3
"""
Operation Dumb Bunny — 3D Printability QA & Mesh Verifier
Audits exported STL, OBJ/MTL/textures, and .blend deliverables for:
  - Binary STL format integrity, triangle count, bounding box (mm), signed volume (cm^3)
  - 2-manifold watertight edge topology (0 boundary edges, 0 non-manifold edges, consistent winding)
  - Zero NaN/Inf vertices & zero degenerate (zero-area) triangles
  - Connected shell component count & Euler characteristic
  - Bilateral X-symmetry RMS error on the repaired face mask STL (and full bunny)
  - OBJ + MTL + referenced texture PNG existence and validity
  - Blender .blend file existence, size, and header magic check
  - Updates work/qa_report.json and work/tracker_state.json
"""

import argparse
import json
import math
import os
import struct
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
sys.path.insert(0, str(ROOT / "src"))
import tracker_util  # noqa: E402

FULL_STL = ROOT / "output" / "dumb_bunny_repaired.stl"
FACE_STL = ROOT / "output" / "dumb_bunny_face_mask_repaired.stl"
OBJ_PATH = ROOT / "output" / "dumb_bunny_repaired.obj"
BLEND_PATH = ROOT / "models" / "dumb_bunny.blend"
QA_REPORT_PATH = ROOT / "work" / "qa_report.json"

EXPECTED_RENDERS = [
    ROOT / "work" / "textures" / "face_damaged_aligned.png",
    ROOT / "work" / "textures" / "face_repaired.png",
    ROOT / "tracker" / "live_renders" / "04b_face_repaired.png",
    ROOT / "tracker" / "live_renders" / "05_hero_34.png",
    ROOT / "tracker" / "live_renders" / "06_front.png",
    ROOT / "tracker" / "live_renders" / "07_left_repaired.png",
    ROOT / "tracker" / "live_renders" / "08_back.png",
]


def fmt_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 ** 2:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 ** 2):.2f} MB"


def parse_binary_stl(path: Path):
    """Parse a binary STL file using struct + numpy."""
    data = path.read_bytes()
    file_size = len(data)
    if file_size < 84:
        raise ValueError(f"STL file too small ({file_size} bytes)")

    header = data[:80].decode("ascii", errors="replace").strip("\x00 ").strip()
    tri_count = struct.unpack_from("<I", data, 80)[0]
    expected_size = 84 + tri_count * 50

    if expected_size != file_size:
        raise ValueError(
            f"Not a valid binary STL (header says {tri_count} tris => {expected_size} B, actual {file_size} B)"
        )
    if tri_count == 0:
        raise ValueError("Binary STL contains 0 triangles")

    stl_dtype = np.dtype(
        [
            ("normal", "<f4", (3,)),
            ("v0", "<f4", (3,)),
            ("v1", "<f4", (3,)),
            ("v2", "<f4", (3,)),
            ("attr", "<u2"),
        ]
    )
    records = np.frombuffer(data, dtype=stl_dtype, offset=84, count=tri_count)
    tris = np.stack([records["v0"], records["v1"], records["v2"]], axis=1)  # (N, 3, 3)
    return header, tris, file_size


def audit_stl(path: Path, expected_height_mm=None, height_tol_mm=20.0, check_symmetry=False):
    result = {
        "path": str(path),
        "exists": path.exists(),
        "pass": False,
        "issues": [],
    }
    if not path.exists():
        result["issues"].append(f"Missing STL file: {path.name}")
        return result

    try:
        header, tris_f32, file_size = parse_binary_stl(path)
    except Exception as e:
        result["issues"].append(str(e))
        return result

    result["file_size_bytes"] = file_size
    result["file_size_human"] = fmt_size(file_size)
    result["header"] = header
    n_tris = int(tris_f32.shape[0])
    result["triangle_count"] = n_tris

    # Finite check
    non_finite_mask = ~np.isfinite(tris_f32)
    non_finite_coords = int(non_finite_mask.sum())
    result["non_finite_coords"] = non_finite_coords
    if non_finite_coords > 0:
        result["issues"].append(f"{non_finite_coords} NaN/Inf vertex coordinates found")
        return result

    # Promote to float64 for precise geometric calculations
    tris = tris_f32.astype(np.float64)
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]

    # Bounding box (mm)
    all_pts = tris.reshape(-1, 3)
    bbox_min = all_pts.min(axis=0)
    bbox_max = all_pts.max(axis=0)
    bbox_size = bbox_max - bbox_min
    result["bbox_min_mm"] = [round(float(x), 3) for x in bbox_min]
    result["bbox_max_mm"] = [round(float(x), 3) for x in bbox_max]
    result["bbox_size_mm"] = {
        "x": round(float(bbox_size[0]), 3),
        "y": round(float(bbox_size[1]), 3),
        "z": round(float(bbox_size[2]), 3),
    }

    if expected_height_mm is not None:
        z_h = float(bbox_size[2])
        if abs(z_h - expected_height_mm) > height_tol_mm:
            result["issues"].append(
                f"Height Z={z_h:.2f} mm outside target {expected_height_mm}±{height_tol_mm} mm"
            )

    # Triangle area & degenerate check
    e1 = v1 - v0
    e2 = v2 - v0
    cross = np.cross(e1, e2)
    double_areas = np.linalg.norm(cross, axis=1)
    areas = 0.5 * double_areas
    surface_area_mm2 = float(areas.sum())
    degenerate_count = int((areas <= 1e-10).sum())
    result["surface_area_cm2"] = round(surface_area_mm2 / 100.0, 3)
    result["min_triangle_area_mm2"] = float(areas.min())
    result["degenerate_triangles"] = degenerate_count
    if degenerate_count > 0:
        result["issues"].append(f"{degenerate_count} zero-area/degenerate triangles")

    # Signed volume via divergence theorem: sum(v0 . (v1 x v2)) / 6
    signed_vol_mm3 = float(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum() / 6.0)
    signed_vol_cm3 = signed_vol_mm3 / 1000.0
    result["signed_volume_mm3"] = round(signed_vol_mm3, 2)
    result["signed_volume_cm3"] = round(signed_vol_cm3, 3)
    if signed_vol_cm3 <= 0.0:
        result["issues"].append(
            f"Signed volume is non-positive ({signed_vol_cm3:.3f} cm^3) — inverted normals or open mesh"
        )

    # Exact float32 vertex welding (canonicalizing -0.0 -> +0.0)
    verts_canon = tris_f32.reshape(-1, 3).copy()
    verts_canon[verts_canon == 0.0] = 0.0
    # View each 3xfloat32 row as 12 raw bytes for ultra-fast exact deduplication
    verts_void = np.ascontiguousarray(verts_canon).view(np.dtype((np.void, 12))).ravel()
    _, unique_idx, inv_idx = np.unique(verts_void, return_index=True, return_inverse=True)
    unique_verts = verts_canon[unique_idx].astype(np.float64)
    faces = inv_idx.reshape(n_tris, 3)
    n_verts = int(unique_verts.shape[0])
    result["unique_vertex_count"] = n_verts

    # Check collapsed triangles in indexed topology
    collapsed_tris = int(
        ((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 2] == faces[:, 0])).sum()
    )
    result["collapsed_index_triangles"] = collapsed_tris
    if collapsed_tris > 0:
        result["issues"].append(f"{collapsed_tris} triangles have duplicate vertex indices")

    # Build directed half-edges (3*N, 2)
    h_src = np.concatenate([faces[:, 0], faces[:, 1], faces[:, 2]])
    h_dst = np.concatenate([faces[:, 1], faces[:, 2], faces[:, 0]])

    # Undirected edges encoded as single int64 key: min * M + max
    u_min = np.minimum(h_src, h_dst).astype(np.int64)
    u_max = np.maximum(h_src, h_dst).astype(np.int64)
    stride = np.int64(n_verts + 1)
    u_keys = u_min * stride + u_max

    uniq_u, u_counts = np.unique(u_keys, return_counts=True)
    n_edges = int(uniq_u.shape[0])
    boundary_edges = int((u_counts == 1).sum())
    manifold_edges = int((u_counts == 2).sum())
    non_manifold_edges = int((u_counts > 2).sum())

    # Directed half-edge consistency check: every directed edge (a, b) should appear once
    # and its opposite (b, a) once, meaning zero duplicate directed half-edges.
    d_keys = h_src.astype(np.int64) * stride + h_dst.astype(np.int64)
    _, d_counts = np.unique(d_keys, return_counts=True)
    inconsistent_orientation_edges = int((d_counts > 1).sum())

    watertight_manifold = (
        boundary_edges == 0
        and non_manifold_edges == 0
        and inconsistent_orientation_edges == 0
        and degenerate_count == 0
        and collapsed_tris == 0
        and signed_vol_cm3 > 0.0
    )

    # Connected components via vertex adjacency
    adj = coo_matrix(
        (np.ones(len(u_min) * 2, dtype=np.int8), (np.concatenate([u_min, u_max]), np.concatenate([u_max, u_min]))),
        shape=(n_verts, n_verts),
    )
    n_components, _ = connected_components(adj, directed=False)

    euler_chi = n_verts - n_edges + n_tris
    result["topology"] = {
        "unique_edges": n_edges,
        "manifold_edges_2": manifold_edges,
        "boundary_edges_1": boundary_edges,
        "non_manifold_edges_gt2": non_manifold_edges,
        "inconsistent_orientation_edges": inconsistent_orientation_edges,
        "connected_components": int(n_components),
        "euler_characteristic": int(euler_chi),
        "watertight_manifold": watertight_manifold,
    }

    if boundary_edges > 0:
        result["issues"].append(f"Mesh is NOT watertight: {boundary_edges} open boundary edges")
    if non_manifold_edges > 0:
        result["issues"].append(f"Mesh is non-manifold: {non_manifold_edges} edges shared by >2 triangles")
    if inconsistent_orientation_edges > 0:
        result["issues"].append(
            f"Inconsistent winding: {inconsistent_orientation_edges} duplicate directed half-edges"
        )

    # Bilateral X-symmetry check (vertex-to-vertex mirrored nearest neighbor)
    if check_symmetry:
        tree = cKDTree(unique_verts)
        # Symmetry around X = 0
        mirrored_zero = unique_verts.copy()
        mirrored_zero[:, 0] = -mirrored_zero[:, 0]
        dists_zero, _ = tree.query(mirrored_zero, k=1)
        rms_zero = float(np.sqrt(np.mean(dists_zero ** 2)))
        mean_zero = float(np.mean(dists_zero))
        p95_zero = float(np.percentile(dists_zero, 95))
        max_zero = float(np.max(dists_zero))

        # Symmetry around bounding-box midpoint X_mid
        x_mid = 0.5 * float(bbox_min[0] + bbox_max[0])
        mirrored_mid = unique_verts.copy()
        mirrored_mid[:, 0] = 2.0 * x_mid - mirrored_mid[:, 0]
        dists_mid, _ = tree.query(mirrored_mid, k=1)
        rms_mid = float(np.sqrt(np.mean(dists_mid ** 2)))

        width_x = max(float(bbox_size[0]), 1e-6)
        rms_pct_width = (rms_zero / width_x) * 100.0

        result["bilateral_symmetry_x"] = {
            "x_midpoint_mm": round(x_mid, 4),
            "rms_about_x0_mm": round(rms_zero, 4),
            "mean_about_x0_mm": round(mean_zero, 4),
            "p95_about_x0_mm": round(p95_zero, 4),
            "max_about_x0_mm": round(max_zero, 4),
            "rms_about_xmid_mm": round(rms_mid, 4),
            "rms_pct_of_width": round(rms_pct_width, 3),
        }
        if rms_zero > 1.5:
            result["issues"].append(
                f"Face mask bilateral X-symmetry RMS is high: {rms_zero:.3f} mm (target < 1.5 mm)"
            )

    result["pass"] = len(result["issues"]) == 0
    return result


def audit_obj_mtl(obj_path: Path):
    result = {
        "path": str(obj_path),
        "exists": obj_path.exists(),
        "pass": False,
        "issues": [],
    }
    if not obj_path.exists():
        result["issues"].append(f"Missing OBJ file: {obj_path.name}")
        return result

    file_size = obj_path.stat().st_size
    result["file_size_bytes"] = file_size
    result["file_size_human"] = fmt_size(file_size)
    if file_size == 0:
        result["issues"].append("OBJ file is empty")
        return result

    v_count = 0
    vt_count = 0
    vn_count = 0
    f_count = 0
    f_with_uv = 0
    mtllibs = []
    used_mtls = set()
    objects = []
    min_v = [math.inf, math.inf, math.inf]
    max_v = [-math.inf, -math.inf, -math.inf]

    with open(obj_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("v "):
                v_count += 1
                parts = line.split()
                if len(parts) >= 4:
                    x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                    if x < min_v[0]: min_v[0] = x
                    if y < min_v[1]: min_v[1] = y
                    if z < min_v[2]: min_v[2] = z
                    if x > max_v[0]: max_v[0] = x
                    if y > max_v[1]: max_v[1] = y
                    if z > max_v[2]: max_v[2] = z
            elif line.startswith("vt "):
                vt_count += 1
            elif line.startswith("vn "):
                vn_count += 1
            elif line.startswith("f "):
                f_count += 1
                tokens = line.split()[1:]
                if tokens and "/" in tokens[0]:
                    segs = tokens[0].split("/")
                    if len(segs) >= 2 and segs[1]:
                        f_with_uv += 1
            elif line.startswith("mtllib "):
                mtllibs.append(line[7:].strip())
            elif line.startswith("usemtl "):
                used_mtls.add(line[7:].strip())
            elif line.startswith("o "):
                objects.append(line[2:].strip())

    result["counts"] = {
        "vertices": v_count,
        "uv_coords": vt_count,
        "normals": vn_count,
        "faces": f_count,
        "faces_with_uv": f_with_uv,
        "objects": objects,
    }
    if v_count > 0:
        result["bbox_size_raw"] = [round(max_v[i] - min_v[i], 4) for i in range(3)]
    else:
        result["issues"].append("OBJ contains 0 vertices")
    if f_count == 0:
        result["issues"].append("OBJ contains 0 faces")
    if vt_count == 0 or f_with_uv == 0:
        result["issues"].append(f"OBJ missing UV mapping (vt={vt_count}, faces_with_uv={f_with_uv})")

    # Audit MTL files
    defined_mtls = set()
    mtl_reports = []
    texture_reports = []
    tex_keywords = {
        "map_Kd", "map_Ka", "map_Ks", "map_Ns", "map_d", "map_Bump", "bump",
        "map_Pr", "map_Pm", "map_Ps", "map_Ke", "norm", "disp", "decal", "refl",
    }

    if not mtllibs:
        result["issues"].append("OBJ does not reference any mtllib")

    for ml in mtllibs:
        mtl_path = obj_path.parent / ml
        m_info = {"name": ml, "path": str(mtl_path), "exists": mtl_path.exists()}
        if not mtl_path.exists():
            result["issues"].append(f"Missing MTL file referenced by OBJ: {ml}")
            mtl_reports.append(m_info)
            continue

        m_size = mtl_path.stat().st_size
        m_info["file_size_bytes"] = m_size
        m_info["file_size_human"] = fmt_size(m_size)
        if m_size == 0:
            result["issues"].append(f"MTL file is empty: {ml}")

        with open(mtl_path, "r", encoding="utf-8", errors="replace") as mf:
            for line in mf:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split()
                key = parts[0]
                if key == "newmtl" and len(parts) >= 2:
                    defined_mtls.add(s[7:].strip())
                elif key in tex_keywords and len(parts) >= 2:
                    # Texture filename is usually the last token (skipping -bm / -o / -s flags)
                    tex_ref = parts[-1]
                    tex_path = Path(tex_ref) if os.path.isabs(tex_ref) else (mtl_path.parent / tex_ref)
                    tex_exists = tex_path.exists()
                    tex_size = tex_path.stat().st_size if tex_exists else 0
                    png_valid = False
                    if tex_exists and tex_size >= 24:
                        sig = tex_path.read_bytes()[:8]
                        png_valid = sig == b"\x89PNG\r\n\x1a\n" or tex_path.suffix.lower() in {".jpg", ".jpeg"}
                    t_rec = {
                        "directive": key,
                        "ref": tex_ref,
                        "resolved_path": str(tex_path),
                        "exists": tex_exists,
                        "file_size_bytes": tex_size,
                        "file_size_human": fmt_size(tex_size),
                        "valid_image_header": png_valid,
                    }
                    texture_reports.append(t_rec)
                    if not tex_exists or tex_size == 0:
                        result["issues"].append(f"Missing/empty texture referenced in {ml}: {tex_ref}")
                    elif not png_valid:
                        result["issues"].append(f"Invalid image header for texture: {tex_ref}")

        mtl_reports.append(m_info)

    missing_mtls = sorted(used_mtls - defined_mtls)
    if missing_mtls:
        result["issues"].append(f"OBJ uses materials not defined in MTL: {missing_mtls}")
    if not texture_reports:
        result["issues"].append("MTL references zero texture image maps (expected repaired face texture)")

    result["mtl_files"] = mtl_reports
    result["defined_materials"] = sorted(defined_mtls)
    result["used_materials"] = sorted(used_mtls)
    result["textures"] = texture_reports
    result["pass"] = len(result["issues"]) == 0
    return result


def audit_blend(blend_path: Path):
    result = {
        "path": str(blend_path),
        "exists": blend_path.exists(),
        "pass": False,
        "issues": [],
    }
    if not blend_path.exists():
        result["issues"].append(f"Missing Blender file: {blend_path.name}")
        return result

    size = blend_path.stat().st_size
    result["file_size_bytes"] = size
    result["file_size_human"] = fmt_size(size)
    if size < 10_000:
        result["issues"].append(f"Blender file suspiciously small ({size} bytes)")
        return result

    magic = blend_path.read_bytes()[:12]
    if magic.startswith(b"BLENDER"):
        result["format"] = "uncompressed_blend"
    elif magic.startswith(b"\x28\xb5\x2f\xfd"):
        result["format"] = "zstd_compressed_blend"
    elif magic.startswith(b"\x1f\x8b"):
        result["format"] = "gzip_compressed_blend"
    else:
        result["format"] = "unknown"
        result["issues"].append(f"Unrecognized .blend header magic: {magic[:8]!r}")

    result["pass"] = len(result["issues"]) == 0
    return result


def audit_renders():
    renders = []
    issues = []
    for p in EXPECTED_RENDERS:
        exists = p.exists()
        size = p.stat().st_size if exists else 0
        renders.append(
            {
                "name": p.name,
                "path": str(p),
                "exists": exists,
                "file_size_bytes": size,
                "file_size_human": fmt_size(size),
            }
        )
        if not exists or size < 1024:
            issues.append(f"Missing or empty visual artifact: {p.relative_to(ROOT)}")
    return {"pass": len(issues) == 0, "files": renders, "issues": issues}


def build_outputs_list(report):
    outputs = []
    full = report["full_stl"]
    if full.get("exists"):
        sz = full.get("bbox_size_mm", {})
        topo = full.get("topology", {})
        wt = "Watertight Manifold ✓" if topo.get("watertight_manifold") else "NON-WATERTIGHT ✗"
        outputs.append(
            {
                "name": "dumb_bunny_repaired.stl",
                "url": "/output/dumb_bunny_repaired.stl",
                "desc": (
                    f"Full 3D-Printable Solid · {full.get('triangle_count', 0):,} tris · "
                    f"{sz.get('x', 0):.1f}×{sz.get('y', 0):.1f}×{sz.get('z', 0):.1f} mm · "
                    f"{full.get('signed_volume_cm3', 0):.1f} cm³ · {wt}"
                ),
                "size": full.get("file_size_human", ""),
            }
        )

    face = report["face_mask_stl"]
    if face.get("exists"):
        sym = face.get("bilateral_symmetry_x", {})
        topo = face.get("topology", {})
        wt = "Watertight ✓" if topo.get("watertight_manifold") else "NON-WATERTIGHT ✗"
        outputs.append(
            {
                "name": "dumb_bunny_face_mask_repaired.stl",
                "url": "/output/dumb_bunny_face_mask_repaired.stl",
                "desc": (
                    f"Repaired Vinyl Face Mask · {face.get('triangle_count', 0):,} tris · "
                    f"X-Symmetry RMS {sym.get('rms_about_x0_mm', 0):.3f} mm · {wt}"
                ),
                "size": face.get("file_size_human", ""),
            }
        )

    obj = report["obj_mtl"]
    if obj.get("exists"):
        cnt = obj.get("counts", {})
        outputs.append(
            {
                "name": "dumb_bunny_repaired.obj",
                "url": "/output/dumb_bunny_repaired.obj",
                "desc": (
                    f"Textured Multi-Part Mesh (+MTL & PNG) · "
                    f"{cnt.get('vertices', 0):,} verts · {cnt.get('faces', 0):,} faces"
                ),
                "size": obj.get("file_size_human", ""),
            }
        )

    bl = report["blend_file"]
    if bl.get("exists"):
        outputs.append(
            {
                "name": "dumb_bunny.blend",
                "url": "/models/dumb_bunny.blend",
                "desc": "Native Blender 5.0 Master Scene (Materials, Rig & Repaired Face)",
                "size": bl.get("file_size_human", ""),
            }
        )

    if QA_REPORT_PATH.exists():
        outputs.append(
            {
                "name": "qa_report.json",
                "url": "/work/qa_report.json",
                "desc": f"Automated Printability & Symmetry Audit · {'PASS ✓' if report['overall_pass'] else 'ISSUES FOUND'}",
                "size": fmt_size(QA_REPORT_PATH.stat().st_size),
            }
        )
    return outputs


def update_tracker(report, finalize=False):
    full = report["full_stl"]
    face = report["face_mask_stl"]
    topo_full = full.get("topology", {})
    topo_face = face.get("topology", {})
    sym = face.get("bilateral_symmetry_x", {})
    sz = full.get("bbox_size_mm", {})

    metrics = {
        "full_stl_tris": full.get("triangle_count", 0),
        "full_stl_dims_mm": f"{sz.get('x', 0):.1f}x{sz.get('y', 0):.1f}x{sz.get('z', 0):.1f}",
        "full_stl_volume_cm3": full.get("signed_volume_cm3", 0),
        "full_stl_watertight": bool(topo_full.get("watertight_manifold", False)),
        "face_stl_watertight": bool(topo_face.get("watertight_manifold", False)),
        "face_symmetry_rms_mm": sym.get("rms_about_x0_mm", None),
        "qa_pass": report["overall_pass"],
    }

    if finalize and report["overall_pass"]:
        tracker_util.update_agent(
            "agent-4",
            status="DONE",
            progress=100,
            task="All geometric, watertightness, symmetry & visual QA checks PASSED",
            log=(
                f"QA PASSED: Full STL {full.get('triangle_count', 0):,} tris, "
                f"{sz.get('z', 0):.1f}mm tall, {full.get('signed_volume_cm3', 0):.1f}cm³, "
                f"0 boundary edges; Face mask X-sym RMS {sym.get('rms_about_x0_mm', 0):.3f}mm."
            ),
            metrics=metrics,
        )
        tracker_util.update_stage(
            "qa",
            "DONE",
            overall_progress=100,
            current_stage="Operation Complete — Print-Ready Prototype Verified",
            event_msg="QA & Mesh Verifier certified all STL/OBJ/Blend deliverables print-ready (100%)",
        )
    else:
        status = "RUNNING"
        progress = 80 if report["overall_pass"] else 50
        task = (
            "Automated mesh & STL audit PASSED — completing visual render inspection"
            if report["overall_pass"]
            else f"QA found {len(report['all_issues'])} issue(s) — reporting to responsible owner"
        )
        log = (
            f"Automated audit {'PASSED' if report['overall_pass'] else 'FAILED'}: "
            f"full_wt={metrics['full_stl_watertight']}, face_wt={metrics['face_stl_watertight']}, "
            f"vol={metrics['full_stl_volume_cm3']}cm³, sym_rms={metrics['face_symmetry_rms_mm']}mm"
        )
        tracker_util.update_agent("agent-4", status=status, progress=progress, task=task, log=log, metrics=metrics)
        tracker_util.update_stage("qa", "RUNNING", overall_progress=92 if report["overall_pass"] else 85)

    # Atomically update outputs list in tracker_state.json
    state = tracker_util.load_state()
    state["outputs"] = build_outputs_list(report)
    tracker_util.save_state(state)


def main():
    parser = argparse.ArgumentParser(description="Verify Operation Dumb Bunny 3D deliverables")
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="Mark agent-4 DONE, stage qa DONE, and overall_progress=100 if all checks pass",
    )
    parser.add_argument(
        "--no-tracker",
        action="store_true",
        help="Skip updating work/tracker_state.json",
    )
    args = parser.parse_args()

    full_stl = audit_stl(FULL_STL, expected_height_mm=180.0, height_tol_mm=20.0, check_symmetry=True)
    face_stl = audit_stl(FACE_STL, expected_height_mm=None, check_symmetry=True)
    obj_mtl = audit_obj_mtl(OBJ_PATH)
    blend_file = audit_blend(BLEND_PATH)
    renders = audit_renders()

    all_issues = (
        [f"[full_stl] {x}" for x in full_stl["issues"]]
        + [f"[face_mask_stl] {x}" for x in face_stl["issues"]]
        + [f"[obj_mtl] {x}" for x in obj_mtl["issues"]]
        + [f"[blend] {x}" for x in blend_file["issues"]]
        + [f"[renders] {x}" for x in renders["issues"]]
    )

    overall_pass = (
        full_stl["pass"]
        and face_stl["pass"]
        and obj_mtl["pass"]
        and blend_file["pass"]
        and renders["pass"]
    )

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "overall_pass": overall_pass,
        "summary": {
            "full_stl_pass": full_stl["pass"],
            "face_mask_stl_pass": face_stl["pass"],
            "obj_mtl_pass": obj_mtl["pass"],
            "blend_file_pass": blend_file["pass"],
            "renders_pass": renders["pass"],
            "issue_count": len(all_issues),
        },
        "all_issues": all_issues,
        "full_stl": full_stl,
        "face_mask_stl": face_stl,
        "obj_mtl": obj_mtl,
        "blend_file": blend_file,
        "renders": renders,
    }

    QA_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(QA_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if not args.no_tracker:
        update_tracker(report, finalize=args.finalize)

    print(json.dumps(report["summary"], indent=2))
    if full_stl.get("exists") and "bbox_size_mm" in full_stl:
        sz = full_stl["bbox_size_mm"]
        t = full_stl["topology"]
        print(
            f"FULL STL: {full_stl['triangle_count']:,} tris | "
            f"{sz['x']}x{sz['y']}x{sz['z']} mm | vol={full_stl['signed_volume_cm3']} cm^3 | "
            f"boundary={t['boundary_edges_1']} non_man={t['non_manifold_edges_gt2']} "
            f"inconsistent={t['inconsistent_orientation_edges']} degen={full_stl['degenerate_triangles']} "
            f"shells={t['connected_components']} watertight={t['watertight_manifold']}"
        )
    if face_stl.get("exists") and "bbox_size_mm" in face_stl:
        sz = face_stl["bbox_size_mm"]
        t = face_stl["topology"]
        s = face_stl.get("bilateral_symmetry_x", {})
        print(
            f"FACE STL: {face_stl['triangle_count']:,} tris | "
            f"{sz['x']}x{sz['y']}x{sz['z']} mm | vol={face_stl['signed_volume_cm3']} cm^3 | "
            f"boundary={t['boundary_edges_1']} non_man={t['non_manifold_edges_gt2']} "
            f"shells={t['connected_components']} watertight={t['watertight_manifold']} | "
            f"X-sym RMS={s.get('rms_about_x0_mm')} mm (mid={s.get('rms_about_xmid_mm')} mm)"
        )
    if obj_mtl.get("exists") and "counts" in obj_mtl:
        c = obj_mtl["counts"]
        print(
            f"OBJ/MTL:  v={c['vertices']:,} vt={c['uv_coords']:,} vn={c['normals']:,} "
            f"f={c['faces']:,} (uv_faces={c['faces_with_uv']:,}) | "
            f"mtls={obj_mtl['defined_materials']} | textures={len(obj_mtl['textures'])}"
        )
    if blend_file.get("exists"):
        print(f"BLEND:    {blend_file['file_size_human']} ({blend_file.get('format')})")

    if all_issues:
        print("\nISSUES:")
        for iss in all_issues:
            print(f"  - {iss}")
        return 1
    print("\nALL AUTOMATED QA CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
