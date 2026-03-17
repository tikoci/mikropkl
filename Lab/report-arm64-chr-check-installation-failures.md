# Why `check-installation` Fails on ARM64 CHR in QEMU

## The short version

RouterOS's `check-installation` command is checking whether the system is running on hardware it recognizes. In QEMU, it's running on virtual hardware that RouterOS doesn't recognize, so the check fails. This is expected and won't affect normal use.

## What the error actually means

When you run `/system/check-installation` on an ARM64 CHR instance booting under QEMU (including in GitHub Actions CI, UTM on macOS, or any other virtualization environment), you get:

```json
{"detail": "damaged system package: bad image", "error": 400}
```

Despite the alarming wording, **your RouterOS installation is not damaged**. The message means: "I couldn't verify my hardware environment." The check is designed to confirm that RouterOS is running on genuine MikroTik hardware (specifically, a Marvell Armada7040 SoC), and QEMU's generic virtual machine doesn't look anything like that.


## Why this happens (without the ARM assembly)

When ARM64 RouterOS boots, it expects specific **hardware descriptor files** to be present in memory — think of them as a catalog of what hardware is attached to the system. On real MikroTik hardware, the bootloader reads hardware description data baked into the firmware and builds this catalog automatically.

In QEMU, the virtual hardware *is* described by a similar mechanism (a "device tree"), but the QEMU generic virtual machine presents a stub that says essentially `"I am a generic Linux virtual machine"` — which RouterOS doesn't know how to read. Without that catalog, when `check-installation` runs its hardware verification, it finds nothing to verify and reports failure.

**The deeper reason is architectural:** we extracted and disassembled the checker binary from both x86 and ARM64 CHR images. The **x86 checker always succeeds** — after scanning for hardware files, it unconditionally runs a fallback program (`/bin/milo`) and returns success. The **ARM checker has no such fallback** — when hardware descriptor files are missing, it returns failure, which RouterOS reports as "damaged system package: bad image." This is a design difference in MikroTik's firmware, not a QEMU configuration problem.

We explored whether different QEMU settings could resolve this:
- **Using a different CPU model** (we tried four variants including ones that match real Armada7040 hardware): no effect — the check doesn't care about CPU model, it cares about hardware descriptors
- **Disabling ACPI** to force QEMU to expose better hardware info: RouterOS then can't find the disk at all, because it relies on ACPI to discover the virtual storage controller
- **Using MMIO transport** (virtio-blk-device) with ACPI disabled: RouterOS kernel doesn't have virtio-mmio drivers — stalls at boot
- **Injecting SMBIOS data** to mimic MikroTik hardware: changes board-name display but doesn't affect the check
- **Patching the device tree** with Marvell hardware identifiers: kernel ignores the DTB when ACPI is present
- **qcow2 instead of raw disk format**: no difference — disk format is irrelevant
- **Different UEFI firmware**: no effect — the firmware starts fine either way, the problem is downstream in RouterOS itself

Every path leads to either "boot works, check fails" or "disk not found, nothing works." There's no configuration of QEMU's standard virtual machine type that satisfies RouterOS's hardware expectations for ARM64.

---

## Does this affect actual use?

**No.** The RouterOS instance boots normally and is fully functional:
- WebFig (the web UI) works
- The REST API works
- Routing, firewall rules, and all RouterOS features work
- You can manage it via WinBox, SSH, and the API

`check-installation` is a MikroTik-specific integrity/licensing check that confirms the system image is running on genuine hardware. For CHR (Cloud Hosted Router), it's conceptually a license-validation step. In a QEMU environment, it will always fail for ARM64 — this is a known limitation of running RouterOS CHR ARM64 outside of real MikroTik hardware or UTM/Apple Virtualization on macOS (which provides the right virtual hardware profile).

**x86_64 CHR does not have this problem** — the x86_64 checker binary always succeeds regardless of hardware state (it has a built-in `/bin/milo` fallback). This is a design difference between the x86 and ARM firmware binaries at the MikroTik level, not a difference in QEMU's ACPI vs DTB support.


## Bottom line

| | ARM64 CHR in QEMU | x86_64 CHR in QEMU |
|---|---|---|
| Boots normally | ✅ | ✅ |
| WebFig / REST API | ✅ | ✅ |
| `check-installation` | ❌ Always fails | ✅ Passes |
| Usable for testing | ✅ | ✅ |

The ARM64 failure is a permanent characteristic of running CHR ARM64 in a generic virtual machine environment — not a bug in the setup or a sign of a corrupted image. The x86 and ARM checker binaries have different failure modes: x86 always succeeds, ARM fails when hardware descriptors are missing. MikroTik would need to align the ARM checker's behavior with the x86 version, or QEMU would need to emulate a Marvell Armada7040 machine (it doesn't), for this to change.