
# Makefile for UTM pkl'er

# TL;DR: essentially builds the .pkl files /Manifests into UTM virtual machines in /Machines
#        each .pkl becomes a .utm directory, and will "open" in UTM App directly after build
#        a .zip file can be used with utm://downloadVM?url= to install a VM into UTM

# NOTE: No "partial" build - so a build will overwrite disks!
#   Thus, while VMs will run from the /Machines directory, any changes will be lost on next `make`. 

.PHONY: all prereq phase1 phase2 pkl clean distclean
.SUFFIXES: 

# basic build "from" and "to" here...
PKL_RUN_DIR := Manifests
PKL_OUTPUT_DIR := Machines
PKL_FILES_DIR := Files
CACHE_DIR := .url-cache

# machine specific properties
CHR_VERSION ?= stable

# options for `pkl` build
# PKL_OPTIONS := -e chrVersion=$(CHR_VERSION)


all: prereq phase1 
	$(info all done)

prereq:
	pkl --version
	make --version
	qemu-img --version
	$(info prereq completed)
	
clean:
	$(info cleaning $(PKL_OUTPUT_DIR))
	rm -rf ./$(PKL_OUTPUT_DIR)

distclean: clean
	$(info cleaning $(CACHE_DIR))
	rm -rf ./$(CACHE_DIR)

# pkl creates the initial files /Manifasts to kickstart a UTM ZIP
phase1: pkl
	$(info ran build phase1)
	$(info recursively call make build now placeholder files are created)
	$(MAKE) phase2
