#!/usr/bin/env python3
"""Test virtio-serial variants on ARM64 per MikroTik's advice.

MikroTik suggested using `-device virtio-serial` instead of
`-device virtio-serial-pci`. This script tests all virtio-serial
transport variants to determine if any enables the QGA daemon on ARM64.

QEMU device alias mapping (virt machine):
  virtio-serial        → alias for virtio-serial-pci (PCI transport)
  virtio-serial-pci    → PCI transport (what we tested before)
  virtio-serial-device → MMIO/platform transport (virtio-bus)
  virtio-serial-pci-non-transitional → modern-only PCI (virtio 1.0+)

Tests run sequentially — each variant gets its own QEMU instance.
"""
import json, socket, subprocess, sys, time, os, signal, urllib.request, base64

# Force unbuffered output
sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1)

IMG = "chr-7.23_ab650-arm64.img"
EFI_CODE = "/usr/local/share/qemu/edk2-aarch64-code.fd"
EFI_VARS = "/usr/local/share/qemu/edk2-arm-vars.fd"

# Per-test unique paths to avoid collisions
BASE_PORT = 9200
QGA_SOCK_TMPL = "/tmp/qga-variant-{name}.sock"
SERIAL_SOCK_TMPL = "/tmp/qga-variant-{name}-serial.sock"
MONITOR_SOCK_TMPL = "/tmp/qga-variant-{name}-monitor.sock"
VARS_TMPL = "/tmp/qga-variant-{name}-vars.fd"

# Variants to test
VARIANTS = [
    {
        "name": "virtio-serial",
        "label": "virtio-serial (MikroTik's suggestion — alias for virtio-serial-pci)",
        "device_type": "virtio-serial",
        "port": BASE_PORT,
    },
    {
        "name": "virtio-serial-pci",
        "label": "virtio-serial-pci (original test — PCI transport)",
        "device_type": "virtio-serial-pci",
        "port": BASE_PORT + 1,
    },
    {
        "name": "virtio-serial-device",
        "label": "virtio-serial-device (MMIO/platform transport)",
        "device_type": "virtio-serial-device",
        "port": BASE_PORT + 2,
        "expect_fail": True,  # RouterOS lacks virtio_mmio
    },
    {
        "name": "virtio-serial-pci-non-transitional",
        "label": "virtio-serial-pci-non-transitional (modern-only, virtio 1.0+)",
        "device_type": "virtio-serial-pci-non-transitional",
        "port": BASE_PORT + 3,
    },
]


