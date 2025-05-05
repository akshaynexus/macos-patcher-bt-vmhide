#!/usr/bin/env python3

import plistlib
import base64
import os
import sys
import subprocess
import re
import time
import argparse
import threading
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Literal

# Add specific exception import
from plistlib import InvalidFileException

# --- Constants ---

# ANSI color codes
COLORS = {
    'RESET': '\033[0m', 'BLACK': '\033[30m', 'RED': '\033[31m',
    'GREEN': '\033[32m', 'YELLOW': '\033[33m', 'BLUE': '\033[34m',
    'MAGENTA': '\033[35m', 'CYAN': '\033[36m', 'WHITE': '\033[37m',
    'BOLD': '\033[1m', 'UNDERLINE': '\033[4m'
}

# Patch identifiers
PATCH_COMMENT_BASE = "Sonoma VM BT Enabler"
PATCH_COMMENT_1 = f"{PATCH_COMMENT_BASE} - PART 1 of 2 - Patch kern.hv_vmm_present=0"
PATCH_COMMENT_2 = f"{PATCH_COMMENT_BASE} - PART 2 of 2 - Patch kern.hv_vmm_present=0"

# Global debug flag
DEBUG_MODE = False

# --- Utility Classes and Functions ---

class Spinner:
    """Displays a spinning cursor in the terminal."""
    def __init__(self, message: str = "Processing", delay: float = 0.1):
        self._spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._delay = delay
        self._message = message
        self._running = False
        self._spinner_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _spin(self) -> None:
        i = 0
        while self._running:
            with self._lock:
                if not self._running: # Check again after acquiring lock
                    break
                char = self._spinner_chars[i % len(self._spinner_chars)]
                # Ensure message doesn't change mid-write
                current_message = self._message
                line = f"\r{COLORS['CYAN']}{char} {current_message}{COLORS['RESET']} "
                sys.stdout.write(line)
                sys.stdout.flush()
            time.sleep(self._delay)
            i += 1

    def start(self, message: Optional[str] = None) -> None:
        """Starts the spinner animation."""
        with self._lock:
            if self._running:
                # Update message if spinner is already running
                if message:
                    self._message = message
                return # Already running
            if message:
                self._message = message
            self._running = True
            self._spinner_thread = threading.Thread(target=self._spin, daemon=True)
            self._spinner_thread.start()

    def stop(self, final_message: Optional[str] = None) -> None:
        """Stops the spinner animation and optionally prints a final message."""
        with self._lock:
            if not self._running:
                return # Already stopped
            self._running = False
            # Clear the spinner line based on the *last* message shown
            clear_line = '\r' + ' ' * (len(self._message) + 5) + '\r'
            sys.stdout.write(clear_line)
            sys.stdout.flush()

        if self._spinner_thread:
            self._spinner_thread.join(timeout=1.0) # Add timeout to join
            if self._spinner_thread.is_alive():
                 log("Spinner thread did not exit cleanly.", "DEBUG")
            self._spinner_thread = None

        if final_message:
            print(final_message)
        # Ensure cursor is at the beginning of the next line if no final message
        elif not final_message and not clear_line.endswith('\n'):
             print() # Move to next line

    def set_message(self, message: str) -> None:
        """Updates the spinner message dynamically."""
        with self._lock:
            self._message = message


def log(message: str, level: str = "INFO", timestamp: bool = True, color_override: Optional[str] = None) -> None:
    """Logs a message to the console with appropriate coloring."""
    if level == "DEBUG" and not DEBUG_MODE:
        return # Suppress debug messages if not enabled

    level_colors = {
        "INFO": COLORS['BLUE'], "ERROR": COLORS['RED'], "SUCCESS": COLORS['GREEN'],
        "WARNING": COLORS['YELLOW'], "DEBUG": COLORS['MAGENTA'],
        "TITLE": COLORS['MAGENTA'] + COLORS['BOLD'], "HEADER": COLORS['CYAN'] + COLORS['BOLD'],
    }
    color = color_override if color_override else level_colors.get(level, COLORS['RESET'])
    time_str = f"[{datetime.now().strftime('%H:%M:%S')}] " if timestamp else ""
    level_str = f"[{level}] " if level not in ["TITLE", "HEADER"] else ""

    # Prepend DEBUG tag explicitly for clarity if level is DEBUG
    if level == "DEBUG":
        message = f"DEBUG: {message}"
        level_str = "[DEBUG] " # Ensure DEBUG tag shows even if timestamp=False

    formatted_message = f"{color}{time_str}{level_str}{message}{COLORS['RESET']}"

    if level == "TITLE":
        print("\n" + "=" * 70)
        print(f"{color}{message.center(70)}{COLORS['RESET']}")
        print("=" * 70)
    elif level == "HEADER":
        print(f"\n{color}=== {message} ==={COLORS['RESET']}")
    else:
        print(formatted_message)
    sys.stdout.flush() # Ensure message is printed immediately


def run_command(command: List[str], check: bool = True, capture_output: bool = True) -> Tuple[int, str, str]:
    """Runs a shell command safely and returns status, stdout, stderr."""
    log(f"Running command: {' '.join(command)}", "DEBUG", timestamp=False)
    try:
        process = subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=True,
            encoding='utf-8',
            errors='ignore' # Ignore potential decoding errors in output
        )
        log(f"Command finished: rc={process.returncode}", "DEBUG", timestamp=False)
        log(f"  stdout: {process.stdout.strip()}", "DEBUG", timestamp=False)
        log(f"  stderr: {process.stderr.strip()}", "DEBUG", timestamp=False)
        return process.returncode, process.stdout.strip(), process.stderr.strip()
    except FileNotFoundError:
        log(f"Error: Command not found: {command[0]}", "ERROR")
        return -1, "", f"Command not found: {command[0]}"
    except subprocess.CalledProcessError as e:
        log(f"Command failed with rc={e.returncode}: {' '.join(command)}", "DEBUG")
        log(f"  stdout: {e.stdout.strip()}", "DEBUG", timestamp=False)
        log(f"  stderr: {e.stderr.strip()}", "DEBUG", timestamp=False)
        # Error already logged by check=True, but we return details
        return e.returncode, e.stdout.strip(), e.stderr.strip()
    except Exception as e:
        log(f"An unexpected error occurred running command '{' '.join(command)}': {e}", "ERROR")
        return -1, "", str(e)


