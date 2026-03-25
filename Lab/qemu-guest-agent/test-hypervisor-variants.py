#!/usr/bin/env python3
"""Test QGA with different QEMU configurations per MikroTik's feedback.

MikroTik said `virtio-serial` works. We've confirmed it's an alias for
virtio-serial-pci. So something ELSE about their test environment must differ.

Hypotheses tested:
1. SMBIOS identity — QGA daemon may check SMBIOS Type 1 to detect hypervisor
2. Machine type sbsa-ref — different ACPI/SMBIOS tables
3. CPU model neoverse-n1 — common ARM server CPU, different feature set
4. Explicit SMBIOS type=1 to identify as KVM/QEMU hypervisor
5. Disable-legacy virtio — modern-only transport might trigger different init
6. ACPI vs DTB — virt machine can be configured with/without ACPI

We can't test KVM here (macOS Intel host, TCG only), but we CAN test
SMBIOS and machine type differences that KVM on Linux would produce.
"""
import json, socket, subprocess, sys, time, os, base64, urllib.request

sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)
sys.stderr = open(sys.stderr.fileno(), mode='w', buffering=1)

IMG = "chr-7.23_ab650-arm64.img"
EFI_CODE = "/usr/local/share/qemu/edk2-aarch64-code.fd"
EFI_VARS = "/usr/local/share/qemu/edk2-arm-vars.fd"

BASE_PORT = 9210

TESTS = [
    {
        "name": "smbios-kvm",
        "label": "SMBIOS Type 1 = KVM (what a real KVM host presents)",
        "extra_args": [
            "-smbios", "type=1,manufacturer=QEMU,product=KVM Virtual Machine,version=7.2.0",
        ],
        "machine": "virt",
        "cpu": "cortex-a710",
    },
    {
        "name": "smbios-proxmox",
        "label": "SMBIOS Type 1 = Proxmox (popular KVM management)",
        "extra_args": [
            "-smbios", "type=1,manufacturer=QEMU,product=Standard PC (Q35 + ICH9),version=pve-qemu-kvm-9.0.2",
        ],
        "machine": "virt",
        "cpu": "cortex-a710",
    },
    {
        "name": "neoverse-n1",
        "label": "CPU neoverse-n1 (ARM server CPU, common in cloud)",
        "extra_args": [],
        "machine": "virt",
        "cpu": "neoverse-n1",
    },
    {
        "name": "sbsa-ref",
        "label": "Machine sbsa-ref (SBSA server reference platform)",
        "extra_args": [],
        "machine": "sbsa-ref",
        "cpu": "neoverse-n1",
        "no_pflash": True,  # sbsa-ref has built-in firmware
    },
    {
        "name": "virt-gic3",
        "label": "virt with GICv3 + neoverse-n1 (realistic server config)",
        "extra_args": [
            "-smbios", "type=1,manufacturer=QEMU,product=KVM Virtual Machine",
        ],
        "machine": "virt,gic-version=3",
        "cpu": "neoverse-n1",
    },
    {
        "name": "virt-its",
        "label": "virt with GICv3+ITS + neoverse-n1 (KVM default on real hardware)",
        "extra_args": [
            "-smbios", "type=1,manufacturer=QEMU,product=KVM Virtual Machine",
        ],
        "machine": "virt,gic-version=3,its=on",
        "cpu": "neoverse-n1",
    },
]