pkl:
	$(info running pkl)
	pkl eval ./$(PKL_RUN_DIR)/*.pkl $(PKL_OPTIONS) -m ./$(PKL_OUTPUT_DIR)

# NOTES:  This Makefile is recursive. `pkl` is run first which produces
#	      some placeholder files like .url, then `make` is run again
#         to find those placeholders in PKL_OUTPUT_DIR ("/Machines").
#		  The found files become targets and deps, with make pattern rules
#         doing the heavy lifting to download, unzip, or run commands.

# pattern rules run the show
# Downloads are cached in $(CACHE_DIR)/ keyed by <sha1-prefix>-<zip-basename>.
# On cache hit the download is skipped.  "make clean" preserves the cache;
# "make distclean" removes it.
%.raw: %.raw.url
	@URL=$$(cat $<); \
	HASH=$$(printf '%s' "$$URL" | shasum | cut -c1-12); \
	CACHED="$(CACHE_DIR)/$$HASH-$$(basename "$$URL")"; \
	mkdir -p "$(CACHE_DIR)"; \
	if [ -f "$$CACHED" ]; then \
	  echo "url-cache hit: $$(basename "$$URL")"; \
	else \
	  echo "url-cache miss: $$(basename "$$URL")"; \
	  wget -q -O "$$CACHED.tmp" "$$URL" && mv "$$CACHED.tmp" "$$CACHED" \
	    || { rm -f "$$CACHED.tmp"; exit 1; }; \
	fi; \
	cp "$$CACHED" $@
%.img: %.img.zip.url
	@URL=$$(cat $<); \
	HASH=$$(printf '%s' "$$URL" | shasum | cut -c1-12); \
	CACHED="$(CACHE_DIR)/$$HASH-$$(basename "$$URL")"; \
	mkdir -p "$(CACHE_DIR)"; \
	if [ -f "$$CACHED" ]; then \
	  echo "url-cache hit: $$(basename "$$URL")"; \
	else \
	  echo "url-cache miss: $$(basename "$$URL")"; \
	  wget -q -O "$$CACHED.tmp" "$$URL" && mv "$$CACHED.tmp" "$$CACHED" \
	    || { rm -f "$$CACHED.tmp"; exit 1; }; \
	fi; \
	unzip -o -q "$$CACHED" -d $(dir $@)
%.qcow2: %.qcow2.zip.url
	@URL=$$(cat $<); \
	HASH=$$(printf '%s' "$$URL" | shasum | cut -c1-12); \
	CACHED="$(CACHE_DIR)/$$HASH-$$(basename "$$URL")"; \
	mkdir -p "$(CACHE_DIR)"; \
	if [ -f "$$CACHED" ]; then \
	  echo "url-cache hit: $$(basename "$$URL")"; \
	else \
	  echo "url-cache miss: $$(basename "$$URL")"; \
	  wget -q -O "$$CACHED.tmp" "$$URL" && mv "$$CACHED.tmp" "$$CACHED" \
	    || { rm -f "$$CACHED.tmp"; exit 1; }; \
	fi; \
	unzip -o -q "$$CACHED" -d $(dir $@)
%.qcow2: %.size
	qemu-img create -f qcow2 $@ `cat $<`M
%: %.localcp
	cp -f ./$(PKL_FILES_DIR)/`cat $<` $@

# Generates a fresh empty UEFI NVRAM variable store for Apple Virtualization.framework.
# Equivalent to Swift's VZEFIVariableStore(creatingVariableStoreAt:) — the API that UTM
# calls when no store exists yet.  Previously, a stale efi_vars.fd captured from a UTM
# CHR boot session was copied into every Apple bundle — it contained accumulated UEFI
# variables (MTC counter, boot device paths, memory type caches) that shouldn't leak
# across VMs.  This rule generates a pristine empty store instead.
#
# pkl cannot emit raw binary, so the .genefi placeholder (containing the volume size
# in KiB, currently 128) triggers this Make rule — same pattern as .size → qcow2.
#
# The 96-byte header has three UEFI structures (all fields little-endian):
#
#   EFI_FIRMWARE_VOLUME_HEADER  (0x00–0x37, 56 bytes)
#     [0x00] ZeroVector            16B   all zeros (reserved)
#     [0x10] FileSystemGuid        16B   EFI_SYSTEM_NV_DATA_FV_GUID
#                                        {fff12b8d-7696-4c8b-a985-2747075b4f50}
#     [0x20] FvLength               8B   0x20000 (128 KiB — must match .genefi value)
#     [0x28] Signature              4B   "_FVH" (0x4856465f)
#     [0x2C] Attributes             4B   0x00000e36 (R/W, erase polarity=1 → 0xFF=empty)
#     [0x30] HeaderLength           2B   0x0048 (72 bytes, includes block map below)
#     [0x32] Checksum               2B   0xe9e6 (uint16 sum of header words = 0)
#     [0x34] ExtHeaderOffset        2B   0x0000 (no extended header)
#     [0x36] Reserved               1B   0x00
#     [0x37] Revision               1B   0x02 (EFI_FVH_REVISION)
#
#   FV_BLOCK_MAP_ENTRY[]  (0x38–0x47, 16 bytes)
#     [0x38] {NumBlocks=32, Length=4096}  — 32 × 4 KiB = 128 KiB
#     [0x40] {0, 0}                       — terminator
#
#   VARIABLE_STORE_HEADER  (0x48–0x5f, 24 bytes)
#     [0x48] Signature             16B   EFI_AUTHENTICATED_VARIABLE_GUID
#                                        {ddcf3616-3275-4164-98b6-fe85707ffe7d}
#     [0x58] Size                   4B   0x0000dfb8 (57272 — variable region capacity)
#     [0x5C] Format                 1B   0x5a (VARIABLE_STORE_FORMATTED)
#     [0x5D] State                  1B   0xfe (VARIABLE_STORE_HEALTHY)
#     [0x5E] Reserved               2B   0x0000
#
# After the header: 0xFF fill to end of volume.  EFI uses 0xFF for erased flash
# (erase polarity bit in Attributes) — the firmware finds free variable slots by
# scanning for 0xFF regions.  Using 0x00 here would corrupt the store.
%: %.genefi
	@echo "generating empty UEFI NVRAM: $@"
	@# EFI_FIRMWARE_VOLUME_HEADER — ZeroVector (16 bytes)
	@printf '\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' > $@
	@# EFI_FIRMWARE_VOLUME_HEADER — FileSystemGuid: EFI_SYSTEM_NV_DATA_FV_GUID (16 bytes)
	@printf '\x8d\x2b\xf1\xff\x96\x76\x8b\x4c\xa9\x85\x27\x47\x07\x5b\x4f\x50' >> $@
	@# EFI_FIRMWARE_VOLUME_HEADER — FvLength=0x20000 (8) + Signature="_FVH" (4) + Attributes (4)
	@printf '\x00\x00\x02\x00\x00\x00\x00\x00\x5f\x46\x56\x48\x36\x0e\x00\x00' >> $@
	@# EFI_FIRMWARE_VOLUME_HEADER — HeaderLength (2) + Checksum (2) + ExtHdrOff (2) + Reserved+Revision (2)
	@printf '\x48\x00\xe6\xe9\x00\x00\x00\x02' >> $@
	@# FV_BLOCK_MAP_ENTRY[]: 32 blocks × 4096 bytes (8) + terminator {0,0} (8)
	@printf '\x20\x00\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' >> $@
	@# VARIABLE_STORE_HEADER — Signature: EFI_AUTHENTICATED_VARIABLE_GUID (16 bytes)
	@printf '\x16\x36\xcf\xdd\x75\x32\x64\x41\x98\xb6\xfe\x85\x70\x7f\xfe\x7d' >> $@
	@# VARIABLE_STORE_HEADER — Size=0xdfb8 (4) + Format=0x5a (1) + State=0xfe (1) + Reserved (2)
	@printf '\xb8\xdf\x00\x00\x5a\xfe\x00\x00' >> $@
	@# 0xFF fill to end of volume (erase polarity — NOT 0x00)
	@PAD=$$(($$(cat $<) * 1024 - 96)); tr '\0' '\377' < /dev/zero | head -c $$PAD >> $@

# search for placeholder files
#   note: these will only work AFTER `pkl`, and why Makefile is recursive
URLFILES := $(wildcard ./$(PKL_OUTPUT_DIR)/*/Data/*.raw.url)
URLTARGETS := $(URLFILES:.url=)
ZIPIMGFILES := $(wildcard ./$(PKL_OUTPUT_DIR)/*/Data/*img.zip.url)
ZIPIMGTARGETS := $(ZIPIMGFILES:.zip.url=)
SIZEFILE := $(wildcard ./$(PKL_OUTPUT_DIR)/*/Data/*.size)
SIZETARGETS := $(subst .size,.qcow2,$(SIZEFILE))
LOCALCPFILE := $(wildcard ./$(PKL_OUTPUT_DIR)/*/Data/*.localcp)
LOCALCPTARGETS := $(subst .localcp,,$(LOCALCPFILE))
GENEFIFILE := $(wildcard ./$(PKL_OUTPUT_DIR)/*/Data/*.genefi)
GENEFITARGETS := $(subst .genefi,,$(GENEFIFILE))

# links all targets together from found placeholders
phase2: libvirt-fixpaths qemu-chmod $(LOCALCPTARGETS) $(GENEFITARGETS) $(SIZETARGETS) $(URLTARGETS) $(ZIPIMGTARGETS)
	$(info ran build phase2)
	$(info used deps: $?)

# download OS drive images
$(URLTARGETS): $(URLFILES)

# images may need unzip & handled seperately here
$(ZIPIMGTARGETS): $(ZIPIMGFILES)

# creates QEMU spare/empty disks
$(SIZETARGETS): $(SIZEFILE)

# converts a .localcp file into a file copy from /Files
$(LOCALCPTARGETS): $(LOCALCPFILE)

# generates fresh UEFI NVRAM variable stores for Apple VZ
$(GENEFITARGETS): $(GENEFIFILE)

# unused currently, for debugging Makefile
.PHONY: debug-patterns
debug-patterns:
	$(info debug URLFILES $(URLFILES))
	$(info debug URLTARGETS $(URLTARGETS))
	$(info debug SIZEFILE $(SIZEFILE))
	$(info debug SIZETARGETS $(SIZETARGETS))
	$(info debug ZIPIMGFILES $(ZIPIMGFILES))
	$(info debug ZIPIMGTARGETS $(ZIPIMGTARGETS))

# macOS-only helpers for UTM
.PHONY: utm-version utm-install utm-uninstall utm-stop utm-start 

tellvm = osascript -e 'tell application "UTM" to $(2) virtual machine named "$(1)"'
doallvms = for i in $(subst .utm,,$(notdir $(wildcard ./$(PKL_OUTPUT_DIR)/*.utm))); do osascript -e "tell application \"UTM\" to $(1) virtual machine named \"$$i\"" ; done

utm-version:
	osascript -e 'get version of application "UTM"'

utm-install: $(wildcard ./$(PKL_OUTPUT_DIR)/*.utm)
	for i in $^; do open $$i; done

utm-uninstall:
	$(call doallvms, delete)

utm-stop:
	$(call doallvms, stop)

utm-start:
	$(call doallvms, start)

# libvirt helpers — EXPERIMENTAL / FUTURE
# libvirt.xml generation is disabled by default (LIBVIRT_OUTPUT=false).
# These targets exist for experimentation; they are not part of the standard build.
# The qemu.sh/qemu.cfg workflow (below) is the primary QEMU integration path.
# See Lab/libvirt/ for documentation and investigation notes.

LIBVIRT_XMLFILES := $(wildcard ./$(PKL_OUTPUT_DIR)/*.utm/libvirt.xml)

.PHONY: libvirt-list libvirt-fixpaths libvirt-define libvirt-start libvirt-stop libvirt-undefine libvirt-validate libvirt-run-qemu

# Show all libvirt.xml files produced by the build
libvirt-list:
	@for f in $(LIBVIRT_XMLFILES); do echo $$f; done

# Replace /LIBVIRT_DATA_PATH placeholder in libvirt.xml with actual absolute Data directory path.
# Run automatically by phase2 or manually at any time after pkl generates the files.
libvirt-fixpaths:
	@for f in $(LIBVIRT_XMLFILES); do \
	  datadir=$$(cd "$$(dirname $$f)" && pwd)/Data; \
	  perl -i -pe "s|/LIBVIRT_DATA_PATH|$$datadir|g" $$f; \
	  echo "libvirt-fixpaths: $$f -> $$datadir"; \
	done

# Validate generated libvirt XML files (requires virt-xml-validate)
libvirt-validate:
	@for f in $(LIBVIRT_XMLFILES); do \
	  echo "Validating $$f ..."; \
	  virt-xml-validate $$f domain || exit 1; \
	done
	@echo "libvirt-validate passed"

# Define (register) all QEMU machines with libvirt from their libvirt.xml
libvirt-define:
	@for f in $(LIBVIRT_XMLFILES); do \
	  echo "Defining $$f ..."; \
	  virsh define $$f; \
	done

# Start all defined libvirt VMs
libvirt-start:
	@for f in $(LIBVIRT_XMLFILES); do \
	  vmname=$$(xmllint --xpath 'string(/domain/name)' $$f 2>/dev/null); \
	  echo "Starting $$vmname ..."; \
	  virsh start "$$vmname"; \
	done

# Stop all libvirt VMs managed here
libvirt-stop:
	@for f in $(LIBVIRT_XMLFILES); do \
	  vmname=$$(xmllint --xpath 'string(/domain/name)' $$f 2>/dev/null); \
	  echo "Stopping $$vmname ..."; \
	  virsh destroy "$$vmname" 2>/dev/null || true; \
	done

# Undefine (deregister) all libvirt VMs managed here
libvirt-undefine:
	@for f in $(LIBVIRT_XMLFILES); do \
	  vmname=$$(xmllint --xpath 'string(/domain/name)' $$f 2>/dev/null); \
	  echo "Undefining $$vmname ..."; \
	  virsh undefine "$$vmname" 2>/dev/null || true; \
	done

# Run a single libvirt VM directly via qemu-system for testing (with REST API port forwarding).
# LIBVIRT_XML must be set to the libvirt.xml path for the machine to run.
# Host port 9180 is forwarded to the VM's port 80 (RouterOS REST API).
# This is used in CI - virsh start is not used because libvirt user networking
# does not support port forwarding without qemu:commandline extensions.
libvirt-run-qemu:
	@test -n "$(LIBVIRT_XML)" || (echo "Set LIBVIRT_XML=<path to libvirt.xml>" && exit 1)
	$(eval _ARCH := $(shell xmllint --xpath 'string(/domain/os/type/@arch)' $(LIBVIRT_XML) 2>/dev/null))
	$(eval _EMULATOR := $(shell xmllint --xpath 'string(/domain/devices/emulator)' $(LIBVIRT_XML) 2>/dev/null))
	$(eval _MEM := $(shell xmllint --xpath 'string(/domain/memory)' $(LIBVIRT_XML) 2>/dev/null))
	$(eval _DISK := $(shell xmllint --xpath 'string(/domain/devices/disk/source/@file)' $(LIBVIRT_XML) 2>/dev/null))
	$(eval _FMT := $(shell xmllint --xpath 'string(/domain/devices/disk/driver/@type)' $(LIBVIRT_XML) 2>/dev/null))
	$(eval _VCPU := $(shell xmllint --xpath 'string(/domain/vcpu)' $(LIBVIRT_XML) 2>/dev/null))
	@echo "Launching $(_EMULATOR) for arch=$(_ARCH) disk=$(_DISK) mem=$(_MEM)MiB vcpu=$(_VCPU)"
	nohup $(_EMULATOR) \
	  -M $$(xmllint --xpath 'string(/domain/os/type/@machine)' $(LIBVIRT_XML) 2>/dev/null) \
	  -m $(_MEM) \
	  -smp $(_VCPU) \
	  -nographic \
	  -drive file=$(_DISK),format=$(_FMT),if=virtio \
	  -netdev user,id=net0,hostfwd=tcp::9180-:80 \
	  -device virtio-net-pci,netdev=net0 \
	  $(LIBVIRT_QEMU_EXTRA) \
	  &>/tmp/qemu-libvirt-test.log &
	echo $$! > /tmp/qemu-libvirt-test.pid
	@echo "QEMU PID=$$(cat /tmp/qemu-libvirt-test.pid) — log: /tmp/qemu-libvirt-test.log"

# QEMU helpers (direct QEMU via qemu.cfg + qemu.sh — no libvirt required)
# qemu.cfg and qemu.sh are generated by pkl directly into each *.utm bundle.
# qemu.cfg is a QEMU --readconfig ini file; qemu.sh is a launcher that handles
# platform-specific flags (UEFI firmware, KVM/TCG, port forwarding, display).

QEMU_CFGFILES := $(wildcard ./$(PKL_OUTPUT_DIR)/*.utm/qemu.cfg)
QEMU_SHFILES := $(wildcard ./$(PKL_OUTPUT_DIR)/*.utm/qemu.sh)

.PHONY: qemu-list qemu-fixpaths qemu-run qemu-start qemu-stop qemu-status qemu-start-all qemu-stop-all

# Show all QEMU-enabled machines produced by the build
qemu-list:
	@for f in $(QEMU_CFGFILES); do \
	  dir=$$(dirname $$f); \
	  name=$$(basename $$dir .utm); \
	  pid_file="/tmp/qemu-$$name.pid"; \
	  if [ -f "$$pid_file" ] && kill -0 $$(cat "$$pid_file") 2>/dev/null; then \
	    printf "  %-40s  [running]\n" "$$name"; \
	  else \
	    printf "  %-40s  [stopped]\n" "$$name"; \
	  fi; \
	done

# No-op: qemu.cfg now uses relative paths (./Data/...) and qemu.sh resolves them
# by changing to its own directory before launching QEMU.
qemu-fixpaths:
	@echo "qemu-fixpaths: no-op (qemu.cfg uses relative paths)"

# Make all qemu.sh scripts executable
qemu-chmod:
	@for f in $(QEMU_SHFILES); do \
	  chmod +x $$f; \
	  echo "qemu-chmod: $$f"; \
	done

# Run a single QEMU machine interactively (foreground, serial on stdio).
# QEMU_UTM must be set to the .utm directory path (e.g. Machines/chr.x86_64.qemu.7.22.utm).
# Passes QEMU_PORT and any extra env vars through to qemu.sh.
# Exit: Ctrl-A X (quit QEMU).  Ctrl-A C (toggle monitor).  Ctrl-C goes to RouterOS.
qemu-run: qemu-chmod
	@test -n "$(QEMU_UTM)" || (echo "Set QEMU_UTM=<path to .utm dir> (e.g. Machines/chr.x86_64.qemu.7.22.utm)" && exit 1)
	@test -f "$(QEMU_UTM)/qemu.sh" || (echo "No qemu.sh in $(QEMU_UTM)" && exit 1)
	@sh "$(QEMU_UTM)/qemu.sh" --port "$${QEMU_PORT:-9180}"

# Start a single QEMU machine in the background (headless, serial on Unix socket).
# QEMU_UTM must be set to the .utm directory path.
qemu-start: qemu-chmod
	@test -n "$(QEMU_UTM)" || (echo "Set QEMU_UTM=<path to .utm dir> (e.g. Machines/chr.x86_64.qemu.7.22.utm)" && exit 1)
	@test -f "$(QEMU_UTM)/qemu.sh" || (echo "No qemu.sh in $(QEMU_UTM)" && exit 1)
	@sh "$(QEMU_UTM)/qemu.sh" --background --port "$${QEMU_PORT:-9180}"

# Stop a running QEMU instance launched by qemu-start
qemu-stop:
	@test -n "$(QEMU_UTM)" || (echo "Set QEMU_UTM=<path to .utm dir>" && exit 1)
	@test -f "$(QEMU_UTM)/qemu.sh" || (echo "No qemu.sh in $(QEMU_UTM)" && exit 1)
	@sh "$(QEMU_UTM)/qemu.sh" --stop

# Start all QEMU machines in the background with auto-assigned ports (9180, 9181, ...).
qemu-start-all: qemu-chmod
	@PORT=9180; \
	for f in $(QEMU_SHFILES); do \
	  name=$$(basename $$(dirname $$f) .utm); \
	  echo "Starting $$name on port $$PORT ..."; \
	  sh "$$f" --background --port $$PORT; \
	  PORT=$$((PORT + 1)); \
	done

# Stop all running QEMU machines
qemu-stop-all:
	@for f in $(QEMU_SHFILES); do \
	  name=$$(basename $$(dirname $$f) .utm); \
	  pid_file="/tmp/qemu-$$name.pid"; \
	  if [ -f "$$pid_file" ]; then \
	    sh "$$f" --stop; \
	  fi; \
	done

# Show detailed status and debug info for all QEMU machines.
# Reports PID, process state, log/socket files, and port for each machine.
qemu-status:
	@echo ""; \
	found=0; \
	for f in $(QEMU_CFGFILES); do \
	  dir=$$(dirname $$f); \
	  name=$$(basename $$dir .utm); \
	  pid_file="/tmp/qemu-$$name.pid"; \
	  log_file="/tmp/qemu-$$name.log"; \
	  serial_sock="/tmp/qemu-$$name-serial.sock"; \
	  monitor_sock="/tmp/qemu-$$name-monitor.sock"; \
	  vars_file="/tmp/qemu-$$name-vars.fd"; \
	  echo "  $$name"; \
	  echo "  $$(printf '%0.s─' $$(seq 1 $${#name}))"; \
	  if [ -f "$$pid_file" ]; then \
	    pid=$$(cat "$$pid_file"); \
	    if kill -0 "$$pid" 2>/dev/null; then \
	      found=1; \
	      ps_info=$$(ps -o pid=,pcpu=,rss=,etime= -p "$$pid" 2>/dev/null || echo "$$pid ? ? ?"); \
	      echo "  PID:      $$pid  (running)"; \
	      echo "  Process:  $$(echo $$ps_info | awk '{printf "cpu=%s%% rss=%sKB elapsed=%s", $$2, $$3, $$4}')"; \
	    else \
	      echo "  PID:      $$pid  (STALE — process not running)"; \
	    fi; \
	  else \
	    echo "  PID:      (not started)"; \
	  fi; \
	  printf "  Log:      $$log_file"; \
	  if [ -f "$$log_file" ]; then \
	    size=$$(wc -c < "$$log_file" | tr -d ' '); \
	    echo "  ($$size bytes)"; \
	  else echo "  (absent)"; fi; \
	  printf "  Serial:   $$serial_sock"; \
	  if [ -S "$$serial_sock" ]; then echo "  (active)"; else echo "  (absent)"; fi; \
	  printf "  Monitor:  $$monitor_sock"; \
	  if [ -S "$$monitor_sock" ]; then echo "  (active)"; else echo "  (absent)"; fi; \
	  if [ -f "$$vars_file" ]; then \
	    echo "  EFI vars: $$vars_file"; \
	  fi; \
	  echo ""; \
	done; \
	if [ "$$found" = "0" ]; then \
	  echo "  No machines currently running."; \
	  echo "  Start one: make qemu-start QEMU_UTM=Machines/<name>.utm"; \
	  echo "  Start all: make qemu-start-all"; \
	  echo ""; \
	fi