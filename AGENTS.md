# AGENTS.md — Agent Reference: Roadmap, Implementation Notes, and Decision Log

This document captures deeper technical context, architecture decisions, and planned
work items for AI coding agents working on this project.  It supplements CLAUDE.md
(which is the primary project reference) with information useful for multi-session
agent work.

## Architecture Summary

The project has three output layers, each derived from the same pkl manifests:

```
   pkl Manifests (.pkl)
        │
        ├─→ UTM bundle (.utm)       macOS/UTM.app — primary user-facing
        │     config.plist
        │     Data/ (disk images)
        │
        ├─→ libvirt.xml              Linux/QEMU — CI testing
        │     (in-bundle, QEMU backend only)
        │
        ├─→ qemu.cfg                 Linux/QEMU — portable bare-metal
        │     (QEMU --readconfig ini format, in-bundle)
        │
        └─→ qemu.sh                  Launch script for qemu.cfg
              (handles pflash, accel, networking, serial)
```

The `.utm` directory IS a ZIP archive — this is the key insight for Linux deployment.
UTM bundles are macOS-first but structurally portable.

## Image Pipeline

```
MikroTik download   ─→  chr-<ver>.img          (x86_64, proprietary boot)
                    ─→  chr-<ver>-arm64.img    (aarch64, standard FAT16 EFI)

tikoci/fat-chr      ─→  chr-efi.img            (x86_64, reformatted FAT16 EFI)
                        (required for Apple VZ / UEFI boot)
```

**When to use which image:**
- QEMU x86_64 → standard `chr-<ver>.img` + SeaBIOS (simplest, fastest)
- QEMU aarch64 → standard `chr-<ver>-arm64.img` + EDK2 UEFI pflash
- Apple VZ x86_64 → `chr-efi.img` from fat-chr (needs proper FAT EFI partition)
- Apple VZ aarch64 → [untested] standard ARM64 image should work (already FAT16)

## VirtIO Deep Dive

This is the single most important QEMU detail for this project. Getting the disk
interface wrong is the #1 cause of boot failures.

### Why UTM says "NVMe" but uses virtio-blk-pci on aarch64

UTM's translation layer maps plist `Interface=NVMe` differently per backend:
- **Apple backend**: actual NVMe (Virtualization.framework handles it)
- **QEMU backend**: UTM passes `-device virtio-blk-pci` regardless of the plist value

For agents: when parsing `config.plist`, do NOT trust the `Interface` field for QEMU
machines.  Check CLAUDE.md's "Backend / Architecture Matrix" for the ground truth.

### The `if=virtio` trap on aarch64

```
QEMU shorthand          q35 (x86_64)              virt (aarch64)
─────────────────────    ────────────────────      ─────────────────────
if=virtio                virtio-blk-pci (PCI)      virtio-blk-device (MMIO)  ← WRONG
-device virtio-blk-pci   virtio-blk-pci (PCI)      virtio-blk-pci (PCI)     ← CORRECT
```

RouterOS has `virtio_pci` but NOT `virtio_mmio`.  On `virt`, `if=virtio` resolves
to MMIO, which causes the kernel to stall.  Always use explicit `-device virtio-blk-pci`
on aarch64.

### Network — universal

All backends: `virtio-net-pci`.  No exceptions, no architecture differences.
The pkl module hardcodes `Hardware = "virtio-net-pci"` in the Network config.

## UEFI Firmware Matrix

| Platform | Code ROM | Vars File | Size | Notes |
|---|---|---|---|---|
| macOS Intel (Homebrew) | `/usr/local/share/qemu/edk2-aarch64-code.fd` | `edk2-arm-vars.fd` | 64 MiB each | Properly paired |
| macOS Apple Silicon | `/opt/homebrew/share/qemu/edk2-aarch64-code.fd` | `edk2-arm-vars.fd` | 64 MiB each | Properly paired |
| macOS Intel (x86 OVMF) | `/usr/local/share/qemu/edk2-x86_64-code.fd` | `edk2-i386-vars.fd` | 64 MiB each | For x86 UEFI testing |
| Ubuntu x86 runner | `/usr/share/AAVMF/AAVMF_CODE.fd` | `AAVMF_VARS.fd` | 64 MiB each | Preferred on CI |
| Ubuntu ARM runner | `/usr/share/AAVMF/AAVMF_CODE.fd` | `AAVMF_VARS.fd` | 64 MiB each | **Symlink** — use `stat -Lc%s`; avoid `QEMU_EFI.fd` (2 MiB) |

