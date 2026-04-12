# Lab: extra-nic.npk — NIC Driver Investigation

**Status:** Complete  
**RouterOS version:** 7.22.1 (stable)  
**Goal:** Determine what drivers `extra-nic.npk` contains, map them to QEMU devices, and understand implications for ARM64 cloud deployments (AWS Graviton, OCI Ampere A1.Flex).

---

## Summary

`extra-nic` is an **ARM64-only** RouterOS package.  It does not exist for x86_64 — x86 already bundles the same drivers inside the base `routeros.npk` under `bndl/extra-nic/`.

The package adds **26 kernel modules** covering Intel datacenter NICs (e1000e, IGB, IXGBE, ICE, I40E), Mellanox ConnectX (MLX4, MLX5), Chelsio T3/T4/T5/T6, Broadcom enterprise NICs, Realtek (out-of-tree r8125), Aquantia AQtion 10G, and the **AWS Elastic Network Adapter (ENA)**.

**Live QEMU test confirms:** Without `extra-nic`, `e1000e` and `igb` devices appear in PCI hardware via `/system/resource/hardware` but no Ethernet interfaces are created.  After installing `extra-nic` and rebooting, `ether2` and `ether3` appear immediately.

---

## Package Format (NPK)

RouterOS `.npk` files have a custom binary format:

```
Offset  Size    Content
──────────────────────────────────────────────
0x0000  4096    MikroTik NPK header (proprietary)
0x1000  varies  SquashFS 4.0 filesystem
                (little-endian, XZ compressed, `hsqs` magic)
```

The header contains: package name, architecture string, channel, version, description text, SHA1 hash.  SquashFS starts at exactly byte 4096 on every `.npk` inspected.

### Extraction

```sh
# Skip 4096-byte header and extract SquashFS
dd if=extra-nic-7.22.1-arm64.npk of=extra-nic.sqfs bs=4096 skip=1
unsquashfs extra-nic.sqfs          # extracts to squashfs-root/
```

---

## Package Availability

```
x86_64:  No separate extra-nic package exists — 404 on all URL variants.
         Drivers are bundled inside routeros.npk at bndl/extra-nic/.

arm64:   https://download.mikrotik.com/routeros/7.22.1/extra-nic-7.22.1-arm64.npk
         Separate 2.3 MiB package. Must be installed for Intel/Mellanox/etc. NICs.
```

On x86, the `bndl/extra-nic/` directory inside the base package is auto-loaded.  On ARM64, the base package ships with only embedded SoC-specific and virtio drivers — `extra-nic` provides generic PC/cloud NIC coverage.

---

## ARM64 Base Package — Bundled Net Drivers

These drivers ship in `routeros-7.22.1-arm64.npk` without any extra packages:

| Module | Hardware | Notes |
|--------|----------|-------|
| `virtio_net.ko` | VirtIO network | Primary QEMU/cloud NIC |
| `vmxnet3.ko` | VMware VMXNET3 | Surprisingly present in ARM64 base |
| `bnxt_en.ko` | Broadcom NetXtreme-C/E | 100G datacenter; in ARM64 base |
| `atl1c.ko` | Atheros AR813x/AR815x | In ARM64 base |
| `r8152.ko` | Realtek USB GbE | USB-NIC support |
| `ax88179_178a.ko` | ASIX USB GbE | USB-NIC support |
| `mvneta.ko` | Marvell Neta GbE | Marvell hardware (RB/CCR/CRS) |
| `mvpp2.ko` | Marvell PPv2 GbE | Marvell hardware |
| `al.ko` | Annapurna Labs | AWS Graviton SoC predecessor |
| `hk_eth.ko` | HiKey (ARM devel board) | Embedded target |
| `via-velocity.ko` | VIA Velocity GbE | Legacy PCI |
| `bonding.ko` | NIC bonding/LAG | Bundled in base |
| `tun.ko` | TUN/TAP | VPN tunnels |
| `veth.ko` | Virtual Ethernet pair | Container networking |
| `wireguard.ko` | WireGuard VPN | In base |

