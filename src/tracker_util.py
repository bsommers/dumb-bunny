#!/usr/bin/env python3
"""Helper utility for updating the live web tracker state atomically."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
STATE_PATH = ROOT / "work" / "tracker_state.json"


def load_state():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_PATH)


def now_hms():
    return datetime.now().strftime("%H:%M:%S")


def update_agent(agent_id, status=None, progress=None, task=None, log=None, metrics=None):
    state = load_state()
    for a in state["agents"]:
        if a["id"] == agent_id:
            if status is not None:
                a["status"] = status
            if progress is not None:
                a["progress"] = progress
            if task is not None:
                a["current_task"] = task
            if log:
                a["logs"].append(f"[{now_hms()}] {log}")
                a["logs"] = a["logs"][-20:]
            if metrics:
                a["metrics"].update(metrics)
            break
    if log:
        state["events"].append({"time": now_hms(), "source": agent_id.upper(), "msg": log})
        state["events"] = state["events"][-50:]
    save_state(state)


def update_stage(stage_id, status, overall_progress=None, current_stage=None, event_msg=None):
    state = load_state()
    for s in state["pipeline_stages"]:
        if s["id"] == stage_id:
            s["status"] = status
            break
    if overall_progress is not None:
        state["overall_progress"] = overall_progress
    if current_stage is not None:
        state["current_stage"] = current_stage
    if event_msg:
        state["events"].append({"time": now_hms(), "source": "PIPELINE", "msg": event_msg})
        state["events"] = state["events"][-50:]
    save_state(state)


def update_blender(connected=None, status=None, stage=None, latest_render=None, render_label=None):
    state = load_state()
    bl = state["blender_live"]
    if connected is not None:
        bl["connected"] = connected
    if status is not None:
        bl["status"] = status
    if stage is not None:
        bl["stage"] = stage
    if latest_render is not None:
        bl["latest_render"] = latest_render
        entry = {"url": latest_render, "label": render_label or stage or "Live Capture", "time": now_hms()}
        bl["renders"] = [r for r in bl["renders"] if r["url"] != latest_render] + [entry]
        bl["renders"] = bl["renders"][-12:]
    save_state(state)


if __name__ == "__main__":
    # CLI usage: tracker_util.py event SOURCE MESSAGE
    if len(sys.argv) >= 4 and sys.argv[1] == "event":
        st = load_state()
        st["events"].append({"time": now_hms(), "source": sys.argv[2], "msg": " ".join(sys.argv[3:])})
        st["events"] = st["events"][-50:]
        save_state(st)
