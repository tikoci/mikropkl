# Running mikropkl RouterOS CHR Machines — Agent Reference

**Audience:** A coding agent (LLM) working on `tikoci/restraml` or similar projects that need
a live RouterOS instance for API testing (`/console/inspect`, REST API, native API).

This guide covers: starting machines from this repo, port mappings for all RouterOS services,
multi-instance management, and CI (GitHub Actions) integration patterns.

---

## Quickstart — Start the ARM64 Machine

> **Why ARM64?** The aarch64 CHR image includes more RouterOS packages than the x86_64 image.
> For `/console/inspect` traversal and package-dependent API coverage, use aarch64.

From the repo root, the machines are **already built** in `Machines/`:

```sh
# Start ARM64 RouterOS in the background, forwarding all key ports
cd /path/to/mikropkl

QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9122-:22,hostfwd=tcp::9291-:8291,hostfwd=tcp::9728-:8728" \
  Machines/chr.aarch64.qemu.7.23beta5.utm/qemu.sh --background

# Wait ~20s for boot (TCG), then verify:
curl -sS -u "admin:" http://localhost:9180/rest/system/resource
```

Or use the latest stable version — substitute whichever version directories exist in `Machines/`.
List available:

```sh
ls Machines/*.utm
```

---

## Port Reference

All RouterOS services are inside the VM.  Forward them with `QEMU_NETDEV` (replaces the default
netdev — include all ports you need in one `QEMU_NETDEV` value).

| Service | Guest port | Suggested host port | Notes |
|---|---|---|---|
| HTTP / WebFig / REST API | 80 | **9180** | Default `--port` value |
| SSH | 22 | 9122 | RouterOS CLI, not Linux shell |
| WinBox / Tile | 8291 | 9291 | MikroTik proprietary GUI protocol |
| API (native Mikrotik) | 8728 | 9728 | RouterOS API (plaintext framed) |
| API-SSL | 8729 | 9729 | RouterOS API over TLS |
| Winbox/New | 8291 | 9291 | Same port as WinBox |

**REST API base URL:** `http://localhost:9180/rest`
**Native API:** TCP to `localhost:9728` (RouterOS sentence-based framed protocol)

Default credentials: `admin` / (empty password).

For REST: `-u "admin:"` (trailing colon, no password).
For native API clients: username `admin`, password `""` (empty string).

---

## Starting a Machine

### Option A — `qemu.sh` directly (most control)

```sh
cd Machines/chr.aarch64.qemu.7.23beta5.utm

# Foreground (serial on stdout, Ctrl-A X to quit):
./qemu.sh

# Background (headless, all services accessible):
./qemu.sh --background

# Background + extra ports (REST + SSH + native API):
QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9122-:22,hostfwd=tcp::9728-:8728" \
  ./qemu.sh --background

# Custom HTTP port:
./qemu.sh --background --port 9280

# Stop:
./qemu.sh --stop
```

---

## Waiting for Boot

RouterOS takes time to start.  The REST API becomes available at port 80 (forwarded to host
`9180` by default) once boot completes.  Poll with a timeout:

```sh
PORT=9180
MAX=24  # 24 × 5s = 120s (TCG needs up to ~60s; KVM/HVF ~10s)
for i in $(seq 1 $MAX); do
  if curl -sf --max-time 3 "http://localhost:${PORT}/" > /dev/null 2>&1; then
    echo "RouterOS ready"
    break
  fi
  echo "Waiting... attempt $i/$MAX"
  sleep 5
done
```

**Expected boot times (by accelerator):**

| Accelerator | Platform | Expected time |
|---|---|---|
| KVM | Linux (native arch) | ~10s |
| HVF | macOS bare-metal Apple Silicon | ~10s |
| TCG | Any (cross-arch or software emulation) | 20–60s |
| TCG aarch64 on x86_64 | Cross-arch | ~20s |
| TCG macOS GitHub runner | GitHub Actions `macos-15` | ~45s |

GitHub Actions macOS runners do NOT have HVF — `qemu.sh` detects this via `sysctl -n kern.hv_support`
and falls back to TCG automatically.

---

## Native RouterOS API (port 8728)

RouterOS has a proprietary binary-framed API on TCP port 8728 (TLS on 8729).
This is separate from the REST API.  To use it, forward port 8728:

```sh
QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9728-:8728" \
  ./qemu.sh --background
```

---

## Serial Console Access (Background Mode)

When running `--background`, QEMU creates Unix sockets for serial and monitor:

```sh
# Serial console — full RouterOS CLI
socat - UNIX-CONNECT:/tmp/qemu-chr.aarch64.qemu.7.23beta5-serial.sock

# QEMU monitor — hardware inspection
echo "info pci" | socat - UNIX-CONNECT:/tmp/qemu-chr.aarch64.qemu.7.23beta5-monitor.sock
```

Socket path pattern: `/tmp/qemu-<machine-name>-serial.sock`

The machine name comes from the `.utm` directory basename without the `.utm` suffix, e.g.
`chr.aarch64.qemu.7.23beta5`.

---

## Available Machines (Pre-built in Machines/)

