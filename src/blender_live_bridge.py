#!/usr/bin/env python3
"""
Blender 5.0 Live GUI Bridge for Operation Dumb Bunny.

Runs inside an interactive (non-headless!) Blender GUI session.
- Configures a clean studio-lit 3D Viewport so the user watches Dumb Bunny being
  assembled and sculpted live in real time.
- Registers a bpy.app.timers poller watching work/blender_ipc/inbox/*.json.
- Executes queued Python scripts/expressions on the live GUI main thread, redraws
  the viewport, optionally smoothly orbits the live viewport camera, and captures
  live viewport snapshots directly into tracker/live_renders/.
"""
import json
import math
import os
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Euler, Vector

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
INBOX = ROOT / "work" / "blender_ipc" / "inbox"
OUTBOX = ROOT / "work" / "blender_ipc" / "outbox"
RENDERS = ROOT / "tracker" / "live_renders"
STATE_PATH = ROOT / "work" / "tracker_state.json"

INBOX.mkdir(parents=True, exist_ok=True)
OUTBOX.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Global animation state for smooth live turntable showcase
ORBIT_STATE = {
    "enabled": True,
    "angle": math.radians(-22.0),
    "speed": math.radians(1.6),
    "distance": 0.42,
    "target": Vector((0.0, 0.0, 0.095)),
    "elevation": math.radians(74.0),
}


def update_tracker_blender(connected=True, status="LIVE GUI CONNECTED", stage=None, render_url=None, render_label=None):
    try:
        from tracker_util import update_blender
        update_blender(
            connected=connected,
            status=status,
            stage=stage,
            latest_render=render_url,
            render_label=render_label,
        )
    except Exception:
        pass


def get_view3d_area():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == "VIEW_3D":
                return win, area
    return None, None