def print_banner() -> None:
    """Prints the script's startup banner."""
    banner = """
    ╔════════════════════════════════════════════════════════╗
    ║                                                        ║
    ║   ███████╗ ██████╗ ███╗   ██╗ ██████╗ ███╗   ███╗ █████╗  ║
    ║   ██╔════╝██╔═══██╗████╗  ██║██╔═══██╗████╗ ████║██╔══██╗ ║
    ║   ███████╗██║   ██║██╔██╗ ██║██║   ██║██╔████╔██║███████║ ║
    ║   ╚════██║██║   ██║██║╚██╗██║██║   ██║██║╚██╔╝██║██╔══██║ ║
    ║   ███████║╚██████╔╝██║ ╚████║╚██████╔╝██║ ╚═╝ ██║██║  ██║ ║
    ║   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝ ║
    ║                                                        ║
    ║      VM Bluetooth Enabler Patch Tool v2.1 (plutil fix) ║
    ║      For macOS Sonoma (and later) OpenCore             ║
    ║                                                        ║
    ╚════════════════════════════════════════════════════════╝
    """
    print(f"{COLORS['CYAN']}{banner}{COLORS['RESET']}")


def request_confirmation(prompt: str, default_yes: bool = False) -> bool:
    """Asks the user for confirmation."""
    suffix = " [Y/n]" if default_yes else " [y/N]"
    while True:
        response = input(f"{COLORS['YELLOW']}{prompt}{suffix}: {COLORS['RESET']}").strip().lower()
        if not response:
            return default_yes
        if response in ['y', 'yes']:
            return True
        if response in ['n', 'no']:
            return False
        log("Invalid input. Please enter 'y' or 'n'.", "WARNING", timestamp=False)

# --- Core Logic Functions ---

def get_disk_list(spinner: Spinner) -> Optional[str]:
    """Gets the output of 'diskutil list'."""
    spinner.start("Scanning disk list...")
    ret_code, stdout, stderr = run_command(['diskutil', 'list'], check=False)
    if ret_code != 0:
        spinner.stop(f"{COLORS['RED']}✗ Failed to get disk list.{COLORS['RESET']}")
        log(f"Error running diskutil: {stderr}", "ERROR")
        return None
    spinner.stop(f"{COLORS['GREEN']}✓ Disk scan complete.{COLORS['RESET']}")
    log(f"diskutil list output:\n{stdout}", "DEBUG")
    return stdout


def get_efi_partitions(disk_info: str) -> List[str]:
    """Extracts EFI partition identifiers (e.g., disk0s1) from diskutil output."""
    log("Analyzing disk information for EFI partitions...", "INFO", timestamp=False)
    efi_partitions = []
    current_disk = None
    # Regex to find partition identifiers like /dev/diskXsY
    disk_id_pattern = re.compile(r'(/dev/disk\d+)\s+\(')
    # Regex to find EFI partitions by type and name/label
    # Looks for 'EFI' type and common names/labels or APFS ISC type
    efi_partition_pattern = re.compile(
        r'\s+(\d+):\s+(Apple_APFS_ISC|EFI)\s+(EFI|ESP|BOOTCAMP|BOOT|NO NAME)\s+.*',
        re.IGNORECASE
    )
    # Regex to find EFI partition by GPT type GUID directly (C12A7328...)
    efi_guid_pattern = re.compile(r'\s+(\d+):\s+C12A7328-F81F-11D2-BA4B-00A0C93EC93B\s+.*')

    for line in disk_info.splitlines():
        disk_match = disk_id_pattern.match(line)
        if disk_match:
            current_disk = disk_match.group(1) # e.g., /dev/disk0
            log(f"Processing disk: {current_disk}", "DEBUG")
            continue # Move to the next line after finding a disk identifier

        if not current_disk:
            continue # Skip lines until we identify a disk

        log(f" Checking line for EFI: {line.strip()}", "DEBUG")
        efi_match = efi_partition_pattern.search(line)
        guid_match = efi_guid_pattern.search(line)

        partition_num = None
        if efi_match:
            partition_num = efi_match.group(1)
            log(f"  Found potential EFI by name/type match: num={partition_num}", "DEBUG")
        elif guid_match:
            partition_num = guid_match.group(1)
            log(f"  Found potential EFI by GUID match: num={partition_num}", "DEBUG")

        if partition_num:
            # Construct the identifier like diskXsY from /dev/diskX and partition_num Y
            disk_num = current_disk.replace('/dev/disk', '')
            partition_id = f"disk{disk_num}s{partition_num}"
            if partition_id not in efi_partitions:
                efi_partitions.append(partition_id)
                log(f"  Identified EFI partition: {partition_id}", "DEBUG", timestamp=False)

    if efi_partitions:
        log(f"Found {len(efi_partitions)} potential EFI partition(s): {', '.join(efi_partitions)}", "SUCCESS", timestamp=False)
    else:
        log("No EFI partitions found using standard identifiers.", "WARNING", timestamp=False)
        log("If you know your EFI partition, you can mount it manually and provide the config.plist path.", "INFO", timestamp=False)

    return efi_partitions