| Directory | Arch | Boot | Extra disks | Notes |
|---|---|---|---|---|
| `chr.x86_64.qemu.<ver>.utm` | x86_64 | SeaBIOS | No | Fastest on Intel/AMD Linux (KVM) |
| `chr.aarch64.qemu.<ver>.utm` | aarch64 | UEFI (EDK2) | No | **Use this for restraml** — more packages |
| `chr.x86_64.apple.<ver>.utm` | x86_64 | UEFI (OVMF) | No | fat-chr image; also has qemu.sh |
| `chr.aarch64.apple.<ver>.utm` | aarch64 | UEFI (EDK2) | No | Same image as qemu, Apple VZ plist |
| `rose.chr.x86_64.qemu.<ver>.utm` | x86_64 | SeaBIOS | 4×10 GB | ROSE/multi-disk testing |
| `rose.chr.aarch64.qemu.<ver>.utm` | aarch64 | UEFI | 4×10 GB | ARM64 + ROSE disks |

Versions present depend on what `make` was last run with (e.g. `7.22.1`, `7.23beta5`).

```sh
# List all available versions of the aarch64 machine:
ls -d Machines/chr.aarch64.qemu.*.utm
```

---

## Running Multiple Instances

Each instance needs a unique port.  Use `--port` to differentiate:

```sh
# Start two versions side-by-side
QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9128-:8728" \
  Machines/chr.aarch64.qemu.7.22.1.utm/qemu.sh --background --port 9180

QEMU_NETDEV="user,id=net0,hostfwd=tcp::9280-:80,hostfwd=tcp::9228-:8728" \
  Machines/chr.aarch64.qemu.7.23beta5.utm/qemu.sh --background --port 9280

# Test both
curl -sS -u "admin:" http://localhost:9180/rest/system/resource | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['version'])"
curl -sS -u "admin:" http://localhost:9280/rest/system/resource | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['version'])"

# Stop both
Machines/chr.aarch64.qemu.7.22.1.utm/qemu.sh --stop
Machines/chr.aarch64.qemu.7.23beta5.utm/qemu.sh --stop
```
---

## Building Machines from Source

If machines are not present (fresh clone), build them first:

```sh
# Install dependencies (macOS)
brew install qemu make wget unzip
pip3 install pkl  # or: brew install pkl

# Install pkl (get binary from https://github.com/apple/pkl/releases)
curl -fsSL -o pkl https://github.com/apple/pkl/releases/download/0.30.2/pkl-macos-aarch64
chmod +x pkl && sudo cp pkl /usr/local/bin/pkl

# Build a specific version
make CHR_VERSION=7.23beta5

# Build all versions (downloads CHR images, ~128 MiB each, cached in .url-cache/)
make
```

For CI, use the pre-built artifact from the build job rather than rebuilding in each test
job (see CI section below).

---

## CI (GitHub Actions) Integration

### Strategy Summary

`qemu-test.yaml` in this repo is the reference CI implementation.  Key patterns to copy:

| Runner | Arch | Machines booted | Accelerator |
|---|---|---|---|
| `ubuntu-latest` (x86_64) | aarch64 + x86_64 | ALL | KVM for x86_64, TCG for aarch64 |
| `ubuntu-24.04-arm` (aarch64) | aarch64 only | aarch64 only | KVM for aarch64 |
| `macos-15` (arm64) | aarch64 only | aarch64 only | TCG (HVF unavailable in GH VMs) |

**Critical constraint:** x86_64 machines on aarch64 runners are **not viable** — x86 I/O port
emulation under TCG on ARM is too slow (never boots within 300s).  Only skip them; don't attempt.

### Minimal CI Job (aarch64 machine, all API ports)

```yaml
jobs:
  routeros-test:
    runs-on: ubuntu-latest    # x86_64 runner can run aarch64 via TCG

    steps:
      - uses: actions/checkout@v4

      - name: Install QEMU
        run: |
          sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
          sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
            qemu-system-arm qemu-efi-aarch64 qemu-utils wget make unzip

      - name: Install pkl
        run: |
          curl -fsSL -o pkl https://github.com/apple/pkl/releases/download/0.30.2/pkl-linux-amd64
          chmod +x pkl && sudo cp pkl /usr/local/bin/pkl

      - name: Enable KVM
        run: |
          echo 'KERNEL=="kvm", GROUP="kvm", MODE="0666"' | sudo tee /etc/udev/rules.d/99-kvm.rules
          sudo udevadm control --reload-rules && sudo udevadm trigger --name-match=kvm || true

      - name: Build machines
        run: make CHR_VERSION=7.23beta5
        # Or: use upload-artifact/download-artifact to share build across jobs

      - name: Make qemu.sh executable
        run: make qemu-chmod

      - name: Start RouterOS aarch64
        run: |
          # Forward HTTP (REST API) + native API
          QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9728-:8728" \
            Machines/chr.aarch64.qemu.7.23beta5.utm/qemu.sh --background
          # Note: KVM is NOT used here because guest=aarch64 but runner=x86_64.
          # qemu.sh auto-detects: HOST_ARCH x86_64 ≠ guest aarch64 → uses TCG.

      - name: Wait for RouterOS boot (TCG ~20-60s)
        run: |
          for i in $(seq 1 24); do
            if curl -sf --max-time 3 http://localhost:9180/ > /dev/null 2>&1; then
              echo "RouterOS ready after ~$((i*5))s"
              break
            fi
            [ $i -eq 24 ] && echo "TIMEOUT" && exit 1
            sleep 5
          done

      - name: Run /console/inspect tests
        run: |
          curl -sS -u "admin:" \
            -X POST http://localhost:9180/rest/console/inspect \
            -H "Content-Type: application/json" \
            -d '{"request":"get-child-list-ex","path":""}' \
            | python3 -m json.tool

      - name: Stop RouterOS
        if: always()
        run: Machines/chr.aarch64.qemu.7.23beta5.utm/qemu.sh --stop || true
```

