# CLAUDE.md — Project Context for AI Agents

This file documents the mikropkl project for AI coding agents.  Read it before making changes.

## Project Purpose

`mikropkl` produces **UTM virtual machine bundles** (`.utm` directories) from [`pkl`](https://pkl-lang.org) manifests, with MikroTik RouterOS CHR as the primary guest OS.

Secondary goal: generate `libvirt.xml` alongside each QEMU machine so the same disk images can be tested under QEMU/libvirt on Linux CI (GitHub Actions).

UTM is a macOS virtualization application.  **This project is macOS-first for users; Linux CI is for automated testing only.**

## Directory Structure

```
Makefile              ← two-phase build orchestration
Manifests/            ← one .pkl file per machine variant (amend Templates/)
Templates/            ← mid-level pkl templates (amend Pkl/utmzip.pkl)
Pkl/                  ← core pkl modules
  utmzip.pkl          ← root module: defines all file outputs for a .utm bundle
  Libvirt.pkl         ← generates libvirt.xml from UTM config fields (QEMU only)
  CHR.pkl             ← RouterOS CHR download URL logic and SVG icon helpers
  UTM.pkl             ← UTM-specific types (SystemArchitecture, BackendType, etc.)
  Randomish.pkl       ← deterministic pseudo-random helpers (MAC address generation)
  URL.pkl, SVG.pkl    ← helper modules
Files/
  efi_vars.fd         ← UEFI variable store (copied into Apple-backend bundles)
  LIBVIRT.md          ← libvirt-specific documentation (see below)
Machines/             ← build output (git-ignored except .url/.size placeholders)
.github/workflows/
  chr.yaml            ← builds and releases UTM packages to GitHub Releases
  libvirt-test.yaml   ← boots each QEMU machine in CI and checks /rest/system/check-installation
  auto.yaml           ← automated trigger for chr.yaml on new RouterOS versions
```

## How the Build Works

The Makefile runs in **two recursive phases**:

1. **`make phase1`** → runs `pkl eval ./Manifests/*.pkl -m ./Machines`
   - pkl emits complete `.utm` directory trees under `Machines/`
   - Binary files it cannot create are represented as placeholder files:
     - `*.img.zip.url` — URL to download from MikroTik
     - `*.size` — qcow2 disk size in MiB (for `qemu-img create`)
     - `*.localcp` — filename of a file to copy from `Files/`
   - Also emits `libvirt.xml` (QEMU machines only) with `/LIBVIRT_DATA_PATH/` sentinel in disk paths

2. **`make phase2`** → resolves placeholders:
   - `*.img.zip.url` → `wget` + `unzip` → raw `.img` disk
   - `*.size` → `qemu-img create -f qcow2`
   - `*.localcp` → `cp` from `Files/`
   - `libvirt-fixpaths` → replaces `/LIBVIRT_DATA_PATH/` sentinel with real absolute paths

Running `make` triggers `phase1` then recursively calls `make phase2`.

## pkl Module Relationships

```
Manifests/chr.x86_64.qemu.pkl
  amends Templates/chr.utmzip.pkl
    extends Pkl/utmzip.pkl          ← main output module
      imports Pkl/Libvirt.pkl       ← produces libvirt.xml (QEMU only)
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
| `<os>` | plain `<os>` | `<os firmware="efi">` (libvirt auto UEFI) |
| machine type | `q35` | `virt` |
| serial target | `isa-serial` / `isa-serial` | `system-serial` / `pl011` |
| emulator path | `/usr/bin/qemu-system-x86_64` | `/usr/bin/qemu-system-aarch64` |

### Disk path sentinel

`Libvirt.pkl` writes `/LIBVIRT_DATA_PATH/<imagename>` in `<source file="">`.
This passes the libvirt RelaxNG `absFilePath` regex `(/|[a-zA-Z]:\\).+` while
remaining a valid placeholder.  `make libvirt-fixpaths` uses `perl -i -pe` to
substitute the real absolute path.

### Why no `migratable` on `<cpu>`

`migratable="on"` with `host-passthrough` is rejected by QEMU builds that don't support
live migration (including Homebrew QEMU on macOS).  It was removed; `check="none"` is enough.

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
  `curl --fail` to exit non-zero, making RouterOS look down even when it's running
- **API calls**: use `http://admin:@localhost:9180/rest/…` (empty password = RouterOS default)
- **ROSE machines**: libvirt.xml contains multiple `<disk>` entries.  The workflow
  extracts ALL disks via `xmllint` loop and passes each as a separate QEMU `-drive` flag
- **Timeouts**: KVM (any arch) = 2 min; x86_64 without KVM = 3 min; aarch64 without KVM = 4 min

### Port forwarding
`libvirt.xml` uses `<interface type="user">` (SLIRP), which does not support port
forwarding in the XML without `<qemu:commandline>` extensions.  The workflow launches QEMU
directly (not via `virsh start`) and adds `-netdev user,id=net0,hostfwd=tcp::9180-:80`.

## Common Pitfalls

- **Running `pkl eval` without `CHR_VERSION` env**: defaults to "stable" channel.
  Always set `CHR_VERSION=<version>` for reproducible builds.
- **Partial build / stale Machines/**: `pkl` always writes all output files.  Run
  `make clean` before builds if you need a pristine state.
- **libvirt-fixpaths writes absolute paths**: If you move the `Machines/` directory,
  re-run `make libvirt-fixpaths` or re-run `make` from scratch.
- **macOS libvirt**: Not a supported testing configuration.  Use UTM for macOS.
- **Apple backend machines**: Do NOT get a `libvirt.xml` — the `when (backend == "QEMU")`
  gate in `utmzip.pkl` prevents it.

## Build Commands

```sh
# Full build (all machines)
make

# Clean + rebuild
make clean && make CHR_VERSION=7.22

# pkl only (no downloads)
pkl eval ./Manifests/*.pkl -m ./Machines

# Fix libvirt paths after pkl runs (normally automatic in phase2)
make libvirt-fixpaths

# Validate libvirt XML
make libvirt-validate   # requires: brew install libvirt (macOS) or apt libvirt-clients (Linux)
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