**Surprise:** `vmxnet3.ko` and `bnxt_en.ko` are in the ARM64 base package — not just x86.

---

## extra-nic ARM64 — Driver Inventory (26 modules)

### Intel Out-of-Tree (OOT) Drivers

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `e1000e.ko` | Intel 82574L / PCH PRO/1000 | `-device e1000e` ✅ | Baremetal HW |
| `igb.ko` | Intel 82575/82576/I210/I350 GbE | `-device igb` ✅ | Baremetal HW |
| `igc.ko` | Intel I225/I226 2.5GbE | No QEMU device | Baremetal HW |
| `ixgbe.ko` | Intel X540/X550 10GbE | No QEMU device | Baremetal HW |
| `ixgbevf.ko` | Intel 10GbE SR-IOV VF | No QEMU device | Bare-metal SR-IOV |
| `i40e.ko` | Intel XL710 25/40GbE | No QEMU device | Baremetal HW |
| `iavf.ko` | Intel Adaptive VF (i40evf) | No QEMU device | SR-IOV VF |
| `ice.ko` | Intel E810 100GbE | No QEMU device | Baremetal HW |
| `intel_auxiliary.ko` | Intel aux bus glue | — (dependency) | — |

### Intel Kernel-Tree Driver

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `igbvf.ko` | Intel 82576 SR-IOV VF | No QEMU device | SR-IOV VF |

### Mellanox / NVIDIA

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `mlx4_core.ko` + `mlx4_en.ko` | ConnectX-3 10/40GbE | No QEMU device | OCI baremetal |
| `mlx5_core.ko` | ConnectX-4/5/6/7 25–400GbE | No QEMU device | OCI baremetal, Azure |

### Chelsio

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `cxgb3.ko` | Chelsio T3 10GbE | No QEMU device | Baremetal |
| `cxgb4.ko` | Chelsio T4/T5/T6 up to 100GbE | No QEMU device | Baremetal |

### Broadcom

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `b44.ko` | BCM44xx 10/100 | No QEMU device | Embedded/old HW |
| `bnx2.ko` | BCM5706/5709 GbE | No QEMU device | Old baremetal |
| `bnx2x.ko` | BCM57710–57840 10/20GbE | No QEMU device | Old baremetal |
| `tg3.ko` | Broadcom Tigon3 GbE | No QEMU device | Older baremetal |

### Realtek

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `r8125.ko` | RTL8125 2.5GbE (OOT) | No QEMU device | Desktop/embedded |
| `r8169.ko` | RTL8169/8111/8168 GbE | `-device rtl8139`* | Desktop/embedded |

\* `rtl8139` in QEMU is a different chip generation but shares the `r8169` driver family for RouterOS purposes; not directly tested.

### Aquantia

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `atlantic.ko` | Aquantia AQtion 1G–10GbE | No QEMU device | Servers with Marvell AQC |

### AWS

| Module | Hardware | QEMU device | Cloud use |
|--------|----------|-------------|-----------|
| `ena.ko` | AWS Elastic Network Adapter | **No QEMU equivalent** | AWS EC2 Graviton — critical |

### Helper Modules

| Module | Notes |
|--------|-------|
| `mdio.ko` | MDIO bus abstraction (needed by cxgb3, cxgb4, b44) |
| `ssb.ko` | Sonics Silicon Backplane (needed by b44) |
| `phy/realtek.ko` | Realtek PHY (needed by r8169) |

### Firmware Blobs

| Firmware | For |
|----------|-----|
| `bnx2/bnx2-*.fw` | Broadcom BCM5706/5709 |
| `bnx2x/*.fw` | Broadcom BCM577xx |
| `intel/ice/ddp/ice.pkg` | Intel ICE DDP policy package |
| `rtl_nic/rtl8125b-2.fw` | Realtek 8125B |
| `rtl_nic/rtl8125d-1.fw` | Realtek 8125D |
| `rtl_nic/rtl8168h-2.fw` | Realtek 8168H |