def check_if_mounted(partition_id: str) -> Optional[str]:
    """Checks if a partition (e.g., disk0s1) is mounted and returns its mount point."""
    log(f"  Checking mount status for {partition_id}...", "DEBUG", timestamp=False)
    # Use full device path for diskutil info
    device_path = f"/dev/{partition_id}"
    ret_code, stdout, stderr = run_command(['diskutil', 'info', device_path], check=False)
    if ret_code == 0:
        mount_point_match = re.search(r"Mount Point:\s+(.*)", stdout)
        mounted_match = re.search(r"Mounted:\s+(Yes|No)", stdout)

        if mounted_match and mounted_match.group(1) == "Yes":
            if mount_point_match:
                mount_point = mount_point_match.group(1).strip()
                if mount_point and mount_point != "Not Mounted":
                    log(f"  Partition {partition_id} is mounted at {mount_point}", "DEBUG", timestamp=False)
                    return mount_point
            # If Mounted is Yes but no mount point found, still return something to indicate mounted status
            log(f"  Partition {partition_id} is mounted but mount point parsing failed. Assuming mounted.", "DEBUG")
            # Attempt to find mount point via 'mount' command as fallback
            ret_code_mount, stdout_mount, _ = run_command(['mount'], check=False)
            if ret_code_mount == 0:
                 mount_pattern = re.compile(rf"{device_path}\s+on\s+(/\S+)\s+\(")
                 mp_match = mount_pattern.search(stdout_mount)
                 if mp_match:
                     mount_point = mp_match.group(1)
                     log(f"  Found mount point via 'mount' command: {mount_point}", "DEBUG")
                     return mount_point
            return "/Volumes/UnknownEFI" # Placeholder if really can't find it
    elif "could not find" in stderr.lower():
         log(f"  Device {device_path} not found by diskutil info.", "DEBUG")
    else:
         log(f"  diskutil info failed for {device_path}: {stderr}", "DEBUG")

    log(f"  Partition {partition_id} is not mounted.", "DEBUG", timestamp=False)
    return None


def mount_efi(partition_id: str, spinner: Spinner) -> Optional[str]:
    """Mounts the specified EFI partition (e.g., disk0s1)."""
    spinner.start(f"Attempting to mount {partition_id}...")

    mount_point = check_if_mounted(partition_id)
    if mount_point:
        spinner.stop(f"{COLORS['GREEN']}✓ Partition {partition_id} already mounted at {mount_point}{COLORS['RESET']}")
        return mount_point

    # Standard mount attempt using partition ID
    ret_code, stdout, stderr = run_command(['diskutil', 'mount', partition_id], check=False)

    if ret_code == 0:
        mount_point_match = re.search(r"mounted at\s+(.*)", stdout, re.IGNORECASE)
        if mount_point_match:
            mount_point = mount_point_match.group(1).strip()
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition_id} at {mount_point}{COLORS['RESET']}")
            return mount_point
        else:
            # Mounted but couldn't parse mount point? Check again.
            spinner.set_message(f"Verifying mount point for {partition_id}...")
            mount_point = check_if_mounted(partition_id)
            if mount_point:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition_id} at {mount_point} (verified){COLORS['RESET']}")
                return mount_point
            else:
                 spinner.stop(f"{COLORS['YELLOW']}⚠ Mounted {partition_id} but failed to determine mount point.{COLORS['RESET']}")
                 log(f"diskutil output: {stdout}", "DEBUG")
                 return None # Uncertain state

    # Mount failed
    spinner.stop(f"{COLORS['RED']}✗ Failed to mount {partition_id} using 'diskutil mount'.{COLORS['RESET']}")
    log(f"Error details: {stderr if stderr else stdout}", "ERROR")
    log("Possible reasons: Permissions, SIP enabled, filesystem issues, or incorrect partition.", "INFO")
    log("Try mounting manually using Disk Utility, then run this script with the config.plist path.", "INFO")
    check_system_constraints() # Offer SIP/OS version context
    return None


def check_system_constraints() -> None:
    """Checks for system constraints like SIP that might affect mounting."""
    try:
        ret_code, stdout, stderr = run_command(['csrutil', 'status'], check=False)
        if ret_code == 0 and "enabled" in stdout.lower():
            log("System Integrity Protection (SIP) is enabled. This might prevent mounting EFI partitions.", "WARNING")
            log("If mounting fails, consider temporarily disabling SIP (requires booting into Recovery).", "INFO")
    except Exception:
        log("Could not check SIP status.", "DEBUG") # Command might not exist or fail

    try:
        ret_code, stdout, stderr = run_command(['sw_vers', '-productVersion'], check=False)
        if ret_code == 0:
            log(f"Detected macOS version: {stdout}", "INFO")
            # Optionally add version-specific warnings here if needed
    except Exception:
        log("Could not determine macOS version.", "DEBUG")


