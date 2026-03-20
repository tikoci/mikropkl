#!/usr/bin/env python3
"""
qga-file-test.py — Detailed test of guest-file-* operations on RouterOS CHR

Tests various file path formats and file operation workflows.
Must be run against a QGA-enabled QEMU instance.

Usage:
    python3 qga-file-test.py /tmp/qga-chr.x86_64.qemu.7.22.sock
"""

import base64
import json
import sys
import os

# Import from sibling module
sys.path.insert(0, os.path.dirname(__file__))
from importlib.machinery import SourceFileLoader
qga_mod = SourceFileLoader("qga_test", os.path.join(os.path.dirname(__file__), "qga-test.py")).load_module()
QGAClient = qga_mod.QGAClient
QGAError = qga_mod.QGAError


def test_path_format(client, path, mode="w"):
    """Test if a specific path format is accepted by guest-file-open."""
    try:
        resp = client.send_command("guest-file-open", {
            "path": path,
            "mode": mode,
        })
        if "return" in resp:
            handle = resp["return"]
            # Close immediately
            try:
                client.send_command("guest-file-close", {"handle": handle})
            except QGAError:
                pass
            return {"path": path, "accepted": True, "handle": handle}
        elif "error" in resp:
            return {"path": path, "accepted": False,
                    "error": resp["error"].get("desc", str(resp["error"]))}
    except QGAError as e:
        return {"path": path, "accepted": False, "error": str(e)}
    return {"path": path, "accepted": False, "error": "unknown"}


def test_file_roundtrip(client, path, data):
    """Write data to a file and read it back."""
    result = {"path": path, "write_data": data}

    # Open for writing
    try:
        resp = client.send_command("guest-file-open", {
            "path": path, "mode": "w"
        })
        if "error" in resp:
            result["open_write"] = False
            result["open_write_error"] = resp["error"].get("desc", "")
            return result
        handle = resp["return"]
        result["open_write"] = True
    except QGAError as e:
        result["open_write"] = False
        result["open_write_error"] = str(e)
        return result

    # Write
    encoded = base64.b64encode(data.encode("utf-8")).decode("ascii")
    try:
        resp = client.send_command("guest-file-write", {
            "handle": handle,
            "buf-b64": encoded,
        })
        if "return" in resp:
            result["write"] = True
            result["write_count"] = resp["return"].get("count")
        else:
            result["write"] = False
            result["write_error"] = resp.get("error", {}).get("desc", "")
    except QGAError as e:
        result["write"] = False
        result["write_error"] = str(e)

    # Flush
    try:
        resp = client.send_command("guest-file-flush", {"handle": handle})
        result["flush"] = "error" not in resp
    except QGAError:
        result["flush"] = False

    # Close write handle
    try:
        client.send_command("guest-file-close", {"handle": handle})
        result["close_write"] = True
    except QGAError:
        result["close_write"] = False

    # Open for reading
    try:
        resp = client.send_command("guest-file-open", {
            "path": path, "mode": "r"
        })
        if "error" in resp:
            result["open_read"] = False
            result["open_read_error"] = resp["error"].get("desc", "")
            return result
        handle = resp["return"]
        result["open_read"] = True
    except QGAError as e:
        result["open_read"] = False
        result["open_read_error"] = str(e)
        return result

    # Read
    try:
        resp = client.send_command("guest-file-read", {
            "handle": handle,
            "count": 65536,
        })
        if "return" in resp and "buf-b64" in resp["return"]:
            read_data = base64.b64decode(
                resp["return"]["buf-b64"]).decode("utf-8", errors="replace")
            result["read"] = True
            result["read_data"] = read_data
            result["roundtrip_ok"] = (read_data == data)
        else:
            result["read"] = False
            result["read_error"] = resp.get("error", {}).get("desc", "")
    except QGAError as e:
        result["read"] = False
        result["read_error"] = str(e)

    # Seek test (rewind to beginning and read again)
    try:
        resp = client.send_command("guest-file-seek", {
            "handle": handle,
            "offset": 0,
            "whence": 0,  # SEEK_SET
        })
        result["seek"] = "error" not in resp
        if result["seek"]:
            resp2 = client.send_command("guest-file-read", {
                "handle": handle, "count": 65536,
            })
            if "return" in resp2 and "buf-b64" in resp2["return"]:
                seek_data = base64.b64decode(
                    resp2["return"]["buf-b64"]).decode("utf-8", errors="replace")
                result["seek_reread_ok"] = (seek_data == data)
    except QGAError:
        result["seek"] = False

    # Close read handle
    try:
        client.send_command("guest-file-close", {"handle": handle})
        result["close_read"] = True
    except QGAError:
        result["close_read"] = False

    return result


