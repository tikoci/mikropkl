
# UTM virtual machine packager

> _or... a proof-of-concept using `pkl` to build macOS virtual machines, using RouterOS as the ginny pig._

[UTM](https://mac.getutm.app) is an open-source app enabling both Apple and QEMU-based machine virtualization for macOS.  In UTM, a virtual machine is just a folder ending in .utm (_i.e._ "package bundle"), with
a `config.plist` and subdirectory `Data` containing virtual disk(s) or other metadata like an icon.
This project produces a valid UTM document package bundle automatically based on [`pkl` files](https://pkl-lang.org).

The created bundle contains a virtualized OS that can be installed into UTM in a few ways:
  * Via app URL, `utm://downloadVM?...`, which downloads and installs a VM into UTM's default store
  * Download ZIP from GitHub, then just open the "document" in Finder -  this will create an "alias" in the UTM app to the location where you opened the UTM package
  * `git clone` (or fork) this project and build locally - then copy or run as desired from the `Machines` directory. 

> [!NOTE] 
>
> **Ready-to-use CHR packages are in GitHub's [Releases](https://github.com/tikoci/mikropkl/releases)**.  
> Installation instructions - including `utm://downloadVM?...` URLs are included in each GitHub Release.

UTM supports two modes of virtualization:
  * [_QEMU_](https://docs.getutm.app/settings-qemu/settings-qemu/) (`QEMU`)
    - support both emulation and virtualization, so ARM can be emulated on Intel, or use direct virtualization if on the same platform.
    - USB device support and a wider range of network adapters available
    - images marked with "QEMU"
  * [_Apple Virtualization Framework_](https://docs.getutm.app/settings-apple/settings-apple/) (`Apple`)
    - more limited support for devices and options
    - quicker startup than QEMU
    - images marked with "Apple" 

Both modes are supported in `pkl` "manifests" and "templates", expressed as the `backend` property in Pkl code.

Additionally, there are a few network modes:
  * `Shared`
    - virtual machine use network (subnet) local to macOS
    - Internet connections from guest OSes are NATed by Apple/QEMU from the "shared" network to the real interface
    - QEMU supports port forwarding from a guest machine.  Apple Virtualization does not, so a `Bridged` network must be used if ports need to be exposed to networks beyond the local Mac. 
  * `Bridged`
    - virtual machine is bound to a macOS interface
    - still "shared" with macOS, but the machine presents its own MAC on the bridged network
    - can use ethernet dongle(s) as bridge interfaces to separate networks
  * `HostOnly` (_using `QEMU` only, no `Apple`_) - Local Mac, No Internet
    - similar to `Shared`, except no internet access is possible
    - no NAT nor default gateway
    - only available when `backend` is `QEMU`

There are some differences in network between Apple Virtualization and QEMU modes.  See specific docs for [QEMU](https://docs.getutm.app/settings-qemu/devices/network/network/) or [Apple](https://docs.getutm.app/settings-apple/devices/network/) for more details on virtual networking.

Please note that using a Mac's Wi-Fi adapter may introduce some jitter in network traffic.  **For maximum bandwidth and more predictable latency use Ethernet.** The issue is noticeable mainly in speed tests, where you'll see the variable speed (and latency). On RouterOS, adding a fq_codel or similar queue helps "smooth" traffic in high-bandwidth tests when using Wi-Fi as a VM network interface.  _And, likely a good way to play with queues, since just using a Wi-Fi adapter alone will produce something to see the effects of queuing._ 

All built packages support UTM's [Headless Mode](https://docs.getutm.app/advanced/headless/). Two serial ports are added, the "built-in Terminal" and a "pseudo-tty" serial port.   These allow direct console access and serial-based automation, respectively.  To use in Headless Mode, the "built-in Terminal" will have to be removed.  No virtual display is connected by default.

All of UTM's settings can be manifested by the `.pkl` scripts in the [tikoci/mikropkl](https://github.com/tikoci/mikropkl) repo. Essentially converting friendly Pkl code into the needed `config.plist` file, with download disk images provided by the [`Makefile`](https://github.com/tikoci/mikropkl/blob/main/Makefile), and finally packaged by a [GitHub Action](https://github.com/tikoci/mikropkl/blob/main/.github/workflows/chr.yaml).  


## Installing UTM on macOS

This projects just build _UTM_ virtual machines, UTM has to be installed to actually run any packaged machines.
UTM is available from:
  * Mac App Store:  https://apps.apple.com/us/app/utm-virtual-machines/id1538878817?mt=12
  * GitHub: https://github.com/utmapp/UTM/releases/latest/download/UTM.dmg

See UTM's [documentation](https://docs.getutm.app) or [website](https://mac.getutm.app) for more details.

## Downloading virtual machines from GitHub

The framework here is pretty agnostic, so while a similar approach works for more common things like Alpine or Ubuntu.  There is only one class of machine today, RouterOS.

### Two options to install machines into UTM

#### Using `utm://` in Terminal's `open`
On macOS, with [UTM](https://mac.getutm.app), install
1. Launch "Terminal" 
2. Type `open '<utm_app_url>'`, replacing _utm_app_url_ with a `utm://...` link shown in [Releases]() - _make sure to 'single quote URL'_
3. UTM will open and prompt you if you want to download the machine
4. If accepted, the machine will be stored in UTM's default document directory
5. Use UTM to start the image, and a new window with a terminal to the machine will appear

#### Just download the ZIP to control the location of the machine
The download links in [Releases](https://github.com/tikoci/mikropkl/releases) contain a UTM package inside a ZIP file.  When expanded,
assuming [UTM](https://mac.getutm.app) is installed, the folder ending in `.utm`
will launch in UTM, like any other macOS "document".  

> The GitHub Action that builds packages uses a `git tag` based on "machine class".  This is used to identify different releases in GitHub's Releases.  For example, RouterOS "CHR" packages are prefixed with `chr-`, like `chr-7.19beta4`.  This scheme allows additional machine classes in future.

### MikroTik RouterOS "CHR" Packages (`*.chr.*.utm`)

**See [Releases](https://github.com/tikoci/mikropkl/releases) section on GitHub for downloads.  Installation instructions are in the release notes.**

RouterOS documentation is available at https://help.mikrotik.com/docs, with Mikrotik's [Forum](https://forum.mikrotik.com) being an additional source for RouterOS usage details.



#### "Free" CHR is limited to 1Mb/s
The CHR packages contain no license, so they run in "free" mode.  The free license level allows CHR to run indefinitely but is limited to 1Mb/s upload per interface.  All features provided by CHR are available without restrictions, other than speed.  There is a "trial" mode – which is also free – but you need to register at https://www.mikrotik.com/client to generate a trial license in CHR.  With a valid account, the trial mode can be activated using CHR's terminal, provide www.mikrotik.com "account" (user) and password when prompted:
```routeros
/system/license/renew level=p10 
```
This will remove the 1Mb/s limit, and allow up 10Gb/s, with only restriction is upgrades are not possible after 60 days without a paid license.  See Mikrotik's [CHR documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud+Hosted+Router+CHR#CloudHostedRouter%2CCHR-Freelicenses) for licensing details.

#### "ROSE" images are the same CHR, just with 4 empty disks
The `rose.*` images are regular CHR images but with disks added by `pkl`/`Makefile` based on the "manifest", as an example of how to further extend the `pkl` framework here to support "sub" machine classes.  But the primary functional usage is to allow test storage-related features _safely_ in CHR and without a lot of manual configuration.  

##### Using "ROSE" feature
After installing and starting the machine, ROSE storage is disabled by default.  To add the "rose-storage" package to CHR, use following commands in terminal, which will cause a reboot:
```routeros
 /system/package { update/check-for-updates duration=10s; enable rose-storage; apply-changes }        
```
You will need to reboot to install ROSE package needed for storage features.  As a starting example, you can format and SMB share the extra disks in ROSE CHR using:
```routeros
 :foreach d in=[/disk/find] do={/disk format $d file-system=btrfs without-paging }          
 :foreach d in=[/disk/find] do={/disk set $d smb-sharing=yes smb-user=rose smb-password=rose }          
```
Once formated, you then use any of the BTRFS features, including RAID 1 and RAID 10 – or, use another file system or other storage features, including snapshots.  See Mikrotik's [ROSE documentation](https://help.mikrotik.com/docs/x/HwCZEQ) for more information.


> [!TIP]
> #### RouterOS also employs a unique "configuration language"
>
> Mikrotik RouterOS is based on the Linux kernel.  However, "userland" is neither GNU nor BSD, but rather a proprietary system with a rich ["scripting" interface](https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting). 
_i.e._ **All router configuration is always scripting** _(outside GUI/web tools, like [winbox](https://mikrotik.com/download))_.  As such, there is no `/bin/sh`, so the CLI is just a REPL for the scripting language.
>
> Also, unlike a traditional shell, RouterOS has a full ["type system"](https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting#Scripting-Datatypes), including mixed-typed, multi-dimensional array, that can contain functions.  As a _router_ config language, there are first-class types like an IP address or another type, `ip-prefix`, which carries a CIDR prefix.  But there is no "float" type.  _A floating point number is not common in networking, so RouterOS does not have one.  But the side-effect is `1.1` in CLI is a `ip` type, as in early RFCs is valid shorter for `1.0.0.1` - but just one oddity that happens in type-aware shell with aggressive casting_.  Also, RouterOS does not have anything like `pkl`'s nifty [`DataSize`](https://pkl-lang.org/package-docs/pkl/0.26.0/base/DataSize.html) type, which does come up in networking.
>
> While left unexplored here, RouterOS does lend itself to using `pkl` to generate configuration as a result of these properties.  For example, a new `pkl` Renderer could be written to output a RouterOS script.  Or, a new [external resource reader](https://pkl-lang.org/main/current/language-reference/index.html#extending-resource-readers) could be used to "fetch" data from RouterOS to use in a `pkl` script. 



## Build locally on macOS 

The original intent was to use this as part of CI system, like GitHub Actions.
However, it will run on macOS desktops too.  You'll need the following packages installed first:
  * `make` (either from XCode or "brew install make")
  * `pkl` (either from https://pkl-lang.org or "brew install pkl")
  * `git` (optional, other than getting source, "brew install git" or XCode)
  * `qemu-img` (optional, unless building machines with extra disks, "brew install qemu")

With those tools, it is only a few steps:
  1. Use `git clone https://github.com/tikoci/mikropkl` (or download source from GitHub)
  2. Change to the directory with source, and run `make`
  3. In a few minutes, images will be built to the `./Machines` directory (on a one-to-one basis to files in `./Manifests`)
  4. To add it as an alias to UTM app, use `open ./Machines/<machine_name>`.

The `Makefile` supports some additional helpers to install/uninstall and start/stop all machines:
```sh
make utm-version

make utm-install
make utm-start

make utm-stop
make utm-uninstall

```

## Further UTM automation options

* Basic operations can be done using the same [`utm` app URL scheme](https://docs.getutm.app/advanced/remote-control/) used to import for other operations, like starting: `utm://start?name=...`.  This is discussed in UTM's docs linked above, which show using macOS's built-in Shortcuts and Automator apps with the `utm` scheme for basic needs.
* [Command Line `utmctl`](https://docs.getutm.app/scripting/scripting/#command-line-interface) offers more basic start and stop.  The tool is part of the UTM.app bundle, _e.g._ `/Applications/UTM.app/Contents/MacOS/utmctl`
* [UTM's rich AppleScript support](https://docs.getutm.app/scripting/scripting/) which can be used to further automate the virtual machines, nearly all of the UI can be automated.  Additionally - for QEMU machines with SPICE installed only - UTM's AppleScript can run commands or access files directly on the _same_ guest virtual machine.  UTM docs also have a [Cheat Sheet](https://docs.getutm.app/scripting/cheat-sheet/) with a few AppleScript commands.
  > To view UTM's AppleScript "API" (`SDEF`), you can use Script Editor app's Library feature, see Apple's doc [View an apps scripting dictionary](https://support.apple.com/guide/script-editor/view-an-apps-scripting-dictionary-scpedt1126/2.11/mac/15.0).  You will need to add UTM.app from `/Applications` in the Script Editor's Library using add item <kbd>+</kbd> button.
* [`Makefile`](https://github.com/tikoci/mikropkl/blob/main/Makefile) also has function helpers to send AppleScript commands to UTM from within a `make <target>`, like `$(call tellutm, chr.aarch64.apple.7.18.1, stop)`.  Targets can also be extended in other ways to invoke `utmctl` or machine-specific operations.
* UTM also support sending serial to a [/dev/stty port](https://docs.getutm.app/advanced/serial/).  This means you can use CLI tools like `screen` or `cu` to access the terminal - instead of a UI window.  Classic UNIX tools like `expect` can also be used, which allows TCL-based automation of terminals via serial too.
  > RouterOS CHR will only use the first serial port as a login console.  By default, that is a UI Window with ANSI support.  Other added serial ports are left unassigned.  To use additional serial ports for console access (_i.e._ login and CLI commands), use `/system/console/add`.  The previous test project [tikoci/chr-utm](https://github.com/tikoci/chr-utm/blob/main/README.md) has more information on UTM Serial usage with RouterOS, including an example `expect` script for setup.

Each virtual machine may have its own automation APIs.  Please refer to a guest machine's own documentation for details on their APIs.  For example,  RouterOS supports many API like [REST API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579162/REST+API), native TCP [API](https://help.mikrotik.com/docs/spaces/ROS/pages/47579160/API), `ssh`, and serial, among others - too many to cover here.  So guest virtual machine APIs are left to other sources.



## Creating new machines

While a bit complex behind the scenes, creating or re-build machines happens in `/Manifests`.  This added layer of abstraction allows just a few simple lines to define a VM in this `pkl` approach, with the rest of UTM `.plist` calculated behind the scenes.

The provided `Makefile` will invoke `pkl` internally and create **_one bundle per file_** in `Manifests`, with resulting virtual machines "building" to `Machines`.  The entire process is done with a simple `make`. 

All "manifest" are rooted in `./Pkl/utmzip.pkl` which defines the structure needed to produce images.  Pkl's `extends` can be used by any future "middleman" in `./Templates`, or a file in `./Manifests` may directly `amend "./Pkl/utmzip.pkl"` - without a "template" - for simple cases. 

If the goal is to just "tweak" an existing configuration, you should be able to either edit or copy an existing `.pkl` file in `./Manifests` without knowing any `pkl` specifics.  

But adapting to new machine types requires a better understanding of `pkl`.  See https://pkl-lang.org for examples and documentation `pkl` syntax and libraries.

> [!TIP]
> #### Difference between _imported_ and _aliased_ machines in UTM
> The difference is the `utm://` will "import" the machine, and use its default store (i.e. `~/Library/Containers/UTM/Data`) along with other machines created from UTM's UI.  While downloading the `.utm` package "manually", the user controls where the machine lives on the file system. 
> 
> When a downloaded package is launched from Finder, UTM will create an "alias" in the UI when opened.
> This is indicated by a (subtle) small arrow in the lower right corner of the machine's icon in UTM.
> A machine __alias__ can be removed in UTM using "Remove" on the machine, and only the _reference_ in UI is removed for an "alias" - **not** the machine nor disks.  
>
> But if `utm://` is used, a "Remove" in UTM will delete machine **and disks** -  since the machine is "imported" into UTM, it also manages the "document" stored, including deletion.


## Understanding the project's structure

#### `Makefile` - runs `pkl` and handles final package processing
A classic Makefile is used to start `pkl`'s generation of virtual machine packages.  Since pkl-lang cannot deal with binary files, the Makefile also processes "placeholder" files, added by pkl code, to download disk and other files after `pkl` completes.  Running just `make` should build all packages, although it is recommended to run `make clean` before any fresh build.


> Running `make` multiple times is fine. However, it will rebuild all /Machines, and replace any disks.
> As the built machines are "runnable" from the build directory (`Machines`), any change will be lost on a `make`.
> `pkl` always produces files, even if unchanged, so `Makefile` mechanisms for partial rebuild are not
> supported. 


#### `./Pkl` - provides the basic framework needed by templates 
`UTM.pkl` is the main file here, and enables Pkl code to transform into UTM's `.plist` format.
UTM supports running VMs under either QEMU or Apple and is controlled via `backend` in Manifests and Templates.
Additional "application-specific" types, like `CHR.pkl`, know
download locations, icons, and other specific details of the application.
Any helpers like randomly generated UUID/MacAddress, live in `Utils.pkl`.  

#### `./Manifests` - defines the actual virtual machine images to be "built"
Each "manifest" will result in a new "machine", on a one-to-one basis.  Typically, by `amends`ing a "template", which allows variants to reuse an existing template or even another manifest as the "base" to modify.

#### `./Machines` - final output of images (_i.e._ "dist")
These are the ready-to-use packages produced.  GitHub Actions will make each a download item on a release.  Or, the machine can be added to UTM using `open ./Machine/<machine_name>` if used locally.

#### `./Templates` - provides `amends` "wrapper" around native types
Pkl code in `Templates` is "glue" between the .plist and a more "amends friendly" manifest.  The idea of a "machine class" is that it `extends` `./Pkl/utmzip.pkl`, adding OS/image specific details so that downstream manifests can use simple `amends` to a "template". For example, the `chr.utmzip.pkl` adds the downloading of a version-specific image, optional extra disks, and controlling colors in the SVG logo. 

#### `./Files` - non-Pkl files & media that may be needed in output (_i.e._ "static files")
Any files that may need to be included in a UTM package, that are not downloadable.  Currently, just `efi_vars.fd` is needed for Apple-based virtual machines.




> #### Disclaimers
> **Not affiliated, associated, authorized, endorsed by, or in any way officially connected with MikroTik, Apple, nor UTM from Turing Software, LLC.**
> While the code in this project is released to public domain (see LICENSE),  CHR image contains software subject to MikroTik's Terms and Conditions, see [MIKROTIKLS MIKROTIK SOFTWARE END-USER LICENCE AGREEMENT](https://mikrotik.com/downloadterms.html).
> **Any trademarks and/or copyrights remain the property of their respective holders** unless specifically noted otherwise.
> Use of a term in this document should not be regarded as affecting the validity of any trademark or service mark. Naming of particular products or brands should not be seen as endorsements.
> MikroTik is a trademark of Mikrotikls SIA.
> Apple and macOS are trademarks of Apple Inc., registered in the U.S. and other countries and regions. UNIX is a registered trademark of The Open Group. 
> **No liability can be accepted.** No representation or warranty of any kind, express or implied, regarding the accuracy, adequacy, validity, reliability, availability, or completeness of any information is offered.  Use the concepts, code, examples, and other content at your own risk. There may be errors and inaccuracies, that may of course be damaging to your system. Although this is highly unlikely, you should proceed with caution. The author(s) do not accept any responsibility for any damage incurred. 
