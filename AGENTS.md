# AGENTS.md — Agent Reference: Roadmap, Implementation Notes, and Decision Log

This document captures deeper technical context, architecture decisions, and planned
work items for AI coding agents working on this project.  It supplements CLAUDE.md
(which is the primary project reference) with information useful for multi-session
agent work.

## Architecture Summary

The project has two output layers, each derived from the same pkl manifests:

```
   pkl Manifests (.pkl)
        │
        ├─→ UTM bundle (.utm)       macOS/UTM.app — primary user-facing
        │     config.plist
        │     Data/ (disk images)
        │     qemu.cfg               QEMU --readconfig ini format
        │     qemu.sh                Launch script (pflash, accel, networking, serial)
        │
        └─→ (libvirt.xml)           Experimental — disabled by default
```

The `.utm` directory IS a ZIP archive — this is the key insight for Linux deployment.
UTM bundles are macOS-first but structurally portable.  Every bundle includes
`qemu.cfg` + `qemu.sh` so users on Linux (or macOS without UTM) can unpack the
ZIP and run QEMU directly.

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
- Apple VZ aarch64 → [untested] standard ARM64 image (already FAT16)

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
`qemu.sh` (companion launcher) for each machine.

**What was built:**
- `QemuCfg.pkl` module with `config()` and `launchScript()` functions
- `qemu.cfg` covers: `[machine]`, `[memory]`, `[smp-opts]`, `[drive]`, `[device]`
- `qemu.sh` handles: UEFI pflash (aarch64), KVM/HVF/TCG detection, networking
  with port forwarding, display/serial config, `--background`/`--dry-run` modes
- Makefile targets: `qemu-list`, `qemu-chmod`, `qemu-run`, `qemu-stop`
- `qemu-test.yaml` CI workflow: x86_64 runner boots ALL machines (x86 native via
  KVM, aarch64 cross-arch via TCG ~20s); aarch64 runner boots only native aarch64
  machines (x86 cross-arch abandoned after 16 CI iterations).  Both runners verify
  qemu.cfg ↔ config.pkl consistency.  Boot timing summary displayed outside
  `::group::` blocks for visibility.  QEMU debug logging (`-d guest_errors,unimp`)
  and monitor socket (`info cpus`/`info registers` via socat) provide post-mortem
  data on timeout.

**Limitations documented in generated files:**
- QEMU `--readconfig` cannot express: pflash drives, `-accel`, `-netdev user,hostfwd`,
  display/serial config.  These are handled by `qemu.sh`.
- `qemu.cfg` uses relative paths (`./Data/...`).  `qemu.sh` changes directory to its
  own location before launching QEMU so relative paths resolve correctly.  Downloaded
  `.utm` ZIPs from GitHub Releases work without any path fixups.

**Bug fix — background mode temp file race (b279532):**
The initial implementation used `mktemp` for the resolved qemu.cfg copy and set an
unconditional `EXIT` trap to delete it.  In `--background` mode, the parent shell exits
after `nohup ... &`, the trap fires, and QEMU (still starting up) finds the config file
deleted.  Fix: use deterministic paths (`/tmp/qemu-<name>-vars.fd`) and only set the
cleanup trap in foreground mode.  The later switch to relative paths in qemu.cfg eliminated
the temp config copy entirely — only the UEFI vars copy (aarch64) still needs temp file
handling.  **Pattern for agents:** when a shell script creates temp files consumed by a
backgrounded child process, either use deterministic paths without cleanup traps, or use
`mktemp` but skip the trap in background mode.

### 2. macOS CI Workflow for UTM Validation (Priority: High)