### Environment Variables That `qemu.sh` Reads

| Variable | Effect |
|---|---|
| `QEMU_NETDEV` | Replaces the default user-mode netdev; include ALL `hostfwd=` entries |
| `QEMU_PORT` | Host port for HTTP (default: 9180); ignored if `QEMU_NETDEV` is set |
| `QEMU_ACCEL` | Override accelerator: `kvm`, `hvf`, `tcg`, `tcg,tb-size=256` |
| `QEMU_EXTRA` | Extra QEMU arguments appended verbatim (useful for `-d guest_errors,unimp -D log`) |
| `QEMU_BIN` | Override path to `qemu-system-aarch64` / `qemu-system-x86_64` |
| `QEMU_EFI_CODE` | Override UEFI code ROM path (aarch64) |
| `QEMU_EFI_VARS` | Override UEFI vars template path (aarch64) |

Example with diagnostics logging enabled:

```sh
QEMU_EXTRA="-d guest_errors,unimp -D /tmp/qemu-debug.log" \
QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9728-:8728" \
  ./qemu.sh --background
```

---

## Troubleshooting

### Serial console for boot debugging

```sh
# Capture serial output from boot start (must start socat before/right after qemu.sh)
SERIAL_SOCK="/tmp/qemu-chr.aarch64.qemu.7.23beta5-serial.sock"
socat -u "UNIX-CONNECT:${SERIAL_SOCK},retry=10,interval=1" STDOUT &
SOCAT_PID=$!
# ...start machine, wait for boot, run tests...
kill $SOCAT_PID 2>/dev/null
```

Use `retry=10,interval=1` — this handles the race where QEMU has called `bind()` on the socket
but not yet `listen()`.

### Check if the process is running

```sh
PID_FILE="/tmp/qemu-chr.aarch64.qemu.7.23beta5.pid"
PID=$(cat "$PID_FILE")
kill -0 "$PID" && echo "running" || echo "dead"
ps -p "$PID" -o pid,stat,%cpu,args
```

### Diagnose QEMU via monitor socket

```sh
MONITOR="/tmp/qemu-chr.aarch64.qemu.7.23beta5-monitor.sock"
echo "info pci"       | socat - UNIX-CONNECT:"$MONITOR"
echo "info cpus"      | socat - UNIX-CONNECT:"$MONITOR"
echo "info registers" | socat - UNIX-CONNECT:"$MONITOR" | head -30
echo "info qtree"     | socat - UNIX-CONNECT:"$MONITOR" | head -50
```

### check-installation on aarch64 always fails

The RouterOS ARM checker binary lacks a fallback path and always returns non-zero in QEMU.
This is a known, unresolvable issue (see `CLAUDE.md` § "check-installation fails on aarch64").
Skip it in tests; all other REST API endpoints work normally.

### Port already in use

`qemu.sh` checks for port conflicts before starting and emits a clear error.  Use `--port`
to change the host port:

```sh
./qemu.sh --background --port 9280
```

### aarch64 UEFI firmware not found

On Ubuntu, install `qemu-efi-aarch64`.  On macOS, `brew install qemu` includes it.
Or override:

```sh
QEMU_EFI_CODE=/path/to/AAVMF_CODE.fd \
QEMU_EFI_VARS=/path/to/AAVMF_VARS.fd \
  ./qemu.sh --background
```

On `ubuntu-24.04-arm`, `AAVMF_CODE.fd` is a symlink — `qemu.sh` uses `stat -Lc%s` (with `-L`)
to get the real file size.  This is already handled correctly.

---

## Key Files in Each Machine Bundle

```
chr.aarch64.qemu.7.23beta5.utm/
├── qemu.sh          ← Run this — platform detection, UEFI pflash, networking
├── qemu.cfg         ← QEMU --readconfig INI: machine type, memory, CPUs, disks
├── qemu.env         ← (create yourself) persistent overrides, sourced by qemu.sh
├── config.plist     ← UTM config (source of truth for hardware; pkl-generated)
└── Data/
    └── chr-7.23beta5-arm64.img   ← 128 MiB raw RouterOS disk image
```

`qemu.cfg` for the aarch64 machine uses `machine type = "virt"` with explicit
`-device virtio-blk-pci` (NOT `if=virtio`, which resolves to MMIO on `virt` and fails).
This is already correct in the generated file — do not change the disk interface.
