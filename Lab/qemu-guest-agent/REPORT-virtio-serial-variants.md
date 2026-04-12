# Follow-Up: ARM64 CHR Guest Agent — Comprehensive Testing

## Context

Following your suggestion to try `-device virtio-serial` instead of `-device virtio-serial-pci`, I ran a comprehensive set of tests with `chr-7.23_ab650-arm64.img`.  Beyond the transport variant, I also tested different machine types, CPU models, interrupt controllers, and SMBIOS hypervisor identities — attempting to replicate the conditions your testing environment might have.

## Part 1: `virtio-serial` Is an Alias for `virtio-serial-pci`

In QEMU 10.2.2, `-device virtio-serial` and `-device virtio-serial-pci` are the **same device**:

```
$ qemu-system-aarch64 -M virt -device help | grep virtio-serial
name "virtio-serial-device", bus virtio-bus
name "virtio-serial-pci", bus PCI, alias "virtio-serial"    ← alias
name "virtio-serial-pci-non-transitional", bus PCI
```

They produce identical QEMU device trees — same PCI address, same driver binding, same behavior.

### Transport Variant Results

All 4 virtio-serial transports available in QEMU:

| QEMU Device | Transport | PCI Detected | Kernel Driver Bound | QGA Responds |
|---|---|---|---|---|
| `virtio-serial` | PCI (alias) | Yes — "Virtio console" | Yes (IRQs allocated) | **No** |
| `virtio-serial-pci` | PCI | Yes — "Virtio console" | Yes (IRQs allocated) | **No** |
| `virtio-serial-device` | MMIO | No (not a PCI device) | No (`virtio_mmio` not in kernel) | **No** |
| `virtio-serial-pci-non-transitional` | PCI (modern-only) | Yes — "Virtio 1.0 console" | Yes (IRQs allocated) | **No** |

## Part 2: Machine Type, CPU, and Hypervisor Variants

I also tested whether a different QEMU environment might trigger the QGA daemon:

| Configuration | Key QEMU Flags | Boot | QGA | board-name |
|---|---|---|---|---|
| SMBIOS = KVM | `-smbios type=1,...product=KVM Virtual Machine` | OK | **No** | CHR QEMU KVM Virtual Machine |
| SMBIOS = Proxmox | `-smbios type=1,...product=Standard PC (Q35 + ICH9)` | OK | **No** | CHR QEMU Standard PC (Q35+ICH9) |
| CPU neoverse-n1 | `-cpu neoverse-n1` | OK | **No** | CHR QEMU QEMU Virtual Machine |
| Machine sbsa-ref | `-M sbsa-ref` | **Timeout** | — | — |
| GICv3 + neoverse-n1 | `-M virt,gic-version=3 -cpu neoverse-n1` | OK | **No** | CHR QEMU KVM Virtual Machine |
| GICv3 + ITS + neoverse-n1 | `-M virt,gic-version=3,its=on -cpu neoverse-n1` | OK | **No** | CHR QEMU KVM Virtual Machine |

**10 unique configurations tested.  Zero QGA responses.**

The `sbsa-ref` machine type (ARM server reference platform — different firmware/ACPI tables) didn't boot the CHR image.  All other variants booted normally with working HTTP/REST.

SMBIOS changes DO affect `board-name` in RouterOS (it reads SMBIOS Type 1 Manufacturer + Product), but do NOT trigger QGA startup.

## Part 3: System Information (from REST API)

Queried the running ARM64 CHR instance:

| Endpoint | Key Value |
|---|---|
| `/rest/system/resource` | `board-name: "CHR QEMU QEMU Virtual Machine"`, `architecture-name: "arm64"`, `version: "7.23_ab650 (development)"` |
| `/rest/system/license` | `level: "free"` |
| `/rest/system/package` | **Only 1 package**: `routeros` (13.8 MB, built 2026-03-23) |
| `/rest/system/routerboard` | `routerboard: false` |

Notable: there is only ONE package (`routeros`).  No separate `chr` or `guest-agent` package — which is normal for RouterOS (MikroTik bundles everything into the single `routeros` package).

## What's Happening at the QEMU Level

For all PCI variants, the kernel infrastructure works:
1. Device enumerated in PCI tree (e.g., `0000:00:03.0: Virtio console`)
2. Kernel driver bound (IRQ interrupts allocated)
3. QEMU chardev created and listening

But **no guest-side process opens the virtio-serial port**.  QEMU monitor shows:
```
chardev: qga0: filename=disconnected:unix:/tmp/qga-test.sock,server=on
```

On x86_64 CHR where QGA works, this shows `connected`.  The `disconnected` status is the definitive observable — QEMU doesn't lie about chardev state.  Something in the guest is not opening the port on ARM64.

## The KVM Question

