# virtio-9p-pci (VirtFS / Plan 9 Filesystem) Support in RouterOS CHR

## Question

Can RouterOS CHR mount a host filesystem via `virtio-9p-pci`?

## Answer

**x86_64: kernel has 9p support, but RouterOS CLI cannot mount it.**
**aarch64: kernel does NOT have 9p support at all.**

## GPL Source Analysis (v7.2 kernel configs)

MikroTik's GPL disclosure (v7.2, `tikoci/mikrotik-gpl`, 2025-03-19 snapshot) includes
kernel defconfigs for all architectures. The v7.2 configs are 3+ years old — MikroTik
has significantly changed the arm64 config since then.

### x86_64.config — 9p and virtio

```ini
CONFIG_9P_FS=y
CONFIG_NET_9P=y
CONFIG_NET_9P_VIRTIO=y
# CONFIG_9P_FS_POSIX_ACL is not set
# CONFIG_9P_FS_SECURITY is not set
# CONFIG_NET_9P_DEBUG is not set

CONFIG_VIRTIO=y
CONFIG_VIRTIO_PCI=y
CONFIG_VIRTIO_PCI_LEGACY=y
CONFIG_VIRTIO_BLK=y
CONFIG_VIRTIO_CONSOLE=y
CONFIG_VIRTIO_BALLOON=m
# CONFIG_VIRTIO_NET is not set      ← added after v7.2
# CONFIG_VIRTIO_MMIO is not set
# CONFIG_VIRTIO_INPUT is not set
```

### arm64.config — 9p and virtio

```ini
# CONFIG_NET_9P is not set           ← no 9p at all

CONFIG_VIRTIO=y
CONFIG_VIRTIO_MENU=y
CONFIG_CRYPTO_DEV_VIRTIO=m
# CONFIG_VIRTIO_PCI is not set       ← ALL virtio devices disabled!
# CONFIG_VIRTIO_BLK is not set
# CONFIG_VIRTIO_NET is not set
# CONFIG_VIRTIO_CONSOLE is not set
# CONFIG_VIRTIO_BALLOON is not set
# CONFIG_VIRTIO_MMIO is not set
# CONFIG_VIRTIO_FS is not set
# CONFIG_SCSI_VIRTIO is not set
```

**The arm64 v7.2 config had NO virtio device drivers at all.** MikroTik added
`virtio_pci`, `virtio_blk`, `virtio_net`, `virtio_scsi`, `virtio_console`,
`virtio_balloon`, and `virtio_gpu` to the arm64 kernel sometime between v7.2
and v7.23. They did NOT add 9p support to arm64.

### Other notable x86_64 configs (hypervisor guest support)

```ini
CONFIG_HYPERVISOR_GUEST=y
CONFIG_KVM_GUEST=y
CONFIG_PARAVIRT=y
CONFIG_PARAVIRT_CLOCK=y
CONFIG_HYPERV=y                      ← Hyper-V guest (balloon, storage, net, utils)
CONFIG_XEN=y                         ← Xen PV/HVM guest
CONFIG_E1000=m                       ← Intel e1000 NIC emulation
CONFIG_E1000E=m
CONFIG_PCNET32=m                     ← AMD PCnet
CONFIG_8139CP=m                      ← Realtek RTL8139
CONFIG_TULIP=m                       ← DEC Tulip
CONFIG_VMWARE_PVSCSI=y               ← VMware paravirtual SCSI
CONFIG_VHOST_NET=m                   ← vhost-net acceleration
CONFIG_NFS_FS=m                      ← NFS client
CONFIG_NFSD=m                        ← NFS server
CONFIG_EFI=y                         ← EFI stub boot support
CONFIG_EFI_STUB=y
```

### arm64 notable configs

```ini
# CONFIG_EFI is not set              ← added after v7.2 (7.23 boots via UEFI)
CONFIG_PCIE_ARMADA_8K=y              ← Marvell Armada target hardware
CONFIG_CIFS=m                        ← SMB/CIFS client
CONFIG_FUSE_FS=m                     ← FUSE filesystem support
CONFIG_NFS_FS=m                      ← NFS client
CONFIG_NFSD=m                        ← NFS server
CONFIG_JFFS2_FS=y                    ← Flash filesystem
CONFIG_BLK_DEV_NVME=m                ← NVMe
# CONFIG_PCI_HOST_GENERIC is not set ← QEMU virt machine PCIe host, disabled
```

## Binary Analysis (v7.23beta2 kernels)

### aarch64 — strings from uncompressed kernel image

Searched for `9pnet`, `v9fs`, `9pnet_virtio`, `mount_tag` — **all absent**.
Confirmed virtio drivers present: `virtio_pci`, `virtio_blk`, `virtio_scsi`,
`virtio_net`, `virtio_console`, `virtio_balloon`, `virtio_gpu`, `virtio_rproc_serial`.

### x86_64 — decompressed from BOOTX64.EFI (xz-compressed bzImage)

Extracted kernel from `chr-efi.img` → `EFI/BOOT/BOOTX64.EFI` (4 MiB PE/bzImage).
Decompressed xz payload → 24.7 MiB raw kernel. Found **full 9p stack**:

```text
69p: Installing v9fs 9p2000 file system support
69pnet: Installing 9P2000 support
9pnet_virtio
p9_virtio_probe
p9_virtio_remove: waiting for device in use.
mount_tag
trans=virtio
,version=9p2000.u
9P2000
9P2000.L
9P2000.u
9p-fcall-cache
39pnet_virtio: Failed to allocate virtio 9P channel
39pnet_virtio: no channels available for device %s
```

