#!/bin/sh
# Lab test: x86_64 cross-arch boot investigation
# Tests pc + -nodefaults + TCG on native x86_64 (simulating the cross-arch config).
# The actual cross-arch issue is on ARM64 hosts, but this validates the config.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACHINE_DIR="$(cd "$SCRIPT_DIR/../../Machines/chr.x86_64.qemu.7.23beta2.utm" && pwd)"
PORT="${1:-19180}"
TIMEOUT_SEC="${2:-60}"

echo "=== x86_64 cross-arch boot test ==="
echo "Machine: $MACHINE_DIR"
echo "Port: $PORT, Timeout: ${TIMEOUT_SEC}s"

# Check for disk image
if [ ! -f "$MACHINE_DIR/Data/chr-7.23beta2.img" ]; then
  echo "ERROR: disk image not found. Run 'make' first."
  exit 1
fi

# Cleanup
pkill -f "qemu-system-x86_64.*test-pc" 2>/dev/null || true
sleep 1
rm -f /tmp/test-pc-serial.sock /tmp/test-pc-monitor.sock /tmp/test-pc.cfg
rm -f /tmp/test-pc-serial.log /tmp/test-pc-stderr.log /tmp/test-pc-debug.log

cd "$MACHINE_DIR"

# Create cross-arch config (pc instead of q35)
sed 's/type = "q35"/type = "pc"/' qemu.cfg > /tmp/test-pc.cfg
echo "--- Config (pc machine type) ---"
grep -A1 '^\[machine\]' /tmp/test-pc.cfg

# ── Test 1: pc + -nodefaults + TCG (simulates cross-arch config) ──
echo ""
echo "=== Test 1: pc + -nodefaults + TCG ==="
qemu-system-x86_64 \
  --readconfig /tmp/test-pc.cfg \
  -accel tcg,tb-size=256 \
  -nodefaults \
  -netdev user,id=net0,hostfwd=tcp::${PORT}-:80 \
  -display none \
  -chardev socket,id=monitor0,path=/tmp/test-pc-monitor.sock,server=on,wait=off \
  -mon chardev=monitor0,mode=readline \
  -chardev socket,id=serial0,path=/tmp/test-pc-serial.sock,server=on,wait=off \
  -serial chardev:serial0 \
  -d guest_errors,unimp -D /tmp/test-pc-debug.log \
  2>/tmp/test-pc-stderr.log &
QPID=$!
echo "  QEMU PID=$QPID"
sleep 2

# Start serial capture
if [ -S /tmp/test-pc-serial.sock ]; then
  socat -u UNIX-CONNECT:/tmp/test-pc-serial.sock CREATE:/tmp/test-pc-serial.log &
  SPID=$!
  echo "  Serial capture PID=$SPID"
else
  SPID=""
  echo "  WARNING: serial socket not found"
fi

# Poll for HTTP
BOOTED=0
ELAPSED=0
POLL=5
while [ "$ELAPSED" -lt "$TIMEOUT_SEC" ]; do
  if ! kill -0 "$QPID" 2>/dev/null; then
    echo "  QEMU exited early!"
    break
  fi
  if curl -s -m 2 --fail "http://localhost:${PORT}/" > /dev/null 2>&1; then
    echo "  HTTP OK after ${ELAPSED}s"
    BOOTED=1
    break
  fi
  CPU=$(ps -p "$QPID" -o %cpu= 2>/dev/null || echo "?")
  echo "  ${ELAPSED}s: not ready (cpu=${CPU}%)"
  sleep "$POLL"
  ELAPSED=$((ELAPSED + POLL))
done

# Collect results
echo ""
echo "--- Serial output (last 20 lines) ---"
if [ -n "$SPID" ]; then
  kill "$SPID" 2>/dev/null || true
  wait "$SPID" 2>/dev/null || true
fi
if [ -s /tmp/test-pc-serial.log ]; then
  wc -c < /tmp/test-pc-serial.log | xargs printf "  (%s bytes)\n"
  tail -20 /tmp/test-pc-serial.log
else
  echo "  (empty)"
fi

echo "--- QEMU stderr ---"
cat /tmp/test-pc-stderr.log 2>/dev/null || echo "  (empty)"

echo "--- Debug log ---"
if [ -s /tmp/test-pc-debug.log ]; then
  wc -l < /tmp/test-pc-debug.log | xargs printf "  (%s lines)\n"
  tail -5 /tmp/test-pc-debug.log
else
  echo "  (empty)"
fi

# Monitor query if still running
if kill -0 "$QPID" 2>/dev/null && [ -S /tmp/test-pc-monitor.sock ]; then
  echo "--- Monitor: info cpus ---"
  echo "info cpus" | socat - UNIX-CONNECT:/tmp/test-pc-monitor.sock 2>/dev/null | head -5 || true
fi

# Cleanup
kill "$QPID" 2>/dev/null || true
rm -f /tmp/test-pc-serial.sock /tmp/test-pc-monitor.sock /tmp/test-pc.cfg
rm -f /tmp/test-pc-serial.log /tmp/test-pc-stderr.log /tmp/test-pc-debug.log

if [ "$BOOTED" = "1" ]; then
  echo ""
  echo "RESULT: PASSED — pc + -nodefaults + TCG boots in ${ELAPSED}s"
  exit 0
else
  echo ""
  echo "RESULT: FAILED — timeout after ${TIMEOUT_SEC}s"
  exit 1
fi
