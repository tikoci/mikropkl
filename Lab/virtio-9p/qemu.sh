#!/bin/sh
# Lab: virtio-9p-pci test — x86_64 UEFI with Plan 9 host filesystem sharing
#
# Uses chr-efi.img from Machines/chr.x86_64.apple.7.23beta2.utm/Data/
# Adds a virtio-9p-pci device sharing ./shared/ into the guest as "host"
#
# Usage:
#   ./qemu.sh                     # foreground, serial on stdio
#   ./qemu.sh --background        # background, serial to socket
#   ./qemu.sh --stop              # stop a backgrounded instance
#   ./qemu.sh --port 9199         # custom host port (default: 9199)
#   ./qemu.sh --dry-run           # print command without executing
#
# RouterOS commands to try once booted:
#   /disk/print                   # should show the 9p device
#   /disk/mount host 9p           # mount the shared directory
#   /file/print                   # list files (should show host share)
#
# Environment variables:
#   QEMU_BIN        — override qemu-system binary path
#   QEMU_ACCEL      — override accelerator (kvm, hvf, tcg)
#   QEMU_PORT       — override host port for RouterOS HTTP (default: 9199)
#   QEMU_EXTRA      — additional QEMU arguments appended to command line
#   QEMU_EFI_CODE   — override UEFI code ROM path
#   QEMU_EFI_VARS   — override UEFI vars template path

set -eu

MACHINE_NAME="lab-virtio-9p"

# Resolve paths relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CFG_FILE="$SCRIPT_DIR/qemu.cfg"

# Create shared directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/shared"
if [ ! -f "$SCRIPT_DIR/shared/hello.txt" ]; then
  echo "Hello from the host! If you see this in RouterOS, virtio-9p works." > "$SCRIPT_DIR/shared/hello.txt"
  echo "Created: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$SCRIPT_DIR/shared/hello.txt"
fi

# Verify the disk image exists
DISK_IMG="$SCRIPT_DIR/../../Machines/chr.x86_64.apple.7.23beta2.utm/Data/chr-efi.img"
if [ ! -f "$DISK_IMG" ]; then
  echo "ERROR: Disk image not found: $DISK_IMG" >&2
  echo "  Run 'make' in the project root to build machines first." >&2
  exit 1
fi

# ── Parse arguments ──
BACKGROUND=0
DRY_RUN=0
STOP=0
PORT="${QEMU_PORT:-9199}"
while [ $# -gt 0 ]; do
  case "$1" in
    --background) BACKGROUND=1; shift ;;
    --stop)       STOP=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --port)       PORT="$2"; shift 2 ;;
    *)            echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Stop mode ──
if [ "$STOP" = "1" ]; then
  PID_FILE="/tmp/qemu-${MACHINE_NAME}.pid"
  if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill "$PID" 2>/dev/null; then
      echo "Stopped $MACHINE_NAME (PID $PID)"
      rm -f "$PID_FILE"
    else
      echo "$MACHINE_NAME not running (stale PID file removed)"
      rm -f "$PID_FILE"
    fi
  else
    echo "No PID file for $MACHINE_NAME — not running or started without --background"
  fi
  exit 0
fi

# ── Locate QEMU binary ──
QEMU="${QEMU_BIN:-}"
if [ -z "$QEMU" ]; then
  QEMU="$(command -v qemu-system-x86_64 2>/dev/null || true)"
  if [ -z "$QEMU" ]; then
    echo "ERROR: qemu-system-x86_64 not found. Install QEMU or set QEMU_BIN." >&2
    exit 1
  fi
fi

# Change to script directory so relative paths in qemu.cfg resolve correctly
cd "$SCRIPT_DIR"

# ── Accelerator detection ──
ACCEL="${QEMU_ACCEL:-}"
if [ -z "$ACCEL" ]; then
  HOST_ARCH="$(uname -m)"
  case "$(uname -s)" in
    Linux)
      if [ -w /dev/kvm ] && [ "$HOST_ARCH" = "x86_64" ]; then
        ACCEL="kvm"
      else
        ACCEL="tcg,tb-size=256"
      fi
      ;;
    Darwin)
      HV_SUPPORT=$(sysctl -n kern.hv_support 2>/dev/null || echo 0)
      if [ "$HV_SUPPORT" = "1" ] && [ "$HOST_ARCH" = "x86_64" ]; then
        ACCEL="hvf"
      else
        ACCEL="tcg,tb-size=256"
      fi
      ;;
    *)
      ACCEL="tcg,tb-size=256"
      ;;
  esac
