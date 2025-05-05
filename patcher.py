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
            self._spinner_thread.join()
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
    level_colors = {
        "INFO": COLORS['BLUE'], "ERROR": COLORS['RED'], "SUCCESS": COLORS['GREEN'],
        "WARNING": COLORS['YELLOW'], "DEBUG": COLORS['MAGENTA'],
        "TITLE": COLORS['MAGENTA'] + COLORS['BOLD'], "HEADER": COLORS['CYAN'] + COLORS['BOLD'],
    }
    color = color_override if color_override else level_colors.get(level, COLORS['RESET'])
    time_str = f"[{datetime.now().strftime('%H:%M:%S')}] " if timestamp else ""
    level_str = f"[{level}] " if level not in ["TITLE", "HEADER"] else ""

    if level == "TITLE":
        print("\n" + "=" * 70)
        print(f"{color}{message.center(70)}{COLORS['RESET']}")
        print("=" * 70)
    elif level == "HEADER":
        print(f"\n{color}=== {message} ==={COLORS['RESET']}")
    else:
        print(f"{color}{time_str}{level_str}{message}{COLORS['RESET']}")


def run_command(command: List[str], check: bool = True, capture_output: bool = True) -> Tuple[int, str, str]:
    """Runs a shell command safely and returns status, stdout, stderr."""
    try:
        process = subprocess.run(
            command,
            check=check,
            capture_output=capture_output,
            text=True,
            encoding='utf-8',
            errors='ignore' # Ignore potential decoding errors in output
        )
        return process.returncode, process.stdout.strip(), process.stderr.strip()
    except FileNotFoundError:
        log(f"Error: Command not found: {command[0]}", "ERROR")
        return -1, "", f"Command not found: {command[0]}"
    except subprocess.CalledProcessError as e:
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
    ║      VM Bluetooth Enabler Patch Tool v2.0 (Refactored) ║
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
    return stdout


def get_efi_partitions(disk_info: str) -> List[str]:
    """Extracts EFI partition identifiers (e.g., disk0s1) from diskutil output."""
    log("Analyzing disk information for EFI partitions...", "INFO", timestamp=False)
    efi_partitions = []
    current_disk = None
    # Regex to find partition identifiers like diskXsY
    disk_id_pattern = re.compile(r'(/dev/disk\d+)\s+\(')
    # Regex to find EFI partitions (matches TYPE and NAME)
    # Handles variations like 'EFI', 'EFI System Partition', 'Microsoft Basic Data' (sometimes used for EFI)
    # Also looks for the specific GUID type code EF00
    efi_partition_pattern = re.compile(r'\s+(\d+):\s+(?:Apple_APFS_ISC|EFI|Microsoft Basic Data)\s+(?:EFI|ESP|BOOTCAMP|BOOT)\s+.*', re.IGNORECASE)
    efi_guid_pattern = re.compile(r'\s+(\d+):\s+[A-Z0-9]{4}\s+\*\*\* NO NAME \*\*\*\s+\d+\.\d+\s+\w+\s+(disk\d+s\d+)') # For EF00 type


    for line in disk_info.splitlines():
        disk_match = disk_id_pattern.match(line)
        if disk_match:
            current_disk = disk_match.group(1)
            continue # Move to the next line after finding a disk identifier

        if not current_disk:
            continue # Skip lines until we identify a disk

        efi_match = efi_partition_pattern.search(line)
        efi_guid_match = efi_guid_pattern.search(line)

        partition_num = None
        partition_id = None

        if efi_match:
            partition_num = efi_match.group(1)
        elif efi_guid_match:
            # Sometimes EF00 partitions don't have names, grab the identifier directly
             partition_id = efi_guid_match.group(2) # e.g., disk0s1
             partition_num = partition_id.split('s')[-1] # Extract number for consistency if needed

        if partition_num:
            if not partition_id: # Construct if not directly grabbed
                partition_id = f"{current_disk}s{partition_num}"
            if partition_id not in efi_partitions:
                efi_partitions.append(partition_id)
                log(f"  Found potential EFI partition: {partition_id} ({line.strip()})", "DEBUG", timestamp=False)

    if efi_partitions:
        log(f"Found {len(efi_partitions)} potential EFI partition(s): {', '.join(efi_partitions)}", "SUCCESS", timestamp=False)
    else:
        log("No EFI partitions found using standard identifiers.", "WARNING", timestamp=False)
        log("If you know your EFI partition, you can mount it manually and provide the config.plist path.", "INFO", timestamp=False)

    return efi_partitions