def unmount_partition(partition_or_mount_point: str, spinner: Spinner) -> bool:
    """Unmounts a partition or mount point."""
    # Determine if we have a partition ID (like disk0s1) or a mount point path
    is_path = "/" in partition_or_mount_point
    is_partition_id = re.match(r'^disk\d+s\d+$', partition_or_mount_point) is not None

    if not is_path and not is_partition_id:
         log(f"Cannot determine how to unmount target: {partition_or_mount_point}", "ERROR")
         return False

    target_desc = f"mount point {partition_or_mount_point}" if is_path else f"partition {partition_or_mount_point}"
    spinner.start(f"Unmounting {target_desc}...")

    # Check if actually mounted before trying to unmount
    current_mount_point = None
    if is_partition_id:
        current_mount_point = check_if_mounted(partition_or_mount_point)
        if not current_mount_point:
            spinner.stop(f"{COLORS['YELLOW']}⚠ {target_desc} was already unmounted.{COLORS['RESET']}")
            return True
        target_to_unmount = current_mount_point # Prefer unmounting by path if possible
        log(f"  Found {partition_or_mount_point} mounted at {current_mount_point}, unmounting path.", "DEBUG")
    else: # is_path
        # Verify the path is actually a mount point (basic check)
        if not Path(partition_or_mount_point).is_mount():
             # It might be a path *inside* a mount point, diskutil should handle it
             log(f"  Target {partition_or_mount_point} is not a direct mount point, proceeding with unmount.", "DEBUG")
        target_to_unmount = partition_or_mount_point


    # Try standard unmount first
    ret_code, stdout, stderr = run_command(['diskutil', 'unmount', target_to_unmount], check=False)
    if ret_code == 0:
        spinner.stop(f"{COLORS['GREEN']}✓ Successfully unmounted {target_desc}{COLORS['RESET']}")
        return True

    # If standard unmount failed, log and potentially try force
    log(f"Standard unmount failed for {target_to_unmount}. Error: {stderr if stderr else stdout}", "WARNING")

    # Check if it got unmounted anyway (e.g., race condition or delayed update)
    is_still_mounted = False
    if is_partition_id:
        is_still_mounted = check_if_mounted(partition_or_mount_point) is not None
    else: # is_path
        is_still_mounted = Path(target_to_unmount).is_mount()

    if not is_still_mounted:
         spinner.stop(f"{COLORS['YELLOW']}⚠ {target_desc} seems to be unmounted now (verified after failed attempt).{COLORS['RESET']}")
         return True

    # Try force unmount (requires sudo)
    log(f"Attempting force unmount for {target_to_unmount}...", "WARNING")
    ret_code_force, stdout_force, stderr_force = run_command(
        ['sudo', 'diskutil', 'unmount', 'force', target_to_unmount],
        check=False
    )
    if ret_code_force == 0:
         spinner.stop(f"{COLORS['GREEN']}✓ Successfully force-unmounted {target_desc}{COLORS['RESET']}")
         return True

    spinner.stop(f"{COLORS['RED']}✗ Failed to unmount {target_desc} even with force.{COLORS['RESET']}")
    log(f"Error details (force unmount): {stderr_force if stderr_force else stdout_force}", "ERROR")
    log("Please try unmounting manually using Disk Utility.", "WARNING")
    return False


def find_opencore_config(mount_point: Path, spinner: Spinner) -> Optional[Path]:
    """Finds the OpenCore config.plist in a standard location."""
    spinner.start(f"Searching for OpenCore config.plist in {mount_point}...")
    expected_path = mount_point / "EFI" / "OC" / "config.plist"
    log(f" Looking for: {expected_path}", "DEBUG")

    if expected_path.is_file():
        spinner.stop(f"{COLORS['GREEN']}✓ Found OpenCore config.plist at: {expected_path}{COLORS['RESET']}")
        return expected_path
    else:
        spinner.stop(f"{COLORS['YELLOW']}⚠ Standard OpenCore config.plist not found at {expected_path}{COLORS['RESET']}")
        # Optionally, list contents for debugging
        try:
             efi_dir = mount_point / "EFI"
             if efi_dir.is_dir():
                 log(f"Contents of {efi_dir}:", "DEBUG")
                 for item in sorted(efi_dir.iterdir()):
                     log(f"  - {item.name}{'/' if item.is_dir() else ''}", "DEBUG", timestamp=False)

                 oc_dir = efi_dir / "OC"
                 if oc_dir.is_dir():
                     log(f"Contents of {oc_dir}:", "DEBUG")
                     for item in sorted(oc_dir.iterdir()):
                         log(f"  - {item.name}{'/' if item.is_dir() else ''}", "DEBUG", timestamp=False)
                 else:
                     log(f" OC directory not found within {efi_dir}", "DEBUG")
             else:
                  log(f" EFI directory not found within {mount_point}", "DEBUG")

        except Exception as e:
             log(f"Could not list directory contents for debugging: {e}", "DEBUG")
        return None


def check_patches_exist(config_data: Dict[str, Any]) -> bool:
    """Checks if the specific BT patches already exist in the loaded config data."""
    log("  Checking for existing Bluetooth patches...", "DEBUG", timestamp=False)
    try:
        kernel_patches = config_data.get('Kernel', {}).get('Patch', [])
        if not isinstance(kernel_patches, list):
            log("Kernel->Patch section is not a list. Cannot reliably check.", "WARNING")
            return False # Treat as not existing to allow patching attempt

        found_patch_1 = False
        found_patch_2 = False
        for patch in kernel_patches:
            if isinstance(patch, dict):
                 comment = patch.get('Comment', '')
                 if comment == PATCH_COMMENT_1:
                     found_patch_1 = True
                     log(f"  Found existing patch 1: {comment}", "DEBUG", timestamp=False)
                 elif comment == PATCH_COMMENT_2:
                     found_patch_2 = True
                     log(f"  Found existing patch 2: {comment}", "DEBUG", timestamp=False)

        # Return True only if *both* specific patches are found
        if found_patch_1 and found_patch_2:
            log("  Both required Bluetooth patches found.", "DEBUG", timestamp=False)
            return True
        elif found_patch_1 or found_patch_2:
            log("  Found only one of the two required patches. Will proceed to add both.", "WARNING")
            return False # Treat as incomplete/missing
        else:
             log("  No existing Bluetooth patches found.", "DEBUG", timestamp=False)
             return False
    except Exception as e:
        log(f"Error checking for existing patches: {e}", "ERROR")
        return False # Assume not present if check fails