**Critical**: Both pflash units (code + vars) must be identical size.  Use
`dd if=/dev/zero of=VARS bs=1 count=0 seek=SIZE` to pad/trim (`truncate` is not available
everywhere; `qemu.sh` uses `dd` for portability).  On `ubuntu-24.04-arm`, `AAVMF_CODE.fd`
is a **symlink** (to `AAVMF_CODE.no-secboot.fd`).  Always use `stat -Lc%s` (with `-L`)
to get the real file size — without `-L`, `stat` returns the symlink path length (~24 bytes).

## Planned Work Items

### 1. QEMU `--readconfig` / ini config file — ✅ IMPLEMENTED

Implemented in `Pkl/QemuCfg.pkl`.  Generates `qemu.cfg` (QEMU --readconfig ini) and
`qemu.sh` (companion launcher) alongside `libvirt.xml` for each QEMU machine.

**What was built:**
- `QemuCfg.pkl` module with `config()` and `launchScript()` functions
- `qemu.cfg` covers: `[machine]`, `[memory]`, `[smp-opts]`, `[drive]`, `[device]`
- `qemu.sh` handles: UEFI pflash (aarch64), KVM/HVF/TCG detection, networking
  with port forwarding, display/serial config, `--background`/`--dry-run` modes
- Makefile targets: `qemu-list`, `qemu-fixpaths`, `qemu-chmod`, `qemu-run`, `qemu-stop`
- `qemu-test.yaml` CI workflow boots each machine via `qemu.sh` and runs REST API checks

**Limitations documented in generated files:**
- QEMU `--readconfig` cannot express: pflash drives, `-accel`, `-netdev user,hostfwd`,
  display/serial config.  These are handled by `qemu.sh`.
