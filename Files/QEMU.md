# Direct QEMU Deployment: `qemu.sh` and `qemu.cfg`

> [!NOTE]
> **Primary use case:** Bring up a version-specific RouterOS instance for testing configurations without installing UTM.  Works on macOS, Linux, and Windows Subsystem for Linux (WSL).

## Overview

When you download a RouterOS UTM machine from [GitHub Releases](https://github.com/tikoci/mikropkl/releases), you get a `.utm` file — which is actually a **ZIP archive** containing:

```
chr.x86_64.qemu.7.22.utm/
  config.plist              ← UTM VM configuration
  qemu.cfg                  ← QEMU --readconfig ini file
  qemu.sh                   ← Shell launcher script (handles platform-specifics)
  Data/
    chr-7.22.img            ← RouterOS CHR disk image
```

The `qemu.sh` and `qemu.cfg` files let you **run the same disk images outside UTM**, directly via QEMU on Linux, macOS, or WSL — without needing the UTM application.

This is useful for:
- Testing on headless Linux servers
- CI/CD integration
- Development scenarios where you don't have UTM installed
- Rapid version testing (spin up/down a specific RouterOS release in seconds)

## Downloading and Extracting

### From GitHub Releases

1. Go to [GitHub Releases](https://github.com/tikoci/mikropkl/releases)
2. Download the ZIP file for your desired machine and version
   - Example: `chr.x86_64.qemu.7.22.utm.zip` (x86_64 QEMU variant)
   - Example: `chr.aarch64.qemu.7.22.utm.zip` (ARM64 QEMU variant)
3. Extract the ZIP:
   ```bash
   unzip chr.x86_64.qemu.7.22.utm.zip
   cd chr.x86_64.qemu.7.22.utm
   ```

### URL Scheme (for scripting)

Release notes in GitHub include downloadable URLs.  You can script the download:

```bash
# Example: Download x86_64 QEMU variant, RouterOS 7.22
VERSION="7.22"
ARCH="x86_64"  # or "aarch64"
VARIANT="qemu"

ZIP_URL="https://github.com/tikoci/mikropkl/releases/download/chr-${VERSION}/chr.${ARCH}.${VARIANT}.${VERSION}.utm.zip"
curl -L "$ZIP_URL" -o machine.zip
unzip machine.zip
cd chr.${ARCH}.${VARIANT}.${VERSION}.utm
```

### From GitHub Raw CDN

If building from source, run `make CHR_VERSION=7.22` in the repo to generate the bundles locally:

```bash
git clone https://github.com/tikoci/mikropkl.git
cd mikropkl
make CHR_VERSION=7.22
cd Machines/chr.x86_64.qemu.7.22.utm
```

## Installation Requirements

QEMU and some supporting tools must be installed.  Choose your platform:

### macOS (Homebrew)

```bash
# Install QEMU and firmware
brew install qemu

# For macOS Intel (x86_64) OpenStack VirtualizationFramework
# Homebrew is already installed; no additional steps needed

# Verify installation:
qemu-system-x86_64 --version
qemu-system-aarch64 --version
```

**UEFI firmware paths** (automatically discovered by `qemu.sh` — no action needed):
- `/opt/homebrew/share/qemu/edk2-aarch64-code.fd` (Apple Silicon)
- `/usr/local/share/qemu/edk2-aarch64-code.fd` (Intel)
- Same directory: `edk2-arm-vars.fd`

### Ubuntu / Debian

#### x86_64 (Intel/AMD)

```bash
# Install QEMU and supporting tools
sudo apt-get update
sudo apt-get install qemu-system-x86 qemu-utils curl unzip

# For KVM acceleration (much faster than TCG):
sudo apt-get install qemu-kvm
sudo usermod -aG kvm "$USER"
# IMPORTANT: Log out and back in to activate the new group

# Verify:
qemu-system-x86_64 --version
ls -la /dev/kvm
```

#### aarch64 (ARM64)

```bash
# Install QEMU and UEFI firmware
sudo apt-get update
sudo apt-get install qemu-system-arm qemu-efi-aarch64 qemu-utils curl unzip

# For KVM acceleration (only on native ARM hardware):
sudo apt-get install qemu-kvm
sudo usermod -aG kvm "$USER"
# Log out and back in

# Verify:
qemu-system-aarch64 --version
ls -la /usr/share/AAVMF/AAVMF_CODE.fd
```

> **Note:** On `ubuntu-24.04-arm` (native ARM64), the UEFI firmware path is `/usr/share/AAVMF/AAVMF_CODE.fd` (symlink to `AAVMF_CODE.no-secboot.fd`). The `qemu.sh` script automatically handles this.

### Fedora / RHEL / CentOS

#### x86_64

```bash
sudo dnf install qemu-system-x86 qemu-img qemu-kvm curl unzip

# KVM group (if not already set up):
sudo usermod -aG kvm "$USER"
# Log out and back in
```

#### aarch64

```bash
sudo dnf install qemu-system-arm edk2-aarch64 qemu-img curl unzip
sudo dnf install qemu-kvm  # optional, for KVM acceleration
sudo usermod -aG kvm "$USER"
```

### Windows (WSL2)

Windows natively doesn't have an easy QEMU path in a command-line environment.  However, **WSL2 (Windows Subsystem for Linux) can run QEMU** if the WSL2 VM passes through nested virtualization.

#### WSL2 Setup

1. Install WSL2 (Windows 11):
   ```powershell
   wsl --install -d Ubuntu
   ```

2. Inside WSL2 Ubuntu terminal, install QEMU (same as Linux steps above):
   ```bash
   sudo apt-get install qemu-system-x86 qemu-system-arm qemu-utils qemu-efi-aarch64
   ```

3. **CRITICAL:** Check if KVM is available inside WSL2:
   ```bash
   ls -la /dev/kvm
   ```
   - If `/dev/kvm` exists and is readable, KVM acceleration is available — you're good.
   - If not, QEMU will fall back to TCG (software emulation), which is dramatically slower.

#### Performance Note

KVM inside WSL2 requires nested virtualization on the Windows host (Hyper-V, with KVM module passed through).  This may not be available on all Windows 11 setups.  If KVM is unavailable, TCG emulation is very slow (especially for cross-architecture like x86_64 on ARM64 Windows).

**For reliable testing on Windows, consider running a Linux VM (Ubuntu) in Hyper-V or another hypervisor.**

## Quick Start

### Run in Foreground (Serial to Console)

The simplest way to start a router and watch boot:

```bash
cd chr.x86_64.qemu.7.22.utm
./qemu.sh
```

You'll see RouterOS boot output.  To exit, type `exit` in the VM or press `Ctrl+A` then `x`.

#### First-time login

Default RouterOS credentials:
- Username: `admin`
- Password: *empty* (just press Enter)

#### Access the Web UI (while running in foreground)

In another terminal on the same machine:
```bash
curl -s http://localhost:9180/
export API_PASS=$(mktemp)
printf ':' > "$API_PASS"  # Empty password
curl -s --passfile "$API_PASS" http://admin@localhost:9180/rest/system/identity
```

### Run in Background (for scripts or headless)

```bash
cd chr.x86_64.qemu.7.22.utm
./qemu.sh --background
```

Output:
```
Starting chr.x86_64.qemu (port 9180, accel=kvm)...
QEMU PID=12345 — log: /tmp/qemu-chr.x86_64.qemu.log
Serial:  socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-serial.sock
Monitor: socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock
```

Background mode:
- QEMU runs as a background process (nohup)
- Logs go to `/tmp/qemu-<vmname>.log`
- Process PID is written to `/tmp/qemu-<vmname>.pid`
- Serial console is available via Unix socket
- QEMU monitor is available via Unix socket (for `info registers`, `info cpus`, etc.)
- To access serial console: `socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-serial.sock`
- To access monitor: `socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock`

### Stop a Background Instance

```bash
kill $(cat /tmp/qemu-chr.x86_64.qemu.pid)
# or simply:
kill 12345  # replace with actual PID
```

### Custom Port Forwarding

By default, RouterOS HTTP port 80 is forwarded to localhost port 9180.  Override with:

```bash
./qemu.sh --port 8080
# Now RouterOS is at http://localhost:8080/
```

Or set the environment variable:

```bash
QEMU_PORT=8080 ./qemu.sh --background
```

## File Descriptions

### `qemu.sh` — Launcher Script

The `qemu.sh` script is a **portable shell launcher** that handles platform-specific details:

```bash
./qemu.sh                          # Foreground, serial to stdio
./qemu.sh --background             # Background with nohup
./qemu.sh --port 9280              # Custom HTTP port
./qemu.sh --dry-run                # Print command without executing
```

**What it does:**

1. **Discovers QEMU binary** — searches for `qemu-system-x86_64` or `qemu-system-aarch64` in `$PATH`
2. **Detects KVM availability** — checks if `/dev/kvm` is writable and matches guest architecture
3. **Selects accelerator**:
   - Linux with matching architecture + `/dev/kvm`: `kvm` (native virtualization, ~5-20s boot)
   - Linux without KVM or cross-architecture: `tcg,tb-size=256` (emulation, ~20-100s boot)
   - macOS (Intel or Apple Silicon): `hvf` (native) or `tcg` (cross-arch)
4. **Handles UEFI firmware** (aarch64 only):
   - Searches standard paths: `/opt/homebrew/share/qemu/`, `/usr/local/share/qemu/`, `/usr/share/AAVMF/`
   - Creates a writable copy of UEFI variables in `/tmp/qemu-<vmname>-vars.fd`
   - Matches size of code ROM (both pflash units must be identical)
5. **Configures networking** — adds port forwarding: `-netdev user,id=net0,hostfwd=tcp::<port>-:80`
6. **Sets up serial/display**:
   - Foreground: serial to stdio
   - Background: serial via Unix socket at `/tmp/qemu-<vmname>-serial.sock`

### `qemu.cfg` — QEMU Configuration File

The `qemu.cfg` is a QEMU `--readconfig` INI format configuration file.  It defines:

```ini
[machine]
  type = "q35"              # x86_64, or "virt" for aarch64

[memory]
  size = "1024M"            # Memory in MiB

[smp-opts]
  cpus = "2"                # CPU count

[drive "drive0"]
  file = "./Data/chr-7.22.img"
  format = "raw"
  if = "virtio"             # x86_64 shorthand works fine

[drive "drive0"]            # aarch64: explicit if=none + device
  file = "./Data/chr-7.22.img"
  format = "raw"
  if = "none"

[device "virtio-blk-drive0"]
  driver = "virtio-blk-pci" # Ensures PCI, not MMIO on aarch64
  drive = "drive0"

[device "nic0"]
  driver = "virtio-net-pci" # Network interface
  netdev = "net0"
  mac = "52:54:00:..."      # Deterministic MAC based on machine name
```

You can also use `qemu.cfg` directly with raw QEMU (if you prefer not to use `qemu.sh`):

```bash
cd chr.x86_64.qemu.7.22.utm
qemu-system-x86_64 --readconfig qemu.cfg \
  -accel kvm \
  -netdev user,id=net0,hostfwd=tcp::9180-:80 \
  -nographic
```

However, **using `qemu.sh` is recommended** because it handles accelerator detection, UEFI firmware (aarch64), and port forwarding automatically.

## Architecture-Specific Details

### x86_64 Machines

- **Machine type:** `q35`
- **Firmware:** SeaBIOS (built-in to QEMU, no separate firmware file needed)
- **Disk interface:** `if=virtio` (resolves to `virtio-blk-pci`)
- **Boot time (with KVM):** ~5-10 seconds
- **Boot time (TCG):** ~30-60 seconds

### aarch64 Machines

- **Machine type:** `virt`
- **Firmware:** EDK2 UEFI (requires external files: `AAVMF_CODE.fd` + `AAVMF_VARS.fd`)
- **Disk interface:** **Must use** `-drive if=none,id=drive0 -device virtio-blk-pci,drive=drive0`
  - **Wrong:** `if=virtio` (resolves to MMIO on `virt` machine type → RouterOS kernel stalls)
  - **Right:** Explicit `-device virtio-blk-pci`
- **Boot time (native KVM on ARM host):** ~10-20 seconds
- **Boot time (TCG on ARM host):** ~30-60 seconds
- **Boot time (cross-arch: x86_64 host, TCG):** ~20-40 seconds
- **Note:** `qemu.sh` automatically uses the correct disk interface for your architecture

## Network Access and REST API

### Web UI (WebFig)

RouterOS HTTP server listens on port 80 inside the VM.  By default, `qemu.sh` forwards this to host port 9180:

```bash
curl http://localhost:9180/
# Output: HTTP 200 (HTML page, no auth required for initial page)
```

### REST API (JSON)

```bash
# Generic request (empty password, admin user)
curl -u admin: http://localhost:9180/rest/system/identity

# List interfaces
curl -u admin: http://localhost:9180/rest/interface

# Check system health
curl -u admin: http://localhost:9180/rest/system/health
```

### Serial Console (Background Mode)

If you're running in background mode and want to interact with the RouterOS CLI:

```bash
socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-serial.sock
```

Then type RouterOS commands.  Press `Ctrl+D` to exit.

### QEMU Monitor (Background Mode)

In background mode, a QEMU human monitor protocol (HMP) socket is exposed for diagnostics:

```bash
# Interactive monitor session
socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock

# One-shot commands
echo "info cpus" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock
echo "info registers" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock
echo "info block" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock
```

## Environment Variables for Advanced Use

You can override defaults by setting environment variables:

| Variable | Purpose | Example |
|---|---|---|
| `QEMU_BIN` | Override QEMU binary path | `QEMU_BIN=/opt/qemu/bin/qemu-system-x86_64 ./qemu.sh` |
| `QEMU_ACCEL` | Override accelerator | `QEMU_ACCEL=tcg ./qemu.sh` (force TCG, no KVM) |
| `QEMU_PORT` | Override HTTP forwarding port | `QEMU_PORT=8080 ./qemu.sh` |
| `QEMU_EXTRA` | Add extra QEMU flags | `QEMU_EXTRA="-smp 4" ./qemu.sh` (4 CPUs) |
| `QEMU_EFI_CODE` (aarch64 only) | Override UEFI code ROM path | `QEMU_EFI_CODE=/path/to/OVMF_CODE.fd ./qemu.sh` |
| `QEMU_EFI_VARS` (aarch64 only) | Override UEFI vars template | `QEMU_EFI_VARS=/path/to/OVMF_VARS.fd ./qemu.sh` |

## Foreground vs. Background Mode

### Foreground (Default)

```bash
./qemu.sh
```

**Characteristics:**
- QEMU output and RouterOS serial console appear directly in your terminal
- Press `Ctrl+A` then `x` to exit (QEMU monitor keybind)
- Or type `exit` in RouterOS CLI to shut down gracefully
- Suitable for interactive use, testing, debugging
- Blocks the terminal until QEMU exits

**Use when:**
- Inspecting boot output
- Debugging connectivity issues
- Interactive CLI testing
- Initial setup and configuration

### Background (Detached)

```bash
./qemu.sh --background
```

**Characteristics:**
- QEMU runs as a detached process (nohup)
- Terminal is immediately returned to you
- Output logged to `/tmp/qemu-<vmname>.log`
- Process PID saved in `/tmp/qemu-<vmname>.pid`
- Serial console accessible via Unix socket (`socat`)
- QEMU monitor accessible via Unix socket (for `info registers`, `info cpus`, etc.)
- Suitable for automation, CI/CD, long-running tests

**Use when:**
- Scripts or CI pipelines
- Running multiple routers simultaneously
- Long-duration topology testing
- Headless servers with no interactive access

### Multi-Router Testing

You can run multiple RouterOS instances simultaneously (on different ports):

```bash
cd chr.x86_64.qemu.7.22.utm
./qemu.sh --background --port 9180 &

cd ../chr.aarch64.qemu.7.22.utm
./qemu.sh --background --port 9181 &

# Now you have:
# Router 1 (x86_64) at http://localhost:9180/
# Router 2 (aarch64) at http://localhost:9181/
```

To stop them:
```bash
kill $(cat /tmp/qemu-chr.x86_64.qemu.pid)
kill $(cat /tmp/qemu-chr.aarch64.qemu.pid)
```

## Troubleshooting

### QEMU binary not found

```
ERROR: qemu-system-x86_64 not found. Install QEMU or set QEMU_BIN.
```

**Fix:** Install QEMU for your platform (see "Installation Requirements" above).

### KVM not available on Linux

```
WARNING: using tcg accelerator  (no /dev/kvm)
Starting chr.x86_64.qemu (port 9180, accel=tcg)...
```

RouterOS will still boot, but much slower (30-60s instead of 5-10s).

**To enable KVM:**
```bash
# Check if available
ls -la /dev/kvm

# If missing or not writable:
sudo modprobe kvm-intel      # Intel CPUs
# or
sudo modprobe kvm-amd        # AMD CPUs

# Add user to kvm group
sudo usermod -aG kvm "$USER"

# Log out and back in for the group change to take effect
# Verify:
id  # should show "kvm" in the output
```

### aarch64 slow boot or hangs during UEFI

RouterOS is stuck at "UEFI Startup" screen.

**Possible causes:**
1. **UEFI firmware files mismatched or missing** — `qemu.sh` searches for them automatically, but the search may fail
2. **Firmware size mismatch** — both pflash units must be identical in size (typically 64 MiB)

**Debug:**
```bash
QEMU_EFI_CODE=/usr/share/AAVMF/AAVMF_CODE.fd QEMU_EFI_VARS=/usr/share/AAVMF/AAVMF_VARS.fd ./qemu.sh --dry-run
# Review the output QEMU command, especially the -drive if=pflash flags
```

**Manual launch (for debugging):**
```bash
qemu-system-aarch64 --readconfig qemu.cfg \
  -accel tcg,tb-size=256 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=/usr/share/AAVMF/AAVMF_CODE.fd \
  -drive if=pflash,format=raw,unit=1,file=/tmp/qemu-vars.fd \
  -netdev user,id=net0,hostfwd=tcp::9180-:80 \
  -nographic
```

### RouterOS not responding to HTTP requests

You can see QEMU is running and boot completed, but `curl http://localhost:9180/` hangs or times out.

**Possible causes:**
1. RouterOS is still booting — wait longer
2. Port forwarding is not active — check the `qemu.sh` output for forwarding details
3. Firewall is blocking localhost:9180 — unlikely, but check `sudo lsof -i :9180`

**Debug:**
```bash
# Check if QEMU is running
ps aux | grep qemu

# Check if port 9180 is listening
netstat -tlnp | grep 9180
# or (macOS/BSD):
lsof -i :9180

# Check RouterOS log (if you have serial access):
socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-serial.sock
```

### Background QEMU process disappears after ./qemu.sh returns

The QEMU process exited immediately after launching.  Check the log:

```bash
cat /tmp/qemu-chr.x86_64.qemu.log
```

Common causes:
- Missing UEFI firmware (aarch64)
- Wrong disk image path
- Hardware acceleration not available and TCG failed to initialize

### x86_64 cross-architecture boot on ARM64 host (not viable)

Running `qemu-system-x86_64` via TCG on an aarch64 host is **not viable**.  Over 16 CI
iterations, progressively more aggressive optimizations were tried:

1. SeaBIOS + q35: ~199% CPU, zero serial output, 300s timeout
2. OVMF + q35 + legacy virtio: timeout (I/O port BARs for disk access)
3. OVMF + pc (i440fx) + modern virtio (`disable-legacy=on`): stuck in PIT timer calibration
4. OVMF + pc + modern virtio + HPET: kernel advanced further (interrupts enabled) but still timed out at 300s

The root cause is pervasive x86 I/O port probing (`in`/`out` instructions at ports
0x40-0x43, 0xCF8/0xCFC, 0xFED40000, etc.) during firmware and kernel init.  ARM64 has
no I/O port space — each access traps to TCG software emulation with 20-50x overhead.
No combination of machine type, firmware, or virtio mode can avoid this.

The reverse direction (aarch64 on x86_64) works fine — EDK2 UEFI uses 64-bit mode with
MMIO throughout, and x86 hardware can emulate ARM MMIO efficiently (~20s boot).

`qemu.sh` detects cross-arch x86-on-ARM64 and still applies mitigations (`pc` machine
type, `-nodefaults`) in case someone wants to experiment, but the CI workflow skips
these tests entirely.

For cross-arch debugging, use the QEMU monitor socket:

```bash
# Check where the vCPU is stuck (background mode)
echo "info cpus" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock
echo "info registers" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu-monitor.sock

# Enable debug logging for diagnosis
QEMU_EXTRA="-d guest_errors,unimp -D /tmp/qemu-debug.log" ./qemu.sh --background
```

### Port conflict (address already in use)

```
bind: permission denied
```

Another process is using port 9180.  Either:

1. Kill the other process:
   ```bash
   kill $(lsof -i :9180 -t)
   ```
2. Use a different port:
   ```bash
   ./qemu.sh --port 9181
   ```

## Performance Characteristics

### Native KVM (matching architecture)

| Machine | Boot time | Notes |
|---|---|---|
| x86_64 on x86_64 host (KVM) | ~5-15s | Fast, native virtualization |
| aarch64 on aarch64 host (KVM) | ~8-15s | Fast, native virtualization |

### TCG Emulation

| Machine | Host | Boot time | Notes |
|---|---|---|---|
| x86_64 (TCG) | x86_64 | ~30-60s | Software emulation (same-arch, no KVM) |
| aarch64 (TCG) | aarch64 | ~20s | Software emulation (same-arch, no KVM) |
| aarch64 (TCG) | x86_64 | ~20s | Cross-architecture — works well (MMIO-based) |
| x86_64 (TCG) | aarch64 | **not viable** | >300s — x86 I/O port bottleneck (see above) |

**TCG Performance Tuning:**

If TCG is bottlenecking your workflow, you can tune `tb-size` (translation block cache size):

```bash
QEMU_ACCEL="tcg,tb-size=512" ./qemu.sh
# Larger values may help or hurt depending on workload; experiment
```

## Known Limitations

### check-installation fails on aarch64

The RouterOS REST API endpoint `/rest/system/check-installation` returns HTTP 400 on aarch64 QEMU machines.  This is a **known limitation** — see [Lab/qemu-arm64/NOTES.md](../Lab/qemu-arm64/NOTES.md) for technical details.

**Workaround:** Ignore the `check-installation` failure for aarch64.  RouterOS continues to boot normally, and all other system functions (HTTP, REST API, CLI) work correctly.

### Routed  DHCPv4 via user-mode networking

RouterOS's `/ip dhcp-server` uses broadcast, which doesn't work well with QEMU's user-mode (SLIRP) networking.  If you need DHCP clients in the topology, use bridged or tapped interfaces (see QEMU advanced networking docs).

## Related Documentation

- [README.md](../README.md) — Project overview
- [LIBVIRT.md](LIBVIRT.md) — libvirt/virsh alternative for Linux VMs
- [AGENTS.md](../AGENTS.md) — Implementation details, architecture decisions
- [CLAUDE.md](../CLAUDE.md) — Full reference: QEMU settings, architecture matrix, build system
- [Lab/qemu-arm64/NOTES.md](../Lab/qemu-arm64/NOTES.md) — ARM64 check-installation root cause analysis
- [Lab/x86-direct-kernel/NOTES.md](../Lab/x86-direct-kernel/NOTES.md) — Why `-kernel` boot doesn't work