---

## QEMU Device Mapping Summary

Devices testable in QEMU **without specialized hardware**:

| QEMU device flag | Kernel module | Status |
|-----------------|---------------|--------|
| `-device virtio-net-pci` | `virtio_net.ko` (base) | Works, no extra-nic needed |
| `-device e1000e` | `e1000e.ko` (extra-nic) | **Requires extra-nic on ARM64** ✅ |
| `-device igb` | `igb.ko` (extra-nic) | **Requires extra-nic on ARM64** ✅ |
| `-device vmxnet3` | `vmxnet3.ko` (base) | In base ARM64 package |
| `-device rtl8139` | `r8169.ko`? | Different chip; driver match unclear |
| `-device e1000` | Legacy Intel | Not in extra-nic |

Devices in extra-nic with **no QEMU emulation**: igc, ixgbe, i40e, ice, mlx4/5, cxgb3/4, bnx2/3/x, tg3, r8125, atlantic, ena.

---

## Live QEMU Test Results

### Setup

```sh
# Test instance: ARM64 CHR 7.22.1 with e1000e + igb added
qemu-system-aarch64 -M virt -cpu cortex-a710 -m 1024M -smp 2 -accel tcg \
  [UEFI pflash] \
  -drive file=chr-7.22.1-arm64.img,format=raw,if=none,id=drive0 \
  -device virtio-blk-pci,drive=drive0 \
  -netdev user,id=net0,hostfwd=tcp::9382-:80,hostfwd=tcp::9322-:22 \
  -device virtio-net-pci,netdev=net0,mac=0e:7e:27:7d:3c:32 \
  -netdev user,id=net1 -device e1000e,netdev=net1,mac=0e:7e:27:7d:3c:33 \
  -netdev user,id=net2 -device igb,netdev=net2,mac=0e:7e:27:7d:3c:34
```

### BEFORE extra-nic

`/rest/interface`:
```
ether1  0E:7E:27:7D:3C:32  (virtio-net-pci)
lo
```

`/rest/system/resource/hardware` — Intel NICs visible in PCI scan but no driver:
```
0000:00:03.0  Ethernet controller  Intel  82574L Gigabit Network Connection
0000:00:04.0  Ethernet controller  Intel  82576 Gigabit Network Connection
```
→ PCI enumeration works, but no kernel modules load → no usable interface.

### AFTER extra-nic (SCP + reboot)

Packages installed:
```
routeros   7.22.1
extra-nic  7.22.1
```

`/rest/interface`:
```
ether1  0E:7E:27:7D:3C:32  (virtio-net)
ether2  0E:7E:27:7D:3C:34  (igb — 82576)
ether3  0E:7E:27:7D:3C:33  (e1000e — 82574L)
lo
```
→ Both Intel NICs are fully operational Ethernet interfaces in RouterOS.

**Observation:** RouterOS assigned `ether2` to igb (PCI `0000:00:04.0`) and `ether3` to e1000e (PCI `0000:00:03.0`) — igb module loads before e1000e alphabetically.

### Install procedure

```sh
scp -P 9322 extra-nic-7.22.1-arm64.npk admin@127.0.0.1:/
# RouterOS automatically detects and queues for install on next reboot
curl -u admin: -X POST http://localhost:9382/rest/system/reboot
# After boot: interfaces ready immediately
```

---

## x86_64 Comparison

On x86_64, `extra-nic` drivers are bundled as `bndl/extra-nic/` inside the base `routeros.npk`.  They activate automatically — no separate installation needed.

x86 base routeros additionally includes drivers **not present in ARM64 extra-nic**:

| Module (x86-only or ARM64-missing) | Hardware |
|------------------------------------|----------|
| `hinic.ko` | Huawei HiNIC (for Huawei cloud/baremetal) |
| `cxgb4vf.ko` | Chelsio T4/T5 SR-IOV VF |
| `pcnet32.ko` | AMD PCnet (legacy QEMU default NIC) |
| `e1000.ko` | Intel E1000 (legacy; QEMU `e1000-82540em`) |
| `8139cp.ko` / `8139too.ko` | Realtek RTL8139 (legacy; QEMU `rtl8139`) |
| `tulip.ko` | DEC Tulip 21140 (QEMU `tulip`) |

x86 `bndl/extra-nic/` also includes newer `r8125.ko`, `igb.ko`, `igbvf.ko`, `ice.ko`, `i40e.ko`, `iavf.ko`, `ixgbe.ko`, `ixgbevf.ko`, `e1000e.ko`, `igc.ko`, `atl1c.ko`, `mlx4/5`, `cxgb3/4`, `bnx2x`, `tg3`, `b44`, `atlantic`, `ena`, matching the ARM64 extra-nic set.

---

## Cloud Platform Implications

### AWS EC2 (Graviton — ARM64)

| Instance type | NIC type | Required driver | In base? | Needs extra-nic? |
|--------------|----------|----------------|----------|-----------------|
| General purpose (T4g, M6g, C6g) | ENA (SR-IOV) | `ena.ko` | No | **Yes** |
| Bare metal (*.metal) | ENA or physical | `ena.ko` | No | **Yes** |

ENA is the AWS Elastic Network Adapter — proprietary to AWS hardware.  No QEMU equivalent.  **extra-nic is required for any AWS Graviton EC2 instance running RouterOS CHR.**

### Oracle Cloud (OCI A1.Flex — Ampere Altra ARM64)

| Instance type | NIC type | Required driver | Needs extra-nic? |
|--------------|----------|----------------|-----------------|
| Standard VMs (A1.Flex) | VirtIO (VFIO-based) | `virtio_net.ko` | No |
| Bare metal (BM.Standard.A1.160) | Mellanox ConnectX | `mlx5_core.ko` | **Yes** |

OCI `chr-armed` project (OCI A1.Flex) uses virtio-net — base `routeros` package is sufficient.  Bare-metal OCI A1 would need `mlx5_core.ko` via extra-nic.

### VMware vSphere (any QEMU replacement)

`vmxnet3.ko` is already in the **ARM64 base package** — no extra-nic needed for VMware virtual hardware.

### Google Cloud GCP T2A (Ampere)

Uses either `virtio-net` or gVNIC (Google Virtual NIC, a VirtIO extension) — no extra-nic needed.

### Azure ARM64 (Cobalt 100)

Likely uses `mlx5_core.ko` (Mellanox ConnectX, common in Azure hardware) or MANA (Microsoft Azure Network Adapter).  `mlx5_core.ko` is in extra-nic.  MANA has no driver in RouterOS 7.22.1.

---

## QEMU Test Recipe

To test ARM64 CHR with Intel NICs (requires extra-nic):

```sh
# Step 1: Copy the CHR disk image (to preserve original)
cp Machines/chr.aarch64.qemu.7.22.1.utm/Data/chr-7.22.1-arm64.img /tmp/chr-arm64-test.img

# Step 2: Copy UEFI vars template
cp /usr/local/share/qemu/edk2-arm-vars.fd /tmp/chr-arm64-test-vars.fd  # Intel Mac
# or /opt/homebrew/share/qemu/edk2-arm-vars.fd  # Apple Silicon Mac

# Step 3: Start QEMU with e1000e + igb + SSH forwarding
qemu-system-aarch64 -M virt -cpu cortex-a710 -m 1024M -smp 2 -accel tcg,tb-size=256 \
  -drive if=pflash,format=raw,readonly=on,unit=0,file=/usr/local/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=/tmp/chr-arm64-test-vars.fd \
  -drive file=/tmp/chr-arm64-test.img,format=raw,if=none,id=drive0 \
  -device virtio-blk-pci,drive=drive0,bootindex=0 \
  -netdev user,id=net0,hostfwd=tcp::9382-:80,hostfwd=tcp::9322-:22 \
  -device virtio-net-pci,netdev=net0 \
  -netdev user,id=net1 -device e1000e,netdev=net1 \
  -netdev user,id=net2 -device igb,netdev=net2 \
  -display none -monitor none \
  -chardev socket,id=s0,path=/tmp/test-serial.sock,server=on,wait=off \
  -serial chardev:s0 &

# Step 4: Wait for boot (~60s TCG), then install extra-nic
sleep 60
scp -o StrictHostKeyChecking=no -P 9322 \
  extra-nic-7.22.1-arm64.npk admin@127.0.0.1:/

# Step 5: Reboot
curl -u admin: -X POST http://localhost:9382/rest/system/reboot

# Step 6: Wait and verify
sleep 60
curl -u admin: http://localhost:9382/rest/interface
# Expected: ether1 (virtio), ether2 (igb), ether3 (e1000e)
```

