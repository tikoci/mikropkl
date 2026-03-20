#!/bin/sh
# stop-qga-test.sh — Stop a machine launched by launch-with-qga.sh
#
# Usage: ./stop-qga-test.sh <machine-dir>

set -eu

if [ $# -lt 1 ]; then
  echo "Usage: $0 <machine-dir>"
  exit 1
fi

MACHINE_DIR="$(cd "$1" && pwd)"
MACHINE_NAME="$(basename "$MACHINE_DIR" .utm)"

echo "Stopping $MACHINE_NAME..."
"$MACHINE_DIR/qemu.sh" --stop 2>/dev/null || true

# Clean up QGA socket
QGA_SOCK="/tmp/qga-${MACHINE_NAME}.sock"
rm -f "$QGA_SOCK"
echo "Done."