def cleanup_files(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def wait_for_http(port, timeout=300, interval=5):
    for i in range(timeout // interval):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
            if r.status == 200:
                return (i + 1) * interval
        except Exception:
            pass
        time.sleep(interval)
    return None


def get_rest(port, endpoint):
    auth = 'Basic ' + base64.b64encode(b'admin:').decode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/rest/{endpoint}")
    req.add_header('Authorization', auth)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def probe_qga(sock_path, timeout=30):
    if not os.path.exists(sock_path):
        return False, "socket missing"
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect(sock_path)
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        return False, f"connect failed: {e}"

    try:
        msg = json.dumps({"execute": "guest-sync-delimited", "arguments": {"id": 77777}}) + "\n"
        s.sendall(b'\xff' + msg.encode())
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
                    return False, "connection closed (guest port off)"
                buf += chunk
                cleaned = buf.replace(b'\xff', b'').strip()
                for line in cleaned.split(b'\n'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        resp = json.loads(line)
                        # Got sync! Try guest-info
                        s.sendall((json.dumps({"execute": "guest-info"}) + "\n").encode())
                        s.settimeout(10)
                        buf2 = b""
                        for _ in range(10):
                            try:
                                chunk2 = s.recv(65536)
                                if not chunk2:
                                    break
                                buf2 += chunk2
                                for line2 in buf2.strip().split(b'\n'):
                                    line2 = line2.strip()
                                    if line2:
                                        try:
                                            info = json.loads(line2)
                                            return True, json.dumps(info, indent=2)
                                        except json.JSONDecodeError:
                                            pass
                            except socket.timeout:
                                continue
                        return True, f"sync OK, guest-info timeout"
                    except json.JSONDecodeError:
                        pass
            except socket.timeout:
                continue
        return False, f"no response after {timeout}s"
    except Exception as e:
        return False, f"error: {e}"
    finally:
        s.close()


def run_test(test, port_offset):
    name = test["name"]
    label = test["label"]
    port = BASE_PORT + port_offset
    qga_sock = f"/tmp/qga-hyp-{name}.sock"
    serial_sock = f"/tmp/qga-hyp-{name}-serial.sock"
    monitor_sock = f"/tmp/qga-hyp-{name}-monitor.sock"
    vars_copy = f"/tmp/qga-hyp-{name}-vars.fd"

    print(f"\n{'#' * 70}")
    print(f"# {label}")
    print(f"{'#' * 70}")

    result = {
        "name": name,
        "label": label,
        "qemu_ok": False,
        "booted": False,
        "qga_ok": False,
        "board_name": "",
        "details": "",
    }

    cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)

    cmd = ["qemu-system-aarch64"]
    cmd += ["-M", test["machine"]]
    cmd += ["-cpu", test["cpu"]]
    cmd += ["-m", "1024", "-smp", "2"]
    cmd += ["-accel", "tcg,tb-size=256"]

    if not test.get("no_pflash"):
        subprocess.run(["cp", EFI_VARS, vars_copy], check=True)
        cmd += ["-drive", f"if=pflash,format=raw,readonly=on,unit=0,file={EFI_CODE}"]
        cmd += ["-drive", f"if=pflash,format=raw,unit=1,file={vars_copy}"]

    cmd += ["-drive", f"file={IMG},format=raw,if=none,id=drive1"]
    cmd += ["-device", "virtio-blk-pci,drive=drive1,bootindex=0"]
    cmd += ["-netdev", f"user,id=net0,hostfwd=tcp::{port}-:80"]
    cmd += ["-device", "virtio-net-pci,netdev=net0"]
    cmd += ["-display", "none"]
    cmd += ["-chardev", f"socket,id=serial0,path={serial_sock},server=on,wait=off"]
    cmd += ["-serial", "chardev:serial0"]
    cmd += ["-chardev", f"socket,id=mon0,path={monitor_sock},server=on,wait=off"]
    cmd += ["-monitor", "chardev:mon0"]
    # QGA channel
    cmd += ["-device", "virtio-serial-pci,id=vserial0"]
    cmd += ["-chardev", f"socket,id=qga0,path={qga_sock},server=on,wait=off"]
    cmd += ["-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0"]
    # Extra test-specific args
    cmd += test.get("extra_args", [])

    print(f"  Machine:  -M {test['machine']}")
    print(f"  CPU:      -cpu {test['cpu']}")
    print(f"  Port:     {port}")
    if test.get("extra_args"):
        print(f"  Extra:    {' '.join(test['extra_args'])}")

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    print(f"  PID:      {proc.pid}")

    # Check immediate crash
    time.sleep(3)
    if proc.poll() is not None:
        stderr = proc.stderr.read().decode('utf-8', errors='replace')
        print(f"  QEMU CRASHED (exit {proc.returncode})")
        print(f"  stderr: {stderr[:500]}")
        result["details"] = f"QEMU crashed: {stderr[:200]}"
        cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)
        return result

    result["qemu_ok"] = True

    # Wait for boot
    print(f"  Waiting for HTTP...")
    boot_time = wait_for_http(port, timeout=300, interval=5)
    if boot_time is None:
        print(f"  TIMEOUT (300s)")
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode('utf-8', errors='replace')
            print(f"  QEMU died: {stderr[:300]}")
        result["details"] = "boot timeout"
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
        cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)
        return result

    result["booted"] = True
    print(f"  Booted in ~{boot_time}s")

    # System info
    sysinfo = get_rest(port, "system/resource")
    board = sysinfo.get("board-name", "?")
    version = sysinfo.get("version", "?")
    result["board_name"] = board
    print(f"  Version:    {version}")
    print(f"  Board:      {board}")

    # PCI devices
    hw = get_rest(port, "system/resource/hardware")
    if isinstance(hw, list):
        for d in hw:
            dname = d.get('name', '')
            cat = d.get('category', '')
            loc = d.get('location', '')
            if 'serial' in cat.lower() or 'console' in dname.lower() or 'communication' in cat.lower():
                print(f"  virtio-serial: {loc}: {dname} [{cat}]")

    # Wait for QGA
    print(f"  Waiting 15s for QGA startup...")
    time.sleep(15)

    # Probe
    responded, details = probe_qga(qga_sock, timeout=30)
    result["qga_ok"] = responded
    result["details"] = details

    if responded:
        print(f"  *** QGA RESPONDED! ***")
        print(f"  {details}")
    else:
        print(f"  QGA: NO RESPONSE ({details})")

    # Cleanup
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    cleanup_files(qga_sock, serial_sock, monitor_sock, vars_copy)
    return result


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists(IMG):
        print(f"ERROR: {IMG} not found")
        sys.exit(1)

    print("=" * 70)
    print("Hypervisor/Machine/CPU Variant Test — ARM64 CHR QGA")
    print("=" * 70)
    print(f"Image: {IMG}")
    print(f"QEMU:  {subprocess.check_output(['qemu-system-aarch64', '--version']).decode().split(chr(10))[0]}")
    print()
    print("Hypotheses:")
    print("  1. QGA daemon checks SMBIOS Type 1 to detect hypervisor type")
    print("  2. Different -M machine type generates different ACPI/SMBIOS")
    print("  3. CPU model affects device tree or ACPI table generation")
    print("  4. KVM on Linux generates different SMBIOS than TCG on macOS")
    print()
    print(f"Tests: {len(TESTS)}")
    for t in TESTS:
        print(f"  - {t['label']}")

    results = []
    for i, test in enumerate(TESTS):
        result = run_test(test, i)
        results.append(result)

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"{'Test':<25} {'Machine':<15} {'CPU':<15} {'Boot':<6} {'QGA':<6} {'Board Name'}")
    print(f"{'-'*25} {'-'*15} {'-'*15} {'-'*6} {'-'*6} {'-'*30}")
    for r in results:
        t = next(t for t in TESTS if t["name"] == r["name"])
        boot = "OK" if r["booted"] else "FAIL"
        qga = "YES" if r["qga_ok"] else "NO"
        print(f"{r['name']:<25} {t['machine']:<15} {t['cpu']:<15} {boot:<6} {qga:<6} {r['board_name']}")
        if not r["qga_ok"] and r["details"]:
            print(f"  -> {r['details'][:70]}")

    any_worked = any(r["qga_ok"] for r in results)
    if any_worked:
        print(f"\n*** QGA WORKS with: ***")
        for r in results:
            if r["qga_ok"]:
                print(f"  {r['label']}")
    else:
        print(f"\n*** QGA did NOT respond on any configuration ***")

    with open("hypervisor-variant-results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to hypervisor-variant-results.json")


if __name__ == "__main__":
    main()