def cleanup_files(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def wait_for_http(port, timeout=300, interval=5):
    """Wait for RouterOS HTTP to come up. Returns seconds elapsed or None."""
    for i in range(timeout // interval):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            if r.status == 200:
                return (i + 1) * interval
        except Exception:
            pass
        time.sleep(interval)
    return None


def get_rest_info(port, endpoint):
    """GET from RouterOS REST API."""
    auth = 'Basic ' + base64.b64encode(b'admin:').decode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/rest/{endpoint}")
    req.add_header('Authorization', auth)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def probe_qga(sock_path, timeout=30):
    """Probe QGA socket. Returns (responded: bool, details: str)."""
    if not os.path.exists(sock_path):
        return False, "socket file does not exist"

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(sock_path)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        return False, f"connection failed: {e}"

    sync_msg = json.dumps({
        "execute": "guest-sync-delimited",
        "arguments": {"id": 99999}
    }) + "\n"

    try:
        s.sendall(b'\xff' + sync_msg.encode())

        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            s.settimeout(min(remaining, 3.0))
            try:
                chunk = s.recv(65536)
                if not chunk:
                    return False, "connection closed by QEMU (guest port off)"
                buf += chunk
                cleaned = buf.replace(b'\xff', b'').strip()
                for line in cleaned.split(b'\n'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        resp = json.loads(line)
                        # Sync worked! Now get guest-info
                        info_msg = json.dumps({"execute": "guest-info"}) + "\n"
                        s.sendall(info_msg.encode())
                        s.settimeout(10)
                        info_buf = b""
                        info_deadline = time.monotonic() + 10
                        while time.monotonic() < info_deadline:
                            try:
                                chunk2 = s.recv(65536)
                                if not chunk2:
                                    break
                                info_buf += chunk2
                                for line2 in info_buf.strip().split(b'\n'):
                                    line2 = line2.strip()
                                    if not line2:
                                        continue
                                    try:
                                        info_resp = json.loads(line2)
                                        return True, json.dumps(info_resp, indent=2)
                                    except json.JSONDecodeError:
                                        pass
                            except socket.timeout:
                                continue
                        return True, f"sync OK: {json.dumps(resp)}, guest-info timeout"
                    except json.JSONDecodeError:
                        pass
            except socket.timeout:
                continue

        if buf:
            return False, f"partial data: {buf!r}"
        return False, f"no response after {timeout}s (guest port not opened)"
    except Exception as e:
        return False, f"error: {e}"
    finally:
        s.close()


def query_monitor(sock_path, command, timeout=5):
    """Send a command to QEMU monitor and return response."""
    if not os.path.exists(sock_path):
        return None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(sock_path)
        # Read banner
        s.recv(4096)
        time.sleep(0.5)
        s.sendall((command + "\n").encode())
        time.sleep(1)
        data = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        s.close()
        return data.decode('utf-8', errors='replace')
    except Exception as e:
        return f"monitor error: {e}"


def build_qemu_cmd(variant):
    """Build QEMU command for a variant."""
    name = variant["name"]
    device_type = variant["device_type"]
    port = variant["port"]
    qga_sock = QGA_SOCK_TMPL.format(name=name)
    serial_sock = SERIAL_SOCK_TMPL.format(name=name)
    monitor_sock = MONITOR_SOCK_TMPL.format(name=name)
    vars_copy = VARS_TMPL.format(name=name)

    cmd = [
        "qemu-system-aarch64",
        "-M", "virt", "-cpu", "cortex-a710", "-m", "1024", "-smp", "2",
        "-accel", "tcg,tb-size=256",
        "-drive", f"if=pflash,format=raw,readonly=on,unit=0,file={EFI_CODE}",
        "-drive", f"if=pflash,format=raw,unit=1,file={vars_copy}",
        "-drive", f"file={IMG},format=raw,if=none,id=drive1",
        "-device", "virtio-blk-pci,drive=drive1,bootindex=0",
        "-netdev", f"user,id=net0,hostfwd=tcp::{port}-:80",
        "-device", "virtio-net-pci,netdev=net0",
        "-display", "none",
        "-chardev", f"socket,id=serial0,path={serial_sock},server=on,wait=off",
        "-serial", "chardev:serial0",
        "-chardev", f"socket,id=mon0,path={monitor_sock},server=on,wait=off",
        "-monitor", "chardev:mon0",
    ]

    if device_type == "virtio-serial-device":
        # MMIO variant — needs to be on virtio-bus, not PCI bus
        # The virtserialport still attaches to the serial bus
        cmd += [
            "-device", f"{device_type},id=vserial0",
            "-chardev", f"socket,id=qga0,path={qga_sock},server=on,wait=off",
            "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0",
        ]
    else:
        # PCI variants
        cmd += [
            "-device", f"{device_type},id=vserial0",
            "-chardev", f"socket,id=qga0,path={qga_sock},server=on,wait=off",
            "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0",
        ]

    return cmd


def test_variant(variant):
    """Test one virtio-serial variant. Returns result dict."""
    name = variant["name"]
    label = variant["label"]
    port = variant["port"]
    qga_sock = QGA_SOCK_TMPL.format(name=name)
    serial_sock = SERIAL_SOCK_TMPL.format(name=name)
    monitor_sock = MONITOR_SOCK_TMPL.format(name=name)
    vars_copy = VARS_TMPL.format(name=name)

    print(f"\n{'#' * 70}")
    print(f"# TEST: {label}")
    print(f"{'#' * 70}")

    result = {
        "name": name,
        "label": label,
        "qemu_started": False,
        "booted": False,
        "qga_responded": False,
        "details": "",
        "pci_devices": [],
        "irqs": [],
    }

    # Cleanup
    cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)

    # Copy EFI vars
    subprocess.run(["cp", EFI_VARS, vars_copy], check=True)

    cmd = build_qemu_cmd(variant)
    print(f"  Device: -device {variant['device_type']}")
    print(f"  Port:   {port}")
    print(f"  Socket: {qga_sock}")
    print(f"  QEMU command:")
    # Print command in readable form
    cmd_str = " ".join(cmd)
    print(f"    {cmd_str[:200]}...")

    # Start QEMU
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print(f"  PID: {proc.pid}")

    # Check if QEMU crashes immediately (give it 3s)
    time.sleep(3)
    if proc.poll() is not None:
        stderr = proc.stderr.read().decode('utf-8', errors='replace')
        print(f"  QEMU EXITED immediately (code {proc.returncode})")
        if stderr:
            print(f"  stderr: {stderr[:1000]}")
        result["details"] = f"QEMU exited: {stderr[:200]}"
        cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)
        return result

    result["qemu_started"] = True

    # Wait for boot
    print(f"  Waiting for HTTP on port {port}...")
    boot_time = wait_for_http(port, timeout=300, interval=5)
    if boot_time is None:
        print(f"  TIMEOUT — RouterOS did not boot within 300s")
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode('utf-8', errors='replace')
            print(f"  QEMU died: {stderr[:500]}")
        result["details"] = "boot timeout (300s)"
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)
        return result

    print(f"  Booted in ~{boot_time}s")
    result["booted"] = True

    # Get system info
    sysinfo = get_rest_info(port, "system/resource")
    print(f"  Version:  {sysinfo.get('version', '?')}")
    print(f"  Arch:     {sysinfo.get('architecture-name', '?')}")

    # Get PCI devices
    hw = get_rest_info(port, "system/resource/hardware")
    if isinstance(hw, list):
        print(f"  PCI devices:")
        for d in hw:
            loc = d.get('location', '')
            dname = d.get('name', '')
            cat = d.get('category', '')
            print(f"    {loc}: {dname} [{cat}]")
            result["pci_devices"].append(f"{loc}: {dname} [{cat}]")
    else:
        print(f"  PCI info: {hw}")

    # Get IRQs
    irqs = get_rest_info(port, "system/resource/irq")
    if isinstance(irqs, list):
        print(f"  IRQs:")
        for irq in irqs:
            iname = irq.get('name', '')
            inum = irq.get('irq', '')
            icount = irq.get('count', '')
            print(f"    {iname}: IRQ {inum} (count: {icount})")
            result["irqs"].append(f"{iname}: IRQ {inum} (count: {icount})")

    # Extra settle time  
    print(f"  Waiting 15s for QGA daemon startup...")
    time.sleep(15)

    # Query QEMU monitor for device info
    print(f"  Querying QEMU monitor for virtio-serial port state...")
    qtree = query_monitor(monitor_sock, "info qtree")
    if qtree:
        # Extract virtio-serial section
        lines = qtree.split('\n')
        in_serial = False
        serial_lines = []
        for line in lines:
            if 'virtio-serial' in line.lower() or 'virtserialport' in line.lower() or 'vserial' in line.lower():
                in_serial = True
            if in_serial:
                serial_lines.append(line)
                if len(serial_lines) > 30:
                    break
            elif serial_lines and line.strip() and not line.startswith(' ' * 4):
                # Left the indented section
                break
        if serial_lines:
            print(f"  QEMU qtree (virtio-serial section):")
            for sl in serial_lines[:20]:
                print(f"    {sl}")

    # Check for "guest" open state in monitor
    chardev_info = query_monitor(monitor_sock, "info chardev")
    if chardev_info:
        for line in chardev_info.split('\n'):
            if 'qga' in line.lower() or 'serial' in line.lower():
                print(f"  chardev: {line.strip()}")

    # Probe QGA
    print(f"\n  === QGA Probe ===")
    responded, details = probe_qga(qga_sock, timeout=30)
    result["qga_responded"] = responded
    result["details"] = details

    if responded:
        print(f"  *** QGA RESPONDED! ***")
        print(f"  {details}")
    else:
        print(f"  QGA: NO RESPONSE — {details}")

    # Cleanup QEMU
    print(f"\n  Shutting down QEMU (PID {proc.pid})...")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)
    return result


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if not os.path.exists(IMG):
        print(f"ERROR: {IMG} not found in {os.getcwd()}")
        sys.exit(1)

    print(f"=" * 70)
    print(f"virtio-serial Variant Test — ARM64 CHR")
    print(f"=" * 70)
    print(f"Image:  {IMG}")
    print(f"Host:   macOS x86_64 (Intel)")
    print(f"QEMU:   {subprocess.check_output(['qemu-system-aarch64', '--version']).decode().split(chr(10))[0]}")
    print(f"Accel:  TCG (cross-arch)")
    print()
    print(f"MikroTik suggested: -device virtio-serial (instead of virtio-serial-pci)")
    print(f"QEMU alias check:  virtio-serial IS an alias for virtio-serial-pci")
    print(f"Testing all variants for completeness:")
    for v in VARIANTS:
        print(f"  - {v['label']}")

    results = []
    for variant in VARIANTS:
        result = test_variant(variant)
        results.append(result)

    # Summary
    print(f"\n{'=' * 70}")
    print(f"SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Variant':<45} {'QEMU':<7} {'Boot':<7} {'QGA':<7}")
    print(f"{'-'*45} {'-'*7} {'-'*7} {'-'*7}")
    for r in results:
        qemu_ok = "OK" if r["qemu_started"] else "FAIL"
        boot_ok = "OK" if r["booted"] else "FAIL"
        qga_ok = "YES" if r["qga_responded"] else "NO"
        print(f"{r['name']:<45} {qemu_ok:<7} {boot_ok:<7} {qga_ok:<7}")
        if r["details"] and not r["qga_responded"]:
            print(f"  └─ {r['details'][:80]}")

    # Detailed notes
    print(f"\nQEMU alias resolution on 'virt' machine:")
    print(f"  virtio-serial = alias for virtio-serial-pci (confirmed)")
    print(f"  virtio-serial-device = MMIO transport (separate device)")

    any_worked = any(r["qga_responded"] for r in results)
    if any_worked:
        print(f"\n*** QGA WORKS on ARM64 with: ***")
        for r in results:
            if r["qga_responded"]:
                print(f"  - {r['label']}")
    else:
        print(f"\n*** QGA did NOT respond on ANY variant ***")
        print(f"The guest agent daemon is not opening the virtio-serial port,")
        print(f"regardless of transport type (PCI vs MMIO).")

    # Save results to JSON
    with open("virtio-serial-variant-results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to virtio-serial-variant-results.json")


if __name__ == "__main__":
    main()
