#!/bin/sh
# launch-with-qga.sh — Launch a mikropkl machine with QEMU Guest Agent channel
#
# This script wraps an existing machine's qemu.sh, injecting the virtio-serial
# device and QGA channel that RouterOS CHR needs for guest agent communication.
#
# Usage:
#   ./launch-with-qga.sh <machine-dir> [--port PORT]
#
# Examples:
#   ./launch-with-qga.sh ../../Machines/chr.x86_64.qemu.7.22.utm
#   ./launch-with-qga.sh ../../Machines/chr.aarch64.qemu.7.22.utm --port 9190
#
# The QGA socket is created at /tmp/qga-<machine-name>.sock
# Connect to it with:  ./qga-test.py /tmp/qga-<machine-name>.sock
#
# Note: This stops any existing instance of the machine first.

set -eu

usage() {
  echo "Usage: $0 <machine-dir> [--port PORT]"
  echo ""
  echo "  machine-dir   Path to a .utm directory (e.g. ../../Machines/chr.x86_64.qemu.7.22.utm)"
  echo "  --port PORT   Host port for HTTP forwarding (default: 9190, avoids conflict with running instances)"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

MACHINE_DIR="$1"
shift

PORT=9190
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

# Resolve machine directory
MACHINE_DIR="$(cd "$MACHINE_DIR" && pwd)"
MACHINE_NAME="$(basename "$MACHINE_DIR" .utm)"

if [ ! -f "$MACHINE_DIR/qemu.sh" ]; then
  echo "ERROR: $MACHINE_DIR/qemu.sh not found" >&2
  exit 1
fi

if [ ! -f "$MACHINE_DIR/qemu.cfg" ]; then
  echo "ERROR: $MACHINE_DIR/qemu.cfg not found" >&2
  exit 1
fi

# Socket path for QGA channel
QGA_SOCK="/tmp/qga-${MACHINE_NAME}.sock"

# Stop any existing instance
if [ -f "/tmp/qemu-${MACHINE_NAME}.pid" ]; then
  echo "Stopping existing instance of $MACHINE_NAME..."
  "$MACHINE_DIR/qemu.sh" --stop 2>/dev/null || true
  sleep 1
fi

# Clean up stale QGA socket
rm -f "$QGA_SOCK"

# The QEMU_EXTRA env var is appended to the QEMU command line by qemu.sh.
# We inject:
#   1. virtio-serial-pci controller (bus for virtio serial ports)
#   2. chardev unix socket for the QGA channel
#   3. virtserialport device connecting the chardev to the guest
#
# The guest sees a virtio-serial port named "org.qemu.guest_agent.0" —
# this is the standard channel name that RouterOS's built-in QGA listens on.
export QEMU_EXTRA="${QEMU_EXTRA:-} \
  -device virtio-serial-pci,id=virtio-serial-qga \
  -chardev socket,id=qga0,path=${QGA_SOCK},server=on,wait=off \
  -device virtserialport,chardev=qga0,name=org.qemu.guest_agent.0,id=qga-port0"

# Launch with a non-conflicting port
echo ""
echo "  Launching $MACHINE_NAME with QGA channel..."
echo "  QGA socket: $QGA_SOCK"
echo "  HTTP port:  $PORT"
echo ""

# Use --background so we get the socket immediately
"$MACHINE_DIR/qemu.sh" --background --port "$PORT"

echo ""
echo "  QGA ready at: $QGA_SOCK"
echo "  Test with:    $(dirname "$0")/qga-test.py $QGA_SOCK"
echo ""
