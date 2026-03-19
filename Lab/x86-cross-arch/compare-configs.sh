#!/bin/sh
# Lab test: Compare x86_64 boot times with various TCG tuning options.
# All tests use TCG (even on x86 host) to measure SeaBIOS overhead.
# On ARM64 host, these numbers would be much higher but proportionally similar.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MACHINE_DIR="$(cd "$SCRIPT_DIR/../../Machines/chr.x86_64.qemu.7.23beta2.utm" && pwd)"
IMG_NAME="$(ls "$MACHINE_DIR"/Data/*.img 2>/dev/null | head -1)"

if [ -z "$IMG_NAME" ]; then
  echo "ERROR: no disk image found. Run 'make' first."
  exit 1
fi

PORT_BASE=19180
TIMEOUT=60
RESULTS=""

run_test() {
  NAME="$1"
  shift
  PORT=$((PORT_BASE))
  PORT_BASE=$((PORT_BASE + 1))
  
  echo ""
  echo "══════════════════════════════════════"
  echo "  TEST: $NAME (port=$PORT)"
  echo "══════════════════════════════════════"
  
  rm -f /tmp/test-boot-serial.sock /tmp/test-boot-monitor.sock
  
  cd "$MACHINE_DIR"
  
  # Start QEMU
  "$@" \
    -netdev user,id=net0,hostfwd=tcp::${PORT}-:80 \
    -display none \
    -chardev socket,id=serial0,path=/tmp/test-boot-serial.sock,server=on,wait=off \
    -serial chardev:serial0 \
    2>/tmp/test-boot-stderr.log &
  QPID=$!
  sleep 1
  
  if ! kill -0 "$QPID" 2>/dev/null; then
    echo "  QEMU failed to start!"
    cat /tmp/test-boot-stderr.log 2>/dev/null
    RESULTS="$RESULTS\n  $NAME: FAILED (startup error)"
    return
  fi
  
  # Capture serial
  socat -u UNIX-CONNECT:/tmp/test-boot-serial.sock CREATE:/tmp/test-boot-serial.log 2>/dev/null &
  SPID=$!
  
  # Poll
  BOOTED=0
  ELAPSED=0
  POLL=5
  START=$(date +%s)
  while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
    if ! kill -0 "$QPID" 2>/dev/null; then
      echo "  QEMU exited!"
      break
    fi
    if curl -s -m 2 --fail "http://localhost:${PORT}/" > /dev/null 2>&1; then
      ELAPSED=$(( $(date +%s) - START ))
      echo "  HTTP OK after ${ELAPSED}s"
      BOOTED=1
      break
    fi
    sleep "$POLL"
    ELAPSED=$(( $(date +%s) - START ))
    echo "  ${ELAPSED}s..."
  done
  
  kill "$SPID" 2>/dev/null; wait "$SPID" 2>/dev/null || true
  
  echo "  Serial:"
  head -5 /tmp/test-boot-serial.log 2>/dev/null | sed 's/^/    /' || echo "    (empty)"
  
  echo "  Stderr:"
  cat /tmp/test-boot-stderr.log 2>/dev/null | head -3 | sed 's/^/    /' || echo "    (empty)"
  
  kill "$QPID" 2>/dev/null; wait "$QPID" 2>/dev/null || true
  
  if [ "$BOOTED" = "1" ]; then
    RESULTS="${RESULTS}\n  ${NAME}: PASSED in ${ELAPSED}s"
  else
    RESULTS="${RESULTS}\n  ${NAME}: FAILED (timeout ${TIMEOUT}s)"
  fi
  
  rm -f /tmp/test-boot-serial.sock /tmp/test-boot-monitor.sock
  rm -f /tmp/test-boot-serial.log /tmp/test-boot-stderr.log
  sleep 2
}

echo "=== x86_64 cross-arch boot optimization tests ==="
echo "Machine: $MACHINE_DIR"
echo "Timeout: ${TIMEOUT}s per test"
echo "Disk: $IMG_NAME"

# ── Test 1: Baseline — q35 + TCG (current config without workaround) ──
run_test "q35 baseline" \
  qemu-system-x86_64 \
  --readconfig "$MACHINE_DIR/qemu.cfg" \
  -accel tcg,tb-size=256

# ── Test 2: pc + -nodefaults + TCG (current cross-arch workaround) ──
sed 's/type = "q35"/type = "pc"/' "$MACHINE_DIR/qemu.cfg" > /tmp/test-pc.cfg
run_test "pc + nodefaults" \
  qemu-system-x86_64 \
  --readconfig /tmp/test-pc.cfg \
  -accel tcg,tb-size=256 \
  -nodefaults

# ── Test 3: pc + nodefaults + disable extra I/O devices ──
run_test "pc + nodefaults + minimal I/O" \
  qemu-system-x86_64 \
  --readconfig /tmp/test-pc.cfg \
  -accel tcg,tb-size=256 \
  -nodefaults \
  -M pc,hpet=off,i8042=off,smm=off,vmport=off,usb=off

# ── Test 4: pc + nodefaults + SMP=1 (single CPU reduces init overhead) ──
sed -e 's/type = "q35"/type = "pc"/' -e 's/cpus = "2"/cpus = "1"/' "$MACHINE_DIR/qemu.cfg" > /tmp/test-pc-1cpu.cfg
run_test "pc + nodefaults + 1 CPU" \
  qemu-system-x86_64 \
  --readconfig /tmp/test-pc-1cpu.cfg \
  -accel tcg,tb-size=256 \
  -nodefaults

# ── Test 5: microvm machine type (minimal x86 machine, no SeaBIOS) ──
# microvm uses a direct kernel boot with minimal firmware — but this requires
# a kernel, which RouterOS bundles inside the disk image. Skip if not feasible.
# Instead test 'isapc' — even more minimal than pc (ISA-only, no PCI)
# Note: this will likely fail since RouterOS needs PCI for virtio
echo "(Skipping microvm — needs -kernel, RouterOS doesn't support direct boot)"

# ── Test 6: pc + nodefaults + larger TB cache ──
run_test "pc + nodefaults + tb-size=512" \
  qemu-system-x86_64 \
  --readconfig /tmp/test-pc.cfg \
  -accel tcg,tb-size=512 \
  -nodefaults

# ── Test 7: pc + nodefaults + one-insn-per-tb (debugging: max TCG granularity) ──
# This should be SLOWER but helps diagnose if TB compilation itself is the bottleneck
run_test "pc + nodefaults + one-insn-per-tb" \
  qemu-system-x86_64 \
  --readconfig /tmp/test-pc.cfg \
  -accel tcg,tb-size=256,one-insn-per-tb=on \
  -nodefaults

# ── Summary ──
echo ""
echo "══════════════════════════════════════"
echo "  RESULTS SUMMARY"
echo "══════════════════════════════════════"
printf "$RESULTS\n"

rm -f /tmp/test-pc.cfg /tmp/test-pc-1cpu.cfg
