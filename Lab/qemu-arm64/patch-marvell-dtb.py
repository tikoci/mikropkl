#!/usr/bin/env python3
"""
Patch QEMU virt DTB to include Marvell Armada7040 compatible strings.
Theory: RouterOS init reads DTB compatible to decide if it should populate /ram/.
With acpi=on, kernel uses ACPI for devices but DTB for hardware identity.
"""
import subprocess
import tempfile
import os

# Decompile DTB to DTS
result = subprocess.run(
    ['dtc', '-I', 'dtb', '-O', 'dts', '/tmp/virt-base.dtb'],
    capture_output=True, text=True
)
dts = result.stdout

# Replace the compatible and model strings
# Original: compatible = "linux,dummy-virt"; model = "linux,dummy-virt";
# New: Add Marvell Armada7040 compatible strings
dts = dts.replace(
    'model = "linux,dummy-virt";',
    'model = "Marvell Armada 7040 DB board";'
)
dts = dts.replace(
    'compatible = "linux,dummy-virt";',
    'compatible = "marvell,armada7040-db", "marvell,armada7040", "marvell,armada-cp110", "marvell,armada-ap806-quad", "marvell,armada-ap806";',
    1  # Only first occurrence (root node)
)

# Write modified DTS
with open('/tmp/virt-marvell.dts', 'w') as f:
    f.write(dts)

# Compile back to DTB
result = subprocess.run(
    ['dtc', '-I', 'dts', '-O', 'dtb', '-o', '/tmp/virt-marvell.dtb', '/tmp/virt-marvell.dts'],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"DTC compile error: {result.stderr}")
else:
    size = os.path.getsize('/tmp/virt-marvell.dtb')
    print(f"Modified DTB: /tmp/virt-marvell.dtb ({size} bytes)")

# Verify
result = subprocess.run(
    ['dtc', '-I', 'dtb', '-O', 'dts', '/tmp/virt-marvell.dtb'],
    capture_output=True, text=True
)
for line in result.stdout.split('\n')[:15]:
    print(line)
