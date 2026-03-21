# CLAUDE.md — Project Context for AI Agents

This file documents the mikropkl project for AI coding agents.  Read it before making changes.

## Project Purpose

`mikropkl` produces **declarative virtual machine packages** for MikroTik RouterOS CHR using [`pkl`](https://pkl-lang.org).  The primary output is UTM bundles (`.utm` directories) for macOS, with QEMU launch scripts (`qemu.sh` + `qemu.cfg`) for Linux and CI testing.

The goal is to streamline getting RouterOS CHR running — whether checking a config on an older version, trying a new feature, or bringing up multiple CHRs for network testing.  Without `mikropkl`, getting CHR running involves downloading images from MikroTik, navigating several UI dialogs or constructing long `qemu-system-*` command lines.  `mikropkl` replaces all that with declarative `pkl` manifests and `make`.

**Two delivery paths:**
- **UTM** (macOS-first): `utm://downloadVM?url=...` one-click install, or download ZIP and open.  UTM handles the VM lifecycle.
- **QEMU** (macOS + Linux): Each `.utm` bundle includes `qemu.sh` + `qemu.cfg`.  Unpack the ZIP, run `./qemu.sh`, get a RouterOS prompt.  Also used for CI validation.

The `.utm` bundle is a ZIP archive — structurally portable.  A future `mikropkl` CLI tool could manage QEMU-based instances from `~/.local/` or `~/.mikropkl/`, providing a Linux-native experience similar to UTM's on macOS.

**Platform focus**: macOS and Linux.  Windows/WSL is not a target — we won't document setup steps, but QEMU on WSL should work since the scripts are POSIX shell.  If someone reports a WSL issue, we'd consider it.  The core challenge on Windows is that there's no default virtualization platform equivalent to KVM or Apple's Hypervisor.framework, so the kind of automation `mikropkl` does doesn't map cleanly to `"brew install qemu"` or `"apt install qemu"`.

## Directory Structure

```
Makefile              ← two-phase build orchestration (source of truth for building)
Manifests/            ← one .pkl file per machine variant (amend Templates/)
Templates/            ← mid-level pkl templates (amend Pkl/utmzip.pkl)
Pkl/                  ← core pkl modules
  utmzip.pkl          ← root module: defines all file outputs for a .utm bundle
  QemuCfg.pkl         ← generates qemu.cfg (ini) + qemu.sh (launcher) for direct QEMU use
  Libvirt.pkl         ← generates libvirt.xml (experimental, disabled by default)
  CHR.pkl             ← RouterOS CHR download URL logic and SVG icon helpers
  UTM.pkl             ← UTM-specific types (SystemArchitecture, BackendType, etc.)
  Randomish.pkl       ← deterministic pseudo-random helpers (MAC address generation)
  URL.pkl, SVG.pkl    ← helper modules
  chr-version.pkl     ← resolves RouterOS version from release channel (env: CHR_VERSION)
Files/
  efi_vars.fd         ← UEFI variable store (copied into Apple-backend bundles)
  QEMU.md             ← user-facing QEMU deployment guide
Machines/             ← build output (git-ignored except .url/.size placeholders)
Lab/                  ← local experiments, debug scripts, investigation notes (NOT build artifacts)
  libvirt/            ← libvirt experiment docs and notes (see LIBVIRT.md inside)
  qemu-arm64/         ← QEMU aarch64 boot investigation (see NOTES.md inside)
  x86-direct-kernel/  ← x86 direct kernel boot experiments (see NOTES.md inside)
.github/workflows/
  chr.yaml            ← builds and releases UTM packages to GitHub Releases
  qemu-test.yaml      ← boots each QEMU machine via qemu.sh and runs REST API checks
  libvirt-test.yaml   ← historical: precursor to qemu-test.yaml (parses XML → raw QEMU)
  auto.yaml           ← automated trigger for chr.yaml on new RouterOS versions
```

## Lab/ — Local Experiments and Investigation

`Lab/` is the place for local-only test scripts, investigation notes, and one-off experiments — **not production code and not part of the build**.  When debugging a hard problem (e.g. a CI failure that needs offline root-cause analysis), create a subdirectory under `Lab/` and work there:

- `Lab/<topic>/NOTES.md` — findings, hypotheses, conclusions
- `Lab/<topic>/*.sh` — reproducible test scripts  
- `Lab/<topic>/*.py` — inspection/analysis utilities
- Disk images (`.img`, `.qcow2`, `.vdi`) are **git-ignored** — do not commit them
- Scripts and notes ARE tracked — commit them so future agents can resume investigation

When a fix is found in `Lab/`, graduate it to the appropriate production file (workflow, Pkl module, Makefile, etc.) and document the root cause in CLAUDE.md and/or the relevant `Lab/*/NOTES.md`.

## RouterOS CHR Image Reference

### Image variants

| Image | Source | Architecture | EFI partition | Boot method |
|---|---|---|---|---|
| `chr-<ver>.img` | download.mikrotik.com | x86_64 | **Proprietary** (not FAT) | SeaBIOS chain-loads custom boot sector |
| `chr-<ver>-arm64.img` | download.mikrotik.com | aarch64 | Standard FAT16 with `EFI/BOOT/BOOTAA64.EFI` | UEFI loads EFI stub kernel |
| `chr-efi.img` | `tikoci/fat-chr` GitHub | x86_64 | Standard FAT16 with `EFI/BOOT/BOOTX64.EFI` | UEFI loads EFI stub kernel |

**Key insight:** The standard x86 CHR image has a *proprietary* boot partition that looks
like an EFI System Partition in GPT but is **not FAT** — the OEM name, bytes/sector, and
sectors/cluster are all zero.  The kernel is stored at raw offset `0x80000` within this
partition.  OVMF/UEFI cannot read it.  SeaBIOS chain-loads via MBR → custom boot sector.

The `tikoci/fat-chr` tool reformats this partition into standard FAT16, placing the kernel
as `EFI/BOOT/BOOTX64.EFI` plus a `map` file (sector-number mapping table).  This is
required for Apple Virtualization.framework (which demands a proper UEFI boot path).

### Disk layout (both architectures, 128 MiB)

Hybrid GPT+MBR:
- **Partition 1**: "RouterOS Boot" — 32–33 MiB, typed as EFI System Partition in GPT
- **Partition 2**: "RouterOS" — ~94 MiB, ext4 root filesystem

### Kernel details

Both architectures: the kernel is a Linux EFI stub (PE/COFF + bzImage/Image dual format).

| | x86_64 | aarch64 |
|---|---|---|
| Kernel file | `BOOTX64.EFI` / bzImage | `BOOTAA64.EFI` / Image |
| Kernel version | 5.6.3-64 | 5.6.3 |
| Size | ~4.0 MiB | ~11.8 MiB |
| EFI stub | Yes (PE + bzImage) | Yes (PE + ARM64 Image) |
| Has initramfs | No | No |
| Direct `-kernel` boot | **Not viable** (hangs in real-mode setup) | **Not viable** (needs EFI boot services) |
| `VZLinuxBootLoader` | Not suitable (no initramfs, needs firmware) | Not suitable (same) |

See `Lab/x86-direct-kernel/NOTES.md` for full analysis of why `-kernel` doesn't work.

## Backend / Architecture Matrix

The project produces machine variants across two backends and two architectures.  The
backend name in the manifest (`*.qemu.*` vs `*.apple.*`) determines the **boot track**:

- **SeaBIOS track** (`*.qemu.*`): Uses MikroTik's standard x86 image with proprietary boot
  sector.  SeaBIOS chain-loads via MBR.  Simplest and fastest.  aarch64 `*.qemu.*` uses
  EDK2 UEFI with the standard ARM64 image.
- **EFI/VirtIO track** (`*.apple.*`): Uses UEFI firmware throughout.  x86_64 requires the
  repackaged FAT16 EFI image from `tikoci/fat-chr`.  aarch64 uses the standard ARM64 image
  (already FAT16 EFI).  On macOS, UTM uses Apple Virtualization.framework; the QEMU scripts
  in `*.apple.*` bundles mirror the same pure-VirtIO configuration for cross-platform testing.

| Machine | Backend | Arch | Firmware | Disk interface (plist) | Actual QEMU device | Image source |
|---|---|---|---|---|---|---|
| `chr.x86_64.qemu` | QEMU | x86_64 | SeaBIOS | VirtIO | `if=virtio` (virtio-blk-pci on q35) | MikroTik |
| `chr.aarch64.qemu` | QEMU | aarch64 | UEFI (EDK2) | NVMe (plist) | **virtio-blk-pci** (NOT NVMe) | MikroTik |
| `chr.x86_64.apple` | Apple VZ | x86_64 | Built-in UEFI | NVMe | NVMe (actual) | tikoci/fat-chr |
| `chr.aarch64.apple` | Apple VZ | aarch64 | Built-in UEFI | VirtIO | VirtIO (actual) | MikroTik |
| `rose.chr.x86_64.qemu` | QEMU | x86_64 | SeaBIOS | VirtIO | same + qcow2 additional disks | MikroTik |
| `rose.chr.aarch64.qemu` | QEMU | aarch64 | UEFI (EDK2) | NVMe (plist) | **virtio-blk-pci** | MikroTik |

"ROSE" variants add 4 × 10 GB qcow2 disks for multi-disk RouterOS testing.

All `*.apple.*` bundles also get `qemu.cfg` + `qemu.sh` (with UEFI firmware) for QEMU-based
testing.  These scripts don't aim to replicate Apple VZ faithfully — they provide a
pure-VirtIO QEMU configuration suitable for cross-platform CI and local testing.

### Important: VirtIO on aarch64

UTM's `config.plist` declares `Interface=NVMe` for aarch64 QEMU machines, but UTM
actually passes `-device virtio-blk-pci` to QEMU (NOT actual NVMe).  When running
QEMU outside UTM:

- **x86_64 (q35):** `if=virtio` shorthand works — resolves to `virtio-blk-pci`
- **aarch64 (virt):** `if=virtio` shorthand resolves to `virtio-blk-device` (MMIO),
  which **does NOT work** — RouterOS kernel lacks the `virtio-mmio` driver.
  Must use explicit:
  ```
  -drive file=disk.img,format=raw,if=none,id=drive1
  -device virtio-blk-pci,drive=drive1
  ```

### RouterOS kernel driver support

**Sources:** MikroTik GPL source (v7.2 kernel configs from `tikoci/mikrotik-gpl`),
binary string analysis of v7.23beta2 kernel images, and runtime QEMU testing.
The v7.2 configs are 3+ years old — MikroTik has significantly changed the arm64
config since then (added all virtio device drivers, EFI support, etc.).

**Bus/transport drivers:**

| Driver | x86_64 | aarch64 | Notes |
|---|---|---|---|
| `virtio_pci` | ✅ | ✅ | ACPI-based discovery (QEMU default) |
| `virtio_mmio` | ❌ | ❌ | Would need `if=virtio` on `virt` — not viable |
| `pci-host-ecam-generic` | N/A | ❌ | DTB-based generic PCIe — ARM only, not present |
| `PCI_HOST_GENERIC` | N/A | ❌ (config) | QEMU `virt` machine's PCIe host — disabled in 7.2 config |
| `marvell,armada7040` | ❌ | ✅ | ARM target hardware — no QEMU machine type |

**VirtIO device drivers:**

| Driver | x86_64 (7.23 binary) | aarch64 (7.23 binary) | x86_64 (7.2 config) | aarch64 (7.2 config) | Used by mikropkl | QEMU device |
| --- | --- | --- | --- | --- | --- | --- |
| `virtio_blk` | ✅ | ✅ | `=y` | **not set** | ✅ disk | `virtio-blk-pci` |
| `virtio_scsi` | ✅ | ✅ | (not listed) | **not set** | ❌ | `virtio-scsi-pci` |
| `virtio_net` | ✅ | ✅ | **not set** | **not set** | ✅ networking | `virtio-net-pci` |
| `virtio_console` | ✅ | ✅ | `=y` | **not set** | ❌ | `virtio-serial-pci` |
| `virtio_balloon` | ✅ | ✅ | `=m` | **not set** | ❌ | `virtio-balloon-pci` |
| `virtio_gpu` | ✅ | ✅ | not listed | not listed | ❌ | `virtio-gpu-pci` |
| `virtio_rproc_serial` | ✅ | ✅ | not listed | not listed | ❌ | remoteproc virtio serial |
| `9pnet_virtio` (v9fs) | **✅** | **❌** | `=y` | **not set** | ❌ | `virtio-9p-pci` |
| `virtiofs` | ❌ | ❌ | not in 5.6.3 | **not set** | — | `vhost-user-fs-pci` |

**Key insight — architecture divergence:** The x86_64 kernel has `CONFIG_9P_FS=y` +
`CONFIG_NET_9P_VIRTIO=y` (confirmed in both v7.2 config and v7.23 binary — protocol
versions 9P2000, 9P2000.L, 9P2000.u all present).  The aarch64 kernel has **none** of
these.  This reflects different heritage: x86 CHR was designed for hypervisor use
(Xen, Hyper-V, KVM support all present), while arm64 targeted Marvell hardware and
only gained virtio device drivers after v7.2.

**9p on x86_64 — present but not usable via RouterOS CLI:** QEMU accepts the
`-device virtio-9p-pci` and the guest kernel binds the `9pnet_virtio` driver
(confirmed via QEMU monitor PCI listing, device `1af4:1009`).  However, RouterOS
does not expose Linux `mount` commands, so the 9p filesystem cannot be mounted
through the normal RouterOS interface.  Container environments (`/container`) may
be able to access it.  See `Lab/virtio-9p/NOTES.md`.

**Other notable kernel configs (from v7.2 GPL source):**

| Feature | x86_64 | aarch64 | Notes |
|---|---|---|---|
| `CONFIG_EFI` | `=y` (+ stub) | **not set** | arm64 gained EFI after v7.2 |
| `CONFIG_KVM_GUEST` | `=y` | N/A | x86 CHR is KVM-aware (paravirt clock, etc.) |
| `CONFIG_HYPERV` | `=y` | N/A | Hyper-V guest support (balloon, storage, net) |
| `CONFIG_XEN` | `=y` | N/A | Xen PV/HVM guest support |
| `CONFIG_PARAVIRT` | `=y` | N/A | Paravirtualization framework |
| `CONFIG_E1000` / `E1000E` | `=m` | ❌ | Intel NIC emulation (QEMU `-device e1000`) |
| `CONFIG_PCNET32` | `=m` | ❌ | AMD PCnet (QEMU legacy NIC) |
| `CONFIG_8139CP` / `8139TOO` | `=m` | ❌ | Realtek RTL8139 (QEMU `-device rtl8139`) |
| `CONFIG_TULIP` | `=m` | ❌ | DEC Tulip (QEMU `-device tulip`) |
| `CONFIG_BLK_DEV_NVME` | `=y` | `=m` | NVMe block device |
| `CONFIG_ATA_PIIX` | `=y` | ❌ | IDE/SATA (QEMU PIIX/ICH9) |
| `CONFIG_VMWARE_PVSCSI` | `=y` | ❌ | VMware paravirtual SCSI |
| `CONFIG_NFS_FS` / `NFSD` | `=m` / `=m` | `=m` / `=m` | NFS client + server |
| `CONFIG_CIFS` | ❌ | `=m` | SMB/CIFS client (arm64 only in config) |
| `CONFIG_FUSE_FS` | ❌ | `=m` | FUSE (arm64 only in config) |
| `CONFIG_HW_RANDOM` | ❌ | `=y` | Hardware RNG |
| `CONFIG_VHOST_NET` | `=m` | ❌ | vhost-net acceleration |
| `CONFIG_SMP` | `=y` | (implied) | Multi-processor support |

**Alternatives for host-guest file sharing:** SMB (`/ip smb`), FTP, HTTP
(`/tool fetch`), REST API file upload, or SFTP.  See `Lab/virtio-9p/NOTES.md`.

### Network interface

All QEMU machines use `virtio-net-pci`.  The pkl module sets `Hardware = "virtio-net-pci"`
in the UTM Network config.  On Apple backend, UTM uses its own VirtIO implementation.

## QEMU Settings Reference

### x86_64 QEMU

```
qemu-system-x86_64 -M q35 -m 1024 -smp 2 \
  -drive file=chr-7.22.img,format=raw,if=virtio \
  -netdev user,id=net0,hostfwd=tcp::9180-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none -serial stdio
```

No UEFI firmware needed — SeaBIOS (QEMU default) chain-loads MikroTik's custom boot
sector.  UTM sets `UEFIBoot=false`, `Hypervisor=true`, `RNGDevice=true` for x86_64.

### aarch64 QEMU

```
qemu-system-aarch64 -M virt -cpu cortex-a710 -m 1024 -smp 2 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=efi-vars-copy.fd \
  -drive file=chr-7.22-arm64.img,format=raw,if=none,id=drive1 \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9180-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none -monitor none \
  -chardev socket,id=serial0,path=/tmp/serial.sock,server=on,wait=off \
  -serial chardev:serial0
```

Critical requirements:
- **UEFI pflash**: Both units must be identical size (64 MiB).  Use
  `AAVMF_CODE.fd` + `AAVMF_VARS.fd` on Ubuntu; `edk2-aarch64-code.fd` +
  `edk2-arm-vars.fd` on Homebrew.  Do NOT use `-bios` (no writable NVRAM).
  The compact `QEMU_EFI.fd` (2 MiB on `ubuntu-24.04-arm`) is unsuitable.
- **Explicit virtio-blk-pci**: Do NOT use `if=virtio` (resolves to MMIO on `virt`).
- **CPU**: `cortex-a710` matches the UTM config.plist setting.
- **No `-nographic`** when backgrounding: redirects serial to stdio, blocks without
  a terminal.  Use `-display none -monitor none -chardev socket... -serial chardev:...`.
- **TCG on macOS**: Add `-accel tcg,tb-size=256` (no KVM on macOS).

### Apple Virtualization.framework 

Uses the fat-chr image (`chr-efi.img`) with proper FAT16 EFI partition on x86_64.  UTM config:
`UEFIBoot=true`, `OperatingSystem=Linux`, NVMe disk interface, `efi_vars.fd` for
UEFI NVRAM.  No direct QEMU flags — Apple VZ handles UEFI internally.

## How the Build Works

The Makefile runs in **two recursive phases**:

1. **`make phase1`** → runs `pkl eval ./Manifests/*.pkl -m ./Machines`
   - pkl emits complete `.utm` directory trees under `Machines/`
   - Binary files it cannot create are represented as placeholder files:
     - `*.img.zip.url` — URL to download from MikroTik
     - `*.size` — qcow2 disk size in MiB (for `qemu-img create`)
     - `*.localcp` — filename of a file to copy from `Files/`
   - Also emits `qemu.cfg` + `qemu.sh` (enabled by default) with relative `./Data/` paths
   - All backends get `qemu.cfg` + `qemu.sh` — Apple backends use UEFI firmware in their QEMU scripts

2. **`make phase2`** → resolves placeholders:
   - `*.img.zip.url` → `wget` + `unzip` → raw `.img` disk (cached in `.url-cache/`)
   - `*.size` → `qemu-img create -f qcow2`
   - `*.localcp` → `cp` from `Files/`
   - `qemu-chmod` → makes `qemu.sh` scripts executable

Running `make` triggers `phase1` then recursively calls `make phase2`.

### Download caching (`.url-cache/`)

Phase 2 download rules cache fetched archives in `.url-cache/` keyed by
`<sha1-prefix>-<zip-basename>`.  Multiple machines that reference the same URL
(e.g. every x86_64 QEMU machine downloads `chr-7.22.img.zip`) share one cached
copy — the image is `unzip`/`cp`'d from cache into each machine's `Data/` directory.

- `make clean` removes `Machines/` but **preserves** `.url-cache/` — rebuilds
  reuse previously downloaded images.
- `make distclean` removes both `Machines/` and `.url-cache/`.
- `.url-cache/` is gitignored.  CI starts fresh (no cache), but local rebuilds
  skip downloads entirely when the version hasn't changed.
- Partial downloads are written to `*.tmp` and atomically renamed on success,
  so an interrupted download leaves no corrupt cache entry.

## pkl Module Relationships

```
Manifests/chr.x86_64.qemu.pkl
  amends Templates/chr.utmzip.pkl
    extends Pkl/utmzip.pkl          ← main output module
      imports Pkl/QemuCfg.pkl       ← produces qemu.cfg + qemu.sh
      imports Pkl/Libvirt.pkl       ← produces libvirt.xml (experimental, disabled by default)
      imports Pkl/Randomish.pkl     ← MAC address
      imports Pkl/CHR.pkl           ← download URL, icon SVG
      imports Pkl/UTM.pkl           ← types
```

`utmzip.pkl` produces a `output.files` map.  Each key is a path relative to the pkl output
directory (`Machines/`).  The value is a resource with `.text` or `.bytes`.

## Key pkl Patterns

- `when (backend == "QEMU" && qemuOutput) { ... }` — conditional output for qemu.cfg/qemu.sh
- `List(primaryImage) + additionalDisks.mapIndexed(...)` — build disk list
- No `pkl:xml` renderer is used — string interpolation for all XML/INI output

## Libvirt — Experimental (Disabled by Default)

`Libvirt.pkl` exists in `Pkl/` and generates `libvirt.xml` when `LIBVIRT_OUTPUT=true`.
It is **not** part of the standard build and is not included in releases.  The
`libvirt-test.yaml` workflow was the precursor to `qemu-test.yaml` — it parsed the
libvirt XML via `xmllint` just to construct raw QEMU command lines, which is how we
arrived at the current `qemu.sh`/`qemu.cfg` approach.

Treat libvirt as a potential future feature.  See `Lab/libvirt/LIBVIRT.md` for docs.
The code is harmless in `Pkl/Libvirt.pkl` (guarded by `libvirtOutput` flag, defaults
to `false`) and Makefile targets are preserved for experimentation.

## Known Limitations

### check-installation fails on aarch64 (all environments)

RouterOS `check-installation` REST POST runs a 32-bit ELF binary (`bin/bash` from the
NPK verification section — NOT real bash).  The ARM checker (29,619 bytes) and x86 checker
(16,972 bytes) have **fundamentally different logic**: the x86 checker always succeeds via
a `/bin/milo` exec fallback, while the ARM checker lacks this fallback and returns non-zero
when `/ram/` exists but contains no capability files (magic `0xbad0f11e`).

Capability files are created by RouterOS init from hardware DTB info.  On QEMU `virt`
with `acpi=on` (default), EDK2 generates an **empty DTB** ("EFI stub: Generating empty
DTB") → no hardware info → no `/ram/` capability files → ARM checker fails.

The ACPI/DTB trilemma is unresolvable:
- `acpi=on` → disk works (ACPI PCIe), but DTB empty → no capability files → check fails
- `acpi=off` + PCI → DTB present, but no `pci-host-ecam-generic` driver → disk not found
- `acpi=off` + MMIO → DTB present, but no `virtio-mmio` driver → kernel stalls

CPU model is irrelevant — tested cortex-a53/a72/neoverse-n1 all fail identically.
RouterOS continues booting normally (HTTP 200 works) — only the capability-file check fails.
The CI workflow skips this check on aarch64.

See `Lab/qemu-arm64/NOTES.md` for full binary reverse engineering details.

### Direct kernel boot not viable (either architecture)

QEMU's `-kernel` flag (Linux boot protocol) does not work for RouterOS CHR:
- **x86_64**: 16-bit real-mode setup code depends on BIOS INT services not present in
  QEMU's Linux boot protocol.  Prints "early console in setup code" then hangs.
- **aarch64**: EFI stub requires EFI boot services (memory map, runtime services).
- **EFI handover**: Entry point offset 0x190 lands in compressed data → `#UD` crash.
- **`VZLinuxBootLoader`**: Not suitable — no initramfs, kernel needs firmware.

See `Lab/x86-direct-kernel/NOTES.md` for full analysis.

### qemu.sh background mode and PID tracking

`qemu.sh --background` uses `nohup sh -c "exec $CMD"` to launch QEMU.  The `exec`
is critical — without it, `$!` captures the PID of the `sh -c` wrapper, not the
actual QEMU process.  Consequences of missing `exec`:

- `kill "$PID"` only kills the shell wrapper; QEMU becomes orphaned
- CPU/state diagnostics show the idle wrapper (0% CPU), not QEMU
- On Ubuntu (dash), `sh -c` does NOT forward SIGTERM to children
- Orphaned QEMU processes accumulate across sequential test runs, consuming
  memory and potentially causing resource contention for subsequent VMs

### Cross-architecture TCG: x86_64 on aarch64 runner (abandoned)

Running `qemu-system-x86_64` via TCG on an aarch64 host has a fundamental performance
issue: x86 I/O port instructions (`in`/`out`) have no ARM hardware equivalent (ARM uses
MMIO exclusively).  This is **not viable** despite extensive optimization attempts over
16 CI iterations:

- SeaBIOS q35: ~199% CPU, zero serial output, 300s timeout (I/O port init)
- OVMF q35 + legacy virtio: timeout (I/O port BARs for disk)
- OVMF `pc` + modern virtio (`disable-legacy="on"`): got further but stuck in
  timer calibration (PIT I/O ports 0x40-0x43)
- OVMF `pc` + modern virtio + HPET (`hpet="on"`): kernel advanced further
  (interrupts enabled, different RIP) but still timed out at 300s

The x86 I/O port bottleneck is pervasive — even with MMIO-based devices, the firmware
and kernel probe legacy I/O ports during init.  There is no practical path to making
x86_64 boot on ARM64 TCG within a usable timeout.

The reverse direction (aarch64 on x86_64 via TCG) works fine — boots in ~20s.
EDK2 UEFI uses 64-bit mode with MMIO throughout, and x86 hardware can emulate
ARM MMIO efficiently.

**CI strategy (adopted):**
- **x86_64 runner**: boots ALL machines (x86 native via KVM, aarch64 cross-arch via TCG)
- **aarch64 runner**: boots only native aarch64 machines (x86 machines skipped)
- This gives full coverage: every machine is tested natively on its matching runner,
  plus aarch64 gets additional cross-arch validation on the x86 runner.

See `Lab/x86-cross-arch/NOTES.md` for the full investigation and test scripts.

## RouterOS CLI Reference for QEMU Debugging

RouterOS does not expose a standard Linux shell.  Use these commands for hardware
inspection and file management when debugging QEMU device configurations.

### Hardware / PCI inspection

```routeros
# List PCI devices (equivalent to lspci)
/system/resource/hardware/print

# List IRQ assignments (shows which virtio devices have drivers bound)
/system/resource/irq/print

# System info (architecture, CPU, memory, uptime)
/system/resource/print
```

Example `/system/resource/hardware/print` output with virtio-9p-pci:

```text
# LOCATION      TYPE  CATEGORY                 VENDOR             NAME
0 0000:00:00.0  pci   Host bridge              Intel Corporation  440FX - 82441FX PMC [Natoma]
4 0000:00:02.0  pci   SCSI storage controller  Red Hat, Inc.      Virtio 1.0 block device
5 0000:00:03.0  pci   Ethernet controller      Red Hat, Inc.      Virtio 1.0 network device
6 0000:00:04.0  pci   Unclassified device      Red Hat, Inc.      Virtio 9P transport
```

### Disk and storage

```routeros
# List disks (block devices + network mounts with rose-storage)
/disk/print
/disk/print detail

# Add network disk (rose-storage package required)
# Valid types: nfs, smb, iscsi (no 9p type — see Lab/virtio-9p/NOTES.md)
/disk/add type=nfs nfs-address=10.0.2.2 nfs-share=/shared

# List files
/file/print
```

### Package management

```routeros
# List installed packages
/system/package/print

# Install a package: upload .npk via SCP then reboot
# From host: scp -P <ssh-port> package.npk admin@127.0.0.1:/
/system/reboot
```

### Network and services

```routeros
# List IP services (SSH, HTTP, etc.) and their ports
/ip/service/print

# List interfaces
/interface/print

# DHCP client address
/ip/address/print
```

### Accessing RouterOS from the host

```sh
# REST API (no auth on fresh install)
curl -sf -u admin: http://127.0.0.1:9180/rest/system/resource

# SSH (RouterOS CLI, not Linux shell)
ssh -o StrictHostKeyChecking=no -p <ssh-port> admin@127.0.0.1

# SCP file upload
scp -o StrictHostKeyChecking=no -P <ssh-port> file.npk admin@127.0.0.1:/

# Serial console (from --background mode)
socat - UNIX-CONNECT:/tmp/qemu-<machine>-serial.sock

# QEMU monitor (PCI info, registers, qtree)
echo "info pci" | socat - UNIX-CONNECT:/tmp/qemu-<machine>-monitor.sock
echo "info qtree" | socat - UNIX-CONNECT:/tmp/qemu-<machine>-monitor.sock
```

## Common Pitfalls

- **Running `pkl eval` without `CHR_VERSION` env**: defaults to "stable" channel.
  Always set `CHR_VERSION=<version>` for reproducible builds.
- **Partial build / stale Machines/**: `pkl` always writes all output files.  Run
  `make clean` before builds if you need a pristine state.  Use `make distclean`
  to also purge the download cache (`.url-cache/`).
- **qemu.cfg uses relative paths**: Disk paths in `qemu.cfg` are relative (`./Data/...`).
  `qemu.sh` changes to its own directory before launching QEMU so relative paths resolve
  correctly.  Downloaded `.utm` ZIPs from GitHub Releases work without path fixups.
- **macOS libvirt**: Not a supported testing configuration.  Use UTM for macOS.
- **Apple backend machines**: Do NOT get `libvirt.xml` — the
  `when (backend == "QEMU")` gate in `utmzip.pkl` prevents it.  However,
  `chr.x86_64.apple` DOES get `qemu.cfg` + `qemu.sh` (with OVMF instead of SeaBIOS)
  via a separate `when (backend == "Apple" && qemuOutput)` gate, enabling
  cross-arch CI testing on ARM64 hosts.
- **Makefile shell commands must be POSIX sh**: GitHub Actions Ubuntu runners use
  `dash` as `/bin/sh`, which Make invokes by default.  `dash` does **not** support
  `\xNN` hex escapes in `printf` — it outputs the literal text `\x00` (4 ASCII chars)
  instead of a null byte.  Always use **octal escapes** (`\NNN`) in `printf`.
  Similarly, `tr` on macOS in UTF-8 locales encodes `\377` as the 2-byte UTF-8
  sequence `c3 bf` instead of raw byte `0xFF` — prefix with `LC_ALL=C` for
  byte-level operation.  See `Lab/nvram-gen/NOTES.md` for the full comparison.

## Build Commands

```sh
# Full build (all machines — qemu.cfg + qemu.sh enabled, libvirt.xml disabled)
make

# Clean + rebuild (reuses cached downloads)
make clean && make CHR_VERSION=7.22

# Full clean including download cache
make distclean && make CHR_VERSION=7.22

# Disable QEMU scripts (just UTM bundles)
QEMU_OUTPUT=false make CHR_VERSION=7.22

# pkl only (no downloads)
pkl eval ./Manifests/*.pkl -m ./Machines

# Make qemu.sh executable (normally automatic in phase2)
make qemu-chmod

# Run a QEMU machine interactively (foreground, serial on stdio)
make qemu-run QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# Start a QEMU machine in the background (headless)
make qemu-start QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# Stop a running QEMU machine
make qemu-stop QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# Start all machines (auto-assigned ports 9180, 9181, ...)
make qemu-start-all

# Stop all running machines
make qemu-stop-all

# List machines with running/stopped state
make qemu-list

# Debug info: PIDs, logs, sockets, CPU/memory for all machines
make qemu-status
```

## Adding a New Machine

1. Create `Manifests/<name>.pkl` that amends a template:
   ```pkl
   amends "../Templates/chr.utmzip.pkl"
   import "../Pkl/CHR.pkl"
   backend = "QEMU"
   architecture = "aarch64"
   ```
2. Run `make` — pkl generates the bundle, make downloads disk images.
3. The `qemu-test.yaml` workflow will automatically pick it up via
   machine discovery (searches `Machines/*.utm/qemu.cfg`).

## GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `chr.yaml` | manual dispatch | Builds and publishes UTM packages to GitHub Releases |
| `auto.yaml` | scheduled | Triggers `chr.yaml` when a new RouterOS version is detected |
| `qemu-test.yaml` | manual dispatch | Boots each QEMU machine via qemu.sh and runs REST API checks |
| `libvirt-test.yaml` | manual dispatch | Historical: precursor to qemu-test.yaml (parses XML → raw QEMU) |

### qemu-test.yaml — How the CI Works

Similar structure to `libvirt-test.yaml`: build job + 2 test jobs (x86_64 + aarch64),
plus an optional macOS job (disabled by default — enable via `macos: true` dispatch input).

#### Cross-arch strategy
- **x86_64 runner**: boots ALL machines — x86 native via KVM, aarch64 cross-arch via TCG (~20s)
- **aarch64 runner**: boots only native aarch64 machines — x86 cross-arch skipped (not viable)
- **macOS runner** (`macos-15`, Apple Silicon): disabled by default (costs more, HVF
  unavailable on GitHub-hosted VMs — see below).  When enabled, boots native aarch64
  machines via TCG.
- Boot timing for each machine is displayed outside `::group::` blocks for visibility

#### Package installation
- Both runners install both architectures: `qemu-system-x86`, `qemu-system-arm`,
  `qemu-efi-aarch64` — x86 runner needs aarch64 packages for cross-arch TCG

#### macOS HVF — unavailable on GitHub-hosted runners

Hypervisor.framework (HVF) is **not available** on any GitHub-hosted macOS runner —
confirmed by [actions/runner-images#13505](https://github.com/actions/runner-images/issues/13505)
(closed as "not planned") and [GitHub docs](https://docs.github.com/en/actions/reference/runners/larger-runners#limitations-for-macos-larger-runners)
("Nested-virtualization is not supported").  This applies to all runner versions and sizes.
`qemu.sh` detects this via `sysctl -n kern.hv_support` and falls back to TCG.

#### macOS HVF — CPU model (when HVF is available, e.g. bare metal)

With `-accel hvf` on Apple Silicon, QEMU uses the host CPU directly via
Hypervisor.framework.  `cortex-a710` is ARMv9.0 and requires SVE2; Apple M-series chips
are ARMv8.5/8.6 and do not expose SVE2 through HVF.  Attempting `-cpu cortex-a710` with
HVF causes QEMU to crash during CPU init (before the VM even starts), which manifests as
socat getting "Connection refused" on the serial socket (the socket file exists from
`bind()` but QEMU never reached `listen()`).

**Fix (in `qemu.sh`, generated by `QemuCfg.pkl`):**
```sh
CPU_FLAGS="-cpu cortex-a710"         # KVM (Linux) / TCG default
if [ "$ACCEL" = "hvf" ]; then
  CPU_FLAGS="-cpu host"              # HVF: let QEMU use the real host CPU
fi
```

The serial socket race (socat "Connection refused") is a secondary symptom handled by
using `socat` with `retry=10,interval=1` in the workflow, so socat retries the connect
rather than failing immediately if QEMU hasn't called `listen()` yet.

#### CI conventions for `apt-get` and downloads

**`apt-get` pattern** (all workflows):
```yaml
run: |
  echo "::group::apt-get install"
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends PKG1 PKG2
  echo "::endgroup::"
```
- `DEBIAN_FRONTEND=noninteractive` — prevents dpkg prompts and debconf timeouts
- `-qq` — suppresses progress output (quieter than `-q`)
- `--no-install-recommends` — minimizes packages, faster install, smaller log
- `::group::` / `::endgroup::` — collapses output in GitHub Actions UI

**`curl` download pattern**: `curl -fsSL -o FILE URL`
- `-f` fail on HTTP error, `-s` silent, `-S` show errors, `-L` follow redirects

**`wget` download pattern** (Makefile): `wget -q -O FILE URL`
- `-q` quiet mode (no progress bar), `-O` output to specific file

#### Key differences from libvirt-test.yaml
- Uses `qemu.sh --background --port $PORT` instead of raw QEMU commands
- qemu.cfg ↔ config.pkl consistency check (pkl PCF is source of truth)
- **KVM cross-arch guard**: qemu.sh checks `HOST_ARCH` matches guest arch before
  using KVM; cross-arch guests always fall back to TCG
- Unique ports per machine (PORT_BASE + offset) to avoid TCP TIME_WAIT collisions

#### Boot diagnostics
- Each poll attempt logs process state and CPU% (`/proc/$PID/stat`, `ps -o %cpu`)
- QEMU debug logging: `-d guest_errors,unimp -D <logfile>` via `QEMU_EXTRA` env var
- QEMU monitor socket: `socat` queries `info cpus` / `info registers` on timeout
- On timeout: dumps QEMU stderr log, debug log, monitor register state, `ps` info,
  and `ss` listening ports
- Early exit if QEMU process dies during boot wait
- Debug logs uploaded as artifacts for post-mortem analysis

#### Timeouts
- HVF/KVM: 30s (6 × 5s polls)
- TCG: 60s (12 × 5s polls) — both native and cross-arch (aarch64 on x86)

#### Expected boot times (from CI observations)
- KVM native (x86 on x86): ~10s
- HVF native (aarch64 on macOS Apple Silicon): ~10s (estimated)
- TCG native (aarch64 on aarch64): ~20s
- TCG cross-arch (aarch64 on x86): ~20s
- TCG cross-arch (x86 on aarch64): not viable — skipped (see Known Limitations)

## Development Toolchain (macOS Intel)

### Required

| Tool | Install | Purpose |
|---|---|---|
| `pkl` | `brew install pkl` or download binary | pkl manifests → UTM bundles |
| `qemu-img` | `brew install qemu` | Create qcow2 spare disks (ROSE variants) |
| `make` | Xcode CLT | Build orchestration |
| `wget` | `brew install wget` | Download CHR disk images |
| `unzip` | Built-in | Extract .img.zip downloads |

### For QEMU local testing

| Tool | Install | Purpose |
|---|---|---|
| `qemu-system-x86_64` | `brew install qemu` | Run x86_64 CHR locally (TCG, no KVM on macOS) |
| `qemu-system-aarch64` | `brew install qemu` | Run aarch64 CHR locally |
| UEFI firmware | Bundled with `brew install qemu` | `edk2-aarch64-code.fd` + `edk2-arm-vars.fd` in `/usr/local/share/qemu/` (Intel) or `/opt/homebrew/share/qemu/` (Apple Silicon) |

### For disk image analysis / debugging

| Tool | Install | Purpose |
|---|---|---|
| `mtools` | `brew install mtools` | Read FAT filesystems without mounting (`mdir`, `mcopy` on .img partitions) |
| `fdisk` | Built-in | GPT/MBR partition table inspection (`fdisk -l` on Linux, `fdisk /dev/diskN` on macOS) |
| Python 3 | Built-in or `brew install python` | Analysis scripts (`struct` for binary parsing, PE/ELF inspection) |
| `file` | Built-in | Identify file types (kernel, ELF, PE) |
| `xxd` / `hexdump` | Built-in | Raw hex inspection of disk images and boot sectors |
| `hdiutil` | Built-in (macOS) | Attach/mount disk images (e.g., `hdiutil attach -nomount chr.img`) |

### For libvirt XML validation (experimental)

| Tool | Install | Purpose |
|---|---|---|
| `virt-xml-validate` | `brew install libvirt` (macOS) or `apt install libvirt-clients` (Linux) | Validate `libvirt.xml` against RelaxNG schema |
| `xmllint` | `brew install libxml2` (macOS) or `apt install libxml2-utils` (Linux) | XPath extraction from libvirt.xml (used by CI workflow and Makefile) |

### macOS-specific notes

- **No KVM on macOS**: QEMU uses TCG (software emulation).  Add `-accel tcg,tb-size=256`.
  x86_64 CHR boots in ~30-60s; aarch64 in ~60-120s under TCG.
- **Homebrew QEMU paths**: Firmware files are at `/usr/local/share/qemu/` (Intel)
  or `/opt/homebrew/share/qemu/` (Apple Silicon).  Linux uses `/usr/share/qemu/`
  or `/usr/share/AAVMF/`.
- **UTM testing**: `make utm-install` opens all built `.utm` bundles in UTM.app;
  `make utm-start/stop` controls VMs via AppleScript.
- **mtools for FAT inspection**: `mdir -i /tmp/efi.fat ::` lists files on the FAT
  partition without mounting.  Extract the EFI partition first with `dd`.

## Future Work

### macOS CI Workflow for UTM Validation (Priority: High)

GitHub Actions macOS runners do **not** support Hypervisor.framework (nested virtualization).
This means UTM/Apple VZ cannot run on GitHub-hosted runners.  A future workflow could still:
- Build `.utm` bundles and validate structure
- Use `utmctl` (UTM's CLI) for basic inspection
- Potentially test on self-hosted macOS runners with bare-metal hardware

### `mikropkl` CLI — Linux Deployment Tool (Priority: Medium)

A CLI tool that downloads and manages RouterOS CHR instances from GitHub Releases:
- Download `.utm` ZIP, extract, and manage in `~/.mikropkl/<machine-name>/`
- Start/stop via `qemu.sh` with PID tracking
- Support multiple versions side-by-side for topology testing
- Provide `--port` flag to override default port mapping
- Consider generating systemd units for persistent deployments

### fat-chr Integration into Makefile (Priority: Medium)

The `tikoci/fat-chr` repackaging step (converts proprietary x86 boot partition to FAT16
EFI) could be done directly in the Makefile using `qemu-img` and `mtools` (already
available as build dependencies).  This would eliminate the `auto.yaml` timing issue where
the mikropkl build triggers fat-chr but doesn't wait for it to complete.

### Post-Boot Automation (Priority: Low)

Scripts to configure RouterOS after initial boot:
- Set passwords, install packages, format ROSE disks
- Run via REST API or serial console automation (`expect` or similar)
- Could integrate with `bun` test framework for validation

### Multi-Version / Multi-Router Topology Testing (Priority: Low)

For testing RouterOS networking between instances:
- Generate bridge/tap configs for inter-VM communication
- Support naming and addressing scheme (router1, router2, etc.)
- Port range allocation (9181, 9182, etc.)
- Richer networking modes: bridged, shared (beyond current port-forwarding only)

### GitHub Pages Download Site (Priority: Low)

A website to view and download images — similar to `tikoci/restraml` pattern.

### GitHub Issue → Custom Package (Priority: Low)

Use Copilot Agent on GitHub to parse an Issue requesting a custom configuration,
generate a pkl template, build, and publish to Releases — without requiring `git clone`.
