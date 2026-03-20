#!/usr/bin/env python3
"""
qga-test.py — QEMU Guest Agent (QGA) test tool for MikroTik RouterOS CHR

Tests all documented QGA commands against a running RouterOS CHR instance
and records which ones are supported, their responses, and any errors.

Usage:
    ./qga-test.py /tmp/qga-<machine>.sock
    ./qga-test.py /tmp/qga-<machine>.sock --command guest-info
    ./qga-test.py /tmp/qga-<machine>.sock --all
    ./qga-test.py /tmp/qga-<machine>.sock --json          # machine-readable output
    ./qga-test.py /tmp/qga-<machine>.sock --exec ":put [/system identity get name]"

Protocol: QEMU Guest Agent JSON-RPC over virtio-serial Unix socket.
Messages are newline-delimited JSON. The guest agent may send a sync
marker (0xFF) which we strip before parsing.

Reference: https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR
"""

import argparse
import base64
import json
import os
import socket
import sys
import time


class QGAError(Exception):
    """Error communicating with the QEMU Guest Agent."""
    pass


class QGAClient:
    """Low-level QEMU Guest Agent client over a Unix socket."""

    def __init__(self, socket_path, timeout=10):
        self.socket_path = socket_path
        self.timeout = timeout
        self.sock = None

    def connect(self):
        if not os.path.exists(self.socket_path):
            raise QGAError(f"Socket not found: {self.socket_path}")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        try:
            self.sock.connect(self.socket_path)
        except (ConnectionRefusedError, OSError) as e:
            raise QGAError(f"Connection failed: {e}")

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def send_command(self, execute, arguments=None):
        """Send a QGA command and return the parsed response."""
        msg = {"execute": execute}
        if arguments:
            msg["arguments"] = arguments

        payload = json.dumps(msg) + "\n"
        try:
            self.sock.sendall(payload.encode("utf-8"))
        except (BrokenPipeError, OSError) as e:
            raise QGAError(f"Send failed: {e}")

        return self._read_response()

    def _read_response(self):
        """Read and parse a QGA JSON response, stripping any sync markers."""
        buf = b""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.sock.settimeout(min(remaining, 2.0))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError as e:
                raise QGAError(f"Read failed: {e}")
            if not chunk:
                raise QGAError("Connection closed by guest agent")
            buf += chunk

            # Strip QGA sync marker bytes (0xFF)
            cleaned = buf.replace(b"\xff", b"")

            # Try to parse complete JSON lines
            for line in cleaned.split(b"\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        raise QGAError(f"Timeout waiting for response (buf={buf!r})")

    def sync(self, sync_id=None):
        """Send a guest-sync-delimited to establish communication.

        This is required before first use to flush any stale data in the
        virtio-serial buffer. The guest agent echoes back the sync_id."""
        if sync_id is None:
            sync_id = int(time.time()) & 0x7FFFFFFF
        try:
            resp = self.send_command("guest-sync-delimited",
                                     {"id": sync_id})
            return resp
        except QGAError:
            # Retry once — first sync often fails if buffer has stale data
            time.sleep(0.5)
            return self.send_command("guest-sync-delimited",
                                     {"id": sync_id})


# ─── Test functions for each QGA command ───

def test_guest_sync(client):
    """Test guest-sync-delimited (required handshake)."""
    sync_id = 12345
    resp = client.sync(sync_id)
    return {
        "command": "guest-sync-delimited",
        "supported": True,
        "response": resp,
        "notes": f"Sync ID sent: {sync_id}"
    }


def test_guest_info(client):
    """Test guest-info — lists supported commands."""
    resp = client.send_command("guest-info")
    if "return" in resp:
        info = resp["return"]
        commands = [c["name"] for c in info.get("supported_commands", [])]
        return {
            "command": "guest-info",
            "supported": True,
            "response": resp,
            "agent_version": info.get("version", "unknown"),
            "supported_commands": sorted(commands),
            "command_count": len(commands),
        }
    return {
        "command": "guest-info",
        "supported": "error" not in resp,
        "response": resp,
    }


def test_guest_network_get_interfaces(client):
    """Test guest-network-get-interfaces — returns guest NIC info."""
    resp = client.send_command("guest-network-get-interfaces")
    if "return" in resp:
        ifaces = resp["return"]
        summary = []
        for iface in ifaces:
            entry = {"name": iface.get("name", "?")}
            if "hardware-address" in iface:
                entry["mac"] = iface["hardware-address"]
            ips = iface.get("ip-addresses", [])
            entry["ips"] = [f"{ip['ip-address']}/{ip['prefix']}"
                           for ip in ips]
            summary.append(entry)
        return {
            "command": "guest-network-get-interfaces",
            "supported": True,
            "response": resp,
            "interfaces": summary,
        }
    return {
        "command": "guest-network-get-interfaces",
        "supported": "error" not in resp,
        "response": resp,
    }


def test_guest_exec(client, script=None):
    """Test guest-exec — execute a RouterOS script in the guest.

    If no script is provided, uses ':put "qga-test-ok"' as a simple probe.
    """
    if script is None:
        script = ':put "qga-test-ok"'

    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")

    resp = client.send_command("guest-exec", {
        "input-data": encoded,
        "capture-output": True,
    })

    if "return" in resp:
        pid = resp["return"].get("pid")
        result = {
            "command": "guest-exec",
            "supported": True,
            "pid": pid,
            "script": script,
            "exec_response": resp,
        }

        # Poll for completion
        if pid is not None:
            status = poll_exec_status(client, pid)
            result["status_response"] = status
            if status and "return" in status:
                sr = status["return"]
                result["exited"] = sr.get("exited", False)
                result["exitcode"] = sr.get("exitcode")
                if "out-data" in sr:
                    try:
                        result["stdout"] = base64.b64decode(
                            sr["out-data"]).decode("utf-8", errors="replace")
                    except Exception:
                        result["stdout_raw"] = sr["out-data"]
                if "err-data" in sr:
                    try:
                        result["stderr"] = base64.b64decode(
                            sr["err-data"]).decode("utf-8", errors="replace")
                    except Exception:
                        result["stderr_raw"] = sr["err-data"]
        return result

    return {
        "command": "guest-exec",
        "supported": "error" not in resp,
        "response": resp,
        "script": script,
    }


def test_guest_exec_with_path(client):
    """Test guest-exec using 'path' field instead of 'input-data'.

    Try to execute a known RouterOS path. This tests whether 'path'
    execution works differently from 'input-data' scripting.
    """
    resp = client.send_command("guest-exec", {
        "path": "/system/script",
        "arg": ["print"],
        "capture-output": True,
    })

    result = {
        "command": "guest-exec (path mode)",
        "supported": "error" not in resp,
        "response": resp,
        "notes": "Tested with path=/system/script, arg=[print]",
    }

    if "return" in resp:
        result["supported"] = True
        pid = resp["return"].get("pid")
        result["pid"] = pid
        if pid is not None:
            status = poll_exec_status(client, pid)
            result["status_response"] = status
            if status and "return" in status:
                sr = status["return"]
                result["exited"] = sr.get("exited", False)
                result["exitcode"] = sr.get("exitcode")
                if "out-data" in sr:
                    try:
                        result["stdout"] = base64.b64decode(
                            sr["out-data"]).decode("utf-8", errors="replace")
                    except Exception:
                        result["stdout_raw"] = sr["out-data"]

    return result


def poll_exec_status(client, pid, max_polls=20, interval=0.5):
    """Poll guest-exec-status until the process exits or we give up."""
    for _ in range(max_polls):
        try:
            resp = client.send_command("guest-exec-status",
                                       {"pid": pid})
            if "return" in resp and resp["return"].get("exited"):
                return resp
            if "error" in resp:
                return resp
        except QGAError:
            pass
        time.sleep(interval)
    return {"error": "timeout", "pid": pid}


def test_guest_file_ops(client):
    """Test guest-file-* operations — open, write, read, close.

    Attempts to write a small test file in RouterOS, read it back, and
    clean up. This tests the file transfer capability.
    """
    results = {}
    test_path = "qga-test-file.txt"
    test_data = "qga-file-test-ok\n"
    handle = None

    # Open for writing
    try:
        resp = client.send_command("guest-file-open", {
            "path": test_path,
            "mode": "w",
        })
        results["file-open-write"] = {
            "supported": "return" in resp,
            "response": resp,
        }
        if "return" in resp:
            handle = resp["return"]
    except QGAError as e:
        results["file-open-write"] = {"supported": False, "error": str(e)}

    # Write
    if handle is not None:
        try:
            encoded = base64.b64encode(test_data.encode()).decode("ascii")
            resp = client.send_command("guest-file-write", {
                "handle": handle,
                "buf-b64": encoded,
            })
            results["file-write"] = {
                "supported": "return" in resp,
                "response": resp,
            }
        except QGAError as e:
            results["file-write"] = {"supported": False, "error": str(e)}

        # Close write handle
        try:
            resp = client.send_command("guest-file-close", {
                "handle": handle,
            })
            results["file-close-write"] = {
                "supported": "error" not in resp,
                "response": resp,
            }
        except QGAError as e:
            results["file-close-write"] = {"supported": False, "error": str(e)}
        handle = None

    # Open for reading
    try:
        resp = client.send_command("guest-file-open", {
            "path": test_path,
            "mode": "r",
        })
        results["file-open-read"] = {
            "supported": "return" in resp,
            "response": resp,
        }
        if "return" in resp:
            handle = resp["return"]
    except QGAError as e:
        results["file-open-read"] = {"supported": False, "error": str(e)}

    # Read
    if handle is not None:
        try:
            resp = client.send_command("guest-file-read", {
                "handle": handle,
                "count": 4096,
            })
            results["file-read"] = {
                "supported": "return" in resp,
                "response": resp,
            }
            if "return" in resp and "buf-b64" in resp["return"]:
                try:
                    data = base64.b64decode(
                        resp["return"]["buf-b64"]).decode("utf-8",
                                                          errors="replace")
                    results["file-read"]["content"] = data
                    results["file-read"]["roundtrip_ok"] = (data == test_data)
                except Exception:
                    pass
        except QGAError as e:
            results["file-read"] = {"supported": False, "error": str(e)}

        # Close read handle
        try:
            resp = client.send_command("guest-file-close", {
                "handle": handle,
            })
            results["file-close-read"] = {
                "supported": "error" not in resp,
                "response": resp,
            }
        except QGAError as e:
            results["file-close-read"] = {"supported": False, "error": str(e)}

    # Test seek and flush (open, seek, flush, close)
    try:
        resp = client.send_command("guest-file-open", {
            "path": test_path,
            "mode": "r",
        })
        if "return" in resp:
            h = resp["return"]
            # Seek
            seek_resp = client.send_command("guest-file-seek", {
                "handle": h,
                "offset": 0,
                "whence": 0,  # SEEK_SET
            })
            results["file-seek"] = {
                "supported": "error" not in seek_resp,
                "response": seek_resp,
            }
            # Flush
            flush_resp = client.send_command("guest-file-flush", {
                "handle": h,
            })
            results["file-flush"] = {
                "supported": "error" not in flush_resp,
                "response": flush_resp,
            }
            client.send_command("guest-file-close", {"handle": h})
    except QGAError as e:
        results.setdefault("file-seek", {"supported": False, "error": str(e)})
        results.setdefault("file-flush", {"supported": False, "error": str(e)})

    return {
        "command": "guest-file-* (open/write/read/seek/flush/close)",
        "supported": any(r.get("supported") for r in results.values()),
        "operations": results,
        "test_path": test_path,
    }


def test_guest_fsfreeze(client):
    """Test guest-fsfreeze-freeze and guest-fsfreeze-thaw."""
    results = {}

    # Freeze
    try:
        resp = client.send_command("guest-fsfreeze-freeze")
        results["freeze"] = {
            "supported": "error" not in resp,
            "response": resp,
        }
    except QGAError as e:
        results["freeze"] = {"supported": False, "error": str(e)}

    # Always try to thaw (even if freeze failed, to avoid leaving FS frozen)
    time.sleep(0.5)
    try:
        resp = client.send_command("guest-fsfreeze-thaw")
        results["thaw"] = {
            "supported": "error" not in resp,
            "response": resp,
        }
    except QGAError as e:
        results["thaw"] = {"supported": False, "error": str(e)}

    # Status
    try:
        resp = client.send_command("guest-fsfreeze-status")
        results["status"] = {
            "supported": "error" not in resp,
            "response": resp,
        }
    except QGAError as e:
        results["status"] = {"supported": False, "error": str(e)}

    return {
        "command": "guest-fsfreeze-*",
        "supported": any(r.get("supported") for r in results.values()),
        "operations": results,
    }


def test_additional_commands(client):
    """Probe additional QGA commands reported by guest-info.

    Tests each non-destructive command individually with reconnection
    between commands in case one kills the connection.

    IMPORTANT: guest-shutdown is DESTRUCTIVE — it actually shuts down the
    guest.  We skip it here and test it separately.
    """
    # Safe to probe (read-only or harmless)
    safe_commands = [
        ("guest-ping", None),
        ("guest-get-host-name", None),
        ("guest-get-osinfo", None),
        ("guest-get-time", None),
        ("guest-get-timezone", None),
        ("guest-get-users", None),
        ("guest-get-memory-blocks", None),
        ("guest-get-memory-block-info", None),
        ("guest-get-vcpus", None),
        ("guest-get-fsinfo", None),
        ("guest-get-disks", None),
    ]

    # Destructive or state-changing — probe but mark as such
    destructive_commands = [
        ("guest-set-user-password", "SKIPPED (would change auth)"),
        ("guest-set-vcpus", "SKIPPED (would change CPU count)"),
        ("guest-set-time", "SKIPPED (would change clock)"),
        ("guest-suspend-ram", "SKIPPED (would suspend VM)"),
        ("guest-suspend-disk", "SKIPPED (would hibernate VM)"),
        ("guest-suspend-hybrid", "SKIPPED (would suspend VM)"),
        ("guest-fstrim", "SKIPPED (would trim filesystem)"),
        ("guest-shutdown", "SKIPPED (confirmed working — shuts down VM)"),
    ]

    results = {}

    for cmd, _ in safe_commands:
        try:
            resp = client.send_command(cmd)
            if "error" in resp:
                results[cmd] = {
                    "supported": False,
                    "error_class": resp["error"].get("class"),
                    "error_desc": resp["error"].get("desc", ""),
                    "response": resp,
                }
            else:
                results[cmd] = {
                    "supported": True,
                    "response": resp,
                }
        except QGAError as e:
            results[cmd] = {
                "supported": False,
                "error": str(e),
                "notes": "Connection may have been disrupted",
            }
            # Try to reconnect for next test
            try:
                client.close()
                client.connect()
                client.sync()
            except QGAError:
                pass

    for cmd, note in destructive_commands:
        results[cmd] = {
            "supported": "unknown",
            "notes": note,
        }

    probed_supported = [k for k, v in results.items()
                       if v.get("supported") is True]
    probed_unsupported = [k for k, v in results.items()
                         if v.get("supported") is False]
    skipped = [k for k, v in results.items()
              if v.get("supported") == "unknown"]

    return {
        "command": "probe-additional-commands",
        "results": results,
        "supported": probed_supported,
        "unsupported": probed_unsupported,
        "skipped_destructive": skipped,
    }


# ─── Main ───

def run_all_tests(client, json_output=False):
    """Run the full QGA test suite and print results."""
    results = []

    # Sync first (required handshake)
    print("=" * 60)
    print("QEMU Guest Agent Test Suite — MikroTik RouterOS CHR")
    print(f"Socket: {client.socket_path}")
    print("=" * 60)
    print()

    tests = [
        ("guest-sync-delimited", test_guest_sync),
        ("guest-info", test_guest_info),
        ("guest-network-get-interfaces", test_guest_network_get_interfaces),
        ("guest-exec (input-data)", lambda c: test_guest_exec(c)),
        ("guest-exec (path mode)", test_guest_exec_with_path),
        ("guest-file-* operations", test_guest_file_ops),
        ("guest-fsfreeze-*", test_guest_fsfreeze),
        ("probe additional commands", test_additional_commands),
    ]

    for name, test_fn in tests:
        print(f"── {name} ", "─" * max(0, 50 - len(name)))
        try:
            result = test_fn(client)
            results.append(result)
            if not json_output:
                print_result(result)
        except QGAError as e:
            result = {"command": name, "supported": False, "error": str(e)}
            results.append(result)
            if not json_output:
                print(f"  ERROR: {e}")
        print()

    if json_output:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_summary(results)

    return results


def print_result(result):
    """Pretty-print a single test result."""
    cmd = result.get("command", "?")
    supported = result.get("supported")

    if supported:
        print(f"  ✓ SUPPORTED")
    elif supported is False:
        print(f"  ✗ NOT SUPPORTED / ERROR")
    else:
        print(f"  ? UNKNOWN")

    # Command-specific details
    if "agent_version" in result:
        print(f"  Agent version: {result['agent_version']}")
    if "supported_commands" in result:
        print(f"  Supported commands ({result['command_count']}):")
        for c in result["supported_commands"]:
            print(f"    - {c}")
    if "interfaces" in result:
        for iface in result["interfaces"]:
            ips = ", ".join(iface.get("ips", []))
            mac = iface.get("mac", "")
            print(f"    {iface['name']}: {mac}  {ips}")
    if "stdout" in result:
        print(f"  stdout: {result['stdout']!r}")
    if "stderr" in result:
        print(f"  stderr: {result['stderr']!r}")
    if "exitcode" in result:
        print(f"  exitcode: {result['exitcode']}")
    if "operations" in result:
        for op_name, op_result in result["operations"].items():
            status = "✓" if op_result.get("supported") else "✗"
            extra = ""
            if "content" in op_result:
                extra = f" → {op_result['content']!r}"
            if "roundtrip_ok" in op_result:
                extra += f" (roundtrip: {'ok' if op_result['roundtrip_ok'] else 'FAIL'})"
            if "error_desc" in op_result:
                extra = f" ({op_result['error_desc']})"
            elif "error" in op_result and isinstance(op_result["error"], str):
                extra = f" ({op_result['error']})"
            print(f"    {status} {op_name}{extra}")
    if "results" in result and "supported" in result and isinstance(result.get("supported"), list):
        if result["supported"]:
            print(f"  Supported commands from probing:")
            for c in result["supported"]:
                r = result["results"][c]
                resp = r.get("response", {}).get("return", "")
                print(f"    ✓ {c}: {json.dumps(resp, default=str)[:120]}")
        if result.get("unsupported"):
            print(f"  Unsupported ({len(result['unsupported'])}):")
            for c in result["unsupported"]:
                r = result["results"][c]
                desc = r.get("error_desc", r.get("error", ""))
                print(f"    ✗ {c}: {desc}")
        if result.get("skipped_destructive"):
            print(f"  Skipped (destructive):")
            for c in result["skipped_destructive"]:
                r = result["results"][c]
                print(f"    ⊘ {c}: {r.get('notes', '')}")
    elif "results" in result and "unexpected_supported" in result:
        if result["unexpected_supported"]:
            print(f"  Unexpectedly supported:")
            for c in result["unexpected_supported"]:
                print(f"    ✓ {c}")
        if result["confirmed_unsupported"]:
            print(f"  Confirmed unsupported ({len(result['confirmed_unsupported'])}):")
            for c in result["confirmed_unsupported"]:
                r = result["results"][c]
                desc = r.get("error_desc", r.get("error", ""))
                print(f"    ✗ {c}: {desc}")
    if "error" in result and isinstance(result["error"], str):
        print(f"  Error: {result['error']}")


def print_summary(results):
    """Print a summary table of all test results."""
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        cmd = r.get("command", "?")
        supported = r.get("supported")
        if supported is True:
            tag = "✓"
        elif supported is False:
            tag = "✗"
        else:
            tag = "?"
        print(f"  {tag}  {cmd}")
    print()


def run_single_command(client, command, arguments=None):
    """Run a single QGA command and print the response."""
    try:
        client.sync()
    except QGAError:
        pass  # Sync may fail on first attempt, that's ok

    args = None
    if arguments:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON arguments: {arguments}", file=sys.stderr)
            return 1

    resp = client.send_command(command, args)
    print(json.dumps(resp, indent=2, default=str))
    return 0 if "error" not in resp else 1


def run_exec(client, script):
    """Execute a RouterOS script via guest-exec and print output."""
    try:
        client.sync()
    except QGAError:
        pass

    result = test_guest_exec(client, script=script)
    if result.get("stdout"):
        print(result["stdout"], end="")
    if result.get("stderr"):
        print(result["stderr"], end="", file=sys.stderr)
    if "exitcode" in result:
        return result["exitcode"] or 0
    return 1


def main():
    parser = argparse.ArgumentParser(
        description="QEMU Guest Agent test tool for MikroTik RouterOS CHR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s /tmp/qga-chr.x86_64.qemu.7.22.sock              # full test suite
  %(prog)s /tmp/qga-chr.x86_64.qemu.7.22.sock --command guest-info
  %(prog)s /tmp/qga-chr.x86_64.qemu.7.22.sock --json       # JSON output
  %(prog)s /tmp/qga-chr.x86_64.qemu.7.22.sock --exec ':put [/system identity get name]'
""")
    parser.add_argument("socket", help="Path to QGA Unix socket")
    parser.add_argument("--command", "-c",
                        help="Run a single QGA command (e.g. guest-info)")
    parser.add_argument("--args", "-a",
                        help="JSON arguments for --command")
    parser.add_argument("--exec", "-e", dest="exec_script",
                        help="Execute a RouterOS script via guest-exec")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--all", action="store_true", default=True,
                        help="Run all tests (default)")
    parser.add_argument("--timeout", "-t", type=int, default=10,
                        help="Socket timeout in seconds (default: 10)")
    parser.add_argument("--wait", "-w", type=int, default=0,
                        help="Wait N seconds for socket to appear before starting")

    args = parser.parse_args()

    # Wait for socket if requested
    if args.wait > 0:
        deadline = time.monotonic() + args.wait
        while not os.path.exists(args.socket):
            if time.monotonic() > deadline:
                print(f"ERROR: Socket {args.socket} did not appear "
                      f"within {args.wait}s", file=sys.stderr)
                return 1
            time.sleep(0.5)
        # Give the agent a moment to start listening
        time.sleep(1)

    with QGAClient(args.socket, timeout=args.timeout) as client:
        if args.command:
            return run_single_command(client, args.command, args.args)
        elif args.exec_script:
            return run_exec(client, args.exec_script)
        else:
            results = run_all_tests(client, json_output=args.json)
            # Exit 0 if guest-info worked, 1 otherwise
            info_ok = any(r.get("command") == "guest-info"
                         and r.get("supported") for r in results)
            return 0 if info_ok else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
