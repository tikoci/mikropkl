
# `mikropkl` — declarative RouterOS virtual machines with `pkl` 

> _Describe a VM in [`pkl`](https://pkl-lang.org), run `make`, get a running RouterOS instance._

`mikropkl` uses [pkl](https://pkl-lang.org) manifests to produce ready-to-run [MikroTik RouterOS CHR](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234) virtual machine packages.  A few lines of pkl declare the architecture, backend, disk layout, and networking — everything else is computed.  Creating a new variant is a one-file `amends` away from an existing template; `make` handles the rest.


> [!TIP]
>
> #### <mark>NEW</mark> [ CHR Image Download Picker](https://tikoci.github.io/chr-images.html) 
> Pick a version, architecture, and type.  The page generates download links and setup instructions for both UTM and QEMU.  _Packages are always in [GitHub Releases](https://github.com/tikoci/mikropkl/releases) too._


Each package is a `.utm` bundle — a folder that [UTM](https://mac.getutm.app) opens directly on macOS.  Inside the same bundle, `qemu.sh` + `qemu.cfg` let you run the VM under QEMU on macOS or Linux without UTM.  Pick what fits: GUI on Mac, headless on a server, CI in GitHub Actions. _The "`.utm` bundle" is really just a ZIP file, and on Linux, just a <del>folder</del> directory that ends in `.utm` when extracted._

> QEMU launch scripts were added in 7.22 to `mikropkl` builds.  Older releases do not have QEMU scripts, `qemu.sh` and `qemu.cfg`.  If one is needed, file an [GitHub issue](https://github.com/tikoci/mikropkl/issues) or [build locally](#build-locally) using `make`.


## Getting Started

> [!NOTE]
> **Homebrew** is used to install both UTM and QEMU.  If you don't have it: [brew.sh](https://brew.sh).

### macOS (UTM)

```sh
brew install --cask utm
```

Open a package from the [CHR Images](https://tikoci.github.io/chr-images.html) page — it provides both a **Download ZIP** button and an **Open in UTM** link that imports the VM directly.

> Alternatives: [UTM.dmg from GitHub](https://github.com/utmapp/UTM/releases/latest/download/UTM.dmg) (free, unsigned) or [Mac App Store](https://apps.apple.com/us/app/utm-virtual-machines/id1538878817?mt=12) (sandbox mode).  All editions run CHR identically.

UTM supports two backends: **QEMU** (cross-architecture emulation, USB pass-through, wider networking) and **Apple Virtualization** (faster startup, native performance, macOS-only). _`*.apple.*` packages use EFI on X86, needed Apple's Virtualization.framework, but work under Linux and QEMU using EFI boot there too. `*.qemu.*` packages always use SeaBIOS and standard RouterOS image._

Default credentials: **admin** with an empty password.  All bundles default to **Shared** networking (NAT) with RouterOS on `192.168.64.0/24`.

> [!TIP]
> **New to UTM + RouterOS?**  The [UTM Guide](Files/UTM.md) covers networking modes, console access, multi-VM topologies, automation, and how UTM settings map to QEMU — oriented toward network admins who use RouterOS regularly.

### macOS or Linux (QEMU)

```sh
brew install qemu          # macOS
# or: sudo apt-get install qemu-system-x86 qemu-utils   # Ubuntu/Debian x86_64
```

Download a package from the [CHR Images](https://tikoci.github.io/chr-images.html) page, then:

```sh
unzip chr.x86_64.qemu.7.22.utm.zip
cd chr.x86_64.qemu.7.22.utm
./qemu.sh
```

`qemu.sh` auto-detects KVM, HVF, or TCG — no manual accelerator config needed.

> [!TIP]
> **Full QEMU details** — platform setup, networking (port forwarding, vmnet on macOS, bridge/tap on Linux), disk snapshots, multi-instance setups — are in the [QEMU Guide](Files/QEMU.md).

## RouterOS CHR

RouterOS documentation: [help.mikrotik.com](https://help.mikrotik.com/docs) · [Forum](https://forum.mikrotik.com)

### CHR Licensing

CHR packages ship unlicensed, running in **free** mode: all features enabled, 1 Mb/s upload cap per interface — permanently.  To activate a **trial** (up to 10 Gb/s, no feature restrictions, expires after 60 days for upgrades):

```routeros
/system/license/renew level=p10
```

This requires a [mikrotik.com](https://www.mikrotik.com/client) account and internet access from the VM.  See MikroTik's [CHR licensing docs](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR#CloudHostedRouter%2CCHR-Freelicenses) for all tier details.

> `/ip/cloud` features (DDNS, BackToHome) require a paid perpetual license — they are not part of the free or trial tiers.

### Extra Packages

CHR images ship with a minimal package set.  MikroTik calls the optional ones "extra packages" — they're bundled inside the CHR image but disabled by default.  Enabling them follows the same pattern: check for updates (downloads the package index, requires internet), enable the package, and apply:

```routeros
/system/package { update/check-for-updates duration=10s; enable <package-name>; apply-changes }
```

> [!IMPORTANT]
> The `check-for-updates` step downloads the package index from MikroTik and **requires internet access** from the VM.  With UTM Shared networking or QEMU user-mode networking (`./qemu.sh`), internet is available by default.  If you're using QEMU socket networking or an isolated bridge, you'll need to add a NATed interface first or install packages manually — see MikroTik's [package management docs](https://help.mikrotik.com/docs/spaces/ROS/pages/328129/Packages).

**Common extra packages:**

| Package | Enable command | Use case |
|---|---|---|
| `rose-storage` | `/system/package { update/check-for-updates duration=10s; enable rose-storage; apply-changes }` | BTRFS, RAID, SMB file sharing — requires ROSE variant with extra disks |
| `container` | `/system/package { update/check-for-updates duration=10s; enable container; apply-changes }` | Run OCI containers inside RouterOS (see [tikoci/containers](https://github.com/tikoci?tab=repositories&q=container)) |

After enabling `container`, you also need to enable advanced device mode:

```routeros
/system/device-mode/update mode=advanced container=yes
```

RouterOS CHR machines needs be "power cycled" for `device-mode` changes, so either stopped or terminated - not `/system/shutdown`.  See MikroTik's [container docs](https://help.mikrotik.com/docs/spaces/ROS/pages/84901929/Container) for the full walkthrough.

### ROSE Variant

The `rose.*` packages add 4 × 10 GB blank qcow2 disks to a standard CHR image.  After enabling `rose-storage` (see above) and rebooting, format and optionally share the disks:

```routeros
:foreach d in=[/disk/find] do={/disk format $d file-system=btrfs without-paging }
:foreach d in=[/disk/find] do={/disk set $d smb-sharing=yes smb-user=rose smb-password=rose }
```

BTRFS supports RAID 1 and RAID 10 across those four disks — test software RAID behaviour without touching real hardware.  See MikroTik's [ROSE docs](https://help.mikrotik.com/docs/x/HwCZEQ) for the full feature set.

> [!TIP]
>
> #### RouterOS employs a unique configuration language
>
> MikroTik RouterOS is built on the Linux kernel, but "userland" is neither GNU nor BSD — it's a proprietary system with a rich [scripting interface](https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting).  **All router configuration is scripting** _(outside GUI tools like [WinBox](https://mikrotik.com/download))_.  There is no `/bin/sh` — the CLI is a REPL for the scripting language.
>
> Unlike a traditional shell, RouterOS has a full [type system](https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting#Scripting-Datatypes): IP addresses and CIDR prefixes are first-class types, arrays can be multi-dimensional and contain functions, but there's no float — _`1.1` is an IP address (shorthand for `1.0.0.1` per early RFCs), not a decimal number._  RouterOS doesn't have anything like pkl's nifty [`DataSize`](https://pkl-lang.org/package-docs/pkl/0.26.0/base/DataSize.html) type, which does come up in networking.
>
> While unexplored here, RouterOS lends itself to pkl-generated configuration.  A pkl [Renderer](https://pkl-lang.org/main/current/language-reference/index.html#renderers) could output RouterOS scripts, or an [external resource reader](https://pkl-lang.org/main/current/language-reference/index.html#extending-resource-readers) could fetch data from RouterOS for use in `pkl` manifests.

## Build locally

Building from source lets you create CHR derivatives, test custom configurations, and run machines directly from the build directory.

### Prerequisites

**macOS:**
```sh
brew install pkl qemu    # pkl + qemu-img (+ qemu-system-* for running)
```

**Ubuntu / Debian:**
```sh
# x86_64 host:
sudo apt-get install make pkl git qemu-system-x86 qemu-system-arm qemu-efi-aarch64 qemu-utils
# aarch64 host:
sudo apt-get install make pkl git qemu-system-arm qemu-efi-aarch64 qemu-utils
```

> `make` and `git` are typically pre-installed.  `qemu-img` (from `qemu-utils`) is only needed for ROSE variants (extra qcow2 disks).

### Build

```sh
git clone https://github.com/tikoci/mikropkl
cd mikropkl
make                         # builds all machines (stable channel)
make CHR_VERSION=7.22        # pin a specific version
make CHR_VERSION=long-term   # use a release channel
```

Output lands in `Machines/` — one `.utm` directory per manifest in `Manifests/`.

### Run

```sh
# Interactive (foreground — serial console on stdio):
make qemu-run QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# Headless (background — serial on Unix socket):
make qemu-start QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm
make qemu-stop  QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm

# All machines at once (auto-assigned ports 9180, 9181, ...):
make qemu-start-all
make qemu-status       # PIDs, logs, sockets, CPU/memory
make qemu-stop-all
```

WebFig: `http://localhost:9180/` — REST API: `http://admin:@localhost:9180/rest/`

### Rebuild

```sh
make clean && make CHR_VERSION=7.22   # rebuild (reuses cached downloads)
make distclean && make                # full clean including download cache
```

> Running `make` overwrites all machines in `Machines/`, including disk images.  Any RouterOS state from previous runs is lost.  See [QEMU.md — Disk Image Management](Files/QEMU.md#disk-image-management) for snapshot and overlay strategies.

### UTM (macOS)

```sh
make utm-install     # open all built .utm bundles in UTM
make utm-start       # start all VMs via AppleScript
make utm-stop        # stop all VMs
make utm-uninstall   # remove all from UTM
```

## Creating new machines

Each file in `Manifests/` produces one machine in `Machines/`.  To create a new variant, copy an existing manifest and adjust:

```sh
cp Manifests/chr.x86_64.qemu.pkl Manifests/my-router.pkl
# Edit my-router.pkl — change architecture, backend, disks, etc.
make
# Output: Machines/my-router.7.22.utm/
```

Manifests are short — typically 4–6 lines that `amend` a template:

```pkl
amends "../Templates/chr.utmzip.pkl"
import "../Pkl/CHR.pkl"
backend = "QEMU"
architecture = "aarch64"
```

To control the CHR version: `make CHR_VERSION=7.23beta2` or `make CHR_VERSION=long-term`.  MikroTik's `stable` channel is the default.

> **Tweaking** an existing configuration doesn't require deep `pkl` knowledge — just edit or copy a file in `Manifests/`.  The complexity lives in `Pkl/` and `Templates/`.  For new machine types beyond CHR, see the [pkl documentation](https://pkl-lang.org).

> [!TIP]
>
> #### Difference between _imported_ and _aliased_ machines in UTM
>
> The difference is the `utm://` will "import" the machine, and use its default store (i.e. `~/Library/Containers/UTM/Data`) along with other machines created from UTM's UI.  While downloading the `.utm` package "manually", the user controls where the machine lives on the file system.
>
> When a downloaded package is launched from Finder, UTM will create an "alias" in the UI when opened.
> This is indicated by a (subtle) small arrow in the lower right corner of the machine's icon in UTM.
> A machine **alias** can be removed in UTM using "Remove" on the machine, and only the _reference_ in UI is removed for an "alias" - **not** the machine nor disks.  
>
> But if `utm://` is used, a "Remove" in UTM will delete machine **and disks** -  since the machine is "imported" into UTM, it also manages the "document" stored, including deletion.

## QEMU launch scripts

Every `.utm` bundle includes `qemu.sh` + `qemu.cfg` for running CHR directly under QEMU — no UTM required, works on macOS and Linux.  The script auto-detects the best accelerator (KVM, HVF, or TCG) and handles UEFI firmware, networking, and serial setup automatically.

Quick start:

```sh
cd chr.x86_64.qemu.7.22.utm
./qemu.sh                        # foreground — serial console on stdio
./qemu.sh --background           # headless — serial on Unix socket
./qemu.sh --port 8080            # custom host port for REST API / WebFig
./qemu.sh --dry-run              # show the QEMU command without running it
```

The `--port` flag (default `9180`) forwards to RouterOS HTTP port 80.  REST API: `http://admin:@localhost:9180/rest/`.  WebFig: `http://localhost:9180/`.

> [!TIP]
> **The full QEMU deployment guide is [Files/QEMU.md](Files/QEMU.md)** — covering platform setup, networking (port forwarding, vmnet on macOS, bridge/tap on Linux), disk snapshots, multi-instance setups, environment variables, and troubleshooting.

### Makefile QEMU targets

After [building locally](#build-locally), the Makefile wraps `qemu.sh` for managing machines from the project directory:

```sh
make qemu-list                                                # machines + running state
make qemu-run   QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm   # foreground (interactive)
make qemu-start QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm   # background (headless)
make qemu-stop  QEMU_UTM=Machines/chr.x86_64.qemu.7.22.utm   # stop a background instance
make qemu-status                                               # debug info: PIDs, logs, sockets
make qemu-start-all                                            # start all (ports 9180, 9181, ...)
make qemu-stop-all                                             # stop all running machines
```

## UTM automation

UTM offers several automation paths: the [`utm://` URL scheme](https://docs.getutm.app/advanced/remote-control/) for basic lifecycle (start, stop, pause), the [`utmctl` CLI](https://docs.getutm.app/scripting/scripting/#command-line-interface) bundled inside UTM.app, [AppleScript](https://docs.getutm.app/scripting/scripting/) for rich scripting, and [Shortcuts](https://docs.getutm.app/advanced/remote-control/) integration for login-item automation.  The Makefile wraps AppleScript with helpers like `make utm-start` and `make utm-stop`.

For the full walkthrough — including headless mode, pseudo-TTY serial, and auto-start at login — see [UTM Guide: Automation](Files/UTM.md#automation).

RouterOS itself exposes the [REST API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API), native TCP [API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579160/API), SSH, and serial console.  See MikroTik's documentation for those.


## Understanding the project's structure

### Files and Folders

#### `Makefile` - runs `pkl` and handles final package processing

A classic Makefile is used to start `pkl`'s generation of virtual machine packages.  Since pkl-lang cannot deal with binary files, the Makefile also processes "placeholder" files, added by pkl code, to download disk and other files after `pkl` completes.  Running just `make` should build all packages, although it is recommended to run `make clean` before any fresh build.

> Running `make` multiple times is fine. However, it will rebuild all /Machines, and replace any disks.
> As the built machines are "runnable" from the build directory (`Machines`), any change will be lost on a `make`.
> `pkl` always produces files, even if unchanged, so `Makefile` mechanisms for partial rebuild are not
> supported.

#### `./Pkl` - provides the basic framework needed by templates

`utmzip.pkl` is the root module — it defines all output files for a `.utm` bundle, including `config.plist`, `qemu.cfg`, and `qemu.sh`.  `UTM.pkl` provides UTM-specific types (architectures, backends, network modes).  `QemuCfg.pkl` generates the QEMU launch scripts.
Additional "application-specific" modules, like `CHR.pkl`, know download locations, icons, and other details specific to that OS image.
Helpers like deterministic MAC address generation live in `Randomish.pkl`.  

#### `./Manifests` - defines the actual virtual machine images to be "built"

Each "manifest" will result in a new "machine", on a one-to-one basis.  Typically, by `amends`ing a "template", which allows variants to reuse an existing template or even another manifest as the "base" to modify.

#### `./Machines` - final output of images (_i.e._ "dist")

These are the ready-to-use packages produced.  GitHub Actions will make each a download item on a release.  Or, the machine can be added to UTM using `open ./Machine/<machine_name>` if used locally.

#### `./Templates` - provides `amends` "wrapper" around native types

Pkl code in `Templates` is "glue" between the .plist and a more "amends friendly" manifest.  The idea of a "machine class" is that it `extends` `./Pkl/utmzip.pkl`, adding OS/image specific details so that downstream manifests can use simple `amends` to a "template". For example, the `chr.utmzip.pkl` adds the downloading of a version-specific image, optional extra disks, and controlling colors in the SVG logo.

#### `./Files` - non-Pkl files & media that may be needed in output (_i.e._ "static files")

Any files that may need to be included in a UTM package, that are not downloadable.  Currently, just `efi_vars.fd` is needed for Apple-based virtual machines.

#### `./Lab` - non-Pkl code uses for testing and experimentation 

Used to store various scripts used to debug issues and try concepts, without effecting the core `pkl`-based scheme.  With one folder per experiment/mini-project.  The structure may vary, look for README.md or NOTES.md.  Any technical finding are summarized as documents in the root of `./Lab`.

### `qemuOutput` and `libvirtOutput` controls

By default, QEMU scripts (`qemu.cfg` + `qemu.sh`) are generated for all machine backends — both QEMU and Apple.  Libvirt XML generation is experimental and disabled by default.  Control this with environment variables during `make`:

In `pkl` Templates, `libvirtOutput` and `qemuOutput` booleans control output of non-UTM formats.  `config.plist` for UTM is always generated.

```sh
# Disable QEMU scripts (just UTM bundles)
QEMU_OUTPUT=false make CHR_VERSION=7.22

# Enable experimental libvirt XML alongside QEMU scripts
LIBVIRT_OUTPUT=true make CHR_VERSION=7.22
```

### Agentic Files

Both [AGENTS.md](https://github.com/tikoci/mikropkl/blob/main/AGENTS.md) and [CLAUDE.md](https://github.com/tikoci/mikropkl/blob/main/CLAUDE.md) are present.  The instruction system targets Claude Sonnet 4.6, via either CoPilot or Claude Code.  Other agents/models likely work, but not been tried (and likely require some steer to use CLAUDE.md for orientation).  Also not tired, but strongly recommended against using "mini" models with this project (e.g. less training data for **both** `pkl` and RouterOS).


> #### Disclaimers
>
> **Not affiliated, associated, authorized, endorsed by, or in any way officially connected with MikroTik, Apple, nor UTM from Turing Software, LLC.**
> While the code in this project is released to public domain (see LICENSE),  CHR image contains software subject to MikroTik's Terms and Conditions, see [MIKROTIKLS MIKROTIK SOFTWARE END-USER LICENCE AGREEMENT](https://mikrotik.com/downloadterms.html).
> **Any trademarks and/or copyrights remain the property of their respective holders** unless specifically noted otherwise.
> Use of a term in this document should not be regarded as affecting the validity of any trademark or service mark. Naming of particular products or brands should not be seen as endorsements.
> MikroTik is a trademark of Mikrotikls SIA.
> Apple and macOS are trademarks of Apple Inc., registered in the U.S. and other countries and regions. UNIX is a registered trademark of The Open Group.
> **No liability can be accepted.** No representation or warranty of any kind, express or implied, regarding the accuracy, adequacy, validity, reliability, availability, or completeness of any information is offered.  Use the concepts, code, examples, and other content at your own risk. There may be errors and inaccuracies, that may of course be damaging to your system. Although this is highly unlikely, you should proceed with caution. The author(s) do not accept any responsibility for any damage incurred.
