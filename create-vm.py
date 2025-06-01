#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def existing_path(path: str) -> Path:
    """Ensure the provided path exists."""
    resolved_path = Path(path).expanduser().resolve()
    if not resolved_path.exists():
        raise argparse.ArgumentTypeError(f"Path '{resolved_path}' does not exist.")
    return resolved_path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a new Windows VM using virt-install."
    )
    parser.add_argument(
        "--vm-path",
        type=Path,
        default=Path("~/vms").expanduser(),
        help="Directory to store the VM files (default: ~/vms)",
    )
    parser.add_argument(
        "--ovmf-code",
        type=existing_path,
        default=Path("/usr/share/OVMF/OVMF_CODE.fd"),
        help="Path to the OVMF code firmware file (default: /usr/share/OVMF/OVMF_CODE.fd)",
    )
    parser.add_argument(
        "--ovmf-vars",
        type=existing_path,
        default=Path("/usr/share/OVMF/OVMF_VARS.fd"),
        help="Path to the OVMF variables firmware file template (default: /usr/share/OVMF/OVMF_VARS.fd)",
    )
    parser.add_argument(
        "--iso",
        type=existing_path,
        required=True,
        help="Path to the Windows installation ISO file.",
    )
    parser.add_argument(
        "--memory",
        type=int,
        default=4096,
        help="Amount of memory for the VM in MB (default: 4096)",
    )
    parser.add_argument(
        "--vcpus",
        type=int,
        default=2,
        help="Number of virtual CPUs for the VM (default: 2)",
    )
    parser.add_argument(
        "--disk-size",
        type=str,
        default="100",
        help="Size of the VM disk (default: 100)",
    )
    parser.add_argument(
        "--os-variant",
        type=str,
        default="win11",
        help="OS variant for the VM (default: win11)",
    )

    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="Name of the VM",
    )

    parser.add_argument(
        "--tpm",
        type=existing_path,
        default=Path("/var/lib/libvirt/qemu/tpm_state"),
        help="Path to the TPM state file (default: /var/lib/libvirt/qemu/tpm_state)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Generate a unique per-VM directory and filenames
    vm_basename = args.name
    vm_dir = args.vm_path.expanduser().resolve() / vm_basename
    vm_dir.mkdir(parents=True, exist_ok=True)

    ovmf_code_dest = (
        vm_dir / f"{args.ovmf_code.stem}_{vm_basename.upper()}{args.ovmf_code.suffix}"
    )

    ovmf_vars_dest = (
        vm_dir / f"{args.ovmf_vars.stem}_{vm_basename.upper()}{args.ovmf_vars.suffix}"
    )

    ovmf_tpm_state = vm_dir / f"{vm_basename.lower()}_tpm_state"

    # Copy firmware files
    shutil.copy2(args.ovmf_code, ovmf_code_dest)
    shutil.copy2(args.ovmf_vars, ovmf_vars_dest)
    # shutil.copy2(args.tpm, ovmf_tpm_state)

    system_disk = str(vm_dir / f"{vm_basename.lower()}_system.qcow2")

    create_disk_cmd = [
        "qemu-img",
        "create",
        "-f",
        "qcow2",
        system_disk,
        args.disk_size,
    ]
    print("Creating disk image:", " ".join(create_disk_cmd))
    subprocess.run(create_disk_cmd, check=True)

    disk_arg = f"{system_disk},size={args.disk_size}"

    boot_arg = (
        f"loader={ovmf_code_dest},"
        "loader.readonly=yes,"
        "loader.type=pflash,"
        f"nvram={ovmf_vars_dest}"
    )

    tpm_arg = (
        "backend.type=emulator,"
        "backend.version=2.0,"
        "backend.persistent_state=yes,"
        f"backend.file={ovmf_tpm_state},"
        "model=crb"
    )

    # --- full virt-install command -----------------
    virt_install_cmd = [
        "virt-install",
        "--print-xml",
        "--name",
        vm_basename,
        "--memory",
        str(args.memory),
        "--vcpus",
        str(args.vcpus),
        "--cpu",
        "host-passthrough",
        "--disk",
        disk_arg,
        "--cdrom",
        str(args.iso),
        "--os-variant",
        args.os_variant,
        "--machine",
        "q35",
        "--boot",
        boot_arg,
        "--tpm",
        tpm_arg,
        "--graphics",
        "spice",
        "--video",
        "qxl",
        "--network",
        "user",
        "--virt-type",
        "kvm",
    ]

    # Build virt-install command
    print("Running virt-install command:", " ".join(virt_install_cmd))
    result = subprocess.run(
        virt_install_cmd, check=True, capture_output=True, text=True
    )

    xml_output = result.stdout

    with open(vm_dir / f"{vm_basename}.xml", "w") as xml_file:
        xml_file.write(xml_output)
    print(f"VM '{vm_basename}' created successfully in {vm_dir}.")
    print(f"VM XML configuration saved to {vm_dir / f'{vm_basename}.xml'}.")


if __name__ == "__main__":
    main()
