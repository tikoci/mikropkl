#!/usr/bin/env python3
"""Test both org.qemu.guest_agent.0 and chr.provision_channel on ARM64.

Launches QEMU with both virtio-serial channels and probes each one
to see if RouterOS opens either (or both) on aarch64.
"""
import json, socket, subprocess, sys, time, os, signal

IMG = "chr-7.23_ab650-arm64.img"
PORT = 9198
QGA_SOCK = "/tmp/qga-dual-test.sock"
PROV_SOCK = "/tmp/chr-provision-test.sock"
SERIAL_SOCK = "/tmp/qga-dual-serial.sock"
VARS_COPY = "/tmp/qga-dual-vars.fd"

EFI_CODE = "/usr/local/share/qemu/edk2-aarch64-code.fd"
EFI_VARS = "/usr/local/share/qemu/edk2-arm-vars.fd"

# Also test on x86_64 if image available
X86_IMG = None  # set below if found

def cleanup_socks():
    for s in [QGA_SOCK, PROV_SOCK, SERIAL_SOCK]:
        try:
            os.unlink(s)
        except FileNotFoundError:
            pass

def probe_socket(path, name, timeout=30):
    """Try to connect and send guest-sync-delimited. Return response or None."""
    print(f"\n{'='*60}")
    print(f"Probing: {name} ({path})")
    print(f"{'='*60}")

    if not os.path.exists(path):
        print(f"  Socket file does not exist: {path}")
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(path)
        print(f"  Connected to socket")
    except (ConnectionRefusedError, socket.timeout) as e:
        print(f"  Connection failed: {e}")
        return None

    # Send sync-delimited
    sync_msg = json.dumps({
        "execute": "guest-sync-delimited",
        "arguments": {"id": 12345}
    }) + "\n"

    try:
        sock.sendall(b'\xff' + sync_msg.encode())
        print(f"  Sent guest-sync-delimited, waiting {timeout}s for response...")

        sock.settimeout(timeout)
        data = sock.recv(65536)
        if data:
            cleaned = data.replace(b'\xff', b'').strip()
            print(f"  RAW response ({len(data)} bytes): {data!r}")
            print(f"  Cleaned: {cleaned!r}")
            try:
                parsed = json.loads(cleaned)
                print(f"  Parsed JSON: {json.dumps(parsed, indent=2)}")

                # If sync worked, try guest-info
                info_msg = json.dumps({"execute": "guest-info"}) + "\n"
                sock.sendall(info_msg.encode())
                sock.settimeout(10)
                info_data = sock.recv(65536).strip()
                print(f"\n  guest-info response: {info_data.decode()}")
                return parsed
            except json.JSONDecodeError:
                print(f"  (not valid JSON)")
                return cleaned
        else:
            print(f"  Empty response (0 bytes)")
            return None
    except socket.timeout:
        print(f"  TIMEOUT after {timeout}s — no response (guest port not opened)")
        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None
    finally:
        sock.close()

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if not os.path.exists(IMG):
        print(f"ERROR: {IMG} not found in {os.getcwd()}")
        sys.exit(1)

    cleanup_socks()

    # Copy UEFI vars
    subprocess.run(["cp", EFI_VARS, VARS_COPY], check=True)

    # Build QEMU command with BOTH channels
    cmd = [
        "qemu-system-aarch64",
        "-M", "virt", "-cpu", "cortex-a710", "-m", "1024", "-smp", "2",
        "-accel", "tcg,tb-size=256",
        "-drive", f"if=pflash,format=raw,readonly=on,unit=0,file={EFI_CODE}",
        "-drive", f"if=pflash,format=raw,unit=1,file={VARS_COPY}",
        "-drive", f"file={IMG},format=raw,if=none,id=drive1",
        "-device", "virtio-blk-pci,drive=drive1,bootindex=0",
        "-netdev", f"user,id=net0,hostfwd=tcp::{PORT}-:80",
        "-device", "virtio-net-pci,netdev=net0",
        "-display", "none", "-monitor", "none",
        "-chardev", f"socket,id=serial0,path={SERIAL_SOCK},server=on,wait=off",
        "-serial", "chardev:serial0",
        # Channel 1: standard QGA channel
        "-device", "virtio-serial-pci,id=virtio-serial0",
        "-chardev", f"socket,id=qga0,path={QGA_SOCK},server=on,wait=off",
        "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0",
        # Channel 2: MikroTik provision channel
        "-chardev", f"socket,id=prov0,path={PROV_SOCK},server=on,wait=off",
        "-device", "virtserialport,chardev=prov0,name=chr.provision_channel,id=prov-port0",
    ]

    print(f"Launching QEMU (aarch64 TCG, port {PORT})...")
    print(f"  Image: {IMG}")
    print(f"  QGA socket: {QGA_SOCK}")
    print(f"  Provision socket: {PROV_SOCK}")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print(f"  PID: {proc.pid}")

    # Wait for boot
    print(f"\nWaiting for RouterOS to boot (checking HTTP on port {PORT})...")
    booted = False
    for i in range(60):  # 5 min max for TCG cross-arch
        time.sleep(5)
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=3)
            if resp.status == 200:
                print(f"  HTTP 200 after {(i+1)*5}s — RouterOS is up!")
                booted = True
                break
        except Exception:
            print(f"  {(i+1)*5}s — not ready yet...")

        # Check if QEMU died
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode()
            print(f"  QEMU exited with code {proc.returncode}")
            if stderr:
                print(f"  stderr: {stderr[:500]}")
            sys.exit(1)

    if not booted:
        print("TIMEOUT waiting for boot — killing QEMU")
        proc.kill()
        sys.exit(1)

    # Give RouterOS a moment to settle
    time.sleep(3)

    # Probe both channels
    print("\n" + "=" * 60)
    print("PROBING CHANNELS")
    print("=" * 60)

    qga_result = probe_socket(QGA_SOCK, "org.qemu.guest_agent.0", timeout=15)
    prov_result = probe_socket(PROV_SOCK, "chr.provision_channel", timeout=15)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  org.qemu.guest_agent.0:  {'RESPONDED' if qga_result else 'NO RESPONSE'}")
    print(f"  chr.provision_channel:   {'RESPONDED' if prov_result else 'NO RESPONSE'}")

    # Cleanup
    print(f"\nShutting down QEMU (PID {proc.pid})...")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    cleanup_socks()
    try:
        os.unlink(VARS_COPY)
    except FileNotFoundError:
        pass

    print("Done.")

if __name__ == "__main__":
    main()