fi
ACCEL_FLAGS="-accel $ACCEL"

# ── x86_64 UEFI firmware (OVMF pflash) ──
EFI_CODE="${QEMU_EFI_CODE:-}"
EFI_VARS_SRC="${QEMU_EFI_VARS:-}"
if [ -z "$EFI_CODE" ]; then
  for p in \
    /opt/homebrew/share/qemu/edk2-x86_64-code.fd \
    /usr/local/share/qemu/edk2-x86_64-code.fd \
    /usr/share/OVMF/OVMF_CODE.fd \
    /usr/share/OVMF/OVMF_CODE_4M.fd \
    /usr/share/edk2/x64/OVMF_CODE.fd \
    /usr/share/edk2/x64/OVMF_CODE.4m.fd \
    /usr/share/OVMF/x64/OVMF_CODE.4m.fd; do
    if [ -f "$p" ]; then EFI_CODE="$p"; break; fi
  done
fi
if [ -z "$EFI_CODE" ]; then
  echo "ERROR: No OVMF firmware found for x86_64 UEFI." >&2
  echo "Install: brew install qemu (macOS) or apt install ovmf (Linux)" >&2
  exit 1
fi
if [ -z "$EFI_VARS_SRC" ]; then
  for v in \
    /opt/homebrew/share/qemu/edk2-i386-vars.fd \
    /usr/local/share/qemu/edk2-i386-vars.fd \
    /usr/share/OVMF/OVMF_VARS.fd \
    /usr/share/OVMF/OVMF_VARS_4M.fd \
    /usr/share/edk2/x64/OVMF_VARS.fd \
    /usr/share/edk2/x64/OVMF_VARS.4m.fd \
    /usr/share/OVMF/x64/OVMF_VARS.4m.fd; do
    if [ -f "$v" ]; then EFI_VARS_SRC="$v"; break; fi
  done
fi
VARS_COPY="/tmp/qemu-${MACHINE_NAME}-vars.fd"
if [ -n "$EFI_VARS_SRC" ]; then
  cp "$EFI_VARS_SRC" "$VARS_COPY"
fi
if [ "$BACKGROUND" = "0" ]; then
  trap 'rm -f "$VARS_COPY" 2>/dev/null' EXIT
fi
CODE_SIZE="$(stat -Lc%s "$EFI_CODE" 2>/dev/null || stat -f%z "$EFI_CODE")"
dd if=/dev/zero of="$VARS_COPY" bs=1 count=0 seek="$CODE_SIZE" 2>/dev/null
PFLASH_FLAGS="-drive if=pflash,format=raw,readonly=on,unit=0,file=$EFI_CODE"
PFLASH_FLAGS="$PFLASH_FLAGS -drive if=pflash,format=raw,unit=1,file=$VARS_COPY"
CPU_FLAGS=""
if [ "$ACCEL" = "hvf" ]; then
  CPU_FLAGS="-cpu host"
fi
MISC_FLAGS="-nodefaults"

# ── Networking — user-mode with HTTP + SSH forwarded ──
NET_FLAGS="-netdev user,id=net0,hostfwd=tcp::${PORT}-:80,hostfwd=tcp::$((PORT + 22))-:22"

# ── Display / Serial / Monitor ──
if [ "$BACKGROUND" = "1" ]; then
  SERIAL_SOCK="/tmp/qemu-${MACHINE_NAME}-serial.sock"
  MONITOR_SOCK="/tmp/qemu-${MACHINE_NAME}-monitor.sock"
  DISPLAY_FLAGS="-display none"
  DISPLAY_FLAGS="$DISPLAY_FLAGS -chardev socket,id=monitor0,path=$MONITOR_SOCK,server=on,wait=off"
  DISPLAY_FLAGS="$DISPLAY_FLAGS -mon chardev=monitor0,mode=readline"
  DISPLAY_FLAGS="$DISPLAY_FLAGS -chardev socket,id=serial0,path=$SERIAL_SOCK,server=on,wait=off"
  DISPLAY_FLAGS="$DISPLAY_FLAGS -serial chardev:serial0"