def check_if_mounted(partition: str) -> Optional[str]:
    """Checks if a partition is mounted and returns its mount point."""
    log(f"  Checking mount status for {partition}...", "DEBUG", timestamp=False)
    ret_code, stdout, stderr = run_command(['diskutil', 'info', partition], check=False)
    if ret_code == 0:
        mount_point_match = re.search(r"Mount Point:\s+(.*)", stdout)
        if mount_point_match:
            mount_point = mount_point_match.group(1).strip()
            if mount_point and mount_point != "Not Mounted":
                 log(f"  Partition {partition} is already mounted at {mount_point}", "DEBUG", timestamp=False)
                 return mount_point
    # Don't log error here, as failure might just mean it's not mounted
    return None


def mount_efi(partition: str, spinner: Spinner) -> Optional[str]:
    """Mounts the specified EFI partition."""
    spinner.start(f"Attempting to mount {partition}...")

    mount_point = check_if_mounted(partition)
    if mount_point:
        spinner.stop(f"{COLORS['GREEN']}✓ Partition {partition} already mounted at {mount_point}{COLORS['RESET']}")
        return mount_point

    # Standard mount attempt
    ret_code, stdout, stderr = run_command(['diskutil', 'mount', partition], check=False)

    if ret_code == 0:
        mount_point_match = re.search(r"mounted at\s+(.*)", stdout, re.IGNORECASE)
        if mount_point_match:
            mount_point = mount_point_match.group(1).strip()
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at {mount_point}{COLORS['RESET']}")
            return mount_point
        else:
            # Mounted but couldn't parse mount point? Check again.
            mount_point = check_if_mounted(partition)
            if mount_point:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at {mount_point} (verified){COLORS['RESET']}")
                return mount_point
            else:
                 spinner.stop(f"{COLORS['YELLOW']}⚠ Mounted {partition} but failed to determine mount point.{COLORS['RESET']}")
                 log(f"diskutil output: {stdout}", "DEBUG")
                 return None # Uncertain state

    # Mount failed
    spinner.stop(f"{COLORS['RED']}✗ Failed to mount {partition} using 'diskutil mount'.{COLORS['RESET']}")
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
    # Determine if we have a partition ID or a mount point path
    is_path = "/" in partition_or_mount_point

    target_desc = f"mount point {partition_or_mount_point}" if is_path else f"partition {partition_or_mount_point}"
    spinner.start(f"Unmounting {target_desc}...")

    # Try standard unmount first
    ret_code, stdout, stderr = run_command(['diskutil', 'unmount', partition_or_mount_point], check=False)
    if ret_code == 0:
        spinner.stop(f"{COLORS['GREEN']}✓ Successfully unmounted {target_desc}{COLORS['RESET']}")
        return True

    # If standard unmount failed, maybe it's already unmounted? Or try force
    log(f"Standard unmount failed for {target_desc}. Trying force unmount.", "WARNING")
    log(f"  Reason: {stderr if stderr else stdout}", "DEBUG")

    # Check if actually mounted before forcing (avoid errors if already gone)
    if is_path:
        mounted_partition = None # Need to find partition from mount point if forced unmount needed
        # This check is complex, skip for simplicity now. Assume force might work.
        pass
    elif not check_if_mounted(partition_or_mount_point):
         spinner.stop(f"{COLORS['YELLOW']}⚠ {target_desc} was already unmounted.{COLORS['RESET']}")
         return True # Effectively unmounted

    # Try force unmount (requires sudo)
    ret_code_force, stdout_force, stderr_force = run_command(
        ['sudo', 'diskutil', 'unmount', 'force', partition_or_mount_point],
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

    if expected_path.is_file():
        spinner.stop(f"{COLORS['GREEN']}✓ Found OpenCore config.plist at: {expected_path}{COLORS['RESET']}")
        return expected_path
    else:
        spinner.stop(f"{COLORS['YELLOW']}⚠ Standard OpenCore config.plist not found at {expected_path}{COLORS['RESET']}")
        log(f"Looked for: {expected_path}", "DEBUG")
        # Optionally, list contents for debugging
        try:
             oc_dir = mount_point / "EFI" / "OC"
             if oc_dir.is_dir():
                 log(f"Contents of {oc_dir}:", "DEBUG")
                 for item in oc_dir.iterdir():
                     log(f"  - {item.name}", "DEBUG", timestamp=False)
             elif (mount_point / "EFI").is_dir():
                 log(f"Contents of {mount_point / 'EFI'}:", "DEBUG")
                 for item in (mount_point / "EFI").iterdir():
                      log(f"  - {item.name}", "DEBUG", timestamp=False)

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

        for patch in kernel_patches:
            if isinstance(patch, dict) and patch.get('Comment') in [PATCH_COMMENT_1, PATCH_COMMENT_2]:
                log(f"  Found existing patch: {patch.get('Comment')}", "DEBUG", timestamp=False)
                return True
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
    """Adds the Sonoma VM BT Enabler kernel patches to the config.plist."""
    log(f"Starting patch process for: {config_path}", "HEADER")
    backup_path = config_path.with_suffix(config_path.suffix + '.backup')

    # 1. Create Backup
    spinner.start(f"Creating backup: {backup_path}")
    try:
        shutil.copy2(config_path, backup_path)
        spinner.stop(f"{COLORS['GREEN']}✓ Backup created successfully.{COLORS['RESET']}")
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error creating backup: {e}{COLORS['RESET']}")
        return "error"

    # 2. Read Plist
    spinner.start("Reading config.plist...")
    config_data: Optional[Dict[str, Any]] = None
    try:
        with config_path.open('rb') as f:
            config_data = plistlib.load(f)
        spinner.stop(f"{COLORS['GREEN']}✓ Config file loaded successfully.{COLORS['RESET']}")
    except FileNotFoundError:
        spinner.stop(f"{COLORS['RED']}✗ Error: Config file not found at {config_path}.{COLORS['RESET']}")
        return "error"
    except plistlib.InvalidFileException as e:
        spinner.stop(f"{COLORS['RED']}✗ Error: Invalid plist format in {config_path}.{COLORS['RESET']}")
        log(f"Plist parsing error: {e}", "ERROR")
        log("The file might be corrupted or not a valid XML plist.", "INFO")
        return "error"
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error reading config file: {e}{COLORS['RESET']}")
        return "error"

    if not config_data: # Should not happen if exceptions are caught, but check anyway
         spinner.stop(f"{COLORS['RED']}✗ Failed to load config data unexpectedly.{COLORS['RESET']}")
         return "error"

    # 3. Check if Patches Already Exist
    if check_patches_exist(config_data):
        log("Patches already present in the configuration.", "SUCCESS", timestamp=False)
        # Clean up backup if no changes are made
        try:
            backup_path.unlink(missing_ok=True)
            log(f"Removed unused backup: {backup_path}", "DEBUG")
        except OSError as e:
            log(f"Could not remove unused backup {backup_path}: {e}", "WARNING")
        return "already_exists"

    # 4. Prepare and Add Patches
    spinner.start("Preparing and adding patches...")
    try:
        # Ensure Kernel section exists
        if 'Kernel' not in config_data:
            config_data['Kernel'] = {}
        if not isinstance(config_data['Kernel'], dict):
             log("Error: 'Kernel' key exists but is not a dictionary.", "ERROR")
             spinner.stop(f"{COLORS['RED']}✗ Invalid config structure ('Kernel' not a dict).{COLORS['RESET']}")
             # Attempt to restore backup before exiting
             shutil.copy2(backup_path, config_path)
             return "error"


        # Ensure Kernel -> Patch section exists and is a list
        if 'Patch' not in config_data['Kernel']:
            config_data['Kernel']['Patch'] = []
        if not isinstance(config_data['Kernel']['Patch'], list):
            log("Error: 'Kernel -> Patch' key exists but is not a list.", "ERROR")
            log("Attempting to fix by replacing it with an empty list.", "WARNING")
            config_data['Kernel']['Patch'] = []
            # Consider making this behavior optional or erroring out

        # Define patches
        patch1 = _create_patch_dict(
            comment=PATCH_COMMENT_1,
            find_b64='aGliZXJuYXRlaGlkcmVhZHkAaGliZXJuYXRlY291bnQA', # hibernatehidready hibernatecount
            replace_b64='aGliZXJuYXRlaGlkcmVhZHkAaHZfdm1tX3ByZXNlbnQA', # hibernatehidready hv_vmm_present
            min_kernel='20.4.0' # Big Sur 11.3+
        )
        patch2 = _create_patch_dict(
            comment=PATCH_COMMENT_2,
            find_b64='Ym9vdCBzZXNzaW9uIFVVSUQAaHZfdm1tX3ByZXNlbnQA', # boot session UUID hv_vmm_present
            replace_b64='Ym9vdCBzZXNzaW9uIFVVSUQAaGliZXJuYXRlY291bnQA', # boot session UUID hibernatecount
            min_kernel='22.0.0' # Ventura+
        )

        # Add patches
        config_data['Kernel']['Patch'].append(patch1)
        config_data['Kernel']['Patch'].append(patch2)

        spinner.stop(f"{COLORS['GREEN']}✓ Patches prepared and added to config data.{COLORS['RESET']}")

    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error preparing patches: {e}{COLORS['RESET']}")
        # Attempt to restore backup
        shutil.copy2(backup_path, config_path)
        return "error"

    # 5. Write Updated Plist (Safely)
    spinner.start("Validating and writing updated config.plist...")
    try:
        # Write to a temporary file first
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, dir=config_path.parent) as tmp_file:
            temp_path = Path(tmp_file.name)
            plistlib.dump(config_data, tmp_file)

        # Validate the temporary file
        log(f"  Validating temporary file: {temp_path}", "DEBUG")
        with temp_path.open('rb') as f_validate:
            plistlib.load(f_validate) # Throws exception if invalid

        # If validation passes, replace the original file atomically
        log(f"  Validation successful. Replacing original file.", "DEBUG")
        os.replace(temp_path, config_path)

        spinner.stop(f"{COLORS['GREEN']}✓ Successfully updated and saved {config_path}{COLORS['RESET']}")
        return "success"

    except plistlib.InvalidFileException as e:
         spinner.stop(f"{COLORS['RED']}✗ Validation failed: Temporary plist is invalid.{COLORS['RESET']}")
         log(f"Error during validation: {e}", "ERROR")
         # Clean up temp file
         temp_path.unlink(missing_ok=True)
         # Restore backup
         log("Restoring original file from backup...", "INFO")
         shutil.copy2(backup_path, config_path)
         return "error"
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error writing or validating updated config file: {e}{COLORS['RESET']}")
        # Clean up temp file if it exists
        if 'temp_path' in locals() and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        # Restore backup
        log("Restoring original file from backup...", "INFO")
        shutil.copy2(backup_path, config_path)
        return "error"

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
        return True # Technically won't be reached if shutdown works
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
        # Monkey patch log to show DEBUG messages
        original_log = log
        def debug_log(message: str, level: str = "INFO", timestamp: bool = True, color_override: Optional[str] = None) -> None:
            if level != "DEBUG":
                 original_log(message, level, timestamp, color_override)
            else:
                 # Always print debug messages if flag is set
                 original_log(f"DEBUG: {message}", "DEBUG", timestamp, color_override)
        globals()['log'] = debug_log # Replace global log function
        log("Debug mode enabled.", "DEBUG")


    print_banner()

    # Check root privileges
    if os.geteuid() != 0:
        log("This script requires administrator privileges (sudo).", "ERROR")
        log(f"Please run with: {COLORS['CYAN']}sudo python3 {sys.argv[0]} [options]{COLORS['RESET']}", "INFO")
        sys.exit(1)

    config_to_patch: Optional[Path] = None
    mounted_partitions: Dict[str, str] = {} # Track {partition: mount_point}

    # --- Mount Only Mode ---
    if args.mount_only:
        log("Mount-Only Mode Activated", "TITLE")
        disk_info = get_disk_list(spinner)
        if not disk_info: sys.exit(1)
        efi_partitions = get_efi_partitions(disk_info)
        if not efi_partitions: sys.exit(1)

        for partition in efi_partitions:
            mount_point = mount_efi(partition, spinner)
            if mount_point:
                mounted_partitions[partition] = mount_point
                log(f"Partition {partition} mounted at {mount_point}", "SUCCESS")
                log(f"-> To unmount later: diskutil unmount {mount_point}", "INFO")
            # Error logged within mount_efi if it fails
        log("Mount-Only mode finished.", "HEADER")
        if not mounted_partitions:
            log("No EFI partitions could be mounted.", "WARNING")
        sys.exit(0)


    # --- Determine Config Path ---
    if args.config_path:
        if args.config_path.is_file():
            log(f"Using provided config path: {args.config_path}", "HEADER")
            config_to_patch = args.config_path
        else:
            log(f"Error: Provided path is not a valid file: {args.config_path}", "ERROR")
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
            log(f"Then run again specifying the path: {COLORS['CYAN']}sudo python3 {sys.argv[0]} /path/to/EFI/OC/config.plist{COLORS['RESET']}", "INFO")
            sys.exit(1)

        log(f"Scanning {len(efi_partitions)} EFI partition(s)...", "HEADER")
        found_config_path: Optional[Path] = None
        processed_partition: Optional[str] = None

        for i, partition in enumerate(efi_partitions):
            log(f"[{i+1}/{len(efi_partitions)}] Processing partition {partition}", "INFO")
            mount_point_str = mount_efi(partition, spinner)
            if not mount_point_str:
                log(f"Skipping partition {partition} due to mount failure.", "WARNING")
                continue # Try next partition

            mount_point = Path(mount_point_str)
            mounted_partitions[partition] = mount_point_str # Track for cleanup
            processed_partition = partition # Store the partition we are currently working on

            config_path = find_opencore_config(mount_point, spinner)
            if config_path:
                found_config_path = config_path
                break # Found it, stop scanning
            else:
                 # Config not found, unmount before trying next partition
                 unmount_partition(mount_point_str, spinner)
                 del mounted_partitions[partition] # Remove from tracked list
                 processed_partition = None


        if found_config_path:
            config_to_patch = found_config_path
        else:
            log("No standard OpenCore config.plist found on any mounted EFI partition.", "ERROR")
            log("Ensure OpenCore is installed correctly (EFI/OC/config.plist).", "INFO")
            log(f"If your setup is non-standard, run again specifying the path: {COLORS['CYAN']}sudo python3 {sys.argv[0]} /path/to/config.plist{COLORS['RESET']}", "INFO")
            # Attempt cleanup of any remaining mounted partitions (shouldn't happen here, but safety first)
            for part, mp in mounted_partitions.items():
                 log(f"Cleaning up mount point {mp} for {part}", "DEBUG")
                 unmount_partition(mp, spinner)
            sys.exit(1)


    # --- Apply Patches ---
    patch_result: Literal["success", "already_exists", "error"] = "error" # Default
    try:
        if not config_to_patch:
             log("Internal Error: config_to_patch is not set.", "ERROR")
             sys.exit(1)

        # Confirmation step
        if not args.auto:
            if not request_confirmation(f"Apply Sonoma Bluetooth patches to {config_to_patch}?"):
                log("Operation cancelled by user.", "WARNING")
                sys.exit(0) # Exit cleanly

        log(f"Proceeding with patching {config_to_patch}...", "INFO")
        patch_result = add_kernel_patches(config_to_patch, spinner)

        if patch_result == "success":
            log("Patching process completed successfully!", "SUCCESS")
            log("A system restart is required to apply the changes.", "INFO")
            if args.restart or (not args.auto and request_confirmation("Restart now?", default_yes=True)):
                 restart_system(spinner) # Attempt restart

        elif patch_result == "already_exists":
             log("Configuration file already contains the required patches.", "SUCCESS")
             log("No changes were made. System restart is not required.", "INFO")

        else: # patch_result == "error"
            log("Patching process failed. See errors above.", "ERROR")
            log("Original config.plist should have been restored from backup.", "INFO")
            sys.exit(1) # Exit with error status

    finally:
        # --- Cleanup ---
        log("Cleaning up mounted partitions...", "HEADER")
        cleaned_up_count = 0
        for part, mp in list(mounted_partitions.items()): # Iterate over a copy
            log(f"Unmounting {mp} (from {part})...", "INFO")
            if unmount_partition(mp, spinner):
                cleaned_up_count += 1
                del mounted_partitions[part] # Remove if successful
            else:
                 log(f"Failed to automatically unmount {mp}. Please unmount manually.", "WARNING")

        if cleaned_up_count > 0:
            log(f"Successfully unmounted {cleaned_up_count} partition(s).", "SUCCESS")
        if mounted_partitions:
             log(f"Could not automatically unmount {len(mounted_partitions)} partition(s). Manual unmount required.", "WARNING")
        else:
             log("All detected mount points cleaned up.", "INFO")

if __name__ == "__main__":
    DEBUG_MODE = False # Global debug flag, set by args later
    try:
        main()
    except Exception as e:
        # Generic fallback catcher
        log(f"An unexpected critical error occurred: {e}", "ERROR")
        import traceback
        log(traceback.format_exc(), "DEBUG") # Print stack trace if debug is on (or just log it)
        sys.exit(1)