---

## GPL Kernel Source Alignment

From `mikrotik-gpl/2025-03-19/configs/`:

- **`arm64.config`**: Almost no mainstream NIC drivers enabled.  Only `CONFIG_VIRTIO=y` in base.  Embedded SoC-specific: Cadence, Cortina, Pensando, Marvell Prestera, Xilinx.
- **`x86_64.config`**: Rich NIC support as `=m` modules: `IGB=m`, `IXGBE=m`, `ICE=m`, `IGC=m`, `ENA_ETHERNET=m`, `BNXT=m`, `MLX4_EN=m`, `MLX5_CORE=m`, `E1000E=m`, `PCNET32=m`, `TULIP=m`, `8139CP=m`, etc.

The `extra-nic` modular package compensates for the minimal ARM64 kernel config by shipping the PC/datacenter NIC drivers as loadable modules.

GPL source also contains out-of-tree modules in `drivers/`: `vmxnet3/`, `atl1c/`, `mvneta/`, `mvpp2/`, `gianfar/`, `ucc_geth/` — confirming these are maintained separately from upstream.

---

## Findings for chr-armed Project

The `chr-armed` project deploys RouterOS CHR to Oracle Cloud A1.Flex (Ampere Altra ARM64).

**Current state (OCI A1.Flex VM):** Uses VirtIO networking → base `routeros` package is sufficient → no `extra-nic` needed.

**If expanding to AWS Graviton:** Must install `extra-nic` before the instance can use ENA.  Workflow:
1. Include `extra-nic-<ver>-arm64.npk` in the image build
2. First boot with virtio-net as management NIC
3. Install extra-nic, reboot, ENA interface appears as `ether2`
4. Configure ENA interface for data traffic

**If expanding to OCI baremetal ARM64:** Would need `mlx5_core.ko` from extra-nic for Mellanox networking.

---

## Open Questions

1. Does `igc.ko` (Intel I225/I226 2.5GbE) in extra-nic have any QEMU device equivalent in future QEMU versions?
2. Can `bnxt_en.ko` (in ARM64 base) drive QEMU's `-device virtio-net-pci` as a fallback?  (No — it's a completely different driver for real Broadcom hardware.)
3. Does RouterOS on ARM64 support SRIOV with `iavf.ko` on OCI bare-metal?
4. What is `al.ko` (Annapurna Labs) — is this used for AWS Nitro internal accelerators?
5. Does `ena.ko` work with KVM's ENA emulation on Linux hosts (`virtio-net` with ENA compatibility layer)?

---

## References

- MikroTik extra-nic package page: https://mikrotik.com/product/extra_nic
- extra-nic NPK (ARM64): `https://download.mikrotik.com/routeros/7.22.1/extra-nic-7.22.1-arm64.npk`
- GPL kernel source: `~/GitHub/mikrotik-gpl/2025-03-19/`
- chr-armed project: `~/GitHub/chr-armed/` (OCI ARM64 CHR deployment)
- CLAUDE.md RouterOS kernel driver table: full x86 vs ARM64 driver support matrix
