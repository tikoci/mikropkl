# CLAUDE.md — Project Context for AI Agents

This file documents the mikropkl project for AI coding agents.  Read it before making changes.

## Project Purpose

`mikropkl` produces **UTM virtual machine bundles** (`.utm` directories) from [`pkl`](https://pkl-lang.org) manifests, with MikroTik RouterOS CHR as the primary guest OS.

Additional goals:
- Generate `qemu.sh` and `qemu.cfg` alongside each QEMU machine so the same disk images can be tested under QEMU/libvirt on Linux CI (GitHub Actions) or users without UTM like Linux.
Note: The `.utm` bundle is a ZIP archive — in principle usable as a deployment format on Linux too (see "Future Work" at the end of this document).

UTM is a macOS virtualization application.  **This project is macOS-first for users;
Linux CI is for automated testing only (currently).**

## Directory Structure

```
Makefile              ← two-phase build orchestration
Manifests/            ← one .pkl file per machine variant (amend Templates/)
Templates/            ← mid-level pkl templates (amend Pkl/utmzip.pkl)
Pkl/                  ← core pkl modules
  utmzip.pkl          ← root module: defines all file outputs for a .utm bundle
  Libvirt.pkl         ← generates libvirt.xml from UTM config fields (QEMU only)
  QemuCfg.pkl         ← generates qemu.cfg (ini) + qemu.sh (launcher) for direct QEMU use
  CHR.pkl             ← RouterOS CHR download URL logic and SVG icon helpers
  UTM.pkl             ← UTM-specific types (SystemArchitecture, BackendType, etc.)
  Randomish.pkl       ← deterministic pseudo-random helpers (MAC address generation)
  URL.pkl, SVG.pkl    ← helper modules
  chr-version.pkl     ← resolves RouterOS version from release channel (env: CHR_VERSION)
Files/
  efi_vars.fd         ← UEFI variable store (copied into Apple-backend bundles)
  LIBVIRT.md          ← libvirt-specific documentation (see below)
Machines/             ← build output (git-ignored except .url/.size placeholders)
Lab/                  ← local experiments, debug scripts, investigation notes (NOT build artifacts)
  qemu-arm64/         ← QEMU aarch64 boot investigation (see NOTES.md inside)
  x86-direct-kernel/  ← x86 direct kernel boot experiments (see NOTES.md inside)
.github/workflows/
  chr.yaml            ← builds and releases UTM packages to GitHub Releases
  libvirt-test.yaml   ← boots each QEMU machine in CI and checks installation
  qemu-test.yaml      ← boots each QEMU machine via qemu.sh and runs REST API checks
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

The project produces five machine variants across two backends and two architectures:

| Machine | Backend | Arch | Firmware | Disk interface (plist) | Actual QEMU device | Image source |
|---|---|---|---|---|---|---|
| `chr.x86_64.qemu` | QEMU | x86_64 | SeaBIOS | VirtIO | `if=virtio` (virtio-blk-pci on q35) | MikroTik |
| `chr.aarch64.qemu` | QEMU | aarch64 | UEFI (EDK2) | NVMe (plist) | **virtio-blk-pci** (NOT NVMe) | MikroTik |
| `chr.x86_64.apple` | Apple VZ | x86_64 | Built-in UEFI | NVMe | NVMe (actual) | tikoci/fat-chr |
| `rose.chr.x86_64.qemu` | QEMU | x86_64 | SeaBIOS | VirtIO | same + qcow2 additional disks | MikroTik |
| `rose.chr.aarch64.qemu` | QEMU | aarch64 | UEFI (EDK2) | NVMe (plist) | **virtio-blk-pci** | MikroTik |

"ROSE" variants add 4 × 10 GB qcow2 disks for multi-disk RouterOS testing.

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

### RouterOS kernel driver support (confirmed via binary analysis)

| Driver | x86_64 | aarch64 | Notes |
|---|---|---|---|
| `virtio_pci` | ✅ | ✅ | ACPI-based discovery (QEMU default) |
| `virtio_mmio` | ❌ unknown | ❌ | Would need `if=virtio` on `virt` — not viable |
| `pci-host-ecam-generic` | N/A | ❌ | DTB-based generic PCIe — ARM only, not present |
| `marvell,armada7040` | ❌ | ✅ | ARM target hardware — no QEMU machine type |

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

### Apple Virtualization.framework (Intel x86_64)

Uses the fat-chr image (`chr-efi.img`) with proper FAT16 EFI partition.  UTM config:
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
   - Also emits `qemu.cfg` + `qemu.sh` (QEMU machines only, enabled by default) with relative `./Data/` paths
   - Optionally emits `libvirt.xml` (QEMU machines only, disabled by default — enable with `LIBVIRT_OUTPUT=true`) with `/LIBVIRT_DATA_PATH/` sentinel

2. **`make phase2`** → resolves placeholders:
   - `*.img.zip.url` → `wget` + `unzip` → raw `.img` disk (cached in `.url-cache/`)
   - `*.size` → `qemu-img create -f qcow2`
   - `*.localcp` → `cp` from `Files/`
   - `libvirt-fixpaths` → replaces `/LIBVIRT_DATA_PATH/` sentinel with real absolute paths
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
      imports Pkl/Libvirt.pkl       ← produces libvirt.xml (QEMU only)
      imports Pkl/QemuCfg.pkl       ← produces qemu.cfg + qemu.sh (QEMU only)
      imports Pkl/Randomish.pkl     ← MAC address
      imports Pkl/CHR.pkl           ← download URL, icon SVG
      imports Pkl/UTM.pkl           ← types
```

`utmzip.pkl` produces a `output.files` map.  Each key is a path relative to the pkl output
directory (`Machines/`).  The value is a resource with `.text` or `.bytes`.

## Key pkl Patterns

- `when (backend == "QEMU") { ... }` — conditional output block for libvirt.xml
- `driveImageNames.mapIndexed((i, n) -> diskElement(i, n)).join("")` — list → XML string
- `List(primaryImage) + additionalDisks.mapIndexed(...)` — build disk list
- No `pkl:xml` renderer is used — the codebase uses string interpolation for all XML output
  (see `Libvirt.pkl` and the SVG helpers in `CHR.pkl`)

## Libvirt.pkl — Design Notes

See `Files/LIBVIRT.md` for end-user documentation.  Agent-relevant details:

### Architecture differences encoded in Libvirt.pkl

| Field | x86_64 | aarch64 |
|---|---|---|
| `<os>` | plain `<os>` (SeaBIOS) | `<os firmware="efi">` (libvirt auto UEFI) |
| machine type | `q35` | `virt` |
| serial target | `isa-serial` / `isa-serial` | `system-serial` / `pl011` |
| emulator path | `/usr/bin/qemu-system-x86_64` | `/usr/bin/qemu-system-aarch64` |
| features | `<acpi/>` + `<apic/>` | (none — `virt` has ACPI by default) |
| disk bus | `<target bus="virtio"/>` | `<target bus="virtio"/>` |

Both architectures use `<target bus="virtio"/>` in libvirt XML.  Libvirt maps this
to `virtio-blk-pci` on both `q35` and `virt` machine types — matching UTM/QEMU
behaviour.  The workflow uses explicit `-device virtio-blk-pci` for aarch64 when
launching QEMU directly (bypassing libvirt).

### Disk path sentinel

`Libvirt.pkl` writes `/LIBVIRT_DATA_PATH/<imagename>` in `<source file="">`.
This passes the libvirt RelaxNG `absFilePath` regex `(/|[a-zA-Z]:\\).+` while
remaining a valid placeholder.  `make libvirt-fixpaths` uses `perl -i -pe` to
substitute the real absolute path.

### Why no `migratable` on `<cpu>`

`migratable="on"` with `host-passthrough` is rejected by QEMU builds that don't support
live migration (including Homebrew QEMU on macOS).  It was removed; `check="none"` is enough.

### Network: user-mode (SLIRP)

`libvirt.xml` uses `<interface type="user">` for networking, which does not support
`hostfwd` port-forwarding via the libvirt XML alone.  Port forwarding requires either
`<qemu:commandline>` extensions in the XML, or launching QEMU directly with
`-netdev user,id=net0,hostfwd=tcp::9180-:80`.  The CI workflow uses the latter approach.

## libvirt-test.yaml — How the CI Works

### Build job (ubuntu-latest, x86_64)
- Installs pkl binary, resolves RouterOS version via `pkl eval ./Pkl/chr-version.pkl`
- Runs `make CHR_VERSION=<version>` which downloads real disk images from MikroTik
- Uploads entire `./Machines/` as an artifact

### Test job (matrix per machine, arch-matched runner)
- `aarch64` machines → `ubuntu-24.04-arm` (native ARM64)
- `x86_64` machines → `ubuntu-latest`
- Installs `qemu-system-arm` or `qemu-system-x86` (no full libvirt daemon needed)
- **KVM setup**: Always applies udev rule first, THEN checks `/dev/kvm` accessibility.
  KVM is available on `ubuntu-latest`; availability on `ubuntu-24.04-arm` varies.
- Without KVM on aarch64: must pass `-cpu cortex-a710` — matches the UTM config.plist
  CPU setting and is the model RouterOS CHR ARM64 is validated against.
  Also pass `-accel tcg,tb-size=256` for TCG performance.
- **aarch64 UEFI**: uses `-drive if=pflash,unit=0` (code, read-only) + `unit=1` (vars,
  writable copy of `QEMU_VARS.fd`). Do NOT use `-bios QEMU_EFI.fd` — newer EDK2 builds
  require a writable pflash1 for NVRAM; `-bios` only provides read-only code ROM and
  can prevent UEFI from completing initialisation.
  Both pflash units must be identical in size — truncate/pad the vars file to match
  the code ROM (typically 64 MiB on Ubuntu).
  **IMPORTANT**: On `ubuntu-24.04-arm` (native ARM runner), `qemu-efi-aarch64` installs
  `QEMU_EFI.fd` at only **2 MiB** — this is a compact variant unsuitable as the code ROM.
  Prefer `AAVMF_CODE.fd` + `AAVMF_VARS.fd` (both 64 MiB, from `qemu-efi-aarch64` package
  at `/usr/share/AAVMF/`). The workflow searches AAVMF first, then QEMU_EFI.fd as fallback.
  **IMPORTANT**: On `ubuntu-24.04-arm`, `AAVMF_CODE.fd` is a **symlink** (e.g. to
  `AAVMF_CODE.no-secboot.fd`).  Use `stat -Lc%s` (not `stat -c%s`) to get the real
  file size — without `-L`, `stat` returns the symlink target path length (~24 bytes)
  instead of the actual 64 MiB ROM size, causing pflash size mismatches.
- **aarch64 disks**: use `-drive if=none,id=driveN -device virtio-blk-pci,drive=driveN`.
  UTM maps its plist `Interface=NVMe` to `virtio-blk-pci` (NOT actual NVMe), and the
  `if=virtio` shorthand resolves to `virtio-blk-device` (MMIO) on the virt machine type,
  which is not what works.
- **Display / serial**: Do NOT use `-nographic` when QEMU is backgrounded — it redirects
  serial to stdio, which blocks indefinitely without an interactive terminal.  Use
  `-display none -monitor none -chardev socket,...,server=on,wait=off -serial chardev:...`
  instead.
- **Health check**: polls `http://localhost:9180/` (WebFig root, returns HTTP 200 without
  auth).  **Never** poll `/rest/` for health — it returns HTTP 401 which causes
  `curl --fail` to exit non-zero, making RouterOS look down even when it's running.
- **`check-installation` on aarch64**: always returns HTTP 400 `"damaged system package:
  bad image"` in QEMU (confirmed even on UTM/macOS). The CI workflow skips this check on
  aarch64.  See "Known Limitations" section below for full root cause analysis.
- **API calls**: use `http://admin:@localhost:9180/rest/…` (empty password = RouterOS default)
- **ROSE machines**: libvirt.xml contains multiple `<disk>` entries.  The workflow
  extracts ALL disks via `xmllint` loop and passes each as a separate QEMU `-drive` flag.
- **Timeouts**: KVM (any arch) = 2 min; x86_64 without KVM = 3 min; aarch64 without KVM = 4 min

### Port forwarding
`libvirt.xml` uses `<interface type="user">` (SLIRP), which does not support port
forwarding in the XML without `<qemu:commandline>` extensions.  The workflow launches QEMU
directly (not via `virsh start`) and adds `-netdev user,id=net0,hostfwd=tcp::9180-:80`.

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

## Common Pitfalls

- **Running `pkl eval` without `CHR_VERSION` env**: defaults to "stable" channel.
  Always set `CHR_VERSION=<version>` for reproducible builds.
- **Partial build / stale Machines/**: `pkl` always writes all output files.  Run
  `make clean` before builds if you need a pristine state.  Use `make distclean`
  to also purge the download cache (`.url-cache/`).
- **libvirt-fixpaths writes absolute paths**: If you move the `Machines/` directory,
  re-run `make libvirt-fixpaths` or re-run `make` from scratch.
- **qemu.cfg uses relative paths**: Disk paths in `qemu.cfg` are relative (`./Data/...`).
  `qemu.sh` changes to its own directory before launching QEMU so relative paths resolve
  correctly.  Downloaded `.utm` ZIPs from GitHub Releases work without path fixups.
- **macOS libvirt**: Not a supported testing configuration.  Use UTM for macOS.
- **Apple backend machines**: Do NOT get `libvirt.xml` — the
  `when (backend == "QEMU")` gate in `utmzip.pkl` prevents it.  However,
  `chr.x86_64.apple` DOES get `qemu.cfg` + `qemu.sh` (with OVMF instead of SeaBIOS)
  via a separate `when (backend == "Apple" && architecture == "x86_64")` gate, enabling
  cross-arch CI testing on ARM64 hosts.
- **libvirt.xml not generated by default**: Set `LIBVIRT_OUTPUT=true` to enable.
  The `libvirt-test.yaml` CI workflow sets this automatically.

## Build Commands

```sh
# Full build (all machines — qemu.cfg + qemu.sh enabled, libvirt.xml disabled)
make

# Clean + rebuild (reuses cached downloads)
make clean && make CHR_VERSION=7.22

# Full clean including download cache
make distclean && make CHR_VERSION=7.22

# Enable libvirt.xml output alongside QEMU scripts
LIBVIRT_OUTPUT=true make CHR_VERSION=7.22

# Disable QEMU scripts (just UTM bundles)
QEMU_OUTPUT=false make CHR_VERSION=7.22

# pkl only (no downloads)
pkl eval ./Manifests/*.pkl -m ./Machines

# Fix libvirt paths after pkl runs (normally automatic in phase2)
make libvirt-fixpaths

# Make qemu.sh executable (normally automatic in phase2)
make qemu-chmod

# Validate libvirt XML
make libvirt-validate   # requires: brew install libvirt (macOS) or apt libvirt-clients (Linux)

# Run a QEMU machine via qemu.sh (after build)
make qemu-run QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# Stop a running QEMU machine
make qemu-stop QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# List all qemu.cfg files
make qemu-list
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
3. If the new manifest is QEMU-backend, `libvirt.xml` is automatically produced.
4. The `libvirt-test.yaml` workflow will automatically pick it up via the `list-machines`
   step (searches for any `Machines/*.utm/libvirt.xml`).

## GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `chr.yaml` | manual dispatch | Builds and publishes UTM packages to GitHub Releases |
| `auto.yaml` | scheduled | Triggers `chr.yaml` when a new RouterOS version is detected |
| `libvirt-test.yaml` | manual dispatch | Boots all QEMU machines in CI and checks installation |
| `qemu-test.yaml` | manual dispatch | Boots each QEMU machine via qemu.sh and runs REST API checks |

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

### For libvirt XML validation

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

### macOS CI runners for UTM validation

GitHub Actions now offers `macos-13` (Intel) and `macos-14`/`macos-15` (Apple Silicon)
runners with UTM/Virtualization.framework support.  A new workflow could:
- Build the `.utm` bundles
- Install UTM via Homebrew Cask (`brew install --cask utm`)
- Use `utmctl` (UTM's CLI) or AppleScript to start VMs and verify HTTP health
- Test the Apple VZ backend (x86_64 on Intel runners, aarch64 on ARM runners)
- Validate that `utm://downloadVM?url=` install links work

This would complement the existing `libvirt-test.yaml` by covering the Apple backend.

### UTM bundle as Linux deployment format

Since `.utm` is a ZIP archive containing disk images + metadata, it could serve as a
deployment format beyond macOS:
- A `chr_install.sh` script could unpack `.utm` ZIP, locate disk images, and
  generate appropriate QEMU launch scripts or systemd units
- Local storage convention: `~/.mikropkl/<machine-name>/` for unpacked images
- Support multiple RouterOS versions side-by-side for testing networking topologies
- The script could download images automatically from GitHub Releases using the
  same URLs in `*.img.zip.url` placeholder files

### Multi-version RouterOS testing

The current build produces one version at a time.  For network topology testing
(multiple RouterOS instances with different versions), the project could:
- Support building multiple versions in parallel (`make CHR_VERSION=7.22 CHR_VERSION_2=7.18`)
- Generate bridge/tap networking configs for inter-VM communication
- Produce docker-compose-like orchestration for multi-router labs
