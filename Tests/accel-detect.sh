#!/bin/sh
# Anchor test for qemu.sh accelerator selection (Pkl/QemuCfg.pkl).
#
# Verifies what the generated launcher *currently* decides, so the decision table
# cannot regress silently.  The interesting case cannot be reproduced on any CI
# runner or on an Intel Mac — HVF + FEAT_SSBS=0 needs Apple M4 hardware — so the
# host probes (`uname`, `sysctl`) are stubbed on PATH and the script is run with
# --dry-run, which prints the assembled QEMU command without launching anything.
#
# Usage:  sh Tests/accel-detect.sh [CHR_VERSION]
# Needs:  pkl on PATH.  No QEMU, no disk images, no network beyond `pkl eval`.

set -eu

VERSION="${1:-${CHR_VERSION:-7.22.1}}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REPO="$(cd "$(dirname "$0")/.." && pwd)"

FAILURES=0
CASES=0

# ── Generate the launchers (phase 1 only — no images) ──
# pkl eval reads random.org for the UTM identifier; retry so a hiccup there does
# not read as a test failure.
ATTEMPT=1
while :; do
  if CHR_VERSION="$VERSION" pkl eval "$REPO"/Manifests/chr.aarch64.qemu.pkl \
       "$REPO"/Manifests/chr.x86_64.qemu.pkl -m "$WORK/machines" >/dev/null 2>"$WORK/pkl.err"; then
    break
  fi
  if [ "$ATTEMPT" -ge 3 ]; then
    echo "FATAL: pkl eval failed after $ATTEMPT attempts" >&2
    cat "$WORK/pkl.err" >&2
    exit 2
  fi
  ATTEMPT=$((ATTEMPT + 1))
done

ARM_VM="$WORK/machines/chr.aarch64.qemu.$VERSION.utm"
X86_VM="$WORK/machines/chr.x86_64.qemu.$VERSION.utm"
chmod +x "$ARM_VM/qemu.sh" "$X86_VM/qemu.sh"

# ── Stubs: host probes, a fake QEMU binary, and pflash-sized firmware ──
mkdir -p "$WORK/stub" "$WORK/fw"
cat > "$WORK/stub/uname" <<'EOF'
#!/bin/sh
case "${1:-}" in
  -s) echo "${STUB_OS:-Darwin}" ;;
  -m) echo "${STUB_ARCH:-arm64}" ;;
  *)  echo "${STUB_OS:-Darwin}" ;;
esac
EOF
cat > "$WORK/stub/sysctl" <<'EOF'
#!/bin/sh
for key; do :; done   # key = last argument
case "$key" in
  kern.hv_support)           echo "${STUB_HV:-1}" ;;
  hw.optional.arm.FEAT_SSBS) [ "${STUB_SSBS:-1}" = "absent" ] && exit 1; echo "${STUB_SSBS:-1}" ;;
  *) exit 1 ;;
esac
EOF
for BIN in qemu-system-aarch64 qemu-system-x86_64; do
  printf '#!/bin/sh\nexit 0\n' > "$WORK/stub/$BIN"
