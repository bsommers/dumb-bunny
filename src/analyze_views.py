#!/usr/bin/env python3
"""
Operation Dumb Bunny — 4-View Photogrammetry, Silhouette Segmentation & Landmark Calibration.

Segments Dumb Bunny from the off-white patterned sheet (rejecting cast shadows via CIE Lab
chromaticity invariance), extracts calibrated metric dimensions at target height 0.180 m,
samples authentic sRGB material colors, generates 4 height-aligned 600x800 RGBA orthographic
reference plates, and renders a 4-panel calibration verification sheet.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
REF_DIR = ROOT / "work" / "ref_images"
OUT_JSON = ROOT / "work" / "measurements.json"
CALIB_IMG = REF_DIR / "calibration_sheet.png"

sys.path.insert(0, str(ROOT / "src"))
try:
    import tracker_util
except ImportError:
    tracker_util = None

TARGET_HEIGHT_M = 0.180  # 180 mm assembled target height
ORTHO_W = 600
ORTHO_H = 800
ORTHO_TOP_PX = 58        # Z = 0.180 m
ORTHO_BOT_PX = 742       # Z = 0.000 m  -> 684 px = 0.180 m -> 3800 px/m (gives generous ear margin!)
ORTHO_PX_PER_M = (ORTHO_BOT_PX - ORTHO_TOP_PX) / TARGET_HEIGHT_M


# ---------------------------------------------------------------------------
# Color space helpers
# ---------------------------------------------------------------------------

def srgb_to_linear(rgb01: np.ndarray) -> np.ndarray:
    arr = np.clip(np.asarray(rgb01, dtype=np.float32), 0.0, 1.0)
    return np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)


def rgb01_to_lab(rgb01: np.ndarray):
    lin = srgb_to_linear(rgb01)
    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float32)
    xyz = lin @ M.T
    xyz[..., 0] /= 0.95047
    xyz[..., 2] /= 1.08883
    eps = 0.008856
    kappa = 903.3
    f = np.where(xyz > eps, np.cbrt(np.maximum(xyz, 0.0)), (kappa * xyz + 16.0) / 116.0)
    L = 116.0 * f[..., 1] - 16.0
    a = 500.0 * (f[..., 0] - f[..., 1])
    b = 200.0 * (f[..., 1] - f[..., 2])
    return L, a, b


def rgb01_to_hsv(rgb01: np.ndarray):
    r, g, b = rgb01[..., 0], rgb01[..., 1], rgb01[..., 2]
    mx = np.max(rgb01, axis=-1)
    mn = np.min(rgb01, axis=-1)
    df = mx - mn
    s = np.where(mx > 1e-5, df / np.maximum(mx, 1e-5), 0.0)
    h = np.zeros_like(mx)
    m = df > 1e-5
    rm = m & (mx == r)
    gm = m & (mx == g)
    bm = m & (mx == b)
    h[rm] = ((g[rm] - b[rm]) / df[rm]) % 6.0
    h[gm] = ((b[gm] - r[gm]) / df[gm]) + 2.0
    h[bm] = ((r[bm] - g[bm]) / df[bm]) + 4.0
    h = (h / 6.0) * 360.0
    return h, s, mx


def format_color(rgb_255):
    r, g, b = [int(round(float(np.clip(c, 0, 255)))) for c in rgb_255]
    s01 = [round(r / 255.0, 4), round(g / 255.0, 4), round(b / 255.0, 4)]
    lin = [round(float(x), 4) for x in srgb_to_linear(np.array(s01))]
    return {
        "hex": f"#{r:02x}{g:02x}{b:02x}",
        "srgb_255": [r, g, b],
        "srgb_01": s01,
        "linear_rgb": lin,
    }


def largest_component(mask_bool: np.ndarray, min_pixels: int = 15) -> np.ndarray:
    labeled, n = ndimage.label(mask_bool)
    if n == 0:
        return np.zeros_like(mask_bool, dtype=bool)
    sizes = ndimage.sum(mask_bool, labeled, range(1, n + 1))
    best = int(np.argmax(sizes))
    if sizes[best] < min_pixels:
        return np.zeros_like(mask_bool, dtype=bool)
    return labeled == (best + 1)


# ---------------------------------------------------------------------------
# Shadow-invariant segmentation in CIE Lab + chromaticity
# ---------------------------------------------------------------------------

def segment_bunny(rgb_u8: np.ndarray, view_name: str):
    """
    Segment Dumb Bunny from the off-white patterned sheet while rejecting soft gray
    cast shadows. Uses CIE Lab chromaticity delta relative to the background sheet.
    Returns (mask_bool, submasks_dict, lab_tuple).
    """
    h, w, _ = rgb_u8.shape
    rgb01 = rgb_u8.astype(np.float32) / 255.0
    L, a, b = rgb01_to_lab(rgb01)
    H_deg, S, V = rgb01_to_hsv(rgb01)

    # Estimate sheet background chromaticity from clean border strips
    bw = max(12, int(min(h, w) * 0.04))
    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[:bw, :] = True
    border_mask[-bw:, :] = True
    border_mask[:, :bw] = True
    border_mask[:, -bw:] = True

    bL = L[border_mask]
    ba = a[border_mask]
    bb = b[border_mask]
    bright = bL > np.percentile(bL, 40)
    a_bg = float(np.median(ba[bright]))
    b_bg = float(np.median(bb[bright]))
    L_bg = float(np.median(bL[bright]))

    da = a - a_bg
    db = b - b_bg
    d_ab = np.hypot(da, db)

    rgb_sum = np.maximum(rgb01.sum(axis=-1), 1e-4)
    rn = rgb01[..., 0] / rgb_sum
    gn = rgb01[..., 1] / rgb_sum
    bn = rgb01[..., 2] / rgb_sum

    # 1. Pink velour (lit & deeply shadowed)
    pink_core = (
        ((da > 7.2) & (L < 79.0) & ((rn - gn) > 0.036))
        | ((da > 10.5) & (L < 86.0))
        | ((da > 5.8) & (db < -3.0) & (L < 74.0) & ((rn - gn) > 0.032))
    )

    # 2. Olive-tan woven cloth (arms, feet, ears)
    olive_core = (
        (db > 8.5)
        & (L < 67.0)
        & (S > 0.28)
        & ((gn - bn) > 0.065)
        & (da > -4.0)
    )
    olive_lit = (
        (db > 11.5)
        & (L < 74.0)
        & (S > 0.30)
        & ((gn - bn) > 0.075)
    )
    olive_mask = olive_core | olive_lit

    # 3. Vintage peach/cream rubber face + warm tape over face contour
    if view_name in ("front", "left_side", "right_side"):
        yy = np.linspace(0.0, 1.0, h)[:, None]
        upper_zone = yy < 0.54
        face_peach = (
            upper_zone
            & (da > 4.2)
            & (db > 4.2)
            & (d_ab > 7.8)
            & (L < 83.0)
            & (L > 22.0)
            & (S > 0.16)
        )
        face_eye = (
            upper_zone
            & (
                ((db < -9.5) & (L < 66.0) & (S > 0.22))
                | ((L < 22.0) & (S < 0.45))
            )
        )
        face_raw = face_peach | face_eye
    else:
        face_raw = np.zeros((h, w), dtype=bool)

    raw = pink_core | olive_mask | face_raw

    scale_px = max(1, int(round(min(h, w) / 450.0)))
    raw = ndimage.binary_opening(raw, structure=np.ones((2 * scale_px + 1, 2 * scale_px + 1)))

    labeled, n_comp = ndimage.label(raw)
    if n_comp == 0:
        raise RuntimeError(f"Segmentation failed on {view_name}: no foreground found")
    sizes = ndimage.sum(raw, labeled, range(1, n_comp + 1))
    main_idx = int(np.argmax(sizes)) + 1
    main_mask = labeled == main_idx

    dilated_main = ndimage.binary_dilation(main_mask, iterations=10 * scale_px)
    combined = main_mask.copy()
    main_area = float(sizes[main_idx - 1])
    for idx in range(1, n_comp + 1):
        if idx == main_idx:
            continue
        if sizes[idx - 1] >= 0.004 * main_area:
            comp = labeled == idx
            if np.any(comp & dilated_main):
                combined |= comp

    # Gently recover desaturated edge pixels inside tight band, excluding cast shadows & bright sheet
    band = ndimage.binary_dilation(combined, iterations=3 * scale_px) & (~combined)
    not_cast_shadow = ~((da < 5.5) & (db < 8.0) & (d_ab < 9.0) & (L < L_bg - 10.0))
    not_bright_sheet = ~((L > 75.0) & (d_ab < 8.5))
    soft_recover = (
        band
        & not_cast_shadow
        & not_bright_sheet
        & (
            ((da > 5.5) & (L < 80.0))
            | ((db > 8.0) & (L < 71.0) & (S > 0.25))
            | ((L < 28.0) & (d_ab > 4.5))
        )
    )
    combined |= soft_recover

    disk_r = 5 * scale_px
    yy_k, xx_k = np.ogrid[-disk_r:disk_r + 1, -disk_r:disk_r + 1]
    disk = (xx_k ** 2 + yy_k ** 2) <= disk_r ** 2
    combined = ndimage.binary_closing(combined, structure=disk)
    combined = ndimage.binary_fill_holes(combined)

    mask = largest_component(combined, min_pixels=100)
    smooth = ndimage.gaussian_filter(mask.astype(np.float32), sigma=1.1 * scale_px)
    mask = smooth >= 0.50

    # Broad olive submask strictly inside segmented bunny (captures shadowed arm/foot halves too)
    olive_inside = (
        olive_mask
        | ((db > 5.0) & (L < 58.0) & (S > 0.20) & (da < 11.5) & ((gn - bn) > 0.042))
    )
    submasks = {
        "pink": mask & pink_core,
        "olive": mask & olive_inside & (~((da > 11.5) & (db < 5.0))),
        "face": mask & face_raw & (~pink_core) & (~olive_mask),
    }
    return mask, submasks, (L, a, b, a_bg, b_bg, L_bg)


# ---------------------------------------------------------------------------
# View alignment & orthographic plate generation
# ---------------------------------------------------------------------------

def compute_torso_center_x(mask: np.ndarray, y_top: int, y_bot: int) -> float:
    """Compute robust horizontal centerline of the torso (z_norm in [0.22, 0.65])."""
    h_px = y_bot - y_top
    z_lo = int(y_bot - 0.65 * h_px)
    z_hi = int(y_bot - 0.22 * h_px)
    mids = []
    for y in range(max(y_top, z_lo), min(y_bot, z_hi)):
        xs = np.where(mask[y])[0]
        if len(xs) > 10:
            mids.append(0.5 * (xs[0] + xs[-1]))
    if not mids:
        xs = np.where(mask)[1]
        return float(0.5 * (xs.min() + xs.max()))
    return float(np.median(mids))


def build_ortho_plate(rgb_u8: np.ndarray, mask: np.ndarray, view_name: str,
                      y_top: int, y_bot: int, cx_torso: float):
    """
    Create a 600x800 RGBA height-aligned orthographic reference plate.
    Maps [y_top, y_bot] -> [ORTHO_TOP_PX, ORTHO_BOT_PX] (exact 3800 px/m)
    and cx_torso -> ORTHO_W / 2.
    """
    h, w, _ = rgb_u8.shape
    bunny_h_px = max(1.0, float(y_bot - y_top))
    scale = (ORTHO_BOT_PX - ORTHO_TOP_PX) / bunny_h_px

    alpha_f = ndimage.gaussian_filter(mask.astype(np.float32), sigma=0.8)
    alpha_u8 = np.clip(alpha_f * 255.0, 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb_u8, alpha_u8])
    src_im = Image.fromarray(rgba, mode="RGBA")

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = src_im.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (ORTHO_W, ORTHO_H), (0, 0, 0, 0))
    paste_x = int(round((ORTHO_W / 2.0) - cx_torso * scale))
    paste_y = int(round(ORTHO_TOP_PX - y_top * scale))
    canvas.paste(resized, (paste_x, paste_y), resized)

    mask_im = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    mask_res = mask_im.resize((new_w, new_h), Image.Resampling.BILINEAR)
    mask_canvas = Image.new("L", (ORTHO_W, ORTHO_H), 0)
    mask_canvas.paste(mask_res, (paste_x, paste_y))
    ortho_mask = np.asarray(mask_canvas) >= 128

    transform = {
        "scale": float(scale),
        "paste_x": int(paste_x),
        "paste_y": int(paste_y),
        "src_y_top": int(y_top),
        "src_y_bot": int(y_bot),
        "src_cx_torso": float(cx_torso),
    }
    return canvas, ortho_mask, transform


def warp_submask_to_ortho(submask: np.ndarray, transform: dict) -> np.ndarray:
    h, w = submask.shape
    new_w = max(1, int(round(w * transform["scale"])))
    new_h = max(1, int(round(h * transform["scale"])))
    im = Image.fromarray((submask.astype(np.uint8) * 255), mode="L")
    res = im.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("L", (ORTHO_W, ORTHO_H), 0)
    canvas.paste(res, (transform["paste_x"], transform["paste_y"]))
    return np.asarray(canvas) >= 128


# ---------------------------------------------------------------------------
# Metric coordinate conversion on 600x800 ortho canvas
# ---------------------------------------------------------------------------

def px_y_to_z_m(y_px: float) -> float:
    return (ORTHO_BOT_PX - float(y_px)) / ORTHO_PX_PER_M


def z_m_to_px_y(z_m: float) -> float:
    return ORTHO_BOT_PX - float(z_m) * ORTHO_PX_PER_M


def px_x_to_coord_m(x_px: float) -> float:
    return (float(x_px) - ORTHO_W / 2.0) / ORTHO_PX_PER_M


def coord_m_to_px_x(coord_m: float) -> float:
    return ORTHO_W / 2.0 + float(coord_m) * ORTHO_PX_PER_M


# ---------------------------------------------------------------------------
# Slice & landmark extraction
# ---------------------------------------------------------------------------

def extract_24_slices(ortho_masks: dict, submasks_ortho: dict):
    """Extract 24 calibrated vertical height slices from z_norm = 0.02 to 0.98."""
    m_front = ortho_masks["front"]
    m_back = ortho_masks["back"]
    m_left = ortho_masks["left_side"]
    m_right = ortho_masks["right_side"]
    yy_grid = np.arange(ORTHO_H)[:, None]
    m_front_no_ear = m_front & (~(submasks_ortho["front"]["olive"] & (yy_grid < z_m_to_px_y(0.125))))

    slices = []
    z_norms = np.linspace(0.02, 0.98, 24)
    band_half = 4

    for idx, zn in enumerate(z_norms):
        z_m = float(zn * TARGET_HEIGHT_M)
        yc = int(round(z_m_to_px_y(z_m)))
        y0 = max(0, yc - band_half)
        y1 = min(ORTHO_H, yc + band_half + 1)

        def row_span(m):
            lefts, rights = [], []
            for r in range(y0, y1):
                xs = np.where(m[r])[0]
                if len(xs) >= 2:
                    lefts.append(xs[0])
                    rights.append(xs[-1])
            if not lefts:
                return None
            return float(np.median(lefts)), float(np.median(rights))

        sp_f = row_span(m_front)
        sp_f_body = row_span(m_front_no_ear)
        sp_b = row_span(m_back)
        sp_l = row_span(m_left)
        sp_r = row_span(m_right)

        if sp_f is not None:
            fx_min = px_x_to_coord_m(sp_f[0])
            fx_max = px_x_to_coord_m(sp_f[1])
            f_hw = 0.5 * (fx_max - fx_min)
        else:
            fx_min, fx_max, f_hw = 0.0, 0.0, 0.0

        hw_candidates = []
        if sp_f_body is not None:
            hw_candidates.append(0.5 * (px_x_to_coord_m(sp_f_body[1]) - px_x_to_coord_m(sp_f_body[0])))
        if sp_b is not None:
            b_hw = 0.5 * (px_x_to_coord_m(sp_b[1]) - px_x_to_coord_m(sp_b[0]))
            hw_candidates.append(b_hw)
        else:
            b_hw = f_hw

        body_hw = float(np.mean(hw_candidates)) if hw_candidates else f_hw

        front_ys, back_ys = [], []
        if sp_l is not None:
            front_ys.append(px_x_to_coord_m(sp_l[0]))
            back_ys.append(px_x_to_coord_m(sp_l[1]))
        if sp_r is not None:
            if z_m > 0.140:
                m_r_no_ear = m_right & (~submasks_ortho["right_side"]["olive"])
                sp_r_clean = row_span(m_r_no_ear)
            else:
                sp_r_clean = sp_r
            if sp_r_clean is not None:
                front_ys.append(-px_x_to_coord_m(sp_r_clean[1]))
                back_ys.append(-px_x_to_coord_m(sp_r_clean[0]))

        side_front_y = float(np.mean(front_ys)) if front_ys else -0.025
        side_back_y = float(np.mean(back_ys)) if back_ys else 0.025
        depth_m = max(0.0, side_back_y - side_front_y)
        center_y = 0.5 * (side_front_y + side_back_y)

        slices.append({
            "index": idx,
            "z_norm": round(float(zn), 4),
            "z_m": round(z_m, 5),
            "front_x_min_m": round(fx_min, 5),
            "front_x_max_m": round(fx_max, 5),
            "front_half_width_m": round(f_hw, 5),
            "back_half_width_m": round(b_hw, 5),
            "body_half_width_m": round(body_hw, 5),
            "side_front_y_m": round(side_front_y, 5),
            "side_back_y_m": round(side_back_y, 5),
            "depth_m": round(depth_m, 5),
            "torso_center_y_m": round(center_y, 5),
        })

    return slices


def extract_landmarks(ortho_masks: dict, submasks_ortho: dict, slices: list):
    """Extract calibrated anatomical landmarks using isolated connected components."""
    sf = submasks_ortho["front"]
    sl = submasks_ortho["left_side"]
    sr = submasks_ortho["right_side"]
    yy_grid = np.arange(ORTHO_H)[:, None]
    xx_grid = np.arange(ORTHO_W)[None, :]

    def mask_bbox_m(m_bool):
        ys, xs = np.where(m_bool)
        if len(xs) < 15:
            return None
        return {
            "x_min": px_x_to_coord_m(np.percentile(xs, 2)),
            "x_max": px_x_to_coord_m(np.percentile(xs, 98)),
            "z_min": px_y_to_z_m(np.percentile(ys, 98)),
            "z_max": px_y_to_z_m(np.percentile(ys, 2)),
            "cx": px_x_to_coord_m(np.median(xs)),
            "cz": px_y_to_z_m(np.median(ys)),
        }

    # --- 1. Neck pinch (use back_half_width + side depth minimum in z in [0.100, 0.130]) ---
    # Back view cleanly exposes the cinched hood neck gather without jaw overhang!
    neck_slices = [s for s in slices if 0.100 <= s["z_m"] <= 0.130]
    neck_s = min(neck_slices, key=lambda s: s["back_half_width_m"] + 0.35 * s["depth_m"])
    neck_z = neck_s["z_m"]
    neck_pinch = {
        "z_m": round(neck_z, 5),
        "half_width_m": round(neck_s["back_half_width_m"], 5),
        "front_half_width_m": round(neck_s["body_half_width_m"], 5),
        "depth_m": round(neck_s["depth_m"], 5),
        "center_y_m": round(neck_s["torso_center_y_m"], 5),
        "front_y_m": round(neck_s["side_front_y_m"], 5),
        "back_y_m": round(neck_s["side_back_y_m"], 5),
    }

    # --- 2. Head & Hood ---
    head_slices = [s for s in slices if s["z_m"] >= neck_z]
    head_max_hw = max(s["body_half_width_m"] for s in head_slices)
    head_z_min = neck_z
    head_z_max = TARGET_HEIGHT_M
    head_cz = 0.5 * (head_z_min + head_z_max)
    head_cy = float(np.mean([s["torso_center_y_m"] for s in head_slices if 0.125 <= s["z_m"] <= 0.168]))
    head_front_y = min(s["side_front_y_m"] for s in head_slices if 0.120 <= s["z_m"] <= 0.165)
    head_back_y = max(s["side_back_y_m"] for s in head_slices if 0.120 <= s["z_m"] <= 0.172)

    head = {
        "center": [0.0, round(head_cy, 5), round(head_cz, 5)],
        "radius_x_m": round(head_max_hw * 0.90, 5),
        "radius_y_m": round(0.5 * (head_back_y - head_front_y) * 0.92, 5),
        "radius_z_m": round(0.5 * (head_z_max - head_z_min) * 0.94, 5),
        "hood_outer_radius_x_m": round(head_max_hw, 5),
        "hood_outer_radius_y_m": round(0.5 * (head_back_y - head_front_y), 5),
        "hood_outer_radius_z_m": round(0.5 * (head_z_max - head_z_min), 5),
        "crown_z_m": round(head_z_max, 5),
        "front_y_m": round(head_front_y, 5),
        "back_y_m": round(head_back_y, 5),
    }

    # Helper disk for closing small interior fray/patch/eye gaps inside material blobs
    def close_fill(m_bool: np.ndarray, r: int = 10) -> np.ndarray:
        yk, xk = np.ogrid[-r:r + 1, -r:r + 1]
        st = (xk ** 2 + yk ** 2) <= r ** 2
        return ndimage.binary_fill_holes(ndimage.binary_closing(m_bool, structure=st))

    # --- 3. Face Oval (from front face submask + side profile protrusion) ---
    face_region = sf["face"] & (yy_grid < z_m_to_px_y(neck_z - 0.012))
    face_closed = largest_component(close_fill(face_region, r=14))
    fb = mask_bbox_m(face_closed)
    if fb is None or (fb["x_max"] - fb["x_min"]) < 0.030:
        face_w = head["radius_x_m"] * 1.65
        face_h = head["radius_z_m"] * 1.65
        face_cz = head_cz - 0.002
    else:
        face_w = fb["x_max"] - fb["x_min"]
        face_h = fb["z_max"] - fb["z_min"]
        face_cz = 0.5 * (fb["z_min"] + fb["z_max"])

    left_face_mask = largest_component(close_fill(sl["face"] & (yy_grid < z_m_to_px_y(neck_z - 0.008)), r=10))
    left_pink_head = sl["pink"] & (yy_grid < z_m_to_px_y(neck_z))
    if np.count_nonzero(left_face_mask) > 30 and np.count_nonzero(left_pink_head) > 30:
        face_y_front = px_x_to_coord_m(np.percentile(np.where(left_face_mask)[1], 3))
        hood_rim_y = px_x_to_coord_m(np.percentile(np.where(left_pink_head)[1], 8))
        y_protrusion = max(0.010, hood_rim_y - face_y_front)
    else:
        face_y_front = head_front_y
        hood_rim_y = head_front_y + 0.016
        y_protrusion = 0.016

    face_oval = {
        "center": [0.0, round(face_y_front + 0.45 * y_protrusion, 5), round(face_cz, 5)],
        "width_m": round(face_w, 5),
        "height_m": round(face_h, 5),
        "half_width_m": round(0.5 * face_w, 5),
        "half_height_m": round(0.5 * face_h, 5),
        "x_min_m": round(-0.5 * face_w, 5),
        "x_max_m": round(0.5 * face_w, 5),
        "z_min_m": round(face_cz - 0.5 * face_h, 5),
        "z_max_m": round(face_cz + 0.5 * face_h, 5),
        "y_front_surface_m": round(face_y_front, 5),
        "hood_rim_y_m": round(hood_rim_y, 5),
        "y_protrusion_m": round(y_protrusion, 5),
    }

    # --- 4. Torso Belly & Back Profile ---
    torso_slices = [s for s in slices if 0.015 <= s["z_m"] <= neck_z]
    max_w_slice = max(torso_slices, key=lambda s: s["body_half_width_m"])
    max_d_slice = max(torso_slices, key=lambda s: s["depth_m"])
    torso_cy = float(np.mean([s["torso_center_y_m"] for s in torso_slices]))

    torso = {
        "z_min_m": 0.0,
        "z_max_m": round(neck_z, 5),
        "center_y_m": round(torso_cy, 5),
        "max_width_m": round(2.0 * max_w_slice["body_half_width_m"], 5),
        "max_width_z_m": round(max_w_slice["z_m"], 5),
        "max_depth_m": round(max_d_slice["depth_m"], 5),
        "max_depth_z_m": round(max_d_slice["z_m"], 5),
        "belly_profile": [{"z_m": s["z_m"], "y_m": s["side_front_y_m"]} for s in torso_slices],
        "back_profile": [{"z_m": s["z_m"], "y_m": s["side_back_y_m"]} for s in torso_slices],
    }

    # --- 5. Arms (closed isolated olive connected component in z in [0.082, 0.128]) ---
    arm_z_band = (yy_grid <= z_m_to_px_y(0.082)) & (yy_grid >= z_m_to_px_y(0.128))
    arm_l_front = largest_component(close_fill(sf["olive"] & arm_z_band & (xx_grid > ORTHO_W // 2 + 10), r=10))
    arm_l_side = largest_component(close_fill(sl["olive"] & arm_z_band, r=10))

    al_f = mask_bbox_m(arm_l_front)
    al_s = mask_bbox_m(arm_l_side)

    if al_f is not None:
        arm_cx = 0.5 * (al_f["x_min"] + al_f["x_max"])
        arm_rx = max(0.010, 0.5 * (al_f["x_max"] - al_f["x_min"]))
        arm_cz_f = 0.5 * (al_f["z_min"] + al_f["z_max"])
        arm_rz_f = 0.5 * (al_f["z_max"] - al_f["z_min"])
    else:
        arm_cx, arm_rx, arm_cz_f, arm_rz_f = 0.036, 0.011, 0.104, 0.016

    if al_s is not None:
        arm_cy = 0.5 * (al_s["x_min"] + al_s["x_max"])
        arm_ry = max(0.010, 0.5 * (al_s["x_max"] - al_s["x_min"]))
        arm_cz = 0.5 * (arm_cz_f + 0.5 * (al_s["z_min"] + al_s["z_max"]))
        arm_rz = 0.5 * (arm_rz_f + 0.5 * (al_s["z_max"] - al_s["z_min"]))
    else:
        arm_cy, arm_ry, arm_cz, arm_rz = 0.004, 0.012, arm_cz_f, arm_rz_f

    arms = {
        "left": {
            "side": "+X",
            "center": [round(arm_cx, 5), round(arm_cy, 5), round(arm_cz, 5)],
            "radius_x_m": round(arm_rx, 5),
            "radius_y_m": round(arm_ry, 5),
            "radius_z_m": round(arm_rz, 5),
            "length_m": round(2.0 * arm_rz, 5),
            "tilt_deg": 20.0,
        },
        "right": {
            "side": "-X",
            "center": [round(-arm_cx, 5), round(arm_cy, 5), round(arm_cz, 5)],
            "radius_x_m": round(arm_rx, 5),
            "radius_y_m": round(arm_ry, 5),
            "radius_z_m": round(arm_rz, 5),
            "length_m": round(2.0 * arm_rz, 5),
            "tilt_deg": -20.0,
        },
    }

    # --- 6. Feet (closed isolated olive connected components in z in [0.000, 0.080]) ---
    # Closing fuses the pink floral repair patch on the right foot back into the full oval!
    foot_z_band = (yy_grid <= z_m_to_px_y(0.000)) & (yy_grid >= z_m_to_px_y(0.080))
    foot_l_front = largest_component(close_fill(sf["olive"] & foot_z_band & (xx_grid > ORTHO_W // 2), r=14))
    foot_r_front = largest_component(close_fill(sf["olive"] & foot_z_band & (xx_grid < ORTHO_W // 2), r=14))
    foot_l_side = largest_component(close_fill(sl["olive"] & foot_z_band, r=14))
    foot_r_side = largest_component(close_fill(sr["olive"] & foot_z_band, r=14))

    fl_f = mask_bbox_m(foot_l_front)
    fr_f = mask_bbox_m(foot_r_front)
    fl_s = mask_bbox_m(foot_l_side)
    fr_s = mask_bbox_m(foot_r_side)

    # Note: In front view, bunny right foot (-X) is slightly lower & left foot (+X) slightly higher
    # due to lying posture; symmetrizing left/right gives clean upright plush doll feet!
    cx_list, rx_list, cz_list, rz_list = [], [], [], []
    for fb_i in (fl_f, fr_f):
        if fb_i is not None:
            cx_list.append(abs(0.5 * (fb_i["x_min"] + fb_i["x_max"])))
            rx_list.append(0.5 * (fb_i["x_max"] - fb_i["x_min"]))
            cz_list.append(0.5 * (fb_i["z_min"] + fb_i["z_max"]))
            rz_list.append(0.5 * (fb_i["z_max"] - fb_i["z_min"]))

    cy_list, ry_list = [], []
    if fl_s is not None:
        cy_list.append(0.5 * (fl_s["x_min"] + fl_s["x_max"]))
        ry_list.append(0.5 * (fl_s["x_max"] - fl_s["x_min"]))
        cz_list.append(0.5 * (fl_s["z_min"] + fl_s["z_max"]))
        rz_list.append(0.5 * (fl_s["z_max"] - fl_s["z_min"]))
    if fr_s is not None:
        cy_list.append(-0.5 * (fr_s["x_min"] + fr_s["x_max"]))
        ry_list.append(0.5 * (fr_s["x_max"] - fr_s["x_min"]))
        cz_list.append(0.5 * (fr_s["z_min"] + fr_s["z_max"]))
        rz_list.append(0.5 * (fr_s["z_max"] - fr_s["z_min"]))

    foot_cx = float(np.mean(cx_list)) if cx_list else 0.036
    foot_rx = float(np.mean(rx_list)) if rx_list else 0.015
    foot_cy = float(np.mean(cy_list)) if cy_list else -0.016
    foot_ry = float(np.mean(ry_list)) if ry_list else 0.020
    foot_cz = float(np.mean(cz_list)) if cz_list else 0.034
    foot_rz = float(np.mean(rz_list)) if rz_list else 0.025
    foot_cz = max(foot_rz + 0.002, foot_cz)

    feet = {
        "left": {
            "side": "+X",
            "center": [round(foot_cx, 5), round(foot_cy, 5), round(foot_cz, 5)],
            "radius_x_m": round(foot_rx, 5),
            "radius_y_m": round(foot_ry, 5),
            "radius_z_m": round(foot_rz, 5),
            "width_m": round(2.0 * foot_rx, 5),
            "length_m": round(2.0 * foot_ry, 5),
            "height_m": round(2.0 * foot_rz, 5),
            "yaw_deg": -14.0,
        },
        "right": {
            "side": "-X",
            "center": [round(-foot_cx, 5), round(foot_cy, 5), round(foot_cz, 5)],
            "radius_x_m": round(foot_rx, 5),
            "radius_y_m": round(foot_ry, 5),
            "radius_z_m": round(foot_rz, 5),
            "width_m": round(2.0 * foot_rx, 5),
            "length_m": round(2.0 * foot_ry, 5),
            "height_m": round(2.0 * foot_rz, 5),
            "yaw_deg": 14.0,
        },
    }

    # --- 7. Bunny Ears (floppy cloth paddle ears from top crown) ---
    ear_z_band = yy_grid <= z_m_to_px_y(0.140)
    ear_f = largest_component(sf["olive"] & ear_z_band & (xx_grid < ORTHO_W // 2 - 20))
    ear_r = largest_component(sr["olive"] & ear_z_band)

    ef = mask_bbox_m(ear_f)
    er = mask_bbox_m(ear_r)

    ear_lengths, ear_widths = [], []
    if ef is not None:
        ear_lengths.append(math.hypot(ef["x_max"] - ef["x_min"], ef["z_max"] - ef["z_min"]))
        ear_widths.append(ef["z_max"] - ef["z_min"])
    if er is not None:
        ear_lengths.append(math.hypot(er["x_max"] - er["x_min"], er["z_max"] - er["z_min"]))
        ear_widths.append(min(er["x_max"] - er["x_min"], er["z_max"] - er["z_min"]) * 0.65)

    ear_len = float(np.clip(np.mean(ear_lengths) if ear_lengths else 0.048, 0.042, 0.056))
    ear_w = float(np.clip(np.mean(ear_widths) if ear_widths else 0.023, 0.018, 0.026))
    ear_base_x = round(head["hood_outer_radius_x_m"] * 0.44, 5)
    ear_base_y = round(head["front_y_m"] + 0.36 * (head["back_y_m"] - head["front_y_m"]), 5)
    ear_base_z = round(TARGET_HEIGHT_M - 0.008, 5)

    ears = {
        "length_m": round(ear_len, 5),
        "width_m": round(ear_w, 5),
        "thickness_m": 0.0055,  # >= 4.5 mm print-safe paddle thickness
        "left": {
            "side": "+X",
            "base": [ear_base_x, ear_base_y, ear_base_z],
            "length_m": round(ear_len, 5),
            "width_m": round(ear_w, 5),
            "thickness_m": 0.0055,
            "splay_angle_deg": 48.0,
            "flop_forward_deg": 18.0,
        },
        "right": {
            "side": "-X",
            "base": [-ear_base_x, ear_base_y, ear_base_z],
            "length_m": round(ear_len, 5),
            "width_m": round(ear_w, 5),
            "thickness_m": 0.0055,
            "splay_angle_deg": -48.0,
            "flop_forward_deg": 18.0,
        },
    }

    return {
        "head": head,
        "face_oval": face_oval,
        "neck_pinch": neck_pinch,
        "torso": torso,
        "arms": arms,
        "feet": feet,
        "ears": ears,
    }


# ---------------------------------------------------------------------------
# Authentic sRGB color sampling
# ---------------------------------------------------------------------------

def sample_authentic_colors(views_rgb: dict, submasks_raw: dict, labs_raw: dict):
    """
    Sample authentic sRGB colors directly from the reference photos:
    pink_velour, pink_velour_shadow, olive_cloth, rubber_skin, eye_blue, nose_pink.
    """
    # 1. Pink velour (lit dusty-rose & fold shadow) across all 4 views
    pink_pixels, pink_L, pink_a = [], [], []
    for vn in ("front", "back", "left_side", "right_side"):
        m = submasks_raw[vn]["pink"]
        L, a, b, a_bg, _, _ = labs_raw[vn]
        # Pure pink velour (strongly rose/mauve, avoiding warm skin bounce)
        pure_p = m & ((a - a_bg) > 10.5) & (b < 9.0)
        if np.count_nonzero(pure_p) > 50:
            pink_pixels.append(views_rgb[vn][pure_p])
            pink_L.append(L[pure_p])
            pink_a.append(a[pure_p])
    all_pink = np.concatenate(pink_pixels, axis=0)
    all_pink_L = np.concatenate(pink_L, axis=0)

    # Lit dusty-rose velour midtone (70th-92nd L percentile)
    lo_lit, hi_lit = np.percentile(all_pink_L, [70, 92])
    pink_velour_rgb = np.median(all_pink[(all_pink_L >= lo_lit) & (all_pink_L <= hi_lit)], axis=0)

    # Fold shadow velour (12th-32nd L percentile)
    lo_sh, hi_sh = np.percentile(all_pink_L, [12, 32])
    pink_shadow_rgb = np.median(all_pink[(all_pink_L >= lo_sh) & (all_pink_L <= hi_sh)], axis=0)

    # 2. Olive-tan woven cloth from front + left_side + right_side
    olive_pixels, olive_L = [], []
    for vn in ("front", "left_side", "right_side"):
        m = submasks_raw[vn]["olive"]
        L = labs_raw[vn][0]
        if np.count_nonzero(m) > 50:
            olive_pixels.append(views_rgb[vn][m])
            olive_L.append(L[m])
    all_olive = np.concatenate(olive_pixels, axis=0)
    all_olive_L = np.concatenate(olive_L, axis=0)
    lo_ol, hi_ol = np.percentile(all_olive_L, [48, 80])
    olive_rgb = np.median(all_olive[(all_olive_L >= lo_ol) & (all_olive_L <= hi_ol)], axis=0)

    # 3. Rubber skin, eye_blue, nose_pink directly from crisp 1200x1200 front_face_closeup.png
    closeup_path = REF_DIR / "front_face_closeup.png"
    fc_u8 = np.asarray(Image.open(closeup_path).convert("RGB")) if closeup_path.exists() else views_rgb["front"]
    fc_f = fc_u8.astype(np.float32)
    fc01 = fc_f / 255.0
    fcL, fca, fcb = rgb01_to_lab(fc01)
    fcH, fcS, fcV = rgb01_to_hsv(fc01)
    ch, cw = fcL.shape
    cy_grid, cx_grid = np.mgrid[0:ch, 0:cw]

    # Smooth intact rubber peach forehead & right cheek (in closeup: y in 0.42..0.78, x in 0.25..0.56)
    skin_zone = (
        (cy_grid >= int(0.42 * ch)) & (cy_grid <= int(0.78 * ch))
        & (cx_grid >= int(0.25 * cw)) & (cx_grid <= int(0.56 * cw))
        & (fcH >= 18.0) & (fcH <= 38.0)
        & (fcS >= 0.20) & (fcS <= 0.42)
        & (fcL >= 62.0) & (fcL <= 82.0)
    )
    if np.count_nonzero(skin_zone) > 100:
        sk_pix = fc_f[skin_zone]
        sk_L = fcL[skin_zone]
        lo_s, hi_s = np.percentile(sk_L, [45, 82])
        rubber_skin_rgb = np.median(sk_pix[(sk_L >= lo_s) & (sk_L <= hi_s)], axis=0)
    else:
        rubber_skin_rgb = np.array([204, 169, 138], dtype=np.float32)

    # Vivid sky-blue eye iris (in closeup: y in 0.50..0.72, x in 0.25..0.65)
    eye_zone = (
        (cy_grid >= int(0.50 * ch)) & (cy_grid <= int(0.72 * ch))
        & (cx_grid >= int(0.24 * cw)) & (cx_grid <= int(0.65 * cw))
        & (fcH >= 195.0) & (fcH <= 235.0)
        & (fcS >= 0.42) & (fcV >= 0.35) & (fcV <= 0.85)
    )
    if np.count_nonzero(eye_zone) > 30:
        epix = fc_f[eye_zone]
        ebr = epix[:, 2] - epix[:, 0]
        eye_blue_rgb = np.median(epix[ebr >= np.percentile(ebr, 55)], axis=0)
    else:
        eye_blue_rgb = np.array([46, 108, 158], dtype=np.float32)

    # Tiny upturned coral-pink button nose (in closeup: x in 0.43..0.49, y in 0.60..0.67; R-G>55, G-B<20)
    nose_box = (
        (cy_grid >= int(0.60 * ch)) & (cy_grid <= int(0.67 * ch))
        & (cx_grid >= int(0.43 * cw)) & (cx_grid <= int(0.49 * cw))
    )
    nose_rg = fc_f[..., 0] - fc_f[..., 1]
    nose_gb = fc_f[..., 1] - fc_f[..., 2]
    nose_cand = nose_box & (nose_rg > 55.0) & (nose_gb < 20.0) & (fc_f[..., 0] > 140.0)
    if np.count_nonzero(nose_cand) > 15:
        npix = fc_f[nose_cand]
        nose_pink_rgb = np.percentile(npix, 75, axis=0)
    else:
        nose_pink_rgb = np.array([152, 78, 66], dtype=np.float32)

    return {
        "pink_velour": format_color(pink_velour_rgb),
        "pink_velour_shadow": format_color(pink_shadow_rgb),
        "olive_cloth": format_color(olive_rgb),
        "rubber_skin": format_color(rubber_skin_rgb),
        "eye_blue": format_color(eye_blue_rgb),
        "nose_pink": format_color(nose_pink_rgb),
    }


# ---------------------------------------------------------------------------
# 4-panel Calibration Verification Graphic
# ---------------------------------------------------------------------------

def render_calibration_sheet(ortho_plates: dict, ortho_masks: dict, views_raw: dict,
                             transforms: dict, landmarks: dict, slices: list, colors: dict):
    """
    Create a crisp 4-panel verification graphic (2400x966) showing all 4 height-aligned
    views with background dimmed, bright cyan silhouette contour, metric Z-grid,
    anatomical landmark overlays, and sampled color palette bar.
    """
    panel_w, panel_h = ORTHO_W, ORTHO_H
    header_h = 56
    footer_h = 110
    total_w = panel_w * 4
    total_h = header_h + panel_h + footer_h

    sheet = Image.new("RGB", (total_w, total_h), (20, 22, 28))
    draw = ImageDraw.Draw(sheet)

    try:
        font_title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
        font_med = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except Exception:
        font_title = ImageFont.load_default()
        font_med = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    draw.text(
        (20, 14),
        f"OPERATION DUMB BUNNY — 4-VIEW PHOTOGRAMMETRY & SILHOUETTE CALIBRATION (TARGET HEIGHT = 180.0 mm | {ORTHO_PX_PER_M:.0f} px/m)",
        fill=(240, 242, 248),
        font=font_title,
    )

    view_order = [
        ("front", "FRONT VIEW (Facing -Y | -X left / +X right)"),
        ("back", "BACK VIEW (Facing +Y | +X left / -X right)"),
        ("left_side", "LEFT SIDE (+X view | Front = Left -Y)"),
        ("right_side", "RIGHT SIDE (-X view | Front = Right -Y)"),
    ]

    for pi, (vname, vlabel) in enumerate(view_order):
        ox = pi * panel_w
        oy = header_h

        src_rgb = Image.fromarray(views_raw[vname], mode="RGB")
        tr = transforms[vname]
        nw = max(1, int(round(src_rgb.width * tr["scale"])))
        nh = max(1, int(round(src_rgb.height * tr["scale"])))
        res_rgb = src_rgb.resize((nw, nh), Image.Resampling.LANCZOS)
        bg_canvas = Image.new("RGB", (panel_w, panel_h), (28, 30, 38))
        bg_canvas.paste(res_rgb, (tr["paste_x"], tr["paste_y"]))

        bg_arr = np.asarray(bg_canvas, dtype=np.float32)
        m = ortho_masks[vname]
        comp = np.where(m[..., None], bg_arr, bg_arr * 0.30 + np.array([14, 16, 22], dtype=np.float32) * 0.70)

        edge = ndimage.binary_dilation(m, iterations=2) & (~m)
        comp[edge] = np.array([0, 235, 220], dtype=np.float32)

        panel_im = Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8), mode="RGB")
        sheet.paste(panel_im, (ox, oy))

        draw.rectangle([ox, oy, ox + panel_w - 1, oy + panel_h - 1], outline=(70, 76, 92), width=1)
        draw.rectangle([ox + 1, oy + 1, ox + panel_w - 2, oy + 28], fill=(16, 18, 24))
        draw.text((ox + 10, oy + 6), vlabel, fill=(130, 230, 255), font=font_med)

        cx = ox + panel_w // 2
        draw.line([(cx, oy + 28), (cx, oy + panel_h)], fill=(90, 95, 115), width=1)

        for z_mm in (0, 45, 90, 135, 180):
            y_l = oy + int(round(z_m_to_px_y(z_mm / 1000.0)))
            col = (255, 210, 80) if z_mm in (0, 180) else (85, 95, 115)
            draw.line([(ox, y_l), (ox + panel_w, y_l)], fill=col, width=1)
            draw.text((ox + 6, y_l - 14), f"{z_mm}mm", fill=col, font=font_sm)

        y_neck = oy + int(round(z_m_to_px_y(landmarks["neck_pinch"]["z_m"])))
        draw.line([(ox + 60, y_neck), (ox + panel_w - 60, y_neck)], fill=(255, 110, 180), width=2)
        draw.text((ox + panel_w - 115, y_neck - 15), f"Neck {landmarks['neck_pinch']['z_m']*1000:.0f}mm", fill=(255, 140, 200), font=font_sm)

        for s in slices:
            ys = oy + int(round(z_m_to_px_y(s["z_m"])))
            if vname == "front":
                x0 = ox + int(round(coord_m_to_px_x(-s["body_half_width_m"])))
                x1 = ox + int(round(coord_m_to_px_x(s["body_half_width_m"])))
            elif vname == "back":
                x0 = ox + int(round(coord_m_to_px_x(-s["back_half_width_m"])))
                x1 = ox + int(round(coord_m_to_px_x(s["back_half_width_m"])))
            elif vname == "left_side":
                x0 = ox + int(round(coord_m_to_px_x(s["side_front_y_m"])))
                x1 = ox + int(round(coord_m_to_px_x(s["side_back_y_m"])))
            else:
                x0 = ox + int(round(coord_m_to_px_x(-s["side_back_y_m"])))
                x1 = ox + int(round(coord_m_to_px_x(-s["side_front_y_m"])))
            draw.ellipse([x0 - 2, ys - 2, x0 + 2, ys + 2], fill=(255, 230, 80))
            draw.ellipse([x1 - 2, ys - 2, x1 + 2, ys + 2], fill=(255, 230, 80))

        if vname == "front":
            fo = landmarks["face_oval"]
            fx0 = ox + coord_m_to_px_x(fo["x_min_m"])
            fx1 = ox + coord_m_to_px_x(fo["x_max_m"])
            fz0 = oy + z_m_to_px_y(fo["z_max_m"])
            fz1 = oy + z_m_to_px_y(fo["z_min_m"])
            draw.ellipse([fx0, fz0, fx1, fz1], outline=(255, 200, 90), width=2)

            for side_k in ("left", "right"):
                a = landmarks["arms"][side_k]
                ax0 = ox + coord_m_to_px_x(a["center"][0] - a["radius_x_m"])
                ax1 = ox + coord_m_to_px_x(a["center"][0] + a["radius_x_m"])
                az0 = oy + z_m_to_px_y(a["center"][2] + a["radius_z_m"])
                az1 = oy + z_m_to_px_y(a["center"][2] - a["radius_z_m"])
                draw.ellipse([ax0, az0, ax1, az1], outline=(140, 255, 120), width=2)

            for side_k in ("left", "right"):
                ft = landmarks["feet"][side_k]
                ftx0 = ox + coord_m_to_px_x(ft["center"][0] - ft["radius_x_m"])
                ftx1 = ox + coord_m_to_px_x(ft["center"][0] + ft["radius_x_m"])
                ftz0 = oy + z_m_to_px_y(ft["center"][2] + ft["radius_z_m"])
                ftz1 = oy + z_m_to_px_y(ft["center"][2] - ft["radius_z_m"])
                draw.ellipse([ftx0, ftz0, ftx1, ftz1], outline=(120, 220, 255), width=2)

            for side_k in ("left", "right"):
                eb = landmarks["ears"][side_k]["base"]
                ex = ox + coord_m_to_px_x(eb[0])
                ez = oy + z_m_to_px_y(eb[2])
                draw.ellipse([ex - 5, ez - 5, ex + 5, ez + 5], fill=(255, 100, 100), outline=(255, 255, 255))

        elif vname in ("left_side", "right_side"):
            sgn = 1.0 if vname == "left_side" else -1.0
            hd = landmarks["head"]
            hy0 = ox + coord_m_to_px_x(sgn * (hd["center"][1] - hd["hood_outer_radius_y_m"]))
            hy1 = ox + coord_m_to_px_x(sgn * (hd["center"][1] + hd["hood_outer_radius_y_m"]))
            hz0 = oy + z_m_to_px_y(hd["center"][2] + hd["hood_outer_radius_z_m"])
            hz1 = oy + z_m_to_px_y(hd["center"][2] - hd["hood_outer_radius_z_m"])
            draw.ellipse([min(hy0, hy1), hz0, max(hy0, hy1), hz1], outline=(255, 180, 120), width=2)

            a = landmarks["arms"]["left"]
            ay0 = ox + coord_m_to_px_x(sgn * (a["center"][1] - a["radius_y_m"]))
            ay1 = ox + coord_m_to_px_x(sgn * (a["center"][1] + a["radius_y_m"]))
            az0 = oy + z_m_to_px_y(a["center"][2] + a["radius_z_m"])
            az1 = oy + z_m_to_px_y(a["center"][2] - a["radius_z_m"])
            draw.ellipse([min(ay0, ay1), az0, max(ay0, ay1), az1], outline=(140, 255, 120), width=2)

            ft = landmarks["feet"]["left"]
            fy0 = ox + coord_m_to_px_x(sgn * (ft["center"][1] - ft["radius_y_m"]))
            fy1 = ox + coord_m_to_px_x(sgn * (ft["center"][1] + ft["radius_y_m"]))
            fz0 = oy + z_m_to_px_y(ft["center"][2] + ft["radius_z_m"])
            fz1 = oy + z_m_to_px_y(ft["center"][2] - ft["radius_z_m"])
            draw.ellipse([min(fy0, fy1), fz0, max(fy0, fy1), fz1], outline=(120, 220, 255), width=2)

    fy = header_h + panel_h + 14
    draw.text((20, fy), "AUTHENTIC SAMPLED sRGB MATERIAL PALETTE:", fill=(220, 225, 235), font=font_med)
    swatch_w = 370
    for idx, (cname, cinfo) in enumerate(colors.items()):
        sx = 20 + idx * (swatch_w + 22)
        sy = fy + 26
        rgb = tuple(cinfo["srgb_255"])
        draw.rectangle([sx, sy, sx + 56, sy + 52], fill=rgb, outline=(230, 230, 235), width=2)
        draw.text((sx + 68, sy + 4), cname, fill=(245, 245, 250), font=font_med)
        draw.text((sx + 68, sy + 24), f"{cinfo['hex']}  RGB{tuple(cinfo['srgb_255'])}", fill=(175, 185, 200), font=font_sm)

    sheet.save(CALIB_IMG)
    return CALIB_IMG


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    if tracker_util:
        tracker_util.update_agent(
            "agent-1",
            status="RUNNING",
            progress=75,
            task="Refining landmark isolation, ear margin & authentic sRGB sampling",
            log="Refining connected-component arm/foot landmarks, neck pinch & closeup color sampling",
        )

    view_files = {
        "front": REF_DIR / "front_preview.png",
        "back": REF_DIR / "back.png",
        "left_side": REF_DIR / "left_side.png",
        "right_side": REF_DIR / "right_side.png",
    }
    ortho_out_names = {
        "front": REF_DIR / "ortho_front.png",
        "back": REF_DIR / "ortho_back.png",
        "left_side": REF_DIR / "ortho_left.png",
        "right_side": REF_DIR / "ortho_right.png",
    }

    views_rgb = {}
    masks_raw = {}
    submasks_raw = {}
    labs_raw = {}
    ortho_plates = {}
    ortho_masks = {}
    submasks_ortho = {}
    transforms = {}
    view_stats = {}

    for vname, fpath in view_files.items():
        im = Image.open(fpath).convert("RGB")
        arr = np.asarray(im, dtype=np.uint8)
        views_rgb[vname] = arr
        mask, subm, lab = segment_bunny(arr, vname)
        masks_raw[vname] = mask
        submasks_raw[vname] = subm
        labs_raw[vname] = lab

        ys, xs = np.where(mask)
        y_top, y_bot = int(ys.min()), int(ys.max())
        x_min, x_max = int(xs.min()), int(xs.max())
        cx_torso = compute_torso_center_x(mask, y_top, y_bot)

        plate, omask, tr = build_ortho_plate(arr, mask, vname, y_top, y_bot, cx_torso)
        plate.save(ortho_out_names[vname])
        ortho_plates[vname] = plate
        ortho_masks[vname] = omask
        transforms[vname] = tr
        submasks_ortho[vname] = {k: warp_submask_to_ortho(v, tr) for k, v in subm.items()}

        view_stats[vname] = {
            "source_file": str(fpath.relative_to(ROOT)),
            "ortho_file": str(ortho_out_names[vname].relative_to(ROOT)),
            "source_resolution": [int(arr.shape[1]), int(arr.shape[0])],
            "mask_area_ratio": round(float(mask.mean()), 4),
            "raw_bbox_px": [x_min, y_top, x_max, y_bot],
            "raw_aspect_w_over_h": round(float((x_max - x_min) / max(1, y_bot - y_top)), 4),
        }
        print(f"[{vname:10s}] bbox={view_stats[vname]['raw_bbox_px']} aspect={view_stats[vname]['raw_aspect_w_over_h']:.3f} area={view_stats[vname]['mask_area_ratio']:.3f}")

    slices = extract_24_slices(ortho_masks, submasks_ortho)
    landmarks = extract_landmarks(ortho_masks, submasks_ortho, slices)
    colors = sample_authentic_colors(views_rgb, submasks_raw, labs_raw)

    max_body_width_m = max(2.0 * s["body_half_width_m"] for s in slices)
    max_total_width_m = max(s["front_x_max_m"] - s["front_x_min_m"] for s in slices)
    max_depth_m = max(s["depth_m"] for s in slices)

    measurements = {
        "schema_version": "1.0",
        "subject": "Dumb Bunny (Vintage Rubber-Face Plush Doll)",
        "coordinate_system": {
            "units": "meters",
            "up": "+Z (bottom at Z=0.0, top at Z=0.180)",
            "front": "-Y",
            "back": "+Y",
            "bunny_right_viewer_left": "-X",
            "bunny_left_viewer_right": "+X",
        },
        "overall_dimensions": {
            "height_m": TARGET_HEIGHT_M,
            "height_mm": round(TARGET_HEIGHT_M * 1000.0, 2),
            "body_width_m": round(max_body_width_m, 5),
            "body_width_mm": round(max_body_width_m * 1000.0, 2),
            "total_width_with_ear_m": round(max_total_width_m, 5),
            "total_width_with_ear_mm": round(max_total_width_m * 1000.0, 2),
            "depth_m": round(max_depth_m, 5),
            "depth_mm": round(max_depth_m * 1000.0, 2),
        },
        "ortho_plates": {
            "resolution": [ORTHO_W, ORTHO_H],
            "px_per_m": ORTHO_PX_PER_M,
            "mm_per_px": round(1000.0 / ORTHO_PX_PER_M, 4),
            "bunny_top_px": ORTHO_TOP_PX,
            "bunny_bottom_px": ORTHO_BOT_PX,
            "center_x_px": ORTHO_W // 2,
            "plane_width_m": round(ORTHO_W / ORTHO_PX_PER_M, 5),
            "plane_height_m": round(ORTHO_H / ORTHO_PX_PER_M, 5),
            "plane_z_min_m": round((ORTHO_BOT_PX - ORTHO_H) / ORTHO_PX_PER_M, 5),
            "plane_z_max_m": round(ORTHO_BOT_PX / ORTHO_PX_PER_M, 5),
            "plane_center_z_m": round(0.5 * ((ORTHO_BOT_PX - ORTHO_H) + ORTHO_BOT_PX) / ORTHO_PX_PER_M, 5),
            "files": {
                "front": "work/ref_images/ortho_front.png",
                "back": "work/ref_images/ortho_back.png",
                "left": "work/ref_images/ortho_left.png",
                "right": "work/ref_images/ortho_right.png",
            },
            "orientation_notes": {
                "ortho_front.png": "Viewed from -Y looking +Y; image left = -X (bunny right), image right = +X (bunny left)",
                "ortho_back.png": "Viewed from +Y looking -Y; image left = +X (bunny left), image right = -X (bunny right)",
                "ortho_left.png": "Viewed from +X looking -X; bunny faces image LEFT (-Y), back is image RIGHT (+Y)",
                "ortho_right.png": "Viewed from -X looking +X; bunny faces image RIGHT (-Y), back is image LEFT (+Y)",
            },
        },
        "slices_24": slices,
        "landmarks": landmarks,
        "colors": colors,
        "views_metadata": view_stats,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(measurements, f, indent=2)

    render_calibration_sheet(ortho_plates, ortho_masks, views_rgb, transforms, landmarks, slices, colors)
    print(f"Saved {OUT_JSON} and {CALIB_IMG}")
    print(f"Overall dims (mm): H={measurements['overall_dimensions']['height_mm']} | Body W={measurements['overall_dimensions']['body_width_mm']} (w/ ear={measurements['overall_dimensions']['total_width_with_ear_mm']}) | D={measurements['overall_dimensions']['depth_mm']}")
    print(f"Neck Z={landmarks['neck_pinch']['z_m']*1000:.1f}mm | Arm L={landmarks['arms']['left']['center']} r=({landmarks['arms']['left']['radius_x_m']:.4f},{landmarks['arms']['left']['radius_y_m']:.4f},{landmarks['arms']['left']['radius_z_m']:.4f})")
    print(f"Foot L={landmarks['feet']['left']['center']} r=({landmarks['feet']['left']['radius_x_m']:.4f},{landmarks['feet']['left']['radius_y_m']:.4f},{landmarks['feet']['left']['radius_z_m']:.4f}) | Ear len={landmarks['ears']['length_m']*1000:.1f}mm w={landmarks['ears']['width_m']*1000:.1f}mm")
    for ck, cv in colors.items():
        print(f"  color {ck:20s}: {cv['hex']} {cv['srgb_255']}")


if __name__ == "__main__":
    main()
