# RouterOS CHR on UTM

[UTM](https://mac.getutm.app) is an open-source virtualisation app for macOS built on top of Apple's Virtualization.framework and QEMU.  Every CHR package from [mikropkl](https://github.com/tikoci/mikropkl/releases) is a ready-to-run UTM bundle — no image wrangling, no manual firmware setup, no QEMU flags to figure out.  Download a ZIP, open it in Finder, and you have a running RouterOS instance in under 30 seconds.

> [!NOTE]
> **No UTM?**  Every bundle also ships with `qemu.sh` + `qemu.cfg` for running directly under QEMU on macOS or Linux.  See [QEMU.md](QEMU.md) for that path.

---

## Installing UTM

Download UTM once.  It runs all packages.

- **Mac App Store** — [UTM Virtual Machines](https://apps.apple.com/us/app/utm-virtual-machines/id1538878817?mt=12) (sandbox mode; updates via App Store)
- **Direct download** — [UTM.dmg from GitHub](https://github.com/utmapp/UTM/releases/latest/download/UTM.dmg) (unsigned; drag to /Applications)

Both editions run CHR identically.  The App Store edition runs in a sandbox which may affect where UTM stores VMs and how it accesses /dev/kvm on Linux.  The GitHub edition is the build used in most documentation.

---

## Getting a CHR Package

### One-click install

Find a `utm://downloadVM?url=…` link in [GitHub Releases](https://github.com/tikoci/mikropkl/releases), paste it into a new browser tab or run from Terminal:

```sh
open 'utm://downloadVM?url=https%3A%2F%2Fgithub.com%2F...'
```

UTM opens, shows a download prompt, then imports the VM into its default library (`~/Library/Containers/com.utmapp.UTM/Data/Documents/`).  When you use this path, UTM **owns** the bundle — "Remove" in the UI deletes the machine and its disk.

### Manual ZIP download

Download a `.utm.zip` from [Releases](https://github.com/tikoci/mikropkl/releases), unzip it, and double-click the resulting `.utm` folder in Finder.  UTM opens and adds it as an **alias** — the bundle stays wherever you put it.  Moving the folder breaks the alias; "Remove" in UTM removes only the reference, not the files.

> Manual placement is better when you want to keep machines in a specific directory or on a separate volume.

### Build from source

```sh
git clone https://github.com/tikoci/mikropkl
cd mikropkl
make CHR_VERSION=7.23
open Machines/chr.x86_64.qemu.7.23.utm
```

See the [project README](../README.md#build-locally) for build prerequisites.

---

## Package Variants at a Glance

Each release publishes several packages.  Pick the right one for your Mac and use case.

| Package | Virtualisation | Architecture | Notes |
|---|---|---|---|
| `chr.x86_64.qemu` | QEMU + SeaBIOS | Intel/AMD | Widest compatibility; USB device pass-through |
| `chr.x86_64.apple` | Apple VZ + UEFI | Intel Mac | Faster startup; no USB |
| `chr.aarch64.qemu` | QEMU + EDK2 UEFI | ARM64 cross-arch | Runs on any Mac; useful for testing aarch64 images |
| `chr.aarch64.apple` | Apple VZ + UEFI | Apple Silicon native | Best performance on M-series |
| `rose.chr.x86_64.qemu` | QEMU + SeaBIOS | Intel/AMD | + 4 × 10 GB blank disks for ROSE / disk feature testing |
| `rose.chr.aarch64.qemu` | QEMU + EDK2 | ARM64 | + 4 × 10 GB blank disks |

**Apple Silicon Macs** can run any package.  The `aarch64.apple` variant is fastest — it uses Apple's native hypervisor.  The `x86_64` packages run under QEMU's TCG emulation (slower, but useful for cross-architecture testing).

**Intel Macs** run `x86_64` variants natively.  `aarch64` packages run under TCG emulation.

### QEMU vs Apple Virtualization

UTM exposes two fundamentally different backends.

**QEMU backend** (`*.qemu.*`) emulates hardware using QEMU.  RouterOS sees a q35 chipset (x86) or `virt` machine (ARM) with VirtIO devices.  You get port forwarding, Host-Only networking, USB device pass-through, and a wider range of network modes.  The backend can run any architecture on any host via software emulation (TCG).

**Apple Virtualization backend** (`*.apple.*`) uses Apple's [Virtualization.framework](https://developer.apple.com/documentation/virtualization) — the same technology behind macOS VMs in Parallels and VMware.  It starts faster and uses less CPU, but only supports the host's native architecture directly.  USB pass-through is not available.  Network modes are limited to Shared and Bridged.

For most networking lab work, the QEMU backend gives you the most control.  The Apple backend shines for persistent, lightweight instances where boot time and CPU efficiency matter.

---

## First Boot

Start a VM by double-clicking it in UTM's main window, or via the toolbar.  The built-in terminal opens automatically and the RouterOS CLI appears within a few seconds.

**Default credentials:** username `admin`, empty password (press Enter when prompted for a password).  RouterOS will ask you to set one on first login — do this before putting the VM on a routable network.

### Access from macOS

All packages default to **Shared** networking.  RouterOS gets a DHCP address on the `192.168.64.0/24` vmnet-shared subnet.  Find it from the CLI:

```routeros
/ip/address/print
```

Or from macOS:

```sh
# macOS shares 192.168.64.1 as the gateway; check ARP for the VM's address
arp -an | grep 192.168.64
```

**WebFig** is available at `http://<vm-ip>/` — no authentication for the initial page.

**REST API:**
```sh
curl -u admin: http://192.168.64.x/rest/system/identity
curl -u admin: http://192.168.64.x/rest/interface
```

The REST API uses HTTP Basic Auth with an empty password, so `admin:` (note the trailing colon) is correct.  See [MikroTik REST API docs](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API) for the full reference.

> [!TIP]
> **Testing queuing?**  The vmnet-shared network is ideal.  RouterOS sees it as a real Ethernet interface.  You can add a `/queue simple` or `/queue tree` on `ether1`, saturate it from macOS with `iperf3`, and watch `/queue/simple/print stats` in real time — no extra hardware needed.  Wi-Fi jitter (see [below](#wi-fi-and-latency)) can actually make this more interesting: queue depth becomes visible in latency measurements.

---

## Networking

This is the section network admins will live in.  The choice of network mode determines how RouterOS connects to macOS, to other VMs, and to the outside world.

### Shared Network (NAT) — default

Every package ships with one interface in Shared mode.  UTM implements this using Apple's `vmnet.framework` — RouterOS gets a private IP (`192.168.64.0/24` by default) and all outbound traffic is NATed through macOS's active interface.

RouterOS can reach the internet.  macOS can reach RouterOS directly.  Other machines on your LAN cannot reach the VM unless you bridge or forward ports.

> From RouterOS's perspective this is a perfectly normal upstream Ethernet link with a default gateway — configure firewall, NAT masquerade, and DHCP server exactly as you would on hardware.

**Customising the Shared subnet** (QEMU backend only): In UTM's network settings under Advanced, you can change "Guest Network" to a different subnet and adjust DHCP start/end ranges.  The "Host Address" field sets the IP macOS presents to RouterOS as the default gateway.

### Port Forwarding — QEMU + Emulated VLAN

Port forwarding is only available on QEMU backend VMs using **Emulated VLAN** network mode (not Shared), and it maps a macOS `localhost` port to a guest port.  Configure it in **VM settings → Devices → Network → Port Forwarding** ([UTM docs](https://docs.getutm.app/settings-qemu/devices/network/port-forwarding/)).

Common RouterOS ports to forward:

| Service | Guest Port | Example Host Port |
|---|---|---|
| HTTP / WebFig | 80 | 8080 |
| SSH | 22 | 2222 |
| WinBox | 8291 | 8291 |
| API | 8728 | 8728 |
| API-SSL | 8729 | 8729 |

> [!NOTE]
> The Emulated VLAN mode (listed in UTM as just "Emulated VLAN") is functionally equivalent to QEMU's user-mode `slirp` networking — the VM gets an isolated subnet and traffic is NATed, but you must explicitly forward every port you want to reach from macOS.  **Shared** mode (vmnet) is generally simpler for lab use because all ports are reachable without port-forwarding rules.

### Bridged — Physical Network Integration

Bridged mode connects RouterOS directly to a macOS network interface via `vmnet-bridged`.  The VM gets its own MAC address on the physical network and can obtain a real DHCP address from your router or act as one.

Configure in **VM settings → Devices → Network → Mode → Bridged**, then select the interface.

This is the right choice when:
- You want RouterOS to run DHCP/DNS/BGP/OSPF for real clients on your LAN
- You need the VM reachable from other machines without port-forwarding
- You're testing MAC-layer behaviour (spanning tree, 802.1Q, etc.)

> [!IMPORTANT]
> **Ethernet dongles make excellent bridge interfaces.**  Bridge to an external USB Ethernet adapter to connect RouterOS to a network segment physically isolated from your Mac's primary interface — no risk of disrupting your own connectivity.  This is the recommended topology for production-like testing.

**Apple VZ backend:** Bridged mode works the same way but Apple's framework handles the bridge.  Configure the interface under **VM settings → Devices → Network → Mode → Bridged** ([Apple VZ network docs](https://docs.getutm.app/settings-apple/devices/network/)).

#### Wi-Fi and Latency

Bridging over Wi-Fi works but introduces variable latency.  The `vmnet.framework` bridge inserts the VM behind the wireless medium, so every packet pays the full 802.11 round-trip.  On a busy 2.4 GHz network this can add 5–30 ms of jitter.

This is largely invisible for management access, but it surfaces in:
- Speed testing (bandwidth fluctuates with Wi-Fi retransmission)
- Latency-sensitive routing protocol testing (OSPF hello timers, BGP hold timers)
- Queue testing where you want clean baseline latency

> [!TIP]
> **Wi-Fi jitter is not always a problem.**  If you're experimenting with `fq_codel`, CAKE, or other AQM techniques, a Wi-Fi bridge produces naturally bursty traffic — perfect material for seeing queue algorithms work.  Set your queue target above the typical Wi-Fi RTT (~10–20 ms) and watch the latency curve smooth out.  Use Ethernet when you want clean numbers.

UTM's own note: bridging with Wi-Fi "may require additional configuration" — on some macOS versions, `vmnet-bridged` on a Wi-Fi interface requires that System Settings → Network grants UTM full network access.  If the VM gets no DHCP address after bridging to Wi-Fi, check macOS Privacy & Security settings.

### Host-Only and Host Networks — Multi-VM Isolation

**Host-Only** mode (QEMU backend only) creates a private network between macOS and the VM with no internet access — no WAN gateway is provided.  Use it when you want RouterOS to be reachable from your Mac but completely isolated from external networks.

**Host Networks** (UTM Preferences → Network) go further: you can create a named isolated network segment and attach multiple VMs to it.  All VMs on the same host network can reach each other directly, but no DHCP is provided — you configure IPs on each RouterOS interface manually.  This is the right primitive for multi-router topologies:

1. Create a host network in UTM Preferences (⌘+, → Network → Host Networks → +)
2. Add a second network interface to each CHR VM, assigned to that host network
3. Configure IP addresses on RouterOS: `/ip/address/add address=10.0.0.1/30 interface=ether2`

> Host Networks in UTM can share a UUID with other vmnet-compatible apps — notably VMware Fusion.  If you have both installed, you can mix CHR instances with other VMs on the same isolated segment.

### Multiple NICs

All packages ship with one NIC.  Add more in **VM settings → Devices → + → Network**.  RouterOS auto-discovers new VirtIO interfaces as `ether2`, `ether3`, etc.

A typical lab topology uses three interfaces:
- `ether1` — Shared (macOS management access, internet)
- `ether2` — Bridged to physical LAN or USB Ethernet (external connectivity)
- `ether3` — Host Network (inter-VM link to another CHR)

```routeros
/ip/address/add address=192.168.88.1/24 interface=ether3
/ip/dhcp-server/add interface=ether3 address-pool=pool1
/ip/pool/add name=pool1 ranges=192.168.88.100-192.168.88.200
```

### How UTM Network Modes Map to QEMU

When running a QEMU-backend VM, UTM translates the `config.plist` network mode into actual QEMU flags:

| UTM Mode | QEMU implementation | Notes |
|---|---|---|
| Emulated VLAN | `-netdev user` (SLIRP) | Port forwarding supported |
| Shared | `-netdev vmnet-shared` | vmnet.framework, macOS only |
| Host-Only | `-netdev vmnet-host,uuid=…` | Requires host network UUID |
| Bridged | `-netdev vmnet-bridged,ifname=…` | Chosen interface |

All CHR packages use `virtio-net-pci` hardware regardless of mode.  You can confirm this in the `config.plist`: `<key>Hardware</key><string>virtio-net-pci</string>` (QEMU backend) or no Hardware key (Apple VZ — framework handles the VirtIO NIC directly).

---

## ROSE: CHR with Extra Disks

The `rose.*` packages add four 10 GB blank disks to a standard CHR image.  RouterOS sees them as `disk1`–`disk4`.

ROSE storage is inactive by default.  Enable it from the CLI and reboot:

```routeros
/system/package { update/check-for-updates duration=10s; enable rose-storage; apply-changes }
```

Format and share all disks over SMB in one pass:

```routeros
:foreach d in=[/disk/find] do={ /disk format $d file-system=btrfs without-paging }
:foreach d in=[/disk/find] do={ /disk set $d smb-sharing=yes smb-user=rose smb-password=rose }
```

BTRFS supports RAID 1 and RAID 10 across those four disks — test software RAID behaviour without touching real hardware.  See [MikroTik ROSE docs](https://help.mikrotik.com/docs/x/HwCZEQ) for the full feature set.

---

## Console Access

### Built-In Terminal

UTM renders a full ANSI terminal window for each VM.  This is RouterOS's primary serial console — the equivalent of a physical serial cable.  The window uses Menlo 12pt on a black background by default, matching a classic terminal look.

Press Enter at the login prompt.  RouterOS's CLI is a REPL, not a shell.  There is no `/bin/sh`.  See [MikroTik Scripting](https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting) for the language reference.

### Pseudo-TTY Serial

Every CHR package adds a second serial device configured as a **pseudo-TTY** (`Ptty`).  When the VM is running, UTM's details pane shows the PTY path (e.g. `/dev/ttys014`).  Connect from Terminal:

```sh
screen /dev/ttys014
```

The PTY is useful for automation: `expect` scripts, scripted RouterOS provisioning, or testing serial-based integrations.

> RouterOS only uses the **first** serial port as a login console.  The second PTY port is unassigned.  To enable it as an additional console: `/system/console/add port=serial1`.  This is covered in more detail in [tikoci/chr-utm](https://github.com/tikoci/chr-utm/blob/main/README.md).

### Headless Mode

Remove the display device and the built-in terminal serial device from VM settings to run completely in the background — no windows, no dock icon activity while VMs run.

To set up headless mode:
1. VM settings → Devices — delete any Display
2. Delete the Serial device with Mode = "Built-in Terminal"
3. Keep the Ptty serial device (your only console path)
4. Start the VM; UTM shows it as running in the main window with no associated window

From UTM Preferences (⌘+,), enable **"macOS 13+ Show menu bar icon"** so you can start/stop headless VMs from the menu bar without opening the main window.  Enable **"Prevent system from sleeping while VMs are running"** if VMs need to stay up overnight.

See [UTM headless docs](https://docs.getutm.app/advanced/headless/) for the full walkthrough.

---

## VM Configuration and Resources

The `config.plist` inside each `.utm` bundle is the source of truth for UTM.  `mikropkl` generates it from the `pkl` manifest with sensible defaults — 1 GB RAM, 2 vCPUs.

Edit settings in UTM's UI (right-click a VM → Edit) or modify `config.plist` directly in a text editor while the VM is stopped.

### Memory and CPU

RouterOS CHR runs comfortably in 1 GB.  For heavy routing tables or large MPLS deployments, 2–4 GB is reasonable.  Set in VM settings → System.

### Disk Image Management

The CHR disk image is 128 MiB — small enough to keep multiple versions around.  RouterOS persists all configuration to disk.  To start fresh, re-extract the original image from the release ZIP:

```sh
unzip -o chr.x86_64.qemu.7.23.utm.zip chr.x86_64.qemu.7.23.utm/Data/chr-7.23.img
```

This resets the CHR to factory defaults while leaving the rest of the bundle intact.

### Cloning a VM

Right-click a VM in UTM and choose **Clone**.  UTM copies the bundle to a new location.  New MAC addresses are generated automatically if "Regenerate MAC addresses on clone" is enabled in Preferences → Network (it is by default).

This is the fastest way to spin up a second router for two-node testing:

1. Clone `chr.x86_64.qemu.7.23`
2. Add each VM to a shared Host Network
3. Start both; configure IPs on the new interfaces
4. Run BGP/OSPF/MPLS between them on a private segment

---

## Under the Hood: config.plist to QEMU

UTM translates `config.plist` into actual QEMU arguments at runtime.  Understanding this mapping helps when debugging or when switching to `qemu.sh`-based operation.

### QEMU x86_64 machine

```
Backend = QEMU → qemu-system-x86_64
System.Architecture = x86_64 → -M q35
System.Boot.UEFIBoot = false → SeaBIOS (no pflash needed)
Drive.Interface = VirtIO → if=virtio (resolves to virtio-blk-pci on q35)
Network.Hardware = virtio-net-pci → -device virtio-net-pci
Network.Mode = Shared → -netdev vmnet-shared,id=net0
```

### Apple VZ x86_64 machine

```
Backend = Apple → Virtualization.framework (not QEMU)
System.Boot.UEFIBoot = true → Apple's built-in UEFI (no pflash file)
Drive.Nvme = true → real NVMe via VZ (not VirtIO)
Network.Mode = Shared → VZ shared networking (same 192.168.64.x subnet)
```

The `chr.x86_64.apple` package uses a specially reformatted disk image (`chr-efi.img`) from [tikoci/fat-chr](https://github.com/tikoci/fat-chr).  Standard MikroTik x86 images have a proprietary boot sector that Apple VZ (and OVMF) cannot read — `fat-chr` repackages the EFI partition as standard FAT16 so Apple's UEFI can load it.

### aarch64 quirk: NVMe plist vs VirtIO reality

The `chr.aarch64.qemu` plist declares `Interface = VirtIO` and there's no Hardware key for disk — UTM internally translates this to `-device virtio-blk-pci` explicitly rather than using the `if=virtio` shorthand.

This matters because on the QEMU `virt` machine type, `if=virtio` resolves to `virtio-blk-device` (MMIO) rather than `virtio-blk-pci` (PCI).  RouterOS has the `virtio_pci` driver but not `virtio_mmio` — using the shorthand on aarch64 causes a boot stall.  UTM knows this and generates the correct explicit device argument.  The `qemu.sh` scripts generated by `mikropkl` do the same.

You can verify what UTM actually passes to QEMU by opening Activity Monitor, finding the `qemu-system-*` process, and checking its full command line in the Info pane.

### Serial ports

Both packages include two serial devices in `config.plist`:
- `Mode = Terminal` → UTM opens a terminal window backed by a virtual UART
- `Mode = Ptty` → UTM creates a `/dev/ttys*` pseudo-TTY

QEMU backend UTM translates these to `-chardev` arguments.  Apple VZ backend uses Virtualization.framework's `VZVirtioConsoleDeviceConfiguration`.

---

## Automation

### URL Scheme

The `utm://` URL scheme drives basic VM lifecycle from Terminal, Shortcuts, or Automator.  All commands take a `name` parameter matching the VM's display name exactly (URL-encoded).

```sh
# Start
open "utm://start?name=chr.x86_64.qemu.7.23"

# Stop (immediate — like pulling the power)
open "utm://stop?name=chr.x86_64.qemu.7.23"

# Pause and resume
open "utm://pause?name=chr.x86_64.qemu.7.23"
open "utm://resume?name=chr.x86_64.qemu.7.23"
```

Stopping via `utm://stop` is not a graceful shutdown.  For graceful shutdown, run `/system/shutdown` via the REST API or serial first, then use `utm://stop` to confirm UTM releases the process.

See [UTM URL scheme reference](https://docs.getutm.app/advanced/remote-control/) for the full command list including `sendText` and `click`.

### `utmctl` — Command-Line Interface

`utmctl` is UTM's bundled CLI tool, wrapping the AppleScript interface:

```sh
# Add to PATH once
sudo ln -sf /Applications/UTM.app/Contents/MacOS/utmctl /usr/local/bin/utmctl

# List all VMs and their status
utmctl list

# Start / stop
utmctl start "chr.x86_64.qemu.7.23"
utmctl stop "chr.x86_64.qemu.7.23"

# Run a command inside the VM (QEMU backend with SPICE only — not applicable to CHR)
# utmctl exec ...
```

For CHR, `utmctl start` and `utmctl stop` (and `list`) are the most useful subcommands.  The `exec` command requires SPICE guest integration which RouterOS does not have.

See [UTM scripting docs](https://docs.getutm.app/scripting/scripting/) for the full reference.

### Shortcuts

UTM registers Shortcuts actions for Find, Start, Stop, Pause, Resume, Restart VMs.  Build a shortcut that starts specific VMs, then add it to Login Items (System Settings → General → Login Items) to auto-start CHR instances at login.

See [UTM remote control docs](https://docs.getutm.app/advanced/remote-control/) for a downloadable example shortcut.

### AppleScript

UTM exposes a rich AppleScript dictionary.  Browse it in Script Editor (File → Open Dictionary → UTM), or check the [AppleScript cheat sheet](https://docs.getutm.app/scripting/cheat-sheet/).

```applescript
-- Start a VM
tell application "UTM"
    start virtual machine named "chr.x86_64.qemu.7.23"
end tell

-- Check status
tell application "UTM"
    set s to status of virtual machine named "chr.x86_64.qemu.7.23"
end tell
```

The `mikropkl` Makefile uses AppleScript internally for its `utm-start`, `utm-stop`, and `utm-install` targets — see the Makefile for examples of batch operations across all machines.

### Start CHR Automatically at Login

1. Create a Shortcut that calls the "Start Virtual Machine" UTM action for your CHR
2. In System Settings → General → Login Items, add the shortcut
3. CHR starts headlessly on every login

Combined with headless mode and a hide-dock-icon preference, CHR runs as a background service with no visible footprint.

---

## Running without UTM

Every `.utm` bundle is a ZIP archive that includes a `qemu.sh` launcher and `qemu.cfg` configuration.  Unzip and run it on any macOS or Linux machine with QEMU installed — no UTM required.

This is how the [GitHub Actions CI](https://github.com/tikoci/mikropkl/blob/main/.github/workflows/qemu-test.yaml) validates every package: it unzips, runs `./qemu.sh --background --port 9180`, and queries the REST API to confirm RouterOS booted.

See [QEMU.md](QEMU.md) for the full guide: platform setup, networking options (including bridge/tap on Linux), disk image management, and `qemu.sh` environment variables.

---

## CHR Licensing

All packages ship unlicensed, running in **free** mode: all features enabled, 1 Mb/s upload cap per interface — permanently.

To activate a **trial** (up to 10 Gb/s, no feature restrictions, expires after 60 days for upgrades):

```routeros
/system/license/renew level=p10
```

RouterOS will prompt for a MikroTik account username and password.  Requires an account at [mikrotik.com/client](https://www.mikrotik.com/client) and internet access from the VM.

Note: `/ip/cloud` features (DDNS, BackToHome) require a paid perpetual license — they are not part of the free or trial tiers.  See [MikroTik CHR licensing docs](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR#CloudHostedRouter%2CCHR-Freelicenses) for all tier details.

---

> **Disclaimers** — Not affiliated with MikroTik, Apple, or Turing Software, LLC.  CHR images are subject to [MikroTik's EULA](https://mikrotik.com/downloadterms.html).  All trademarks remain property of their respective holders.