def _create_patch_dict(comment: str, find_b64: str, replace_b64: str, min_kernel: str) -> Dict[str, Any]:
    """Helper to create a patch dictionary."""
    return {
        'Arch': 'x86_64', 'Base': '', 'Comment': comment, 'Count': 1, 'Enabled': True,
        'Find': base64.b64decode(find_b64), 'Identifier': 'kernel', 'Limit': 0, 'Mask': b'',
        'MaxKernel': '', 'MinKernel': min_kernel,
        'Replace': base64.b64decode(replace_b64), 'ReplaceMask': b'', 'Skip': 0,
    }


def add_kernel_patches(config_path: Path, spinner: Spinner) -> Literal["success", "already_exists", "error"]:
    """
    Adds the Sonoma VM BT Enabler kernel patches to the config.plist.
    Includes pre-conversion to XML format for robustness.
    """
    log(f"Starting patch process for: {config_path}", "HEADER")
    # Create a unique backup name based on timestamp
    backup_path = config_path.with_suffix(config_path.suffix + f'.backup_{int(time.time())}')

    # --- 1. Create Backup ---
    spinner.start(f"Creating backup: {backup_path.name}")
    try:
        shutil.copy2(config_path, backup_path)
        spinner.stop(f"{COLORS['GREEN']}✓ Backup created successfully.{COLORS['RESET']}")
        log(f"  Backup saved to: {backup_path}", "DEBUG")
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error creating backup: {e}{COLORS['RESET']}")
        return "error"

    # --- 2. Check and Convert Plist to XML Format using plutil ---
    spinner.start("Checking and ensuring config.plist is in XML format...")
    try:
        # First, lint the file to catch major errors before conversion
        lint_cmd = ['plutil', '-lint', str(config_path)]
        ret_code_lint, _, stderr_lint = run_command(lint_cmd, check=False)
        if ret_code_lint != 0:
            spinner.stop(f"{COLORS['RED']}✗ Plist validation failed (plutil -lint).{COLORS['RESET']}")
            log(f"Error from plutil: {stderr_lint}", "ERROR")
            log("The config file is likely corrupted. Please fix it manually or restore from a known good backup.", "INFO")
            # Don't restore our backup here, original file wasn't touched by us yet
            return "error"

        # Convert to XML format (this command is idempotent if already XML)
        convert_cmd = ['plutil', '-convert', 'xml1', str(config_path)]
        ret_code_convert, _, stderr_convert = run_command(convert_cmd, check=False)
        if ret_code_convert != 0:
            spinner.stop(f"{COLORS['RED']}✗ Failed to convert plist to XML format.{COLORS['RESET']}")
            log(f"Error during 'plutil -convert xml1': {stderr_convert}", "ERROR")
            log("Attempting to restore original file from backup...", "INFO")
            try:
                # Use move to restore the original state saved in backup
                shutil.move(str(backup_path), config_path)
                log("Original file restored from backup.", "SUCCESS")
            except Exception as restore_e:
                log(f"CRITICAL: Failed to restore from backup '{backup_path}': {restore_e}", "ERROR")
                log(f"Your original file might be at '{backup_path}'. Manual recovery needed.", "ERROR")
            return "error"

        spinner.stop(f"{COLORS['GREEN']}✓ Config checked and converted to XML format.{COLORS['RESET']}")

    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Unexpected error during plist check/conversion: {e}{COLORS['RESET']}")
        log("Attempting to restore original file from backup...", "INFO")
        try:
            shutil.move(str(backup_path), config_path)
            log("Original file restored from backup.", "SUCCESS")
        except Exception as restore_e:
            log(f"CRITICAL: Failed to restore from backup '{backup_path}': {restore_e}", "ERROR")
        return "error"


    # --- 3. Read Plist (Now likely XML) ---
    spinner.start("Reading config.plist...")
    config_data: Optional[Dict[str, Any]] = None
    try:
        # DEBUG: Log file size before reading
        try:
            file_size = config_path.stat().st_size
            log(f"  File size after conversion: {file_size} bytes", "DEBUG")
        except Exception as stat_e:
            log(f"  Could not get file size: {stat_e}", "DEBUG")

        with config_path.open('rb') as f:
            config_data = plistlib.load(f)
        spinner.stop(f"{COLORS['GREEN']}✓ Config file loaded successfully.{COLORS['RESET']}")

    except FileNotFoundError: # Should not happen after checks, but safety
        spinner.stop(f"{COLORS['RED']}✗ Error: Config file disappeared after conversion! {config_path}.{COLORS['RESET']}")
        log("This is unexpected. Check filesystem and permissions.", "ERROR")
        log(f"Backup (pre-conversion state) available at: {backup_path}", "INFO")
        return "error"
    except InvalidFileException as e:
        spinner.stop(f"{COLORS['RED']}✗ Error: Invalid plist format even after plutil conversion.{COLORS['RESET']}")
        log(f"Plist parsing error: {e}", "ERROR")
        log("This suggests a deeper issue with the file structure or an uncommon encoding problem.", "INFO")
        log("Please manually inspect the file. Use 'plutil -lint' to check.", "INFO")
        log(f"Backup (pre-conversion state) available at: {backup_path}", "INFO")
        # Restore the backup created *before* plutil conversion attempt
        try:
            shutil.move(str(backup_path), config_path)
            log("Original file (pre-conversion state) restored from backup.", "SUCCESS")
        except Exception as restore_e:
             log(f"CRITICAL: Failed to restore pre-conversion state from backup '{backup_path}': {restore_e}", "ERROR")
        return "error"
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error reading config file: {e}{COLORS['RESET']}")
        log(f"Backup (pre-conversion state) available at: {backup_path}", "INFO")
        try:
            shutil.move(str(backup_path), config_path)
            log("Original file (pre-conversion state) restored from backup.", "SUCCESS")
        except Exception as restore_e:
             log(f"CRITICAL: Failed to restore pre-conversion state from backup '{backup_path}': {restore_e}", "ERROR")
        return "error"

    if not config_data: # Should not happen if exceptions are caught
         spinner.stop(f"{COLORS['RED']}✗ Failed to load config data unexpectedly after read attempt.{COLORS['RESET']}")
         # Attempt restore before exiting
         try:
            shutil.move(str(backup_path), config_path)
            log("Original file (pre-conversion state) restored from backup.", "SUCCESS")
         except Exception as restore_e:
             log(f"CRITICAL: Failed to restore pre-conversion state from backup '{backup_path}': {restore_e}", "ERROR")
         return "error"

    # --- 4. Check if Patches Already Exist (using the loaded data) ---
    if check_patches_exist(config_data):
        log("Patches already present in the configuration.", "SUCCESS", timestamp=False)
        # Clean up backup if no changes are made AFTER conversion
        try:
            backup_path.unlink(missing_ok=True)
            log(f"Removed unused backup: {backup_path.name}", "DEBUG")
        except OSError as e:
            log(f"Could not remove unused backup {backup_path}: {e}", "WARNING")
        return "already_exists"

    # --- 5. Prepare and Add Patches ---
    spinner.start("Preparing and adding patches...")
    try:
        # Ensure Kernel section exists
        if 'Kernel' not in config_data:
            config_data['Kernel'] = {}
        if not isinstance(config_data['Kernel'], dict):
             log("Error: 'Kernel' key exists but is not a dictionary.", "ERROR")
             spinner.stop(f"{COLORS['RED']}✗ Invalid config structure ('Kernel' not a dict).{COLORS['RESET']}")
             shutil.move(str(backup_path), config_path) # Restore pre-conversion state
             return "error"

        # Ensure Kernel -> Patch section exists and is a list
        if 'Patch' not in config_data['Kernel']:
            config_data['Kernel']['Patch'] = []
        if not isinstance(config_data['Kernel']['Patch'], list):
            log("Warning: 'Kernel -> Patch' key exists but is not a list. Replacing with list.", "WARNING")
            config_data['Kernel']['Patch'] = [] # Replace invalid type with list

        # Define patches
        patch1 = _create_patch_dict(
            comment=PATCH_COMMENT_1,
            find_b64='aGliZXJuYXRlaGlkcmVhZHkAaGliZXJuYXRlY291bnQA',
            replace_b64='aGliZXJuYXRlaGlkcmVhZHkAaHZfdm1tX3ByZXNlbnQA',
            min_kernel='20.4.0'
        )
        patch2 = _create_patch_dict(
            comment=PATCH_COMMENT_2,
            find_b64='Ym9vdCBzZXNzaW9uIFVVSUQAaHZfdm1tX3ByZXNlbnQA',
            replace_b64='Ym9vdCBzZXNzaW9uIFVVSUQAaGliZXJuYXRlY291bnQA',
            min_kernel='22.0.0'
        )

        # Add patches (avoid adding duplicates if check_patches_exist logic changes)
        current_comments = {p.get('Comment') for p in config_data['Kernel']['Patch'] if isinstance(p, dict)}
        if patch1['Comment'] not in current_comments:
             config_data['Kernel']['Patch'].append(patch1)
             log("Added Patch 1", "DEBUG")
        if patch2['Comment'] not in current_comments:
             config_data['Kernel']['Patch'].append(patch2)
             log("Added Patch 2", "DEBUG")

        spinner.stop(f"{COLORS['GREEN']}✓ Patches prepared and added to config data.{COLORS['RESET']}")

    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error preparing patches: {e}{COLORS['RESET']}")
        log(f"Error details: {e}", "DEBUG")
        shutil.move(str(backup_path), config_path) # Restore pre-conversion state
        return "error"

    # --- 6. Write Updated Plist (Safely) ---
    spinner.start("Validating and writing updated config.plist...")
    temp_path = None # Define outside try block for cleanup
    try:
        # Write to a temporary file first in the same directory
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, dir=config_path.parent,
                                         prefix=config_path.name + '.tmp_') as tmp_file:
            temp_path = Path(tmp_file.name)
            log(f" Writing patched data to temporary file: {temp_path}", "DEBUG")
            plistlib.dump(config_data, tmp_file)

        # Validate the temporary file by trying to load it back using plistlib
        log(f"  Validating temporary file (plistlib): {temp_path}", "DEBUG")
        with temp_path.open('rb') as f_validate:
            plistlib.load(f_validate) # Throws exception if invalid

        # Additionally validate using plutil for extra safety
        log(f"  Validating temporary file (plutil): {temp_path}", "DEBUG")
        lint_cmd_tmp = ['plutil', '-lint', str(temp_path)]
        ret_code_lint_tmp, _, stderr_lint_tmp = run_command(lint_cmd_tmp, check=False)
        if ret_code_lint_tmp != 0:
            raise InvalidFileException(f"plutil validation failed for temporary file: {stderr_lint_tmp}")


        # If validation passes, replace the original file atomically
        log(f"  Validation successful. Replacing original file.", "DEBUG")
        # os.replace might fail across filesystem boundaries if /tmp is different
        # Using shutil.move is generally safer for this case
        shutil.move(str(temp_path), config_path)
        temp_path = None # Prevent deletion in finally if move succeeded

        spinner.stop(f"{COLORS['GREEN']}✓ Successfully updated and saved {config_path}{COLORS['RESET']}")
        # Backup is now outdated, remove it
        try:
            backup_path.unlink(missing_ok=True)
            log(f"Removed successful backup: {backup_path.name}", "DEBUG")
        except OSError as e:
            log(f"Could not remove backup file {backup_path}: {e}", "WARNING")
        return "success"

    except InvalidFileException as e:
         spinner.stop(f"{COLORS['RED']}✗ Validation failed: Written plist is invalid.{COLORS['RESET']}")
         log(f"Error during validation: {e}", "ERROR")
         log("Restoring original file (pre-patch state) from backup...", "INFO")
         shutil.move(str(backup_path), config_path) # Restore pre-conversion state
         return "error"
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error writing or validating updated config file: {e}{COLORS['RESET']}")
        log(f"Error details: {e}", "DEBUG")
        log("Restoring original file (pre-patch state) from backup...", "INFO")
        shutil.move(str(backup_path), config_path) # Restore pre-conversion state
        return "error"
    finally:
         # Clean up temp file if it still exists (i.e., move failed or validation failed)
         if temp_path and temp_path.exists():
             log(f"Cleaning up temporary file: {temp_path}", "DEBUG")
             temp_path.unlink(missing_ok=True)