else
  DISPLAY_FLAGS="-display none -chardev stdio,id=serial0,mux=on,signal=off -mon chardev=serial0,mode=readline -serial chardev:serial0"
fi

# ── Assemble and run ──
# shellcheck disable=SC2086
CMD="$QEMU \
  --readconfig $CFG_FILE \
  $ACCEL_FLAGS \
  $CPU_FLAGS \
  $PFLASH_FLAGS \
  $MISC_FLAGS \
  $NET_FLAGS \
  $DISPLAY_FLAGS \
  ${QEMU_EXTRA:-}"

if [ "$DRY_RUN" = "1" ]; then
  echo "$CMD"
  exit 0
fi

# ── Port conflict check ──
_PORT_IN_USE=0
if command -v lsof >/dev/null 2>&1; then
  lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1 && _PORT_IN_USE=1
elif command -v ss >/dev/null 2>&1; then
  ss -tln 2>/dev/null | grep -q ":${PORT} " && _PORT_IN_USE=1
fi
if [ "$_PORT_IN_USE" = "1" ]; then
  echo "ERROR: Port ${PORT} is already in use." >&2
  echo "  Try: ./qemu.sh --port $((PORT + 1))" >&2
  exit 1
fi

# ── ANSI formatting ──
if [ -t 1 ] 2>/dev/null; then
  _B=$(printf '\033[1m') _D=$(printf '\033[2m') _R=$(printf '\033[0m')
  _G=$(printf '\033[32m') _Y=$(printf '\033[33m')
else
  _B='' _D='' _R='' _G='' _Y=''
fi
case "$ACCEL" in
  kvm|hvf) _ACCEL_TAG="${_G}accelerated${_R}" ;;
  *)       _ACCEL_TAG="${_Y}emulated${_R}" ;;
esac

echo ""
echo "  ${_B}$MACHINE_NAME${_R}  ${_D}accel=${ACCEL}${_R} ${_ACCEL_TAG}"
echo "  ${_D}WebFig:${_R}   ${_B}http://localhost:${PORT}/${_R}"
echo "  ${_D}SSH:${_R}      ${_B}ssh -p $((PORT + 22)) admin@127.0.0.1${_R}"
echo "  ${_D}Login:${_R}    admin / no password"
echo "  ${_D}9p share:${_R} $SCRIPT_DIR/shared/ → mount_tag \"host\""
echo ""
echo "  ${_B}RouterOS commands to try:${_R}"
echo "    /disk/print                ${_D}# see if 9p device appears${_R}"
echo "    /disk/mount host 9p        ${_D}# mount the shared dir${_R}"
echo "    /file/print                ${_D}# list files${_R}"
echo ""

if [ "$BACKGROUND" = "1" ]; then
  nohup sh -c "exec $CMD" >/tmp/qemu-${MACHINE_NAME}.log 2>&1 &
  echo $! > /tmp/qemu-${MACHINE_NAME}.pid
  SERIAL_SOCK="/tmp/qemu-${MACHINE_NAME}-serial.sock"
  MONITOR_SOCK="/tmp/qemu-${MACHINE_NAME}-monitor.sock"
  echo "  ${_D}PID:${_R}      $!"
  echo "  ${_D}Log:${_R}      /tmp/qemu-${MACHINE_NAME}.log"
  echo "  ${_D}Serial:${_R}   ${_B}socat - UNIX-CONNECT:$SERIAL_SOCK${_R}"
  echo "  ${_D}Monitor:${_R}  socat - UNIX-CONNECT:$MONITOR_SOCK"
  echo "  ${_D}Stop:${_R}     ${_B}./qemu.sh --stop${_R}"
  echo ""
else
  printf '\033]0;%s\007' "$MACHINE_NAME — Ctrl-A X quit"
  echo "  ${_B}Ctrl-A X${_R}  quit    ${_D}|${_R}  ${_B}Ctrl-A C${_R}  monitor    ${_D}|${_R}  ${_B}Ctrl-A H${_R}  help"
  echo "  ${_D}Ctrl-C → RouterOS${_R}"
  echo ""
  exec $CMD
fi