def setup_live_viewport():
    # Clean default scene (keep camera & lights, remove default cube)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0

    # Render engine setup (EEVEE Next / Workbench fast live renders)
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        try:
            scene.render.engine = eng
            break
        except Exception:
            continue

    scene.render.resolution_x = 1280
    scene.render.resolution_y = 800
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"

    # Dark studio world background
    if scene.world is None:
        scene.world = bpy.data.worlds.new("BionicStudioWorld")
    scene.world.use_nodes = True
    nt = scene.world.node_tree
    bg = nt.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.025, 0.038, 0.068, 1.0)
        bg.inputs[1].default_value = 0.75

    # Studio 3-point lighting
    def add_light(name, ltype, loc, rot_deg, energy, color, size=0.45):
        ld = bpy.data.lights.new(name=name, type=ltype)
        ld.energy = energy
        ld.color = color
        if ltype == "AREA":
            ld.size = size
        obj = bpy.data.objects.new(name=name, object_data=ld)
        scene.collection.objects.link(obj)
        obj.location = loc
        obj.rotation_euler = tuple(math.radians(a) for a in rot_deg)
        return obj

    add_light("KeyLight", "AREA", (0.28, -0.35, 0.34), (58, 0, 38), 18.0, (1.0, 0.96, 0.92), 0.38)
    add_light("FillLight", "AREA", (-0.32, -0.25, 0.22), (68, 0, -50), 9.0, (0.78, 0.90, 1.0), 0.45)
    add_light("RimLight", "AREA", (0.05, 0.36, 0.28), (62, 0, 172), 14.0, (0.45, 0.85, 1.0), 0.35)

    # Studio camera
    cam_data = bpy.data.cameras.new("LiveStudioCamera")
    cam_data.lens = 55.0
    cam_data.clip_start = 0.005
    cam_data.clip_end = 50.0
    cam_obj = bpy.data.objects.new("LiveStudioCamera", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj
    position_studio_camera(angle_deg=-22.0, elev_deg=14.0, dist=0.38, target=(0.0, 0.0, 0.09))

    # Configure live 3D viewport shading to Material Preview + Cavity for crisp live viewing
    win, area = get_view3d_area()
    if area:
        space = area.spaces.active
        space.shading.type = "MATERIAL"
        space.shading.use_scene_lights = True
        space.shading.use_scene_world = False
        space.shading.studio_light = "studio.exr"
        space.clip_start = 0.005
        space.overlay.show_floor = True
        space.overlay.show_axis_x = True
        space.overlay.show_axis_y = True
        r3d = space.region_3d
        r3d.view_perspective = "PERSP"
        r3d.view_location = ORBIT_STATE["target"].copy()
        r3d.view_distance = ORBIT_STATE["distance"]
        r3d.view_rotation = Euler((ORBIT_STATE["elevation"], 0.0, ORBIT_STATE["angle"]), "XYZ").to_quaternion()

    update_tracker_blender(
        connected=True,
        status="LIVE GUI CONNECTED",
        stage="Studio Viewport Initialized — Ready for 4-View Rig & Sculpting",
    )


def position_studio_camera(angle_deg=-22.0, elev_deg=14.0, dist=0.38, target=(0.0, 0.0, 0.09)):
    cam = bpy.data.objects.get("LiveStudioCamera")
    if not cam:
        return
    az = math.radians(angle_deg)
    el = math.radians(elev_deg)
    tx, ty, tz = target
    x = tx + dist * math.cos(el) * math.sin(az)
    y = ty - dist * math.cos(el) * math.cos(az)
    z = tz + dist * math.sin(el)
    cam.location = (x, y, z)
    direction = Vector(target) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def set_viewport_camera(angle_deg=-22.0, elev_deg=74.0, dist=0.38, target=(0.0, 0.0, 0.09), orbit=None):
    ORBIT_STATE["angle"] = math.radians(angle_deg)
    ORBIT_STATE["elevation"] = math.radians(elev_deg)
    ORBIT_STATE["distance"] = dist
    ORBIT_STATE["target"] = Vector(target)
    if orbit is not None:
        ORBIT_STATE["enabled"] = bool(orbit)
    win, area = get_view3d_area()
    if area:
        r3d = area.spaces.active.region_3d
        r3d.view_location = ORBIT_STATE["target"].copy()
        r3d.view_distance = ORBIT_STATE["distance"]
        r3d.view_rotation = Euler((ORBIT_STATE["elevation"], 0.0, ORBIT_STATE["angle"]), "XYZ").to_quaternion()
        area.tag_redraw()


def capture_live_snapshot(filename: str, label: str, angle_deg=-20.0, elev_deg=12.0, dist=0.36, target=(0.0, 0.0, 0.09)):
    """Capture a crisp render from the live studio camera and publish to web tracker."""
    out_path = RENDERS / filename
    position_studio_camera(angle_deg=angle_deg, elev_deg=elev_deg, dist=dist, target=target)
    scene = bpy.context.scene
    scene.render.filepath = str(out_path)
    try:
        bpy.ops.render.render(write_still=True)
    except Exception:
        # Fallback to viewport OpenGL render if needed
        win, area = get_view3d_area()
        if win and area:
            with bpy.context.temp_override(window=win, area=area):
                bpy.ops.render.opengl(write_still=True)
    rel_url = f"/tracker/live_renders/{filename}"
    update_tracker_blender(
        connected=True,
        status="LIVE GUI ACTIVE",
        stage=label,
        render_url=rel_url,
        render_label=label,
    )
    return str(out_path)


def process_inbox_timer():
    # Gentle live turntable orbit so user can visually watch the model rotate live!
    if ORBIT_STATE["enabled"]:
        win, area = get_view3d_area()
        if area:
            ORBIT_STATE["angle"] += ORBIT_STATE["speed"]
            r3d = area.spaces.active.region_3d
            r3d.view_location = ORBIT_STATE["target"].copy()
            r3d.view_distance = ORBIT_STATE["distance"]
            r3d.view_rotation = Euler((ORBIT_STATE["elevation"], 0.0, ORBIT_STATE["angle"]), "XYZ").to_quaternion()
            area.tag_redraw()

    # Check for incoming IPC commands
    files = sorted(INBOX.glob("*.json"))
    if files:
        cmd_file = files[0]
        cmd_id = cmd_file.stem
        result = {"id": cmd_id, "ok": True, "output": "", "error": None}
        try:
            payload = json.loads(cmd_file.read_text(encoding="utf-8"))
            cmd_file.unlink(missing_ok=True)
            action = payload.get("action", "exec_file")
            ns = {
                "bpy": bpy,
                "ROOT": ROOT,
                "capture_live_snapshot": capture_live_snapshot,
                "set_viewport_camera": set_viewport_camera,
                "position_studio_camera": position_studio_camera,
                "ORBIT_STATE": ORBIT_STATE,
                "update_tracker_blender": update_tracker_blender,
            }
            if action == "exec_file":
                script_path = Path(payload["script"])
                code = script_path.read_text(encoding="utf-8")
                exec(compile(code, str(script_path), "exec"), ns)
                result["output"] = f"Executed {script_path.name}"
            elif action == "exec_code":
                exec(compile(payload["code"], "<ipc>", "exec"), ns)
                result["output"] = "Executed inline code"
            elif action == "snapshot":
                p = capture_live_snapshot(
                    payload["filename"],
                    payload.get("label", "Live Capture"),
                    angle_deg=payload.get("angle_deg", -20.0),
                    elev_deg=payload.get("elev_deg", 12.0),
                    dist=payload.get("dist", 0.36),
                    target=tuple(payload.get("target", [0.0, 0.0, 0.09])),
                )
                result["output"] = p
            elif action == "ping":
                result["output"] = "pong"

            # Force live GUI redraw immediately so the user sees every step
            win, area = get_view3d_area()
            if area:
                area.tag_redraw()
            try:
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            except Exception:
                pass
        except Exception as exc:
            result["ok"] = False
            result["error"] = traceback.format_exc()
            print(f"[LiveBridge ERROR] {exc}\n{result['error']}", flush=True)

        out_file = OUTBOX / f"{cmd_id}.json"
        tmp = out_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        os.replace(tmp, out_file)

    return 0.15


def bootstrap():
    setup_live_viewport()
    bpy.app.timers.register(process_inbox_timer, first_interval=0.25, persistent=True)
    # Write ready beacon
    (OUTBOX / "bridge_ready.json").write_text(
        json.dumps({"ready": True, "blender": bpy.app.version_string}), encoding="utf-8"
    )
    print("[LiveBridge] Ready and polling work/blender_ipc/inbox/", flush=True)
    return None


bpy.app.timers.register(bootstrap, first_interval=0.6)