def restart_system(spinner: Spinner) -> bool:
    """Initiates a system restart with a countdown."""
    log("Initiating system restart...", "INFO")
    try:
        for i in range(5, 0, -1):
            spinner.start(f"System will restart in {i} seconds... (Press Ctrl+C to cancel)")
            time.sleep(1)
        spinner.stop(f"{COLORS['GREEN']}Restarting now...{COLORS['RESET']}")
        # Use sudo explicitly for shutdown
        ret_code, stdout, stderr = run_command(['sudo', 'shutdown', '-r', 'now'], check=False)
        if ret_code != 0:
             log(f"Error initiating restart: {stderr if stderr else stdout}", "ERROR")
             log("Please restart your system manually.", "WARNING")
             return False
        # If shutdown succeeds, script will terminate here.
        # Add a small delay to allow shutdown command to process
        time.sleep(5)
        log("Shutdown command sent. If system does not restart, please do so manually.", "WARNING")
        return True # Technically won't be reached if shutdown works immediately

    except KeyboardInterrupt:
        spinner.stop(f"{COLORS['YELLOW']}Restart cancelled by user.{COLORS['RESET']}")
        return False
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}An unexpected error occurred during restart sequence: {e}{COLORS['RESET']}")
        log("Please restart your system manually.", "WARNING")
        return False

