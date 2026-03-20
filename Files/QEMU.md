# Running RouterOS CHR with QEMU

Pre-built RouterOS Cloud Hosted Router (CHR) packages are available on [GitHub Releases](https://github.com/tikoci/mikropkl/releases).  Each release ZIP contains a ready-to-run QEMU configuration — download, extract, run `./qemu.sh`, and you have a RouterOS instance in under 30 seconds.

No GUI needed.  No disk image wrangling.  Every release includes the CHR disk image, a QEMU config file (`qemu.cfg`), and a launch script (`qemu.sh`) that handles platform detection automatically.

> [!TIP]
> These packages originate from [mikropkl](https://github.com/tikoci/mikropkl), which builds [UTM](https://mac.getutm.app) virtual machine bundles for macOS.  A `.utm` file is just a ZIP archive — and every bundle ships with `qemu.cfg` + `qemu.sh` so you can run CHR directly via QEMU on **macOS or Linux** without UTM installed.

---

## Platform Setup

Install QEMU once, then every CHR package works.

### macOS

```sh
brew install qemu
```

Homebrew provides `qemu-system-x86_64`, `qemu-system-aarch64`, and all UEFI firmware files.  On Intel Macs, QEMU uses Apple's Hypervisor.framework (HVF) for near-native speed.  On Apple Silicon, HVF accelerates aarch64 guests; x86_64 guests run under TCG emulation.

### Ubuntu / Debian

**x86_64 host:**
```sh
sudo apt-get install qemu-system-x86 qemu-system-arm qemu-efi-aarch64 qemu-utils
```

**aarch64 host:**
```sh
sudo apt-get install qemu-system-arm qemu-efi-aarch64 qemu-utils
```

For hardware-accelerated virtualization (recommended on bare-metal Linux):
```sh
sudo apt-get install qemu-kvm
sudo usermod -aG kvm "$USER"
# Log out and back in to activate
```

### Fedora / RHEL

```sh
sudo dnf install qemu-system-x86 qemu-system-arm edk2-aarch64 qemu-img
sudo dnf install qemu-kvm   # optional, for KVM
```

> [!NOTE]
> `qemu.sh` auto-detects KVM, HVF, or TCG — no manual accelerator configuration needed.

---

## Getting a CHR Package

The [CHR Images](https://tikoci.github.io/chr-images.html) page is the quickest way — pick a version and architecture and it generates the download commands for your platform.  Or use the methods below directly.

### Download from GitHub Releases

```sh
cd ~/Downloads
curl -fsSL -o chr.x86_64.qemu.7.22.utm.zip \
  https://github.com/tikoci/mikropkl/releases/download/chr-7.22/chr.x86_64.qemu.7.22.utm.zip
unzip chr.x86_64.qemu.7.22.utm.zip
```

Each release typically includes these variants:

| Package | Architecture | Use case |
|---|---|---|
| `chr.x86_64.qemu.<ver>.utm.zip` | x86_64 | Standard CHR — simplest, fastest on Intel/AMD |
| `chr.aarch64.qemu.<ver>.utm.zip` | aarch64 | ARM64 CHR — native on Apple Silicon / ARM servers |
| `rose.chr.x86_64.qemu.<ver>.utm.zip` | x86_64 | CHR + 4×10 GB extra disks for ROSE / disk testing |
| `rose.chr.aarch64.qemu.<ver>.utm.zip` | aarch64 | ARM64 variant with extra disks |

### Scripted download (any version)

```sh
VERSION=7.22  ARCH=x86_64
curl -fsSL -o chr.utm.zip \
  "https://github.com/tikoci/mikropkl/releases/download/chr-${VERSION}/chr.${ARCH}.qemu.${VERSION}.utm.zip"
unzip chr.utm.zip
```

### Build from source

```sh
git clone https://github.com/tikoci/mikropkl.git
cd mikropkl
make CHR_VERSION=7.22
# Output in Machines/chr.x86_64.qemu.7.22.utm/
```

---

## Starting RouterOS

### Foreground (interactive)

```sh
cd ~/Downloads/chr.x86_64.qemu.7.22.utm
./qemu.sh
```

```
  chr.x86_64.qemu.7.22  accel=hvf
  WebFig:   http://localhost:9180/
  Login:    admin / no password

  Ctrl-A X  quit    |  Ctrl-A C  monitor    |  Ctrl-C → RouterOS
```

RouterOS serial console appears directly in your terminal.  Default login: **admin** with an empty password (just press Enter).

**Exit:** press `Ctrl-A` then `X`.  Or type `/quit` in the RouterOS CLI.

> [!NOTE]
> `Ctrl-C` is forwarded to RouterOS (it does not kill QEMU).  Use `Ctrl-A X` to exit.

### Background (headless)

```sh
cd ~/Downloads/chr.x86_64.qemu.7.22.utm
./qemu.sh --background
```

```
Starting chr.x86_64.qemu.7.22 (port 9180, accel=hvf)...
QEMU PID=54321 — log: /tmp/qemu-chr.x86_64.qemu.7.22.log
Serial:  socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-serial.sock
Monitor: socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-monitor.sock
```

Background mode writes the PID to `/tmp/qemu-<name>.pid` and provides Unix sockets for serial console and QEMU monitor access.

**Stop:**
```sh
./qemu.sh --stop
```

### Dry-run (see the QEMU command without executing)

```sh
./qemu.sh --dry-run
```

Useful for debugging or passing a modified command to QEMU manually.

---

## Accessing RouterOS

Port 80 (HTTP) inside the VM is forwarded to **localhost:9180** by default.

### WebFig

Open `http://localhost:9180/` in a browser — no authentication required for the initial page.

### REST API

```sh
# System identity
curl -u admin: http://localhost:9180/rest/system/identity

# List interfaces
curl -u admin: http://localhost:9180/rest/interface

# RouterOS version
curl -u admin: http://localhost:9180/rest/system/resource
```

The REST API uses HTTP basic auth.  The default password is empty, so `-u admin:` (note the trailing colon) is sufficient.

### Serial console (background mode)

```sh
socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-serial.sock
```

Full RouterOS CLI access.  Press `Ctrl-D` to disconnect from socat (the VM keeps running).

### SSH

RouterOS enables SSH by default on port 22.  To expose it, forward an additional port:

```sh
QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9122-:22" ./qemu.sh
```

> [!NOTE]
> `QEMU_NETDEV` replaces the default user-mode networking entirely.  Include all `hostfwd=` entries you need, including port 80 if you still want HTTP.  See [Forwarding Additional Ports](#forwarding-additional-ports) below.

---

## Changing the Port

The `--port` flag changes which host port maps to RouterOS HTTP (port 80):

```sh
./qemu.sh --port 8080
# RouterOS at http://localhost:8080/
```

Or via environment variable:
```sh
QEMU_PORT=8080 ./qemu.sh --background
```

---

## Running Multiple Instances

Each instance needs a unique port.  Run different versions side-by-side for comparison testing:

```sh
cd ~/Downloads/chr.x86_64.qemu.7.22.utm
./qemu.sh --background --port 9180

cd ~/Downloads/chr.x86_64.qemu.7.21.utm
./qemu.sh --background --port 9181
```

```sh
# Compare behavior across versions
curl -u admin: http://localhost:9180/rest/system/resource | jq .version
curl -u admin: http://localhost:9181/rest/system/resource | jq .version
```

Stop each:
```sh
cd ~/Downloads/chr.x86_64.qemu.7.22.utm && ./qemu.sh --stop
cd ~/Downloads/chr.x86_64.qemu.7.21.utm && ./qemu.sh --stop
```

> [!TIP]
> This is particularly useful when testing configuration migration between RouterOS versions — export from one, import to the other, and validate via the REST API.

---

## What's Inside the Package

```
chr.x86_64.qemu.7.22.utm/
├── qemu.sh              ← Launch script (run this)
├── qemu.cfg             ← QEMU machine definition (edit this for hardware)
├── qemu.env             ← Optional: persistent overrides (create this yourself)
├── config.plist         ← UTM configuration (ignore unless using UTM)
└── Data/
    └── chr-7.22.img     ← RouterOS CHR disk image (128 MiB)
```

### `qemu.cfg` — the machine definition

A standard QEMU [`--readconfig`](https://www.qemu.org/docs/master/system/invocation.html#hxtool-8) INI file (see [QEMU invocation docs](https://www.qemu.org/docs/master/system/invocation.html)).  This is where you change VM hardware — memory, CPUs, disks, NIC settings:

```ini
[machine]
  type = "q35"

[memory]
  size = "1024M"

[smp-opts]
  cpus = "2"

[drive "drive0"]
  file = "./Data/chr-7.22.img"
  format = "raw"
  if = "virtio"

[device "nic0"]
  driver = "virtio-net-pci"
  netdev = "net0"
  mac = "0e:fe:a9:e7:24:09"
```

**Editable.** Change memory, CPU count, or add drives directly in this file.  Paths are relative to the package directory.

> [!NOTE]
> **About the MAC address:** The `mac` line in `qemu.cfg` exists because these packages originate from UTM, whose `config.plist` requires an explicit MAC address.  For standalone QEMU use, this line is optional — QEMU auto-generates a unique MAC (from the `52:54:00:xx:xx:xx` range) if omitted.  You can safely remove or change it.  If you run multiple instances on the same bridge network, you **should** either remove or change the MAC to avoid conflicts, since all packages of the same version share the same generated value.

### `qemu.sh` — the launcher

A POSIX shell script that wraps `qemu.cfg` with platform detection (KVM/HVF/TCG), networking, UEFI firmware (aarch64), and serial/display setup.  Things that QEMU's `--readconfig` format cannot express live here.

In most cases, **edit `qemu.cfg` for hardware changes** and use `qemu.sh` flags, environment variables, or a `qemu.env` file for runtime behavior.

### `qemu.env` — persistent overrides (optional)

Create a `qemu.env` file alongside `qemu.sh` to set persistent environment variable overrides without modifying any generated file.  `qemu.sh` sources it automatically if present:

```sh
# qemu.env — example overrides
QEMU_PORT=9280
QEMU_ACCEL=tcg
QEMU_EXTRA="-m 2048"
```

Command-line flags (`--port`, `--shared`, etc.) take precedence over values in `qemu.env`.  The file is plain shell — any valid `VAR=value` assignment works.  This is the recommended way to persist per-machine settings like a custom port or alternate networking.

---

## Tuning VM Resources

### Memory

Edit `qemu.cfg`:
```ini
[memory]
  size = "2048M"
```

Or override at launch without editing:
```sh
QEMU_EXTRA="-m 2048" ./qemu.sh
```

### CPUs

Edit `qemu.cfg`:
```ini
[smp-opts]
  cpus = "4"
```

### Adding a disk

Append to `qemu.cfg` (x86_64 example):
```ini
[drive "drive1"]
  file = "./Data/extra.qcow2"
  format = "qcow2"
  if = "virtio"
```

Create the disk image first:
```sh
qemu-img create -f qcow2 ./Data/extra.qcow2 10G
```

RouterOS will see it as an additional drive — format it from the CLI with `/disk format-drive`.

> [!NOTE]
> The ROSE variants (`rose.chr.*.qemu`) ship with 4×10 GB qcow2 disks pre-configured in `qemu.cfg` — useful for testing RouterOS disk features without manual setup.

---

## Networking

The default configuration uses QEMU [user-mode (SLIRP)](https://www.qemu.org/docs/master/system/devices/net.html#using-the-user-mode-network-stack) networking with port forwarding.  This works without root privileges and is sufficient for management access.  Several alternatives exist for more advanced scenarios — see the [QEMU networking docs](https://www.qemu.org/docs/master/system/devices/net.html) for full details on each backend.

### Default: port forwarding (user-mode)

`qemu.sh` passes `-netdev user,id=net0,hostfwd=tcp::<port>-:80` on the command line.  The `qemu.cfg` defines the NIC hardware:

```ini
[device "nic0"]
  driver = "virtio-net-pci"
  netdev = "net0"
  mac = "0e:fe:a9:e7:24:09"
```

The `netdev` in `qemu.cfg` references `net0`, which `qemu.sh` creates.  This separation exists because QEMU's `--readconfig` format does not support the `hostfwd=` option needed for port forwarding.

### Forwarding additional ports

To expose SSH (22), WinBox (8291), and API (8728) alongside HTTP:

```sh
QEMU_NETDEV="user,id=net0,hostfwd=tcp::9180-:80,hostfwd=tcp::9122-:22,hostfwd=tcp::9291-:8291,hostfwd=tcp::9728-:8728" \
  ./qemu.sh
```

`QEMU_NETDEV` replaces the default netdev completely, so include the `hostfwd` for port 80 if you still want HTTP access.  All services are then reachable on `localhost` at their mapped ports.

> [!TIP]
> RouterOS uses many well-known ports.  Common ones to forward:
>
> | Service | Guest port | Example host port |
> |---|---|---|
> | HTTP/WebFig | 80 | 9180 |
> | SSH | 22 | 9122 |
> | WinBox | 8291 | 9291 |
> | API | 8728 | 9728 |
> | API-SSL | 8729 | 9729 |

### macOS networking (vmnet)

macOS does not have kernel tap/tun support.  Instead, QEMU 8+ supports Apple's [`vmnet.framework`](https://developer.apple.com/documentation/vmnet), which provides shared (NAT) and bridged networking modes.  `qemu.sh` has built-in flags for both:

**Shared networking (NAT):**
```sh
sudo ./qemu.sh --shared
```

Uses `vmnet-shared` — RouterOS gets an IP on a private NAT network (typically `192.168.64.x/24`).  The VM can reach the internet through macOS's NAT.  Requires `sudo` because `vmnet.framework` needs root.

**Bridged networking:**
```sh
sudo ./qemu.sh --bridge en0
```

Uses `vmnet-bridged` on the specified interface *plus* `vmnet-shared` as a second NIC.  RouterOS sees two interfaces: `ether1` bridged to your physical LAN (gets a real LAN IP via DHCP or static config), and `ether2` on the private vmnet NAT.  This gives full LAN access while keeping a management path.  Requires `sudo`.

> [!NOTE]
> When `qemu.sh` runs as root on macOS without explicit networking flags, it defaults to `vmnet-shared` automatically (more useful than SLIRP under `sudo`).

**Port forwarding is not used with vmnet.**  Access RouterOS by its vmnet IP address directly.  Find it via the serial console (`/ip address print`) or check your DHCP leases.

Both modes work in foreground and background:
```sh
sudo ./qemu.sh --shared --background
sudo ./qemu.sh --bridge en0 --background --port 9180
# (--port is ignored with vmnet, but harmless)
```

> [!TIP]
> If you only need management access (WebFig, SSH, REST API), the default user-mode networking with `--port` is simpler and does not require `sudo`.  Use vmnet when you need the CHR to participate on a real network — for example, testing DHCP server, OSPF, or BGP.

> [!NOTE]
> **Bridging over Wi-Fi** (macOS or Linux) introduces variable latency — the vmnet/tap bridge inserts the VM behind the wireless medium, so every packet pays the full 802.11 round-trip.  This can add 5–30 ms of jitter, visible in speed tests, latency-sensitive routing protocols (OSPF hello timers, BGP hold timers), and queue testing.  Use Ethernet when you need clean baseline numbers.  _That said, Wi-Fi jitter is great material for experimenting with `fq_codel`, CAKE, or other AQM techniques — set your queue target above the typical Wi-Fi RTT and watch the latency curve smooth out._

### Bridge networking (Linux)

Bridge networking connects the VM directly to a host network — the CHR gets its own IP address on the LAN (or from DHCP).  This is essential for testing DHCP server, routing protocols, or any scenario where port forwarding is insufficient.

> [!NOTE]
> The commands below illustrate the general approach for Linux bridge + tap networking.  Adapt interface names, IP addresses, and routes to your environment.  See the [QEMU networking docs](https://www.qemu.org/docs/master/system/devices/net.html#using-tap-network-interfaces) for full tap/bridge details.

**Setup:**
```sh
# Create a bridge and tap interface (requires root)
sudo ip link add br0 type bridge
sudo ip link set br0 up
sudo ip tuntap add tap0 mode tap user "$USER"
sudo ip link set tap0 master br0
sudo ip link set tap0 up

# Attach your physical interface (e.g. eth0) to the bridge
sudo ip link set eth0 master br0
# Move IP from eth0 to br0 (adjust for your network)
sudo ip addr del 192.168.88.100/24 dev eth0
sudo ip addr add 192.168.88.100/24 dev br0
sudo ip route add default via 192.168.88.1 dev br0
```

**Launch with the tap interface:**
```sh
QEMU_NETDEV="tap,id=net0,ifname=tap0,script=no,downscript=no" ./qemu.sh
```

This replaces the user-mode netdev.  RouterOS will bridge onto your physical network — configure its IP via CLI or DHCP as you would a real router.

> [!IMPORTANT]
> Bridge networking replaces user-mode networking entirely.  Port forwarding (`--port`) has no effect in bridge mode — access RouterOS by its bridge IP address.

### Shared networking / NAT with a bridge (Linux)

If you want multiple VMs to talk to each other *and* reach the internet, but don't want to bridge to a physical interface, create an isolated bridge with NAT.

> [!NOTE]
> This is a conceptual example showing the general pattern.  Interface names, subnets, and iptables rules will vary by distribution and existing network configuration.

```sh
# Create an isolated bridge
sudo ip link add br-chr type bridge
sudo ip addr add 10.99.0.1/24 dev br-chr
sudo ip link set br-chr up

# Create tap interfaces for each VM
sudo ip tuntap add tap0 mode tap user "$USER"
sudo ip link set tap0 master br-chr
sudo ip link set tap0 up

sudo ip tuntap add tap1 mode tap user "$USER"
sudo ip link set tap1 master br-chr
sudo ip link set tap1 up

# Enable NAT (outbound internet for the VMs)
sudo iptables -t nat -A POSTROUTING -s 10.99.0.0/24 ! -d 10.99.0.0/24 -j MASQUERADE
sudo sysctl -w net.ipv4.ip_forward=1
```

Launch two CHR instances on the same bridge:
```sh
cd ~/Downloads/chr.x86_64.qemu.7.22.utm
QEMU_NETDEV="tap,id=net0,ifname=tap0,script=no,downscript=no" ./qemu.sh --background

cd ~/Downloads/chr.x86_64.qemu.7.21.utm
QEMU_NETDEV="tap,id=net0,ifname=tap1,script=no,downscript=no" ./qemu.sh --background
```

Assign static IPs in each RouterOS instance (e.g. `10.99.0.2/24` and `10.99.0.3/24`) or run a DHCP server on one of them.  The two CHRs can reach each other and the internet via the host's NAT.

### Socket networking (inter-VM without root)

QEMU [socket networking](https://www.qemu.org/docs/master/system/devices/net.html#connecting-emulated-networks-between-qemu-instances) lets two VMs communicate over a shared Unix socket — no root, no bridge, no tap:

```sh
# VM 1 (server side)
QEMU_NETDEV="socket,id=net0,listen=:9500" ./qemu.sh --background --port 9180

# VM 2 (client side) — in a different CHR package directory
QEMU_NETDEV="socket,id=net0,connect=:9500" ./qemu.sh --background --port 9181
```

The two VMs share a virtual Ethernet segment.  Assign IPs manually in RouterOS and they can ping each other.  No host network involvement.

> [!NOTE]
> Socket networking supports exactly two peers per socket.  For more than two VMs, combine with a QEMU multi-point socket (`mcast`) or use bridge/tap.

### Adding a second NIC

To give RouterOS a WAN + LAN topology, add a second NIC in `qemu.cfg`:

```ini
[device "nic1"]
  driver = "virtio-net-pci"
  netdev = "net1"
```

Then provide the second netdev at launch:
```sh
QEMU_EXTRA="-netdev tap,id=net1,ifname=tap1,script=no,downscript=no" ./qemu.sh
```

> [!NOTE]
> Use `QEMU_NETDEV` to replace the *first* NIC's netdev (net0).  Use `QEMU_EXTRA` to *add* a second netdev (net1) — the two work together.

RouterOS will see `ether1` (net0, management) and `ether2` (net1, your tap).  Configure routing, NAT, or bridging in RouterOS as you would on hardware.

---

## Environment Variables

Override any default without editing files.  For persistent per-machine overrides, put these in a `qemu.env` file alongside `qemu.sh` (see [What's Inside the Package](#whats-inside-the-package)).

| Variable | Purpose | Example |
|---|---|---|
| `QEMU_PORT` | Host port for HTTP forwarding | `QEMU_PORT=8080 ./qemu.sh` |
| `QEMU_ACCEL` | Force accelerator | `QEMU_ACCEL=tcg ./qemu.sh` |
| `QEMU_BIN` | Path to QEMU binary | `QEMU_BIN=/opt/qemu/bin/qemu-system-x86_64 ./qemu.sh` |
| `QEMU_EXTRA` | Append additional QEMU flags | `QEMU_EXTRA="-m 2048" ./qemu.sh` |
| `QEMU_NETDEV` | Replace default netdev | `QEMU_NETDEV="tap,id=net0,ifname=tap0,script=no,downscript=no" ./qemu.sh` |
| `QEMU_EFI_CODE` | UEFI code ROM path (aarch64) | `QEMU_EFI_CODE=/path/to/AAVMF_CODE.fd ./qemu.sh` |
| `QEMU_EFI_VARS` | UEFI vars template (aarch64) | `QEMU_EFI_VARS=/path/to/AAVMF_VARS.fd ./qemu.sh` |

---

## QEMU Monitor

In background mode, the QEMU [Human Monitor Protocol (HMP)](https://www.qemu.org/docs/master/system/monitor.html) is exposed on a Unix socket for diagnostics:

```sh
# Interactive session
socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-monitor.sock

# One-shot queries
echo "info block" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-monitor.sock
echo "info network" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-monitor.sock
echo "info cpus" | socat - UNIX-CONNECT:/tmp/qemu-chr.x86_64.qemu.7.22-monitor.sock
```

Useful commands: `info block` (disk state), `info network` (netdev/NIC mapping), `info snapshots`, `system_powerdown` (graceful shutdown).

In foreground mode, press `Ctrl-A` then `C` to toggle between the serial console and the QEMU monitor.  `Ctrl-C` is forwarded to RouterOS — use `Ctrl-A X` to quit QEMU.

---

## Architecture Notes

### x86_64

- **Machine type:** `q35`
- **Firmware:** SeaBIOS (built into QEMU — no external files needed)
- **Disk:** `if=virtio` in `qemu.cfg` (resolves to `virtio-blk-pci` on q35)
- **Boot time:** ~10s with KVM/HVF, ~30–60s with TCG

### aarch64

- **Machine type:** `virt`
- **Firmware:** EDK2 UEFI — `qemu.sh` searches standard paths automatically (`/opt/homebrew/share/qemu/`, `/usr/local/share/qemu/`, `/usr/share/AAVMF/`)
- **Disk:** Explicit `virtio-blk-pci` device in `qemu.cfg` (the `if=virtio` shorthand maps to VirtIO-MMIO on `virt`, which RouterOS lacks a driver for — see [QEMU VirtIO docs](https://www.qemu.org/docs/master/system/devices/virtio-net.html))
- **Boot time:** ~10–20s with KVM/HVF, ~20–30s with TCG
- **Cross-arch:** aarch64 CHR boots on x86_64 hosts via TCG in ~20s — including macOS Intel

> [!NOTE]
> The reverse direction (x86_64 CHR on an aarch64 host) is not viable.  x86 firmware probes legacy I/O ports that have no ARM equivalent, making TCG emulation prohibitively slow.

---

## Disk Image Management

The CHR disk image is a 128 MiB raw disk — small enough to keep multiple versions around.

### Persistent vs. ephemeral

RouterOS writes its configuration to the disk image.  Every run accumulates state.  To start fresh:

```sh
# Re-extract the original image from the ZIP
cd ~/Downloads
unzip -o chr.x86_64.qemu.7.22.utm.zip chr.x86_64.qemu.7.22.utm/Data/chr-7.22.img
```

### Snapshots with qcow2

Convert the raw image to qcow2 for snapshot support:

```sh
cd ~/Downloads/chr.x86_64.qemu.7.22.utm
qemu-img convert -f raw -O qcow2 ./Data/chr-7.22.img ./Data/chr-7.22.qcow2
```

Update `qemu.cfg`:
```ini
[drive "drive0"]
  file = "./Data/chr-7.22.qcow2"
  format = "qcow2"
  if = "virtio"
```

Now you can snapshot from the QEMU monitor:
```
savevm baseline
# ... make changes ...
loadvm baseline
```

### Backing files (copy-on-write clones)

Need five CHRs running the same version?  Share one base image:

```sh
cd ~/Downloads
# One base (read-only after this)
BASE=chr.x86_64.qemu.7.22.utm/Data/chr-7.22.img

for i in 1 2 3 4 5; do
  qemu-img create -f qcow2 -b "$(pwd)/$BASE" -F raw "router${i}.qcow2"
done
```

Each `router*.qcow2` is a thin clone (~200 KB initially) storing only its own changes.  Point each instance's `qemu.cfg` at its own overlay file.

---

## Performance

| Scenario | Boot time | Notes |
|---|---|---|
| x86_64 on Intel/AMD host (KVM) | ~10s | Bare-metal Linux, fastest |
| x86_64 on macOS Intel (HVF) | ~10s | Near-native via Hypervisor.framework |
| aarch64 on ARM host (KVM) | ~10–15s | ARM servers, Raspberry Pi 5, etc. |
| aarch64 on macOS Apple Silicon (HVF) | ~10s | M1/M2/M3 native |
| aarch64 on x86_64 host (TCG) | ~20s | Cross-arch — fast because ARM uses MMIO |
| x86_64 on macOS Intel (TCG) | ~30–60s | Same-arch emulation, no HVF |

`qemu.sh` selects the fastest available accelerator automatically.  Force a specific one with `QEMU_ACCEL=tcg` or `QEMU_ACCEL=kvm` if needed.

---

## Troubleshooting

### QEMU not found

```
ERROR: qemu-system-x86_64 not found. Install QEMU or set QEMU_BIN.
```

Install QEMU for your platform (see [Platform Setup](#platform-setup)).

### Slow boot (no KVM)

If `qemu.sh` reports `accel=tcg` on a Linux host, KVM may not be enabled:

```sh
ls -la /dev/kvm           # should exist and be writable
sudo modprobe kvm-intel    # or kvm-amd
sudo usermod -aG kvm "$USER"
# Log out and back in
```

### Port conflict

```
bind: Address already in use
```

Another instance (or process) is using port 9180:
```sh
./qemu.sh --port 9181
# or find and kill the conflicting process:
lsof -i :9180
```

### Background instance dies immediately

Check the log:
```sh
cat /tmp/qemu-chr.x86_64.qemu.7.22.log
```

Common causes: missing UEFI firmware (aarch64), disk image not found (wrong working directory), or port already in use.

### aarch64 UEFI firmware not found

`qemu.sh` searches standard paths automatically.  Force a specific path:
```sh
QEMU_EFI_CODE=/usr/share/AAVMF/AAVMF_CODE.fd \
QEMU_EFI_VARS=/usr/share/AAVMF/AAVMF_VARS.fd \
  ./qemu.sh --dry-run
```

### HTTP not responding after boot

RouterOS takes a few seconds after boot to start HTTP.  On TCG, wait 30–60 seconds.  Verify the process is running and the port is listening:

```sh
ps aux | grep qemu
lsof -i :9180   # macOS
ss -tlnp | grep 9180  # Linux
```

---

## Known Limitations

- **`check-installation` fails on aarch64:** The RouterOS `check-installation` command returns an error on all aarch64 QEMU machines.  This is a known CHR limitation (ARM checker binary behavior) — RouterOS itself works fine.
- **DHCP server with user-mode networking:** QEMU's SLIRP backend does not pass broadcast traffic, so running a DHCP server in the CHR for external clients requires bridge or tap networking.
- **Disk size:** The CHR image is 128 MiB.  RouterOS manages its own partition layout — there is no need to resize it for typical use.
- **x86_64 on ARM64 hosts:** Not viable under TCG emulation (see [Architecture Notes](#architecture-notes)).

