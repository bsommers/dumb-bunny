#!/usr/bin/env python3
"""IPC client to drive the live Blender GUI bridge."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny")
INBOX = ROOT / "work" / "blender_ipc" / "inbox"
OUTBOX = ROOT / "work" / "blender_ipc" / "outbox"


def wait_for_bridge(timeout=45.0):
    ready = OUTBOX / "bridge_ready.json"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if ready.exists():
            return json.loads(ready.read_text(encoding="utf-8"))
        time.sleep(0.3)
    raise TimeoutError("Timed out waiting for Blender Live Bridge to become ready.")


def send_cmd(payload: dict, timeout: float = 120.0) -> dict:
    INBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    cmd_id = f"{int(time.time() * 1000)}_{os.getpid()}"
    in_file = INBOX / f"{cmd_id}.json"
    tmp = in_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, in_file)

    out_file = OUTBOX / f"{cmd_id}.json"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if out_file.exists():
            data = json.loads(out_file.read_text(encoding="utf-8"))
            out_file.unlink(missing_ok=True)
            if not data.get("ok"):
                raise RuntimeError(f"Blender Live Bridge command failed:\n{data.get('error')}")
            return data
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for Blender IPC response for {cmd_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: blender_ipc_client.py <script.py> | --ping | --wait")
        sys.exit(1)
    arg = sys.argv[1]
    if arg == "--wait":
        print(wait_for_bridge())
    elif arg == "--ping":
        print(send_cmd({"action": "ping"}))
    else:
        print(send_cmd({"action": "exec_file", "script": str(Path(arg).resolve())}))
