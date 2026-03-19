# Copilot Instructions — mikropkl

## What This Project Does

`mikropkl` builds **declarative virtual machine packages** for MikroTik RouterOS CHR using [`pkl`](https://pkl-lang.org).  The primary output is UTM bundles (`.utm` directories) for macOS, with QEMU launch scripts (`qemu.sh` + `qemu.cfg`) for Linux and CI testing.

**Read `CLAUDE.md` first** — it is the comprehensive project reference.  `AGENTS.md` has deeper architecture decisions and investigation history for multi-session work.

## Core Concepts

- **Declarative configuration**: `pkl` manifests in `/Manifests` define machines.  `make` builds them to `/Machines`.  The `Makefile` is the source of truth for building.
- **Two boot tracks** for CHR:
  - **SeaBIOS track** (`*.qemu.*`): Standard MikroTik x86 image with proprietary boot sector.  QEMU loads via SeaBIOS chain-load.  Simplest and fastest.
  - **EFI/VirtIO track** (`*.apple.*`): Repackaged FAT16 EFI image (from `tikoci/fat-chr` for x86, standard for aarch64).  Uses UEFI firmware (OVMF or EDK2).  Required for Apple Virtualization.framework.  The QEMU versions of `*.apple.*` bundles mirror the same pure-VirtIO scheme that Virtualization.framework uses.
- **UTM-first, QEMU second**: UTM is the primary user experience on macOS.  QEMU scripts make the same bundles work on Linux and in CI.  A future CLI tool may manage QEMU-based instances from `~/.mikropkl/` or `~/.local/`.
- **Platforms**: macOS and Linux.  Windows/WSL is not a focus — we won't document setup steps, but won't reject bug reports either.

## Project Layout

| Directory | Purpose |
|-----------|---------|
| `Manifests/` | One `.pkl` per machine variant — what gets built |
| `Templates/` | Mid-level pkl templates (amend `Pkl/utmzip.pkl`) |
| `Pkl/` | Core pkl modules: `utmzip.pkl`, `QemuCfg.pkl`, `CHR.pkl`, `UTM.pkl`, etc. |
| `Machines/` | Build output (git-ignored).  One `.utm` directory per manifest |
| `Files/` | Static files and user-facing supplementary docs (`QEMU.md`, `efi_vars.fd`) |
| `Lab/` | Experiments, investigations, debug scripts — NOT production code |
| `.github/workflows/` | CI: `chr.yaml` (build+release), `auto.yaml` (version detection), `qemu-test.yaml` (QEMU validation) |

## Key Technical Facts

- RouterOS CHR kernel: Linux 5.6.3 (no initramfs, EFI stub)
- Default credentials: `admin` / (empty password)
- WebFig: port 80 (HTTP 200, no auth).  REST API: port 80 at `/rest/` (needs `admin:` basic auth)
- Disk: 128 MiB, hybrid GPT+MBR.  Partition 1 = boot, Partition 2 = ext4 root
- **aarch64 QEMU**: Must use explicit `-device virtio-blk-pci` (NOT `if=virtio`, which resolves to MMIO on `virt`)
- **x86_64 QEMU**: `if=virtio` shorthand works fine on `q35`
- `check-installation` always fails on aarch64 in QEMU — this is a known, unresolvable issue (ARM checker binary lacks fallback)
- Direct `-kernel` boot is not viable for either architecture

## Coding Conventions

- **pkl**: Use idiomatic pkl patterns — `amends`, `extends`, `when` blocks, typed properties.  `/Manifests` should be simple (4-6 lines).  Complexity lives in `/Pkl` and `/Templates`.
- **Makefile**: Idiomatic `make` — pattern rules, phony targets, recursive phases.  Prefer Makefile solutions before shell scripts or CI workarounds.
- **CI workflows**: Use `make` where possible.  Testing scripts in GitHub Actions are acceptable.  Collect diagnostic artifacts on failure for post-mortem analysis.
- **Lab/**: Use for experiments and investigations.  Include `NOTES.md` with findings.  Graduate fixes to production files when proven.

## Libvirt — Experimental

`Libvirt.pkl` exists but libvirt XML generation is **disabled by default** (`LIBVIRT_OUTPUT=false`).  The `libvirt-test.yaml` workflow was the precursor to `qemu-test.yaml` — it parsed libvirt XML via `xmllint` just to construct raw QEMU commands, which led to the current `qemu.sh`/`qemu.cfg` approach.  Treat libvirt as a potential future feature, not an active build option.  See `Lab/libvirt/` for docs.

## fat-chr Dependency

`chr.x86_64.apple` bundles require the repackaged EFI image from `tikoci/fat-chr`.  The `auto.yaml` workflow triggers fat-chr's auto build but does not wait for it to complete — this is a known timing issue.  Consider integrating the repackaging step directly into the Makefile since the tools (`qemu-img`, `mtools`) are already available.

## Cross-Architecture CI Strategy

- **x86_64 runner**: Boots ALL machines — x86 native (KVM), aarch64 cross-arch (TCG, ~20s)
- **aarch64 runner**: Boots only native aarch64 machines — x86 on ARM TCG is not viable
- **macOS runner**: HVF is unavailable on GitHub-hosted runners; falls back to TCG
- `qemu-test.yaml` is the primary CI validation path, with comprehensive diagnostics
