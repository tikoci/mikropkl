
# Experimental: Libvirt / `virsh` Support

> [!WARNING]
> This is experimental support. Only QEMU-backend machines are supported (not `*.apple.*` packages).
> It has not been broadly tested across Linux distributions or libvirt versions.
> Feedback and fixes welcome.

Each QEMU machine bundle produced by `make` includes a `libvirt.xml` alongside the standard `config.plist`.  This allows the **same disk images** that run in UTM on macOS to be defined and started under [libvirt](https://libvirt.org) / `virsh` on Linux (or macOS via Homebrew).

The `libvirt.xml` maps UTM configuration attributes directly to libvirt domain XML:

| UTM concept | libvirt XML |
| --- | --- |
| `memory` | `<memory unit="MiB">` |
| `cpus` | `<vcpu placement="static">` |
| `architecture` / `backend` | `<type arch="..." machine="q35/virt">hvm</type>` |
| aarch64 backend | `<os firmware="efi">` (libvirt auto-selects UEFI) |
| primary drive image | `<disk type="raw">` on `vda` |
| additional `qdiskN.qcow2` | `<disk type="qcow2">` on `vdb`, `vdc`, … |
| `Shared` network | `<interface type="user">` (SLIRP / usermode) |
| serial / console | `<serial>` + `<console>` (PL011 on aarch64, ISA on x86_64) |

## Installing libvirt & QEMU

### Ubuntu (apt)

```sh
sudo apt update
sudo apt install -y qemu-system-x86 qemu-system-arm libvirt-clients libvirt-daemon-system \
                    virtinst qemu-utils
sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt $USER   # re-login after this
```

For aarch64 guest support on aarch64 hosts, also install:

```sh
sudo apt install -y qemu-efi-aarch64
```

### Using `virsh` with a downloaded release ZIP

1. Download and extract a QEMU `.utm` ZIP from [Releases](https://github.com/tikoci/mikropkl/releases):

   ```sh
   unzip chr.x86_64.qemu.7.xx.utm.zip
   cd chr.x86_64.qemu.7.xx.utm
   ```

2. Update the `<source file>` disk paths in `libvirt.xml` to absolute paths:

   ```sh
   datadir=$(pwd)/Data
   perl -i -pe "s|/LIBVIRT_DATA_PATH|$datadir|g" libvirt.xml
   ```

3. Define and start the VM:

   ```sh
   virsh define libvirt.xml
   virsh start chr.x86_64.qemu.7.xx
   virsh console chr.x86_64.qemu.7.xx   # connect to serial console (Ctrl+] to exit)
   ```

4. To stop and remove:

   ```sh
   virsh destroy chr.x86_64.qemu.7.xx   # force stop (like power-off)
   virsh undefine chr.x86_64.qemu.7.xx  # remove definition (disks are NOT deleted)
   ```

> [!NOTE]
> The `<interface type="user">` (SLIRP usermode networking) requires `qemu-system` to run without KVM
> acceleration in some system configurations.  If you see a networking error, ensure `qemu-system-x86_64`
> is in your `$PATH`.  For KVM-accelerated networking, switch to `<interface type="network">` with a
> libvirt network bridge — see `virsh net-list --all`.

### Using `make` targets for libvirt (build from source)

After `make` completes (which automatically fixes disk paths via `make libvirt-fixpaths`):

```sh
make libvirt-validate   # schema-check all generated libvirt.xml files
make libvirt-list       # show paths to all generated libvirt.xml files
make libvirt-define     # register all QEMU machines with libvirt
make libvirt-start      # start all registered machines
make libvirt-stop       # force-stop (destroy) all running machines
make libvirt-undefine   # unregister all machines (disks are NOT deleted)
```

The `libvirt-fixpaths` target (run automatically by `make` / `phase2`) replaces the `/LIBVIRT_DATA_PATH` placeholder in `libvirt.xml` with the real absolute path to each `.utm` bundle's `Data` directory.  This must be re-run if the `Machines` directory is moved.

### Notes on libvirt networking

The generated XML uses `<interface type="user">` which is QEMU's SLIRP usermode networking — equivalent to UTM's "Shared" network mode.  The VM gets outbound internet access via NAT but is not directly reachable from the host without port forwarding.

To add port forwarding (e.g., SSH on port 2222 → guest port 22), add inside the `<interface>` element in `libvirt.xml` (before using `virsh define`):

```xml
<interface type="user">
  <mac address="0e:xx:xx:xx:xx:xx"/>
  <model type="virtio"/>
  <!-- port forward: host 2222 -> guest 22 -->
  <source>
    <portForward proto="tcp" address="127.0.0.1" port="2222" guestPort="22"/>
  </source>
</interface>
```
