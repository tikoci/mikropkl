#!/usr/bin/env python3
"""Wait for RouterOS to boot, then run clean QGA test.
No intermediate connections to avoid consuming the chardev socket."""
import urllib.request, socket, time, json, base64, sys, os

# Force unbuffered output
sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1)

PORT = 9197
QGA_SOCK = '/tmp/qga-arm64-test.sock'
SERIAL_SOCK = '/tmp/qga-arm64-test-serial.sock'

print("Waiting for RouterOS HTTP to come up...")
for i in range(60):
    try:
        r = urllib.request.urlopen(f'http://localhost:{PORT}/', timeout=3)
        if r.status == 200:
            print(f"  HTTP 200 after {(i+1)*5}s")
            break
    except:
        pass
    time.sleep(5)
else:
    print("  TIMEOUT - RouterOS did not boot")
    sys.exit(1)

# Extra wait for QGA daemon to start (if present)
print("Waiting 15s extra for QGA daemon startup...")
time.sleep(15)

# Get version info
auth = 'Basic ' + base64.b64encode(b'admin:').decode()
try:
    req = urllib.request.Request(f'http://localhost:{PORT}/rest/system/resource')
    req.add_header('Authorization', auth)
    r = urllib.request.urlopen(req, timeout=5)
    info = json.loads(r.read())
    print(f"\nRouterOS: {info.get('version', '?')} ({info.get('architecture-name', '?')})")
    print(f"Build:    {info.get('build-time', '?')}")
    print(f"Board:    {info.get('board-name', '?')}")
except Exception as e:
    print(f"REST error: {e}")

# Check PCI hardware for virtio-serial
try:
    req = urllib.request.Request(f'http://localhost:{PORT}/rest/system/resource/hardware')
    req.add_header('Authorization', auth)
    r = urllib.request.urlopen(req, timeout=5)
    hw = json.loads(r.read())
    print(f"\nPCI devices:")
    for d in hw:
        loc = d.get('location', '')
        name = d.get('name', '')
        cat = d.get('category', '')
        print(f"  {loc}: {name} [{cat}]")
except:
    pass

# Check QGA socket — single clean test
print(f"\n=== QGA Socket Test ===")
print(f"Socket file exists: {os.path.exists(QGA_SOCK)}")

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(10)
try:
    s.connect(QGA_SOCK)
    print("QGA: CONNECTED to QEMU chardev")
    
    # Send guest-sync-delimited
    sync_msg = json.dumps({"execute": "guest-sync-delimited", "arguments": {"id": 42}}) + "\n"
    s.sendall(sync_msg.encode())
    print("Sent guest-sync-delimited, waiting 30s for response...")
    
    buf = b""
    deadline = time.monotonic() + 30
    got_response = False
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        s.settimeout(min(remaining, 3.0))
        try:
            chunk = s.recv(65536)
            if not chunk:
                print("QGA: connection closed by remote (guest port off)")
                break
            buf += chunk
            cleaned = buf.replace(b"\xff", b"")
            for line in cleaned.split(b"\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line)
                    print(f"QGA SYNC RESPONSE: {json.dumps(resp)}")
                    got_response = True
                    break
                except json.JSONDecodeError:
                    pass
            if got_response:
                break
        except socket.timeout:
            elapsed = 30 - (deadline - time.monotonic())
            print(f"  ... waiting ({elapsed:.0f}s elapsed)")
    
    if got_response:
        # QGA is alive! Run guest-info
        print("\n--- guest-info ---")
        info_msg = json.dumps({"execute": "guest-info"}) + "\n"
        s.sendall(info_msg.encode())
        buf2 = b""
        deadline2 = time.monotonic() + 15
        while time.monotonic() < deadline2:
            s.settimeout(min(deadline2 - time.monotonic(), 3.0))
            try:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf2 += chunk
                cleaned2 = buf2.replace(b"\xff", b"")
                for line in cleaned2.split(b"\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        resp = json.loads(line)
                        print(json.dumps(resp, indent=2))
                        break
                    except json.JSONDecodeError:
                        pass
                else:
                    continue
                break
            except socket.timeout:
                continue
        
        print("\n*** QGA IS FUNCTIONAL ON ARM64! ***")
    else:
        if buf:
            print(f"QGA: partial data received: {buf!r}")
        else:
            print("QGA: NO RESPONSE (timeout) — guest agent daemon not running")
            print("  The virtio-serial PCI device is present, but")
            print("  no guest process has opened org.qemu.guest_agent.0")
    
    s.close()

except ConnectionRefusedError:
    print("QGA: CONNECTION REFUSED — QEMU chardev not accepting connections")
    print("  This may indicate the socket file is stale or QEMU chardev crashed")
except Exception as e:
    print(f"QGA: ERROR: {e}")

# Also check serial as reference
print(f"\n=== Serial Console Check ===")
s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s2.settimeout(5)
try:
    s2.connect(SERIAL_SOCK)
    print("Serial: CONNECTED")
    s2.sendall(b"\r\n")
    time.sleep(2)
    s2.settimeout(3)
    try:
        data = s2.recv(4096)
        # Just show first line
        text = data.decode('utf-8', errors='replace').strip()
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for l in lines[:3]:
            print(f"  {l}")
    except socket.timeout:
        print("  Serial: no immediate response")
    s2.close()
except ConnectionRefusedError:
    print("Serial: REFUSED")
except Exception as e:
    print(f"Serial: {e}")

print("\n=== DONE ===")