def test_guest_exec_file_check(client, filename):
    """Use guest-exec to verify the file exists in RouterOS filesystem."""
    script = f':put [/file get "{filename}" contents]'
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")

    try:
        resp = client.send_command("guest-exec", {
            "input-data": encoded,
            "capture-output": True,
        })
        if "return" in resp:
            pid = resp["return"].get("pid")
            if pid is not None:
                import time
                for _ in range(20):
                    status = client.send_command("guest-exec-status", {"pid": pid})
                    if "return" in status and status["return"].get("exited"):
                        sr = status["return"]
                        stdout = ""
                        if "out-data" in sr:
                            stdout = base64.b64decode(
                                sr["out-data"]).decode("utf-8", errors="replace")
                        return {
                            "verified_via_exec": True,
                            "exitcode": sr.get("exitcode"),
                            "contents": stdout.strip(),
                        }
                    time.sleep(0.5)
    except QGAError as e:
        return {"verified_via_exec": False, "error": str(e)}
    return {"verified_via_exec": False, "error": "timeout"}


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <qga-socket>")
        sys.exit(1)

    socket_path = sys.argv[1]

    with QGAClient(socket_path, timeout=10) as client:
        client.sync()

        print("=" * 60)
        print("QGA File Operations Test — MikroTik RouterOS CHR")
        print(f"Socket: {socket_path}")
        print("=" * 60)
        print()

        # ── Test 1: Path format acceptance ──
        print("── Test 1: Path format acceptance ──")
        path_tests = [
            "/tmp/test.txt",           # Unix absolute path
            "/etc/test.txt",           # Unix system path
            "test-qga.txt",            # Simple filename (RouterOS root)
            "disk1/test-qga.txt",      # RouterOS disk1 path
            "flash/test-qga.txt",      # RouterOS flash path
            "./test-qga.txt",          # Relative with dot
            "test-dir/test-qga.txt",   # Subdirectory
            "test qga.txt",            # Space in name
            "qga-test-123.rsc",        # .rsc extension (RouterOS script)
        ]

        for path in path_tests:
            result = test_path_format(client, path)
            status = "✓ ACCEPTED" if result["accepted"] else f"✗ REJECTED: {result.get('error', '')}"
            print(f"  {status:45s}  path={path!r}")

        print()

        # ── Test 2: File roundtrip ──
        print("── Test 2: File write/read roundtrip ──")
        roundtrip = test_file_roundtrip(client, "qga-test-roundtrip.txt",
                                        "Hello from QEMU Guest Agent!\nLine 2\n")
        for key, val in roundtrip.items():
            print(f"  {key}: {val!r}")

        print()

        # ── Test 3: Verify file via guest-exec ──
        print("── Test 3: Verify file via guest-exec ──")
        if roundtrip.get("write"):
            verify = test_guest_exec_file_check(client, "qga-test-roundtrip.txt")
            for key, val in verify.items():
                print(f"  {key}: {val!r}")
        else:
            print("  (skipped — file write failed)")

        print()

        # ── Test 4: RouterOS script file ──
        print("── Test 4: Write and execute RouterOS script via file API ──")
        script_content = ':put "executed-via-file-api"'
        script_write = test_file_roundtrip(client, "qga-test-script.rsc",
                                           script_content)
        print(f"  write: {script_write.get('write')}")
        print(f"  roundtrip_ok: {script_write.get('roundtrip_ok')}")

        # Now try to execute the written script via guest-exec
        if script_write.get("write"):
            exec_script = '/import qga-test-script.rsc'
            encoded = base64.b64encode(exec_script.encode("utf-8")).decode("ascii")
            try:
                resp = client.send_command("guest-exec", {
                    "input-data": encoded,
                    "capture-output": True,
                })
                if "return" in resp:
                    pid = resp["return"].get("pid")
                    import time
                    if pid is not None:
                        for _ in range(20):
                            status = client.send_command("guest-exec-status", {"pid": pid})
                            if "return" in status and status["return"].get("exited"):
                                sr = status["return"]
                                stdout = ""
                                if "out-data" in sr:
                                    stdout = base64.b64decode(
                                        sr["out-data"]).decode("utf-8", errors="replace")
                                print(f"  exec stdout: {stdout.strip()!r}")
                                print(f"  exec exitcode: {sr.get('exitcode')}")
                                break
                            time.sleep(0.5)
            except QGAError as e:
                print(f"  exec error: {e}")

        print()

        # ── Test 5: guest-exec useful RouterOS commands ──
        print("── Test 5: guest-exec with various RouterOS scripts ──")
        scripts = [
            (":put [/system identity get name]", "system identity"),
            (":put [/system resource get version]", "RouterOS version"),
            (":put [/system resource get uptime]", "uptime"),
            (":put [/system resource get architecture-name]", "architecture"),
            (":put [/system resource get cpu-count]", "CPU count"),
            (":put [/system resource get total-memory]", "total memory"),
            (":put [/system resource get free-memory]", "free memory"),
            (":put [/system routerboard get serial-number]", "serial number"),
            ("/ip address print terse", "IP addresses"),
            ("/interface print terse", "interfaces"),
            (":put [/system license get level]", "license level"),
        ]

        for script, desc in scripts:
            encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
            try:
                resp = client.send_command("guest-exec", {
                    "input-data": encoded,
                    "capture-output": True,
                })
                if "return" in resp:
                    pid = resp["return"].get("pid")
                    import time
                    if pid is not None:
                        for _ in range(20):
                            status = client.send_command("guest-exec-status", {"pid": pid})
                            if "return" in status and status["return"].get("exited"):
                                sr = status["return"]
                                stdout = ""
                                if "out-data" in sr:
                                    stdout = base64.b64decode(
                                        sr["out-data"]).decode("utf-8", errors="replace")
                                stderr = ""
                                if "err-data" in sr:
                                    stderr = base64.b64decode(
                                        sr["err-data"]).decode("utf-8", errors="replace")
                                exitcode = sr.get("exitcode", "?")
                                output = stdout.strip() or stderr.strip() or "(empty)"
                                print(f"  {desc:25s}  exit={exitcode}  → {output}")
                                break
                            time.sleep(0.5)
                        else:
                            print(f"  {desc:25s}  (timeout)")
                elif "error" in resp:
                    print(f"  {desc:25s}  ERROR: {resp['error'].get('desc', '')}")
            except QGAError as e:
                print(f"  {desc:25s}  QGA ERROR: {e}")

        print()
        print("Done.")


if __name__ == "__main__":
    main()