done
chmod +x "$WORK/stub"/*
head -c 65536 /dev/zero > "$WORK/fw/code.fd"
head -c 65536 /dev/zero > "$WORK/fw/vars.fd"

# check <description> <vm-dir> <expect-accel> <expect-cpu> <expect-note: note|no-note> [extra env...]
check() {
  DESC="$1"; VM="$2"; WANT_ACCEL="$3"; WANT_CPU="$4"; WANT_NOTE="$5"
  shift 5
  CASES=$((CASES + 1))
  if env PATH="$WORK/stub:$PATH" \
      QEMU_EFI_CODE="$WORK/fw/code.fd" QEMU_EFI_VARS="$WORK/fw/vars.fd" \
      "$@" "$VM/qemu.sh" --dry-run >"$WORK/out" 2>"$WORK/err"; then
    :
  else
    echo "FAIL: $DESC — qemu.sh --dry-run exited $?"
    sed 's/^/      /' "$WORK/err"
    FAILURES=$((FAILURES + 1))
    return
  fi

  PROBLEM=""
  grep -q -- "-accel $WANT_ACCEL" "$WORK/out" || PROBLEM="$PROBLEM accel(want=$WANT_ACCEL)"
  case "$WANT_CPU" in
    "")     : ;;                                     # don't care
    none)   grep -q -- "-cpu " "$WORK/out" && PROBLEM="$PROBLEM unexpected-cpu-flag" ;;
    *)      grep -q -- "-cpu $WANT_CPU" "$WORK/out" || PROBLEM="$PROBLEM cpu(want=$WANT_CPU)" ;;
  esac
  if [ "$WANT_NOTE" = "note" ]; then
    grep -q "FEAT_SSBS" "$WORK/err" || PROBLEM="$PROBLEM missing-ssbs-note"
  else
    grep -q "FEAT_SSBS" "$WORK/err" && PROBLEM="$PROBLEM unexpected-ssbs-note"
  fi

  if [ -n "$PROBLEM" ]; then
    echo "FAIL: $DESC —$PROBLEM"
    echo "      got: $(grep -oE -- '-accel [^ ]+|-cpu [^ ]+' "$WORK/out" | tr '\n' ' ')"
    [ -s "$WORK/err" ] && sed 's/^/      stderr: /' "$WORK/err"
    FAILURES=$((FAILURES + 1))
  else
    echo "ok: $DESC"
  fi
}

echo "== aarch64 guest =="
# The regression this test exists for: HVF is available, but the host omits
# FEAT_SSBS (Apple M4+), so the launcher must pick TCG and say why (issue #11).
check "M4 (hv=1, FEAT_SSBS=0) → TCG + note" \
  "$ARM_VM" "tcg,tb-size=256" "cortex-a710" note \
  STUB_OS=Darwin STUB_ARCH=arm64 STUB_HV=1 STUB_SSBS=0
check "M1/M2/M3 (hv=1, FEAT_SSBS=1) → HVF + -cpu host" \
  "$ARM_VM" "hvf" "host" no-note \
  STUB_OS=Darwin STUB_ARCH=arm64 STUB_HV=1 STUB_SSBS=1
check "older macOS (sysctl key absent) → HVF" \
  "$ARM_VM" "hvf" "host" no-note \
  STUB_OS=Darwin STUB_ARCH=arm64 STUB_HV=1 STUB_SSBS=absent
check "QEMU_ACCEL=hvf overrides the fallback on an M4" \
  "$ARM_VM" "hvf" "host" no-note \
  STUB_OS=Darwin STUB_ARCH=arm64 STUB_HV=1 STUB_SSBS=0 QEMU_ACCEL=hvf
check "no HVF (GitHub macOS runner) → TCG, no SSBS note" \
  "$ARM_VM" "tcg,tb-size=256" "cortex-a710" no-note \
  STUB_OS=Darwin STUB_ARCH=arm64 STUB_HV=0 STUB_SSBS=1
check "Linux x86_64 host, aarch64 guest → cross-arch TCG" \
  "$ARM_VM" "tcg,tb-size=256" "cortex-a710" no-note \
  STUB_OS=Linux STUB_ARCH=x86_64

echo "== x86_64 guest (must be untouched by the SSBS probe) =="
check "M4 host, x86_64 guest → cross-arch TCG, no SSBS note" \
  "$X86_VM" "tcg,tb-size=256" none no-note \
  STUB_OS=Darwin STUB_ARCH=arm64 STUB_HV=1 STUB_SSBS=0
# The SeaBIOS x86 machine passes no -cpu at all, under any accelerator: the
# -cpu host override exists for the OVMF/UEFI x86 machines (*.apple.*), where the
# default qemu64 CPUID advertises AMD SVM and hangs OVMF.  Asserted so the
# difference between the two x86 tracks stays visible.
check "Intel Mac, x86_64 guest → HVF with QEMU's default CPU" \
  "$X86_VM" "hvf" none no-note \
  STUB_OS=Darwin STUB_ARCH=x86_64 STUB_HV=1

echo "== generated scripts are POSIX sh =="
for VM in "$ARM_VM" "$X86_VM"; do
  CASES=$((CASES + 1))
  if sh -n "$VM/qemu.sh"; then
    echo "ok: sh -n $(basename "$VM")/qemu.sh"
  else
    echo "FAIL: sh -n $(basename "$VM")/qemu.sh"
    FAILURES=$((FAILURES + 1))
  fi
done

echo ""
if [ "$FAILURES" -gt 0 ]; then
  echo "$FAILURES of $CASES checks FAILED"
  exit 1
fi
echo "all $CASES checks passed"