GitHub Actions macOS runners do **not** support Hypervisor.framework (nested virtualization).
A future workflow could still:
- Build `.utm` bundles and validate structure
- Use `utmctl` (UTM's CLI) for basic inspection
- Potentially test on self-hosted macOS runners with bare-metal hardware

**Considerations:**
- UTM port forwarding works differently from QEMU — need to check UTM's config for
  mapped ports or use `utmctl` to query
- Apple VZ machines may expose network differently (shared vs bridged)
- macOS runners cost more than Linux — keep test matrix minimal
- `utmctl` (UTM CLI) capabilities need investigation — it may support start/stop/status

### 3. `mikropkl` CLI — Linux Deployment Tool (Priority: Medium)

A CLI tool that downloads and manages RouterOS CHR instances from GitHub Releases:

```sh
# Usage examples:
mikropkl install chr.x86_64.qemu 7.22    # download + unpack to ~/.mikropkl/
mikropkl list                              # show installed versions
mikropkl start chr.x86_64.qemu.7.22       # launch QEMU from qemu.cfg
mikropkl stop chr.x86_64.qemu.7.22        # stop running instance
```

**Storage convention:** `~/.mikropkl/<machine-name>/` with:
- `config.plist` (UTM VM configuration, from UTM bundle)
- `qemu.cfg` (launch config, from UTM bundle)
- `qemu.sh` (launch script, from UTM bundle)
- `Data/` (disk images)
- `run.pid` (PID of running QEMU process)

**Implementation notes:**
- Download `.utm` ZIP from GitHub Releases
- Unpack — `qemu.cfg` uses relative paths, works without path fixups
- Support multiple versions side-by-side for topology testing
- Provide `--port` flag to override default port mapping
- Consider generating systemd units for persistent deployments

### 4. fat-chr Integration into Makefile (Priority: Medium)

The `tikoci/fat-chr` repackaging step (converts proprietary x86 boot partition to FAT16
EFI) could be done directly in the Makefile using `qemu-img` and `mtools` (already
available as build dependencies).  This would eliminate the `auto.yaml` timing issue
where the mikropkl build triggers fat-chr but doesn't wait for it to complete.

### 5. Multi-Version / Multi-Router Topology Testing (Priority: Low)

For testing RouterOS networking between instances:
- Generate bridge/tap configs for inter-VM communication
- Support naming and addressing scheme (router1, router2, etc.)
- Port range allocation (9181, 9182, etc.)
- Richer networking modes: bridged, shared (beyond current port-forwarding only)

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

### Why `host-passthrough` without `migratable` (libvirt — experimental)

Homebrew QEMU on macOS rejects `migratable="on"` — it's only meaningful for live
migration, which QEMU-on-macOS doesn't support.  `check="none"` is sufficient for
our use case.  This applies only to `Libvirt.pkl` output (disabled by default).

### Why `/LIBVIRT_DATA_PATH/` sentinel (libvirt — experimental)

Libvirt's RelaxNG schema requires absolute file paths in `<source file="">`.  The
regex pattern is `(/|[a-zA-Z]:\\).+` — relative paths fail with a misleading error.
The sentinel is a valid absolute path that `make libvirt-fixpaths` replaces at build
time.  This applies only to `Libvirt.pkl` output (disabled by default).

### Why deterministic temp file paths in qemu.sh (not mktemp)

`mktemp` + `trap ... EXIT` is the standard pattern for temp file cleanup, but it breaks
when the script backgrounds a child process that needs the temp file.  The `EXIT` trap
fires when the parent shell exits — before the background child (QEMU) reads the file.
Using deterministic paths (`/tmp/qemu-<vmname>.cfg`) with no cleanup trap in background
mode avoids the race.  The trade-off is temp file leakage, but deterministic paths mean
repeated runs overwrite rather than accumulate, and `/tmp` is cleaned on reboot.

### Why KVM requires host/guest architecture match in qemu.sh

`/dev/kvm` may be present and writable on a Linux host even when the QEMU guest is a
different architecture.  Running `qemu-system-aarch64 -accel kvm` on an x86_64 host
(or vice versa) crashes immediately.  `qemu.sh` gates KVM usage on
`[ "$HOST_ARCH" = "<guest-arch>" ]` so cross-architecture guests always fall back to
TCG.  Cross-arch TCG emulation: aarch64 CHR boots on an x86_64 runner in ~20s
(EDK2 UEFI uses 64-bit MMIO); x86_64 on ARM64 is not viable (I/O port bottleneck,
abandoned after 16 CI iterations — see decision log below).
High CPU (~194%) during cross-arch TCG is normal and confirms active emulation.

### Why `.apple.` machine gets `qemu.cfg` + `qemu.sh` with OVMF

The `chr.x86_64.apple` bundle already contains the fat-chr image (proper FAT16 EFI
partition).  All `*.apple.*` bundles get `qemu.cfg` + `qemu.sh` (gated by
`backend == "Apple" && qemuOutput` in `utmzip.pkl`).  The x86_64 apple machine's
`qemu.sh` uses OVMF (x86_64 UEFI firmware) instead of SeaBIOS, which starts in
64-bit mode with MMIO — no real-mode I/O port bottleneck.  This enables the apple
machine to be tested on native x86 runners via KVM (fastest boot: ~10s) alongside
the SeaBIOS machines.

**Note**: Cross-arch testing of x86_64 on ARM64 was attempted over 16 CI iterations
using `pc` + OVMF + modern virtio + HPET, but the pervasive x86 I/O port probing
(TPM at 0xFED40000, PIT at 0x40-0x43, ACPI, etc.) makes it not viable under ARM64 TCG.
The apple machine's `qemu.cfg`/`qemu.sh` now serve primarily for native x86 testing.

The apple machine's `qemu.cfg` uses the `pc` (i440fx) machine type instead of `q35`.
The i440fx has a much simpler PCI topology than q35's ICH9/PCIe root complex — fewer
built-in devices, a single flat PCI bus instead of a PCIe hierarchy.  This dramatically
reduces the number of PCI config space accesses (I/O ports 0xCF8/0xCFC) during OVMF
boot, which is critical for cross-arch TCG where every I/O port operation is trapped.

Virtio devices in `qemu.cfg` use explicit `[device]` sections with `disable-legacy = "on"`
(force virtio-1.0 modern transport, MMIO BARs instead of I/O port BARs).  Both OVMF and
Linux 5.6.3 support virtio-1.0 modern.  The launch script (`qemu.sh`) also passes
`-nodefaults` to skip unnecessary device enumeration.

There is no "faithfulness to config.plist" constraint for the apple machine's QEMU config —
Apple VZ doesn't use QEMU at all.  The `qemu.cfg`/`qemu.sh` exist purely for cross-arch
CI testing.

OVMF firmware paths searched (in order):
- macOS: `/opt/homebrew/share/qemu/edk2-x86_64-code.fd`, `/usr/local/share/qemu/...`
- Linux: `/usr/share/OVMF/OVMF_CODE.fd`, `OVMF_CODE_4M.fd`, `/usr/share/edk2/x64/...`
- Override: `QEMU_EFI_CODE` / `QEMU_EFI_VARS` environment variables

### Why `-cpu host` for HVF on macOS (not `cortex-a710`)

`cortex-a710` is an ARMv9.0 CPU model.  ARMv9.0 mandates SVE2 as a core feature.
Apple M-series chips (used in GitHub Actions `macos-15` runners) implement ARMv8.5/8.6,
not ARMv9.  When QEMU tries to set up `cortex-a710` with `-accel hvf`, the HVF backend
cannot satisfy the SVE2 requirement, and QEMU crashes during CPU initialization — before
actually starting the VM.  The crash is subtle: QEMU creates the chardev Unix socket
files (calls `bind()` early in init) but never reaches `listen()`, so socat clients get
"Connection refused" rather than a proper error message.

The same fix applies to x86_64 HVF on macOS Intel (`chr.x86_64.apple`).  Without
`-cpu host`, QEMU uses a default CPU model (e.g. `qemu64`) that requests AMD-specific
CPUID features — specifically the SVM bit (bit 2 of `CPUID[eax=80000001h].ECX`, AMD
Secure Virtual Machine / AMD-V).  Intel CPUs do not have SVM.  With HVF, QEMU passes
CPUID directly to the guest hardware, so OVMF receives a contradictory feature set and
hangs during initialization.  Using `-cpu host` exposes the real Intel CPUID, which OVMF
handles correctly.

**Fix in `qemu.sh` (generated by `QemuCfg.pkl`):**
```sh
CPU_FLAGS="-cpu cortex-a710"   # TCG/KVM default — emulates exact model
if [ "$ACCEL" = "hvf" ]; then
  CPU_FLAGS="-cpu host"        # HVF: expose real host CPU (avoid feature mismatch)
fi
```

For x86_64 UEFI machines (`useUefi=true`):
```sh
CPU_FLAGS=""                   # TCG/KVM: QEMU default CPU (qemu64 or similar)
if [ "$ACCEL" = "hvf" ]; then
  CPU_FLAGS="-cpu host"        # HVF: expose real Intel CPUID (no SVM)
fi
```

With `-cpu host` + HVF, QEMU passes the Mac's CPU features directly to the guest.
RouterOS CHR (Linux 5.6.3, generic x86_64) boots fine on Intel CPU features.

The default CPU model is preserved for TCG and KVM where it defines an exact emulation
target; `-cpu host` is only needed when QEMU maps guest CPUID directly to hardware.

**Secondary fix**: the workflow's socat serial capture now uses `retry=10,interval=1`
so it handles the race window between QEMU calling `bind()` and `listen()`.

### Why `sysctl kern.hv_support` check before selecting HVF

GitHub Actions `macos-15` runners are VMs on Apple Silicon — nested Hypervisor.framework
is not supported.  The previous `qemu.sh` detection logic assumed HVF was available on any
macOS host where `uname -m` = `arm64`, causing QEMU to crash with:

```
qemu-system-aarch64: -accel hvf: Error: ret = HV_UNSUPPORTED (0xfae9400f, at ../target/arm/hvf/hvf.c:843)
```

The `HV_UNSUPPORTED` error occurs during `hv_vm_create()` / `hv_vcpu_create()` in QEMU's
ARM HVF backend — the Hypervisor.framework API is present in the OS but the underlying
hardware virtualization support is not exposed to the VM guest.

**Fix**: `qemu.sh` now checks `sysctl -n kern.hv_support` (returns 1 if available, 0
otherwise) before selecting HVF.  When HVF is not available, it falls back to TCG.
The workflow's `Set accelerator info (macOS)` step also exports `HV_SUPPORT` for the
boot-test expected-accel calculation.

### Why ALL x86_64 machines are skipped on ARM64 runner

x86_64 on ARM64 TCG is fundamentally not viable.  Over 16 CI iterations, progressively
more aggressive optimizations were tried:

1. SeaBIOS + q35: 199% CPU, zero serial output, 300s timeout
2. OVMF + q35 + legacy virtio: timeout (I/O port BARs)
3. OVMF + pc + modern virtio (`disable-legacy=on`): stuck in PIT timer calibration
4. OVMF + pc + modern virtio + HPET: kernel reached further (interrupts enabled,
   new RIP), but still timed out at 300s

The root cause is pervasive: x86 firmware and kernel probe legacy I/O ports during
init (TPM at 0xFED40000, PIT at 0x40-0x43, ACPI PM at 0x600, etc.).  Each I/O port
access traps to ARM TCG emulation with no hardware equivalent, causing 20-50x overhead.
No combination of machine type, firmware, or virtio mode can avoid this.

The CI workflow now skips ALL x86_64 machines on the aarch64 runner.  The x86_64 runner
provides complete coverage: x86 native via KVM, aarch64 cross-arch via TCG.

### Why SLIRP / user-mode networking

QEMU's user-mode networking (`-netdev user,hostfwd=...`) doesn't require root
privileges or host network configuration.  Good enough for CI testing where we just
need HTTP access via port forwarding.  `qemu.sh` generates the appropriate
`-netdev user,id=net0,hostfwd=tcp::<port>-:80` arguments.  A future topology testing
feature may add bridge/tap support for inter-VM communication.

### Why `.url-cache/` with SHA1-keyed filenames

Multiple machines reference the same CHR download URL (e.g. every x86_64 QEMU machine
uses `chr-7.22.img.zip`).  Without caching, `make clean && make` re-downloads identical
images for each machine.  CHR images never change once a version is released.

Cache key is `<sha1-prefix>-<zip-basename>` where the SHA1 is computed from the full
URL string.  This avoids collisions between different sources that use the same zip
filename (e.g. `download.mikrotik.com/.../chr-7.22.img.zip` vs
`github.com/tikoci/fat-chr/.../chr-7.22.img.zip`).

Downloads use `*.tmp` + atomic `mv` to prevent corrupt cache entries from interrupted
downloads.  `make clean` preserves the cache; `make distclean` removes it.

### Why `::group::` + `-qq` + `--no-install-recommends` for apt-get in CI

`-q` (single) is still quite verbose — dpkg extraction messages flood the build log.
`-qq` suppresses nearly all output; `--no-install-recommends` avoids pulling in
unnecessary packages (faster, less log noise); `DEBIAN_FRONTEND=noninteractive`
prevents debconf prompts that hang CI.  `::group::` / `::endgroup::` collapses
any remaining output in the GitHub Actions log viewer so it doesn't obscure the
actual build and test output.

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
| `Lab/x86-cross-arch/` | x86_64 on ARM64 TCG | Complete | x86 I/O port bottleneck makes cross-arch TCG not viable; abandoned after 16 iterations |
| `Lab/libvirt/` | Libvirt XML generation | Experimental | Precursor to qemu.sh/qemu.cfg; `LIBVIRT.md` docs moved here from `Files/` |
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