# --- Main Execution ---

def main() -> None:
    """Main script execution logic."""
    global DEBUG_MODE # Allow modification

    parser = argparse.ArgumentParser(
        description="Apply Sonoma VM BT Enabler patches to OpenCore config.plist.",
        formatter_class=argparse.RawDescriptionHelpFormatter
        )
    parser.add_argument(
        "config_path", nargs="?", type=Path,
        help="Path to specific config.plist (optional). If omitted, script scans EFI partitions."
        )
    parser.add_argument(
        "--auto", "-y", "--yes", action="store_true",
        help="Auto-confirm applying patches without prompting."
        )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable colored output."
        )
    parser.add_argument(
        "--restart", "-r", action="store_true",
        help="Automatically restart after successful patching."
        )
    parser.add_argument(
        "--debug", "-d", "--verbose", action="store_true",
        help="Enable additional debug output."
        )
    parser.add_argument(
        "--mount-only", "-m", action="store_true",
        help="Only attempt to mount EFI partitions and exit (useful for debugging mount issues)."
        )

    args = parser.parse_args()

    # --- Initial Setup ---
    spinner = Spinner() # Initialize spinner

    if args.no_color or "NO_COLOR" in os.environ or not sys.stdout.isatty():
        for key in COLORS:
            COLORS[key] = ""

    DEBUG_MODE = args.debug
    if DEBUG_MODE:
        log("Debug mode enabled.", "DEBUG", timestamp=False)


    print_banner()

    # Check root privileges
    if os.geteuid() != 0:
        log("This script requires administrator privileges (sudo).", "ERROR")
        log(f"Please run with: {COLORS['CYAN']}sudo python3 {Path(sys.argv[0]).name} [options]{COLORS['RESET']}", "INFO")
        sys.exit(1)

    config_to_patch: Optional[Path] = None
    mounted_partitions: Dict[str, str] = {} # Track {partition_id: mount_point}
    exit_code = 0 # Default to success

    try: # Wrap main logic in try/finally for cleanup

        # --- Mount Only Mode ---
        if args.mount_only:
            log("Mount-Only Mode Activated", "TITLE")
            disk_info = get_disk_list(spinner)
            if not disk_info: sys.exit(1)
            efi_partitions = get_efi_partitions(disk_info)
            if not efi_partitions: sys.exit(1)

            mounted_count = 0
            for partition in efi_partitions:
                mount_point = mount_efi(partition, spinner)
                if mount_point:
                    mounted_partitions[partition] = mount_point
                    log(f"Partition {partition} mounted at {mount_point}", "SUCCESS")
                    log(f"-> To unmount later: diskutil unmount '{mount_point}'", "INFO")
                    mounted_count += 1
                # Error logged within mount_efi if it fails
            log("Mount-Only mode finished.", "HEADER")
            if mounted_count == 0:
                log("No EFI partitions could be mounted.", "WARNING")
            # Keep partitions mounted in this mode
            sys.exit(0)


        # --- Determine Config Path ---
        if args.config_path:
            # Resolve relative paths and check existence
            config_to_patch_arg = args.config_path.resolve()
            if config_to_patch_arg.is_file():
                log(f"Using provided config path: {config_to_patch_arg}", "HEADER")
                config_to_patch = config_to_patch_arg
            else:
                log(f"Error: Provided path is not a valid file: {args.config_path}", "ERROR")
                log(f"Resolved path: {config_to_patch_arg}", "DEBUG")
                sys.exit(1)
        else:
            # --- Automatic Scan Mode ---
            log("Scanning for EFI partitions and OpenCore config...", "TITLE")
            disk_info = get_disk_list(spinner)
            if not disk_info:
                sys.exit(1) # Error logged in get_disk_list

            efi_partitions = get_efi_partitions(disk_info)
            if not efi_partitions:
                log("Could not automatically find any EFI partitions.", "ERROR")
                log("Please ensure your EFI partition is identifiable or mount it manually.", "INFO")
                log(f"Then run again specifying the path: {COLORS['CYAN']}sudo python3 {Path(sys.argv[0]).name} /path/to/EFI/OC/config.plist{COLORS['RESET']}", "INFO")
                sys.exit(1)

            log(f"Scanning {len(efi_partitions)} EFI partition(s)...", "HEADER")
            found_config_path: Optional[Path] = None
            processed_partition: Optional[str] = None

            for i, partition_id in enumerate(efi_partitions):
                log(f"[{i+1}/{len(efi_partitions)}] Processing partition {partition_id}", "INFO")
                mount_point_str = mount_efi(partition_id, spinner)
                if not mount_point_str:
                    log(f"Skipping partition {partition_id} due to mount failure.", "WARNING")
                    continue # Try next partition

                mount_point = Path(mount_point_str)
                mounted_partitions[partition_id] = mount_point_str # Track for cleanup
                processed_partition = partition_id # Store the partition we are currently working on

                config_path = find_opencore_config(mount_point, spinner)
                if config_path:
                    found_config_path = config_path
                    break # Found it, stop scanning
                else:
                     # Config not found, unmount before trying next partition
                     log(f" No config found on {partition_id}. Unmounting...", "INFO")
                     unmount_partition(mount_point_str, spinner) # Use mount point path for unmount
                     del mounted_partitions[partition_id] # Remove from tracked list
                     processed_partition = None


            if found_config_path:
                config_to_patch = found_config_path
            else:
                log("No standard OpenCore config.plist found on any mounted EFI partition.", "ERROR")
                log("Ensure OpenCore is installed correctly (EFI/OC/config.plist).", "INFO")
                log(f"If your setup is non-standard, run again specifying the path: {COLORS['CYAN']}sudo python3 {Path(sys.argv[0]).name} /path/to/config.plist{COLORS['RESET']}", "INFO")
                exit_code = 1 # Indicate failure


        # --- Apply Patches ---
        if config_to_patch and exit_code == 0:
            patch_result: Literal["success", "already_exists", "error"] = "error" # Default

            # Confirmation step
            if not args.auto:
                if not request_confirmation(f"Apply Sonoma Bluetooth patches to {config_to_patch}?"):
                    log("Operation cancelled by user.", "WARNING")
                    exit_code = 0 # User cancelled, not an error
                    # Still need to unmount if auto-scan was used
                    config_to_patch = None # Prevent further processing
                else:
                    log(f"Proceeding with patching {config_to_patch}...", "INFO")
            else:
                 log(f"Auto-confirm enabled. Proceeding with patching {config_to_patch}...", "INFO")


            if config_to_patch: # Check if still set after potential cancellation
                patch_result = add_kernel_patches(config_to_patch, spinner)

                if patch_result == "success":
                    log("Patching process completed successfully!", "SUCCESS")
                    log("A system restart is required to apply the changes.", "INFO")
                    if args.restart:
                        log("Auto-restart enabled.", "INFO")
                        # Pass spinner to restart function
                        if not restart_system(spinner):
                             exit_code = 1 # Restart failed or was cancelled
                    elif not args.auto: # Ask only if interactive and patch was successful
                        if request_confirmation("Restart now?", default_yes=True):
                            if not restart_system(spinner):
                                exit_code = 1 # Restart failed or was cancelled

                elif patch_result == "already_exists":
                     log("Configuration file already contains the required patches.", "SUCCESS")
                     log("No changes were made. System restart is not required.", "INFO")

                else: # patch_result == "error"
                    log("Patching process failed. See errors above.", "ERROR")
                    log("Original config.plist should have been restored from backup (check backup file too).", "INFO")
                    exit_code = 1 # Indicate failure

    finally:
        # --- Cleanup ---
        if not args.mount_only and mounted_partitions:
            log("Cleaning up mounted partitions...", "HEADER")
            cleaned_up_count = 0
            # Unmount in reverse order? Might not matter much.
            for part_id, mp in list(mounted_partitions.items()): # Iterate over a copy
                log(f"Unmounting {mp} (from {part_id})...", "INFO")
                if unmount_partition(mp, spinner): # Unmount by path
                    cleaned_up_count += 1
                    # Keep track even if unmount fails, just log it
                else:
                     log(f"Failed to automatically unmount {mp}. Please unmount manually.", "WARNING")
                     if exit_code == 0: exit_code = 1 # Mark failure if cleanup fails

            if cleaned_up_count == len(mounted_partitions):
                log("All detected mount points cleaned up successfully.", "SUCCESS")
            else:
                 log(f"Successfully unmounted {cleaned_up_count} out of {len(mounted_partitions)} partition(s).", "WARNING")
        elif not args.mount_only:
             log("No partitions were mounted or needed cleanup.", "DEBUG")

        log("Script finished.", "INFO")
        sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Generic fallback catcher
        log(f"An unexpected critical error occurred: {e}", "ERROR")
        import traceback
        # Print stack trace regardless of debug mode for critical errors
        print("-" * 60)
        traceback.print_exc(file=sys.stdout)
        print("-" * 60)
        log("Please report this error if it persists.", "ERROR")
        sys.exit(1)
