#!/usr/bin/env python3
"""Quick probe of RouterOS system info via REST API to check hypervisor detection."""
import json, urllib.request, base64, sys, subprocess, time, os

sys.stdout = open(sys.stdout.fileno(), mode='w', buffering=1)

IMG = "chr-7.23_ab650-arm64.img"
EFI_CODE = "/usr/local/share/qemu/edk2-aarch64-code.fd"
EFI_VARS = "/usr/local/share/qemu/edk2-arm-vars.fd"
PORT = 9220
SERIAL_SOCK = "/tmp/probe-serial.sock"
VARS_COPY = "/tmp/probe-vars.fd"

os.chdir(os.path.dirname(os.path.abspath(__file__)))

for f in [SERIAL_SOCK, VARS_COPY]:
    try:
        os.unlink(f)
    except FileNotFoundError:
        pass

subprocess.run(["cp", EFI_VARS, VARS_COPY], check=True)

cmd = [
    "qemu-system-aarch64", "-M", "virt", "-cpu", "cortex-a710",
    "-m", "1024", "-smp", "2", "-accel", "tcg,tb-size=256",
    "-drive", f"if=pflash,format=raw,readonly=on,unit=0,file={EFI_CODE}",
    "-drive", f"if=pflash,format=raw,unit=1,file={VARS_COPY}",
    "-drive", f"file={IMG},format=raw,if=none,id=drive1",
    "-device", "virtio-blk-pci,drive=drive1,bootindex=0",
    "-netdev", f"user,id=net0,hostfwd=tcp::{PORT}-:80",
    "-device", "virtio-net-pci,netdev=net0",
    "-display", "none", "-monitor", "none",
    "-chardev", f"socket,id=serial0,path={SERIAL_SOCK},server=on,wait=off",
    "-serial", "chardev:serial0",
]

print("Booting aarch64 CHR...")
proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

for i in range(60):
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=3)
        if r.status == 200:
            print(f"Booted in ~{(i+1)*5}s")
            break
    except Exception:
        pass
    time.sleep(5)
else:
    print("TIMEOUT")
    proc.kill()
    sys.exit(1)

auth = 'Basic ' + base64.b64encode(b'admin:').decode()

endpoints = [
    "system/resource",
    "system/license",
    "system/routerboard",
    "system/package",
    "system/health",
    "ip/service",
]

for ep in endpoints:
    print(f"\n=== /rest/{ep} ===")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/rest/{ep}")
    req.add_header('Authorization', auth)
    try:
        r = urllib.request.urlopen(req, timeout=5)
        data = json.loads(r.read())
        print(json.dumps(data, indent=2))
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"HTTP {e.code}: {body}")
    except Exception as e:
        print(f"Error: {e}")

proc.terminate()
try:
    proc.wait(10)
except subprocess.TimeoutExpired:
    proc.kill()

for f in [SERIAL_SOCK, VARS_COPY]:
    try:
        os.unlink(f)
    except FileNotFoundError:
        pass