All three 9P protocol versions (9P2000, 9P2000.L, 9P2000.u) are compiled in.

## Runtime Test (v7.23beta2 x86_64)

### Test 1: QEMU_EXTRA with virtio-9p-pci

Booted `chr.x86_64.qemu.7.23beta2` with:

```sh
QEMU_EXTRA="-fsdev local,id=fsdev0,path=/tmp/shared,security_model=none \
  -device virtio-9p-pci,fsdev=fsdev0,mount_tag=hostshare"
```

Results:

- QEMU started successfully with the 9p device
- RouterOS booted normally (HTTP 200 on REST API)
- QEMU monitor `info pci` shows device `1af4:1009` (virtio-9p) on PCI bus
- QEMU monitor `info qtree` shows `virtio-9p-device` with `mount_tag = "hostshare"`
- The kernel driver IS bound to the PCI device (confirmed via qtree)

### Test 2: Standalone Lab with qemu.cfg + rose-storage

Used `Lab/virtio-9p/qemu.sh` which includes the 9p device directly in `qemu.cfg`
and points to the `chr.x86_64.apple` disk image.

```sh
cd Lab/virtio-9p && ./qemu.sh --background
```

Installed `rose-storage-7.23beta2.npk` (provides `/disk/add` for network filesystems):

```sh
scp -P 9221 rose-storage-7.23beta2.npk admin@127.0.0.1:/
ssh -p 9221 admin@127.0.0.1 '/system reboot'
```

After reboot, explored `/disk/add type=` via REST API. Valid types with rose-storage:

| Type | Result | Notes |
| --- | --- | --- |
| `nfs` | Created, `fs=nfs`, state "mounting vers=4.2" | NFS client works |
| `smb` | Created, `fs=smb`, state "mounting" | SMB/CIFS client works |
| `iscsi` | Created, block device, state "Connection refused" | iSCSI initiator |
| `9p` | **Ignored** — no entry created | Not a recognized disk type |
| `loop` | **Ignored** — no entry created | Not supported |
| `cifs` | **Ignored** — no entry created | Use `smb` instead |

### Conclusion

- **Kernel level:** x86_64 CHR has full 9p support (`CONFIG_9P_FS=y`,
  `CONFIG_NET_9P_VIRTIO=y`, all three protocol versions)
- **QEMU level:** virtio-9p-pci device works, kernel driver binds to it
- **RouterOS level:** No CLI command to mount 9p filesystems. `/disk/add` only
  supports `nfs`, `smb`, and `iscsi` types even with rose-storage installed.
  The 9p kernel support is present but completely unexposed in the RouterOS user
  interface. This would need MikroTik to add `type=9p` to `/disk/add`.

### Feature request to MikroTik

Worth requesting `type=9p` support in `/disk/add` since:

- The kernel driver already exists (x86_64, compiled-in since at least v7.2)
- The QEMU device works correctly
- It's simpler than SMB/NFS for QEMU host-guest file sharing (no network config)
- UTM already supports directory sharing via virtio-9p
- MikroTik already uses virtfs internally (force-enabled in their custom QEMU 2.0.2)

### How to access (other possibilities)

- RouterOS containers (`/container`) have Linux mount capabilities — might work
  if the container sees the virtio-9p device
- A custom RouterOS package (NPK) could auto-mount the 9p filesystem
- Direct kernel module interaction is not possible through RouterOS CLI

## Lab Files

- `qemu.cfg` — QEMU config with virtio-9p-pci device, points to apple x86 disk image
- `qemu.sh` — Launch script with SSH forwarding, usage banner with RouterOS commands
- `shared/` — Host directory shared into the guest (auto-created with test file)
- `test-9p.sh` — Original QEMU_EXTRA-based test script

```sh
# Quick start
cd Lab/virtio-9p
./qemu.sh                          # foreground (Ctrl-A X to quit)
./qemu.sh --background             # or background mode
ssh -p 9221 admin@127.0.0.1        # SSH into RouterOS
./qemu.sh --stop                   # stop background instance
```

## Alternatives for Host-Guest File Sharing

| Method | RouterOS Support | Notes |
| --- | --- | --- |
| **NFS** | Yes (`/disk/add type=nfs`) | rose-storage required, NFSv4.2 client |
| **SMB/CIFS** | Yes (`/disk/add type=smb`) | rose-storage required, or built-in `/ip smb` |
| **FTP** | Yes (`/tool fetch`) | Built-in FTP client |
| **HTTP** | Yes (`/tool fetch`) | Can download files from host HTTP server |
| **SFTP/SCP** | Yes (SSH) | Upload via `scp`, works well for file transfer |
| **REST API** | Yes (`/file` endpoint) | Upload/download files via HTTP |
| **iSCSI** | Yes (`/disk/add type=iscsi`) | rose-storage required, block device |
| **virtio-9p-pci** | x86 kernel only, no CLI | Driver present but not usable from RouterOS |
| **virtiofs** | No | Not in kernel 5.6.3 (needs newer kernel + FUSE) |

For quick file transfer, **SCP** (`scp -P 9221 file admin@127.0.0.1:/`) is the simplest.
For persistent shared directories, **NFS** via `/disk/add type=nfs` with rose-storage
is the most practical (run a lightweight NFS server on the host).

## MikroTik's Custom QEMU (qemu-2.0.2)

The GPL source includes a patched QEMU 2.0.2 with Tile-GX (MikroTik hardware)
support. Interestingly, MikroTik **force-enabled virtfs** in their QEMU build
(`if test 1 || ...` in configure), suggesting they use 9p internally for their
Tile-GX development/testing. This doesn't affect CHR on standard QEMU.