- `qemu.cfg` uses `/QEMU_DATA_PATH/` sentinel (like libvirt's `/LIBVIRT_DATA_PATH/`)
  replaced by `make qemu-fixpaths`; `qemu.sh` resolves paths at runtime automatically.

**Bug fix — background mode temp file race (b279532):**
The initial implementation used `mktemp` for the resolved qemu.cfg copy and set an
unconditional `EXIT` trap to delete it.  In `--background` mode, the parent shell exits
after `nohup ... &`, the trap fires, and QEMU (still starting up) finds the config file
deleted.  Fix: use deterministic paths (`/tmp/qemu-<name>.cfg`, `/tmp/qemu-<name>-vars.fd`)
and only set the cleanup trap in foreground mode.  **Pattern for agents:** when a shell
script creates temp files consumed by a backgrounded child process, either use deterministic
paths without cleanup traps, or use `mktemp` but skip the trap in background mode.

### 2. macOS CI Workflow for UTM Validation (Priority: High)

New workflow `utm-test.yaml`:
- Trigger: manual dispatch (same pattern as `libvirt-test.yaml`)
- Runner: `macos-13` (Intel) for x86_64 Apple VZ, `macos-15` (ARM) for aarch64
- Steps:
  1. Build bundles with `make`
  2. Install UTM: `brew install --cask utm`
  3. Open each `.utm` bundle: `open <bundle>.utm` or `utmctl` CLI
  4. Health check: poll `http://localhost:80/` (UTM port mapping may differ)
  5. REST API verification

**Considerations:**
- UTM port forwarding works differently from QEMU — need to check UTM's config for
  mapped ports or use `utmctl` to query
- Apple VZ machines may expose network differently (shared vs bridged)
- macOS runners cost more than Linux — keep test matrix minimal
- `utmctl` (UTM CLI) capabilities need investigation — it may support start/stop/status
- Test the `utm://downloadVM?url=` deep link scheme if possible

### 3. `chr_install.sh` — Linux Deployment Script (Priority: Medium)

A shell script that downloads and manages RouterOS CHR instances from GitHub Releases:

```sh
# Usage examples:
chr_install.sh install chr.x86_64.qemu 7.22    # download + unpack to ~/.mikropkl/
chr_install.sh list                              # show installed versions
chr_install.sh start chr.x86_64.qemu.7.22       # launch QEMU from qemu.cfg
chr_install.sh stop chr.x86_64.qemu.7.22        # stop running instance
```

**Storage convention:** `~/.mikropkl/<machine-name>/` with:
- `config.plist` (metadata, from UTM bundle)
- `qemu.cfg` (launch config, from UTM bundle)
- `Data/` (disk images)
- `run.pid` (PID of running QEMU process)

**Implementation notes:**
- Download `.utm` ZIP from GitHub Releases
- Unpack, locate `qemu.cfg`, fix disk paths to local storage
- Support multiple versions side-by-side for topology testing
- Provide `--port` flag to override default port mapping
- Consider generating systemd units for persistent deployments

### 4. Multi-Version / Multi-Router Topology Testing (Priority: Low)

For testing RouterOS networking between instances:
- Generate bridge/tap configs for inter-VM communication
- Support naming and addressing scheme (router1, router2, etc.)
- Port range allocation (9181, 9182, etc.)
- Optionally generate a `docker-compose.yml`-like manifest

This depends on items 1 and 3 above being complete first.

## Decision Log

### Why SeaBIOS for x86 QEMU (not UEFI)

MikroTik's standard x86 CHR image has a proprietary boot partition that OVMF cannot
read.  SeaBIOS chain-loads via MBR → custom boot sector and works out of the box.
UEFI boot requires the fat-chr reformatted image, which adds an external dependency
(`tikoci/fat-chr`).  SeaBIOS is simpler and faster for QEMU.

Apple VZ requires UEFI (no SeaBIOS option), so it uses the fat-chr image.

### Why `cortex-a710` for aarch64

UTM's default for aarch64 CHR.  The config.plist specifies `CPU = "cortex-a710"`,
and all CI testing uses this CPU model.  It's a Cortex-A710 compatible core profile
that works with RouterOS.  CPU model does NOT affect the `check-installation` issue —
tested cortex-a53, a72, neoverse-n1 and they all work identically.

### Why VirtIO (not NVMe) for QEMU

RouterOS CHR kernel has `virtio_pci` driver. While UTM's plist declares NVMe for
aarch64, UTM actually passes `virtio-blk-pci` — matching the kernel's capabilities.
True NVMe would require a different driver in the RouterOS kernel, which MikroTik
doesn't include in CHR builds.

### Why `host-passthrough` without `migratable`

Homebrew QEMU on macOS rejects `migratable="on"` — it's only meaningful for live
migration, which QEMU-on-macOS doesn't support.  `check="none"` is sufficient for
our use case.

### Why `/LIBVIRT_DATA_PATH/` sentinel (not relative paths)

Libvirt's RelaxNG schema requires absolute file paths in `<source file="">`.  The
regex pattern is `(/|[a-zA-Z]:\\).+` — relative paths fail with a misleading error.
The sentinel is a valid absolute path that `make libvirt-fixpaths` replaces at build
time.

### Why deterministic temp file paths in qemu.sh (not mktemp)

`mktemp` + `trap ... EXIT` is the standard pattern for temp file cleanup, but it breaks
when the script backgrounds a child process that needs the temp file.  The `EXIT` trap
fires when the parent shell exits — before the background child (QEMU) reads the file.
Using deterministic paths (`/tmp/qemu-<vmname>.cfg`) with no cleanup trap in background
mode avoids the race.  The trade-off is temp file leakage, but deterministic paths mean
repeated runs overwrite rather than accumulate, and `/tmp` is cleaned on reboot.

### Why SLIRP networking (not bridge/tap)

`<interface type="user">` (SLIRP) doesn't require root privileges or host network
configuration.  Good enough for CI testing where we just need HTTP access.  The
trade-off is no port forwarding in libvirt XML — we add it via QEMU command line.

## Useful Commands for Image Analysis

These are one-off commands useful when debugging disk images or boot issues.
See `Lab/*/NOTES.md` for full investigation context.

```sh
# Extract EFI partition from CHR image (partition 1 starts at sector 34, 33 MiB)
dd if=chr-7.22-arm64.img of=/tmp/efi.fat bs=512 skip=34 count=67537

# List files on FAT filesystem without mounting
mdir -i /tmp/efi.fat ::
mdir -i /tmp/efi.fat ::/EFI/BOOT/

# Extract kernel from FAT partition
mcopy -i /tmp/efi.fat ::/EFI/BOOT/BOOTAA64.EFI /tmp/kernel

# Identify kernel type
file /tmp/kernel

# Mount CHR image partition on macOS (read-only)
hdiutil attach -nomount chr-7.22.img
# then: diskutil list  to find partition device, mount manually

# Check QEMU firmware file sizes (pflash must match)
ls -la /usr/local/share/qemu/edk2-*
ls -la /opt/homebrew/share/qemu/edk2-*     # Apple Silicon

# Parse GPT with Python
python3 -c "
import struct
with open('chr-7.22.img', 'rb') as f:
    f.seek(512)  # GPT header at LBA 1
    hdr = f.read(92)
    sig, rev, hdr_sz, crc, _, my_lba, alt_lba, first, last, guid = struct.unpack('<8sIIII2Q2Q16s', hdr)
    print(f'GPT Signature: {sig}')
    print(f'First usable LBA: {first}, Last: {last}')
"

# Connect to RouterOS serial (QEMU socket)
socat - UNIX-CONNECT:/tmp/serial.sock

# Quick health check
curl -s -m 5 http://localhost:9180/ | head -1
curl -s -u "admin:" http://localhost:9180/rest/system/identity
```

## Lab Experiments Index

| Directory | Topic | Status | Key Finding |
|---|---|---|---|
| `Lab/qemu-arm64/` | ARM64 boot, check-installation | Complete | ARM checker binary lacks `/bin/milo` fallback; unresolvable ACPI/DTB trilemma |
| `Lab/x86-direct-kernel/` | x86 `-kernel` boot, UEFI handover | Complete | 16-bit setup needs BIOS INT; EFI handover offset hits compressed data |
| `Lab/report-arm64-chr-check-installation-failures.md` | User-facing report | Complete | Plain-language summary of ARM64 check failure |

Each `Lab/*/NOTES.md` contains reproducible test procedures and binary analysis details.

## Key Technical Facts (Quick Reference)

- RouterOS CHR kernel: Linux 5.6.3 (x86_64: `-64` suffix, aarch64: plain)
- Both kernels are EFI stub (PE/COFF dual format), no initramfs
- x86 bzImage: 4,020,448 bytes, XZ compressed payload
- ARM64 Image: ~11.8 MiB
- Disk: 128 MiB, hybrid GPT+MBR, partition 1 = boot, partition 2 = ext4 root
- Default credentials: admin / (empty password)
- WebFig: port 80 (HTTP 200 without auth)
- REST API: port 80 at `/rest/` (HTTP 401 without auth, use `admin:` basic auth)
- RouterOS version resolution: `pkl eval ./Pkl/chr-version.pkl` (reads `CHR_VERSION` env)
- MikroTik download URL pattern: `https://download.mikrotik.com/routeros/<ver>/chr-<ver>[-arm64].img.zip`
- fat-chr URL pattern: `https://github.com/tikoci/fat-chr/releases/download/<ver>/chr-<ver>.img.zip`
- Deterministic MAC: SHA1-based from machine name (see `Randomish.pkl`)