**My test host is macOS x86_64 (Intel).**  QEMU only offers TCG (software emulation) — no KVM:

```
$ qemu-system-aarch64 -M virt -accel help
Accelerators supported in QEMU binary:
tcg
```

I **cannot** test with KVM on native aarch64 hardware.  This may be significant because under real KVM on ARM, the guest kernel sees a fundamentally different environment:

| Aspect | TCG (my tests) | KVM (native aarch64) |
|---|---|---|
| PSCI method | SMC (firmware) | HVC (hypervisor) |
| KVM hypercalls | Not available | Available |
| ARM ID registers | Emulated (QEMU model) | Real host hardware |
| ACPI/timer behavior | Emulated | Hardware-backed |
| `/dev/kvm` on host | Not present | Present |
| `CONFIG_KVM_GUEST` | Kernel may detect "no KVM" | Kernel detects KVM |

On x86_64, our original positive result was on Linux + KVM.  A later local
Intel Mac double-check did not reproduce x86_64 QGA under either HVF or TCG,
so we should not treat non-KVM x86_64 support as established.  ARM64 is
different again — the same RouterOS ARM64 kernel runs on both CHR and physical
RouterBoard hardware (MikroTik ships many ARM64 devices).  QGA makes no sense
on a physical router, so the simplest gate is a kernel-level KVM check: if
running under KVM, start CHR-specific services like QGA; if not, skip them.

On ARM with KVM, the guest kernel detects the hypervisor via PSCI (HVC instead of SMC) and KVM-specific SMCCC hypercalls — these are kernel-level signals that can't be faked from QEMU's command line.  Under TCG, none of these are present, so the kernel would see the same environment as bare metal.

I tried faking KVM identity via SMBIOS (`-smbios type=1,product=KVM Virtual Machine`), which changed `board-name` in RouterOS but didn't trigger QGA — consistent with the detection being at the kernel/hypervisor level, not userspace string matching.

## Questions

1. **What host did you test on?**  Native aarch64 with KVM?  Or x86_64 with TCG cross-arch emulation?  (This seems like the most likely difference between our environments.)
2. **What QEMU version and `-M` / `-cpu` flags?**  We tested `-M virt -cpu cortex-a710` and `-M virt -cpu neoverse-n1`.
3. **Is there a newer build we should test?**  The `ab650` build is from 2026-03-23.

Even a full QEMU command line from your working test would help us reproduce.  The QEMU chardev `disconnected` status is the definitive indicator — the guest side isn't opening the virtio-serial port.

## Test Environment

- **Image**: `chr-7.23_ab650-arm64.img` (your dev build, 2026-03-23)
- **Host**: macOS x86_64 (Intel), QEMU 10.2.2, **TCG only** (no KVM)
- **Base QEMU config**: `-M virt -cpu cortex-a710 -m 1024 -smp 2 -accel tcg,tb-size=256`
- **UEFI firmware**: `edk2-aarch64-code.fd` + `edk2-arm-vars.fd` (64 MiB each)
- **Disk**: `-device virtio-blk-pci` (explicit PCI, NOT `if=virtio` which maps to MMIO on `virt`)
- RouterOS boots fully in all tested variants — HTTP/REST API fully operational

## QEMU Command Used

```sh
qemu-system-aarch64 \
  -M virt -cpu cortex-a710 -m 1024 -smp 2 \
  -accel tcg,tb-size=256 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=efi-vars-copy.fd \
  -drive file=chr-7.23_ab650-arm64.img,format=raw,if=none,id=drive1 \
  -device virtio-blk-pci,drive=drive1,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9200-:80 \
  -device virtio-net-pci,netdev=net0 \
  -display none \
  -chardev socket,id=serial0,path=/tmp/serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -device virtio-serial,id=vserial0 \
  -chardev socket,id=qga0,path=/tmp/qga-test.sock,server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0
```

## For Reference: x86_64 QGA Works on Linux/KVM

Same QEMU guest-agent device configuration on x86_64 CHR 7.22 produces:
- QGA version: 2.10.50
- 21 supported commands
- Responds immediately on the same `org.qemu.guest_agent.0` named port
- Verified on Linux x86_64 + KVM; not reproduced later on local macOS x86_64 under HVF or TCG

## Test Scripts

All scripts and machine-readable results are in the [mikropkl](https://github.com/tikoci/mikropkl) repository at `Lab/qemu-guest-agent/`:

- `test-virtio-serial-variants.py` — 4 transport variant tests
- `test-hypervisor-variants.py` — 6 machine/CPU/SMBIOS variant tests
- `probe-system-info.py` — REST API endpoint probe
- `virtio-serial-variant-results.json` — transport variant results
- `hypervisor-variant-results.json` — hypervisor variant results
