#!/usr/bin/env python3
"""
Sonoma VM Bluetooth Enabler Patch Tool.

This script patches OpenCore config.plist files to enable Bluetooth functionality
in macOS Sonoma virtual machines. It identifies EFI partitions, finds OpenCore
configurations, and applies the necessary kernel patches safely.

Usage:
  sudo python3 sonoma_bt_patcher.py [path/to/config.plist] [options]

Options:
  --auto, -a     Automatically confirm patches without prompting
  --no-color     Disable colored output
  --restart, -r  Automatically restart after patching
  --mount-only   Only mount EFI partitions without patching
  --debug, -d    Enable additional debug output
"""

import argparse
import base64
import fcntl
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union


# ANSI color codes
COLORS = {
    'RESET': '\033[0m',
    'BLACK': '\033[30m',
    'RED': '\033[31m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'BLUE': '\033[34m',
    'MAGENTA': '\033[35m',
    'CYAN': '\033[36m',
    'WHITE': '\033[37m',
    'BOLD': '\033[1m',
    'UNDERLINE': '\033[4m',
    'BG_GREEN': '\033[42m',
    'BG_BLUE': '\033[44m'
}


class FileLock:
    """A file locking mechanism to ensure atomic file operations."""

    def __init__(self, file_path: str, timeout: int = 10):
        """Initialize the file lock.
        
        Args:
            file_path: Path to the file to lock
            timeout: Maximum time to wait for lock acquisition in seconds
        """
        self.file_path = file_path
        self.lockfile = f"{file_path}.lock"
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        """Acquire the lock when entering context manager."""
        self.fd = open(self.lockfile, 'w+')
        start_time = time.time()
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except IOError as e:
                if e.errno != fcntl.errno.EAGAIN:
                    raise
                elif time.time() - start_time >= self.timeout:
                    raise TimeoutError(
                        f"Could not acquire lock on {self.lockfile} within {self.timeout} seconds")
                time.sleep(0.1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Release the lock when exiting context manager."""
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()
            try:
                os.remove(self.lockfile)
            except OSError:
                pass


class Spinner:
    """Progress spinner for command-line operations."""

    def __init__(self, message: str = "Processing", delay: float = 0.1):
        """Initialize the spinner.
        
        Args:
            message: The message to display next to the spinner
            delay: Time between spinner animation frames in seconds
        """
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.delay = delay
        self.message = message
        self.running = False
        self.spinner_thread = None

    def spin(self):
        """Run the spinner animation in a loop."""
        i = 0
        while self.running:
            sys.stdout.write(f"\r{COLORS['CYAN']}{self.spinner_chars[i]} "
                             f"{self.message}{COLORS['RESET']} ")
            sys.stdout.flush()
            time.sleep(self.delay)
            i = (i + 1) % len(self.spinner_chars)

    def start(self, message: Optional[str] = None):
        """Start the spinner.
        
        Args:
            message: Optional new message to display
        """
        if message:
            self.message = message
        self.running = True
        self.spinner_thread = threading.Thread(target=self.spin)
        self.spinner_thread.daemon = True
        self.spinner_thread.start()

    def stop(self, message: Optional[str] = None):
        """Stop the spinner.
        
        Args:
            message: Optional message to display after stopping
        """
        self.running = False
        if self.spinner_thread:
            self.spinner_thread.join()
        # Clear the spinner line
        sys.stdout.write('\r' + ' ' * (len(self.message) + 10) + '\r')
        if message:
            print(message)


def progress_bar(iteration: int, total: int, prefix: str = '', 
                 suffix: str = '', length: int = 50, 
                 fill: str = '█', empty: str = '░'):
    """Display a progress bar.
    
    Args:
        iteration: Current iteration
        total: Total iterations
        prefix: Prefix string
        suffix: Suffix string
        length: Character length of bar
        fill: Bar fill character
        empty: Bar empty character
    """
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + empty * (length - filled_length)
    bar_colored = f"{COLORS['GREEN']}{bar}{COLORS['RESET']}"
    sys.stdout.write(f'\r{prefix} |{bar_colored}| {percent:.1f}% {suffix}')
    sys.stdout.flush()
    if iteration == total:
        sys.stdout.write('\n')


def log(message: str, level: str = "INFO", timestamp: bool = True):
    """Log a message with color formatting.
    
    Args:
        message: The message to log
        level: Log level (INFO, ERROR, SUCCESS, WARNING, TITLE, HEADER)
        timestamp: Whether to include a timestamp
    """
    level_colors = {
        "INFO": COLORS['BLUE'],
        "ERROR": COLORS['RED'],
        "SUCCESS": COLORS['GREEN'],
        "WARNING": COLORS['YELLOW'],
        "TITLE": COLORS['MAGENTA'] + COLORS['BOLD'],
        "HEADER": COLORS['CYAN'] + COLORS['BOLD'],
    }
    
    color = level_colors.get(level, COLORS['RESET'])
    time_str = f"[{datetime.now().strftime('%H:%M:%S')}] " if timestamp else ""
    level_str = f"[{level}] " if level not in ["TITLE", "HEADER"] else ""
    
    if level == "TITLE":
        print("\n" + "="*70)
        print(f"{color}{message.center(70)}{COLORS['RESET']}")
        print("="*70)
    elif level == "HEADER":
        print(f"\n{color}=== {message} ==={COLORS['RESET']}")
    else:
        print(f"{color}{time_str}{level_str}{message}{COLORS['RESET']}")


def print_banner():
    """Display the script banner."""
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
    ║   VM Bluetooth Enabler Patch Tool v1.5                ║
    ║   For MacOS Sonoma OpenCore                           ║
    ║   (Fixed version)                                     ║
    ║                                                        ║
    ╚════════════════════════════════════════════════════════╝
    """
    print(f"{COLORS['CYAN']}{banner}{COLORS['RESET']}")


def restart_system() -> bool:
    """Restart the system.
    
    Returns:
        bool: True if restart initiated successfully, False otherwise
    """
    log("Initiating system restart...", "INFO")
    spinner = Spinner("Preparing to restart")
    spinner.start()
    
    # Countdown animation
    for i in range(5, 0, -1):
        spinner.stop(f"{COLORS['YELLOW']}System will restart in {i} seconds... "
                     f"Press Ctrl+C to cancel{COLORS['RESET']}")
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("")  # Add a newline after the ^C
            log("Restart cancelled by user.", "WARNING")
            return False
    
    log("Restarting now...", "INFO")
    try:
        subprocess.run(['shutdown', '-r', 'now'], check=True)
        return True
    except Exception as e:
        log(f"Error restarting system: {e}", "ERROR")
        log("Please restart your system manually to apply changes.", "WARNING")
        return False


def get_disk_list() -> str:
    """Get a list of all disks in the system.
    
    Returns:
        str: Output from diskutil list command
    """
    spinner = Spinner("Scanning disk list")
    spinner.start()
    try:
        result = subprocess.run(['diskutil', 'list'], 
                             capture_output=True, text=True, check=True)
        spinner.stop()
        return result.stdout
    except Exception as e:
        spinner.stop(f"Error getting disk list: {e}")
        return ""


def get_efi_partitions(disk_info: str) -> List[str]:
    """Extract EFI partition information from diskutil output.
    
    Args:
        disk_info: Output from diskutil list command
        
    Returns:
        List of EFI partition identifiers
    """
    log("Analyzing disk information for EFI partitions...", "INFO")
    efi_partitions = []
    disk_lines = disk_info.split('\n')
    current_disk = None
    
    for line in disk_lines:
        # Track which disk we're currently examining
        if line.startswith("/dev/"):
            current_disk = line.split()[0]
        
        # Look for EFI partitions - multiple ways to identify them
        if (("EFI" in line or "EF00" in line or 
             "C12A7328-F81F-11D2-BA4B-00A0C93EC93B" in line) and current_disk):
            # Parse the partition number - handle multiple patterns
            match = re.search(r'\s+(\d+):\s+.*?(EFI|EF00|C12A7328-F81F-11D2-BA4B-00A0C93EC93B)', 
                             line)
            if match:
                partition_num = match.group(1)
                partition_id = f"{current_disk}s{partition_num}"
                efi_partitions.append(partition_id)
    
    if efi_partitions:
        log(f"Found {len(efi_partitions)} EFI partition(s): {', '.join(efi_partitions)}", 
           "SUCCESS")
    else:
        log("No EFI partitions found", "WARNING")
    
    return efi_partitions


def check_if_mounted(partition: str) -> Optional[str]:
    """Check if the partition is already mounted.
    
    Args:
        partition: Partition identifier (e.g., /dev/disk0s1)
        
    Returns:
        Mount point if mounted, None otherwise
    """
    try:
        result = subprocess.run(['diskutil', 'info', partition], 
                             capture_output=True, text=True, check=True)
        
        # If the partition is mounted, the output will contain "Mounted: Yes"
        if "Mounted: Yes" in result.stdout:
            # Extract the mount point
            match = re.search(r'Mount Point:\s+(.*)', result.stdout)
            if match:
                return match.group(1).strip()
        return None
    except Exception as e:
        log(f"Error checking mount status: {e}", "ERROR")
        return None


def check_system_constraints():
    """Check for system constraints that could prevent mounting."""
    # Check if SIP is enabled (which might restrict mounting)
    try:
        sip_result = subprocess.run(['csrutil', 'status'], 
                                 capture_output=True, text=True)
        
        if "enabled" in sip_result.stdout.lower():
            log("System Integrity Protection (SIP) is enabled, which might restrict "
               "mounting operations.", "WARNING")
            log("You may need to temporarily disable SIP to mount EFI partitions. "
               "See Apple support for details.", "INFO")
    except Exception:
        pass  # Ignore if csrutil command fails
    
    # Check macOS version
    try:
        os_version_result = subprocess.run(['sw_vers', '-productVersion'], 
                                        capture_output=True, text=True)
        
        version = os_version_result.stdout.strip()
        log(f"Running on macOS version: {version}", "INFO")
        
        if version.startswith(("14.", "13.")):  # Sonoma or Ventura
            log("Recent macOS versions have additional security measures for mounting "
               "partitions.", "INFO")
            log("Try using 'Disk Utility' GUI application to mount the EFI partition "
               "manually.", "INFO")
    except Exception:
        pass  # Ignore if sw_vers command fails


def mount_efi(partition: str) -> Optional[str]:
    """Mount an EFI partition and return the mount point.
    
    Args:
        partition: Partition identifier (e.g., /dev/disk0s1)
        
    Returns:
        Mount point if successful, None otherwise
    """
    spinner = Spinner(f"Mounting {partition}")
    spinner.start()
    
    # Create a global lock for mount operations
    if not hasattr(mount_efi, 'global_mount_lock'):
        mount_efi.global_mount_lock = threading.Lock()
    
    # First check if already mounted
    mount_point = check_if_mounted(partition)
    if mount_point:
        spinner.stop(f"{COLORS['GREEN']}✓ Partition {partition} is already mounted at "
                    f"{mount_point}{COLORS['RESET']}")
        return mount_point
    
    # Acquire global lock for the entire mount operation
    with mount_efi.global_mount_lock:
        # Check again after acquiring lock in case another thread mounted it
        mount_point = check_if_mounted(partition)
        if mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Partition {partition} was mounted by "
                        f"another process at {mount_point}{COLORS['RESET']}")
            return mount_point
        
        # Track mount attempts
        mounted = False
        mount_point = None
        errors = []
        
        # Method 1: Try standard mount
        try:
            # Add a small delay to prevent race conditions
            time.sleep(0.5)
            
            result = subprocess.run(['diskutil', 'mount', partition], 
                                capture_output=True, text=True)
            
            # Parse mount point from output
            if result.returncode == 0:
                match = re.search(r'mounted at (.*)', result.stdout)
                if match:
                    mount_point = match.group(1).strip()
                    # Verify the mount point exists
                    if os.path.exists(mount_point):
                        mounted = True
                    else:
                        errors.append(
                            f"Mount point {mount_point} does not exist after mount operation")
            else:
                errors.append(f"Standard mount: {result.stderr or result.stdout}")
        except Exception as e:
            errors.append(f"Standard mount exception: {str(e)}")
        
        # If standard mount succeeded, return the mount point
        if mounted and mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at "
                        f"{mount_point}{COLORS['RESET']}")
            return mount_point
        
        # Method 2: Try mounting by volume name
        if not mounted:
            try:
                # Create a temporary directory for mounting
                efi_mount_dir = '/Volumes/EFI'
                if not os.path.exists(efi_mount_dir):
                    os.makedirs(efi_mount_dir, exist_ok=True)
                
                # Add a small delay to prevent race conditions
                time.sleep(0.5)
                
                # Try to mount by volume name
                result = subprocess.run(['diskutil', 'mount', 'EFI'], 
                                    capture_output=True, text=True)
                
                if result.returncode == 0:
                    # Check if the correct partition was mounted
                    info_result = subprocess.run(['diskutil', 'info', '/Volumes/EFI'], 
                                            capture_output=True, text=True)
                    if partition in info_result.stdout:
                        mount_point = '/Volumes/EFI'
                        # Verify the mount point exists
                        if os.path.exists(mount_point) and os.path.isdir(mount_point):
                            mounted = True
                        else:
                            errors.append(
                                f"Mount point {mount_point} exists but is not a directory")
                    else:
                        # Wrong partition mounted, try to unmount it
                        log("Wrong EFI partition mounted, unmounting...", "WARNING")
                        subprocess.run(['diskutil', 'unmount', '/Volumes/EFI'], 
                                    capture_output=True, text=True)
                else:
                    errors.append(f"Volume name mount: {result.stderr or result.stdout}")
            except Exception as e:
                errors.append(f"Volume name mount exception: {str(e)}")
        
        # If method 2 succeeded, return the mount point
        if mounted and mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at "
                        f"{mount_point}{COLORS['RESET']}")
            return mount_point
        
        # Method 3: Try direct mount using mount_msdos command
        if not mounted:
            try:
                # Ensure mount point exists
                efi_mount_dir = '/Volumes/EFI'
                if not os.path.exists(efi_mount_dir):
                    os.makedirs(efi_mount_dir, exist_ok=True)
                
                # Add a small delay to prevent race conditions
                time.sleep(0.5)
                
                # Try mounting with mount_msdos
                result = subprocess.run(['sudo', 'mount_msdos', partition, efi_mount_dir], 
                                    capture_output=True, text=True)
                
                if (result.returncode == 0 or 
                    (os.path.exists(efi_mount_dir) and len(os.listdir(efi_mount_dir)) > 0)):
                    mount_point = efi_mount_dir
                    mounted = True
                else:
                    errors.append(f"mount_msdos: {result.stderr or result.stdout}")
            except Exception as e:
                errors.append(f"mount_msdos exception: {str(e)}")
        
        # If method 3 succeeded, return the mount point
        if mounted and mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at "
                        f"{mount_point} using mount_msdos{COLORS['RESET']}")
            return mount_point
    
    # If all methods failed, log the errors and return None
    spinner.stop(f"{COLORS['RED']}✗ Failed to mount {partition} after trying "
                f"multiple methods{COLORS['RESET']}")
    
    # Log detailed errors
    log("Mount failure details:", "ERROR")
    for i, error in enumerate(errors):
        log(f"  Method {i+1}: {error}", "ERROR")
    
    # Check for system-level reasons for mounting failures
    check_system_constraints()
    
    return None


def unmount_efi(partition: str) -> bool:
    """Unmount an EFI partition.
    
    Args:
        partition: Partition identifier (e.g., /dev/disk0s1)
        
    Returns:
        True if unmounted successfully, False otherwise
    """
    spinner = Spinner(f"Unmounting {partition}")
    spinner.start()
    
    # Create a global lock for unmount operations
    if not hasattr(unmount_efi, 'global_unmount_lock'):
        unmount_efi.global_unmount_lock = threading.Lock()
    
    # First check if the partition is mounted
    mount_point = check_if_mounted(partition)
    if not mount_point:
        spinner.stop(f"{COLORS['YELLOW']}⚠ Partition {partition} is not "
                    f"mounted{COLORS['RESET']}")
        return True
    
    # Acquire global lock for the entire unmount operation
    with unmount_efi.global_unmount_lock:
        # Check again after acquiring lock in case another thread unmounted it
        mount_point = check_if_mounted(partition)
        if not mount_point:
            spinner.stop(f"{COLORS['YELLOW']}⚠ Partition {partition} was unmounted by "
                        f"another process{COLORS['RESET']}")
            return True
        
        # Add a small delay to prevent race conditions
        time.sleep(0.5)
        
        # Try unmounting by mount point first (more reliable)
        try:
            result = subprocess.run(['diskutil', 'unmount', mount_point], 
                                capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully unmounted "
                            f"{mount_point}{COLORS['RESET']}")
                # Verify the unmount actually worked
                time.sleep(0.5)  # Brief delay to ensure system state is updated
                if not os.path.ismount(mount_point):
                    return True
                else:
                    log("Unmount reported success but mount point still exists, "
                       "trying alternative method", "WARNING")
            else:
                log(f"Error in primary unmount: {result.stderr}", "WARNING")
        except Exception as e:
            log(f"Error in primary unmount: {e}", "WARNING")
        
        # If that failed, try unmounting by partition
        try:
            # Add a small delay before retry
            time.sleep(1.0)
            
            result = subprocess.run(['diskutil', 'unmount', partition], 
                                capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully unmounted "
                            f"{partition}{COLORS['RESET']}")
                # Verify the unmount actually worked
                time.sleep(0.5)
                if check_if_mounted(partition) is None:
                    return True
                else:
                    log("Unmount reported success but partition is still mounted, "
                       "trying force unmount", "WARNING")
            else:
                log(f"Error in partition unmount: {result.stderr}", "WARNING")
        except Exception as e:
            log(f"Error in partition unmount: {e}", "WARNING")
        
        # If both methods failed, try force unmounting
        try:
            # Add a small delay before retry
            time.sleep(1.0)
            
            # Try force unmount on mount point
            result = subprocess.run(['diskutil', 'unmount', 'force', mount_point], 
                                capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully force unmounted "
                            f"{mount_point}{COLORS['RESET']}")
                return True
            
            # If mount point force unmount fails, try on partition
            result = subprocess.run(['diskutil', 'unmount', 'force', partition], 
                                capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully force unmounted "
                            f"{partition}{COLORS['RESET']}")
                return True
        except Exception as e:
            log(f"Error in force unmount: {e}", "WARNING")
    
    # If we get here, all unmount attempts failed
    spinner.stop(f"{COLORS['RED']}✗ Failed to unmount {partition}{COLORS['RESET']}")
    log("Please unmount the partition manually using Disk Utility.", "WARNING")
    return False


def find_config_plist(mount_point: str) -> Optional[str]:
    """Find OpenCore config.plist in the mounted EFI partition.
    
    Args:
        mount_point: The mount point to search
        
    Returns:
        Path to config.plist if found, None otherwise
    """
    # Common paths for OpenCore config.plist
    possible_paths = [
        os.path.join(mount_point, 'EFI', 'OC', 'config.plist'),
        os.path.join(mount_point, 'OC', 'config.plist'),
        os.path.join(mount_point, 'config.plist'),
        os.path.join(mount_point, 'EFI', 'CLOVER', 'config.plist')  # Also check for Clover
    ]
    
    spinner = Spinner(f"Searching for OpenCore config.plist")
    spinner.start()
    
    for i, path in enumerate(possible_paths):
        # Add a short pause to show progress
        time.sleep(0.2)
        progress_bar(i+1, len(possible_paths), prefix='Progress:', 
                    suffix='Complete', length=30)
        
        if os.path.exists(path):
            if 'CLOVER' in path:
                spinner.stop(f"{COLORS['YELLOW']}⚠ Found Clover config.plist at {path} - "
                            f"may not be compatible{COLORS['RESET']}")
            else:
                spinner.stop(f"{COLORS['GREEN']}✓ Found OpenCore config.plist at "
                            f"{path}{COLORS['RESET']}")
            return path
    
    # Additional deep search for config.plist in case it's in a non-standard location
    try:
        spinner.stop()
        spinner = Spinner(f"Performing deep search for config.plist")
        spinner.start()
        
        # Use find command to search for config.plist files
        find_result = subprocess.run(['find', mount_point, '-name', 'config.plist'], 
                                  capture_output=True, text=True)
        
        if find_result.returncode == 0 and find_result.stdout.strip():
            paths = find_result.stdout.strip().split('\n')
            for path in paths:
                if os.path.exists(path):
                    if 'CLOVER' in path:
                        spinner.stop(f"{COLORS['YELLOW']}⚠ Found Clover config.plist at "
                                    f"{path} - may not be compatible{COLORS['RESET']}")
                    else:
                        spinner.stop(f"{COLORS['GREEN']}✓ Found config.plist at "
                                    f"{path}{COLORS['RESET']}")
                    return path
    except Exception:
        pass  # Ignore if find command fails
    
    spinner.stop(f"{COLORS['YELLOW']}⚠ No OpenCore config.plist found{COLORS['RESET']}")
    return None


def check_if_patches_exist(config_path: str) -> Tuple[bool, str]:
    """Check if the Sonoma VM BT Enabler patches already exist in the config.
    
    Args:
        config_path: Path to config.plist
        
    Returns:
        Tuple of (bool, str) where the bool indicates if patches exist
        and the string provides details about which patches were found
    """
    spinner = Spinner(f"Checking for existing patches")
    spinner.start()
    
    try:
        with open(config_path, 'rb') as f:
            config = plistlib.load(f)
        
        patch1_found = False
        patch2_found = False
        
        if 'Kernel' in config and 'Patch' in config['Kernel']:
            for patch in config['Kernel']['Patch']:
                if isinstance(patch, dict) and 'Comment' in patch:
                    # Check for patch 1
                    if ('Sonoma VM BT Enabler' in patch['Comment'] and 
                        'PART 1' in patch['Comment'] and
                        patch.get('Find') and patch.get('Replace')):
                        patch1_found = True
                        
                    # Check for patch 2    
                    if ('Sonoma VM BT Enabler' in patch['Comment'] and 
                        'PART 2' in patch['Comment'] and
                        patch.get('Find') and patch.get('Replace')):
                        patch2_found = True
        
        # Return appropriate message based on what was found
        if patch1_found and patch2_found:
            spinner.stop(f"{COLORS['GREEN']}✓ Both Sonoma VM BT Enabler patches "
                        f"found{COLORS['RESET']}")
            return (True, "both_found")
        elif patch1_found and not patch2_found:
            spinner.stop(f"{COLORS['YELLOW']}⚠ Only Patch 1 found, Patch 2 "
                        f"missing{COLORS['RESET']}")
            return (False, "patch1_only")
        elif not patch1_found and patch2_found:
            spinner.stop(f"{COLORS['YELLOW']}⚠ Only Patch 2 found, Patch 1 "
                        f"missing{COLORS['RESET']}")
            return (False, "patch2_only")
        else:
            spinner.stop(f"{COLORS['BLUE']}ℹ No existing patches found{COLORS['RESET']}")
            return (False, "none")
            
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error checking for existing patches: "
                    f"{e}{COLORS['RESET']}")
        log("Continuing anyway - will attempt to apply patches", "WARNING")
        return (False, "error")


def add_kernel_patches(config_path: str) -> str:
    """Add Sonoma VM BT Enabler kernel patches to config.plist.
    
    Args:
        config_path: Path to config.plist
        
    Returns:
        Result status: "success", "already_exists", or "error"
    """
    log("Starting patch process...", "INFO")
    
    # Make a backup of the original file
    backup_path = config_path + '.backup'
    
    spinner = Spinner(f"Creating backup at {backup_path}")
    spinner.start()
    
    # Use file lock to prevent race conditions during backup
    try:
        with FileLock(config_path):
            # Check if backup already exists
            if not os.path.exists(backup_path):
                shutil.copy2(config_path, backup_path)
            spinner.stop(f"{COLORS['GREEN']}✓ Backup created at {backup_path}{COLORS['RESET']}")
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error creating backup: {e}{COLORS['RESET']}")
        return "error"
    
    # Read the plist file with proper locking
    spinner = Spinner(f"Reading config file")
    spinner.start()
    
    try:
        with FileLock(config_path):
            with open(config_path, 'rb') as f:
                config = plistlib.load(f)
        spinner.stop(f"{COLORS['GREEN']}✓ Config file loaded successfully{COLORS['RESET']}")
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error reading config file: {e}{COLORS['RESET']}")
        log(f"Error details: {str(e)}", "ERROR")
        return "error"
    
    # First check if patches already exist
    patches_exist, patch_status = check_if_patches_exist(config_path)
    
    # If both patches already exist, we're done
    if patches_exist:
        log("Both patches already exist in config.plist. No changes needed.", "SUCCESS")
        return "already_exists"
    
    # Prepare the patch entries
    log("Preparing patch data...", "INFO")
    
    # Show a progress bar for patch preparation
    for i in range(10):
        progress_bar(i+1, 10, prefix='Preparing patches:', suffix='Complete', length=30)
        time.sleep(0.05)
    
    # Prepare patches with updated patterns
    patch1 = {
        'Arch': 'x86_64',
        'Base': '',
        'Comment': 'Sonoma VM BT Enabler - PART 1 of 2 - Patch kern.hv_vmm_present=0',
        'Count': 1,
        'Enabled': True,
        'Find': base64.b64decode('aGliZXJuYXRlaGlkcmVhZHkAaGliZXJuYXRlY291bnQA'),
        'Identifier': 'kernel',
        'Limit': 0,
        'Mask': b'',
        'MaxKernel': '',
        'MinKernel': '20.4.0',
        'Replace': base64.b64decode('aGliZXJuYXRlaGlkcmVhZHkAaHZfdm1tX3ByZXNlbnQA'),
        'ReplaceMask': b'',
        'Skip': 0,
    }
    
    patch2 = {
        'Arch': 'x86_64',
        'Base': '',
        'Comment': 'Sonoma VM BT Enabler - PART 2 of 2 - Patch kern.hv_vmm_present=0',
        'Count': 1,
        'Enabled': True,
        'Find': base64.b64decode('Ym9vdCBzZXNzaW9uIFVVSUQAaHZfdm1tX3ByZXNlbnQA'),
        'Identifier': 'kernel',
        'Limit': 0,
        'Mask': b'',
        'MaxKernel': '',
        'MinKernel': '22.0.0',
        'Replace': base64.b64decode('Ym9vdCBzZXNzaW9uIFVVSUQAaGliZXJuYXRlY291bnQA'),
        'ReplaceMask': b'',
        'Skip': 0,
    }
    
    # Determine which patches need to be applied based on the check result
    patches_to_apply = []
    if patch_status == "none" or patch_status == "error":
        # No patches found or error during check, apply both patches
        patches_to_apply = [patch1, patch2]
        log("Adding both patches to config.plist", "INFO")
    elif patch_status == "patch1_only":
        # Only patch 1 exists, add patch 2
        patches_to_apply = [patch2]
        log("Adding missing Patch 2 to config.plist", "INFO")
    elif patch_status == "patch2_only":
        # Only patch 2 exists, add patch 1
        patches_to_apply = [patch1]
        log("Adding missing Patch 1 to config.plist", "INFO")
    
    # Add patches to the kernel patch section
    if 'Kernel' not in config:
        config['Kernel'] = {}
    
    if 'Patch' not in config['Kernel']:
        config['Kernel']['Patch'] = []
    elif not isinstance(config['Kernel']['Patch'], list):
        log("Warning: Kernel->Patch is not a list. Converting to list.", "WARNING")
        config['Kernel']['Patch'] = []
    
    # Adding patches with animation
    spinner = Spinner(f"Adding patches to config")
    spinner.start()
    time.sleep(0.5)  # Add a slight delay for visual effect
    
    # Add only the patches that need to be applied
    for patch in patches_to_apply:
        config['Kernel']['Patch'].append(patch)
    
    spinner.stop(f"{COLORS['GREEN']}✓ Added {len(patches_to_apply)} Sonoma VM BT Enabler "
                f"patch(es) to config.plist{COLORS['RESET']}")
    
    # Write the updated plist file with proper atomic operations
    spinner = Spinner(f"Writing updated config to disk")
    spinner.start()
    
    try:
        # Use a file lock to ensure atomic operations
        with FileLock(config_path):
            # Create a temporary file with the updates
            with tempfile.NamedTemporaryFile(delete=False, suffix='.tmp') as temp_file:
                temp_path = temp_file.name
                plistlib.dump(config, temp_file)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            
            # Verify the temporary file by loading it back
            with open(temp_path, 'rb') as f:
                test_load = plistlib.load(f)
                
                # Extra verification: check if our patches are in the test_load
                patch_found_in_test = False
                if 'Kernel' in test_load and 'Patch' in test_load['Kernel']:
                    for patch in test_load['Kernel']['Patch']:
                        if isinstance(patch, dict) and 'Comment' in patch:
                            if 'Sonoma VM BT Enabler' in patch['Comment']:
                                patch_found_in_test = True
                                break
                
                if not patch_found_in_test:
                    raise ValueError("Verification failed: patches not found in test load")
            
            # If we get here, it's safe to replace the original
            shutil.move(temp_path, config_path)
            
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully updated {config_path}{COLORS['RESET']}")
            return "success"
            
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error writing config file: {e}{COLORS['RESET']}")
        log(f"Detailed error: {str(e)}", "ERROR")
        log(f"Attempting to restore from backup...", "INFO")
        
        try:
            with FileLock(config_path):
                # Clean up temp file if it exists
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
                # Restore from backup if it exists
                if os.path.exists(backup_path):
                    shutil.copy2(backup_path, config_path)
                    log(f"Successfully restored from backup.", "SUCCESS")
        except Exception as restore_e:
            log(f"Failed to restore from backup: {str(restore_e)}", "ERROR")
        
        return "error"


def main(auto_confirm: bool = False, auto_restart: bool = False) -> None:
    """Main function to run the patching process.
    
    Args:
        auto_confirm: Whether to automatically confirm patches without prompting
        auto_restart: Whether to automatically restart after patching
    """
    print_banner()
    log("Starting automatic OpenCore config.plist patching...", "TITLE")
    
    # Track overall script state
    state = {
        "config_found": False,
        "config_patched": False,
        "mount_points": [],  # Track mounted partitions to ensure cleanup
    }
    
    # Set up cleanup on keyboard interrupt
    def cleanup_handler(signum, frame):
        log("\nInterrupt received, cleaning up...", "WARNING")
        for mount_point in state["mount_points"]:
            log(f"Unmounting {mount_point} during cleanup", "INFO")
            # Get partition from mount point
            try:
                info_result = subprocess.run(['diskutil', 'info', mount_point], 
                                          capture_output=True, text=True)
                for line in info_result.stdout.split('\n'):
                    if "Device Identifier:" in line:
                        partition = line.split(":")[1].strip()
                        unmount_efi(partition)
                        break
            except Exception:
                pass
        sys.exit(1)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, cleanup_handler)
    
    try:
        # Get list of disks
        disk_info = get_disk_list()
        if not disk_info:
            log("Failed to get disk information.", "ERROR")
            return
        
        # Extract EFI partitions
        efi_partitions = get_efi_partitions(disk_info)
        if not efi_partitions:
            log("No EFI partitions found.", "ERROR")
            log("Consider mounting EFI manually with Disk Utility, then run this script "
                "with the specific path.", "INFO")
            return
        
        log(f"Scanning {len(efi_partitions)} EFI partition(s) for OpenCore configuration", 
           "HEADER")
        
        # Progress counter for partition scanning
        total_partitions = len(efi_partitions)
        
        # Check each EFI partition
        for idx, partition in enumerate(efi_partitions):
            partition_progress = f"[{idx+1}/{total_partitions}]"
            log(f"{partition_progress} Processing partition {partition}", "INFO")
            
            # Mount the EFI partition
            mount_point = mount_efi(partition)
            if not mount_point:
                log(f"{partition_progress} Failed to mount {partition}, skipping...", 
                   "WARNING")
                if idx == total_partitions - 1 and idx > 0:
                    log("All mount attempts failed. Please try manually mounting with "
                        "Disk Utility.", "ERROR")
                continue
            
            # Track mounted partitions for cleanup
            state["mount_points"].append(mount_point)
            
            try:
                # Look for config.plist
                config_path = find_config_plist(mount_point)
                if config_path:
                    state["config_found"] = True
                    
                    # Use our improved check function
                    patches_exist, patch_status = check_if_patches_exist(config_path)
                    
                    if patches_exist:
                        log(f"Patches already exist in {config_path}", "TITLE")
                        log("No changes needed. Your system is already patched.", "SUCCESS")
                        # Clean up before exiting
                        unmount_efi(partition)
                        state["mount_points"].remove(mount_point)
                        return
                    
                    # Ask for confirmation before applying patch
                    log(f"OpenCore configuration found", "TITLE")
                    log(f"Path: {config_path}", "INFO")
                    
                    if patch_status != "none" and patch_status != "error":
                        log(f"Partial patches found: {patch_status}", "WARNING")
                        log("Will add missing patches to complete the set", "INFO")
                    
                    proceed = True
                    if not auto_confirm:
                        while True:
                            response = input(f"{COLORS['CYAN']}Do you want to apply the "
                                           f"Sonoma VM BT Enabler patch? [y/n/skip]: "
                                           f"{COLORS['RESET']}").lower()
                            if response in ['y', 'yes']:
                                break
                            elif response in ['n', 'no']:
                                log("Operation cancelled by user.", "WARNING")
                                proceed = False
                                break
                            elif response == 'skip':
                                log(f"Skipping {config_path}. Looking for other configs...", 
                                   "INFO")
                                proceed = False
                                break
                            else:
                                log("Please enter 'y' for yes, 'n' for no, or 'skip' to "
                                    "try next partition.", "WARNING")
                        
                        if response == 'skip':
                            continue
                    
                    if proceed:
                        # Apply patches
                        success = add_kernel_patches(config_path)
                        if success == "success":
                            log(f"Successfully patched OpenCore config at {config_path}", 
                               "SUCCESS")
                            state["config_patched"] = True
                        elif success == "already_exists":
                            log(f"Patches already exist in {config_path}", "TITLE")
                            log("No changes needed. Your system is already patched.", 
                               "SUCCESS")
                            # Clean up before exiting
                            unmount_efi(partition)
                            state["mount_points"].remove(mount_point)
                            return
                        else:
                            log(f"Failed to patch config at {config_path}", "ERROR")
                else:
                    log(f"{partition_progress} No OpenCore config.plist found on {partition}", 
                       "WARNING")
            finally:
                # Always unmount the partition when done
                time.sleep(1)  # Brief pause before unmounting
                unmount_success = unmount_efi(partition)
                if unmount_success and mount_point in state["mount_points"]:
                    state["mount_points"].remove(mount_point)
                
                # If we found and patched a config, we can stop
                if state["config_patched"]:
                    break
        
        if state["config_patched"]:
            log("Patching process completed successfully", "TITLE")
            log("Please reboot your system to apply the changes.", "SUCCESS")
            
            # Offer to restart if auto_restart is enabled
            if auto_restart:
                log("Auto-restart enabled. System will restart automatically.", "INFO")
                restart_system()
            else:
                # Offer restart option
                if not auto_confirm:  # Only ask if not in auto mode
                    response = input(f"{COLORS['CYAN']}Would you like to restart now to "
                                   f"apply changes? [y/n]: {COLORS['RESET']}").lower()
                    if response in ['y', 'yes']:
                        restart_system()
        elif state["config_found"]:
            # Found configs but patching failed
            log("Found OpenCore config.plist but patching was not successful", "WARNING")
            log("Please check the logs above for errors.", "INFO")
        else:
            log("No OpenCore config.plist found on any EFI partition", "TITLE")
            log("Make sure OpenCore is properly installed.", "WARNING")
            log("If you know the location of your config.plist, try running this script "
                "with that path:", "INFO")
            log(f"  sudo python3 {sys.argv[0]} /path/to/config.plist", "INFO")
            log("You may also need to mount your EFI manually using Disk Utility.", "INFO")
    
    except Exception as e:
        log(f"Unexpected error: {str(e)}", "ERROR")
        import traceback
        log(traceback.format_exc(), "ERROR")
    
    finally:
        # Final cleanup for any remaining mounted partitions
        if state["mount_points"]:
            log("Performing final cleanup of mounted partitions...", "INFO")
            for mount_point in state["mount_points"]:
                try:
                    info_result = subprocess.run(['diskutil', 'info', mount_point], 
                                              capture_output=True, text=True)
                    for line in info_result.stdout.split('\n'):
                        if "Device Identifier:" in line:
                            partition = line.split(":")[1].strip()
                            unmount_efi(partition)
                            break
                except Exception:
                    # If we can't get the partition, try direct unmount
                    try:
                        subprocess.run(['diskutil', 'unmount', 'force', mount_point], 
                                    capture_output=True, text=True)
                    except Exception:
                        pass


def process_specific_config(config_path: str, auto_confirm: bool = False, 
                          auto_restart: bool = False) -> None:
    """Process a specific config.plist file.
    
    Args:
        config_path: Path to config.plist
        auto_confirm: Whether to automatically confirm patches without prompting
        auto_restart: Whether to automatically restart after patching
    """
    log(f"Using provided config path: {config_path}", "HEADER")
    
    # Check if patches already exist before asking user
    if check_if_patches_exist(config_path)[0]:
        log(f"Patches already exist in {config_path}", "TITLE")
        log("No changes needed. Your system is already patched.", "SUCCESS")
        return
    
    # For specific paths, still ask for confirmation unless --auto is specified
    if not auto_confirm:
        response = input(f"{COLORS['CYAN']}Apply Sonoma VM BT Enabler patch to "
                       f"{config_path}? [y/n]: {COLORS['RESET']}").lower()
        if response not in ['y', 'yes']:
            log("Operation cancelled.", "WARNING")
            return
                
    success = add_kernel_patches(config_path)
    if success == "success":
        log("Patches applied successfully. Please reboot to apply changes.", "SUCCESS")
        
        # Handle auto-restart if enabled
        if auto_restart:
            log("Auto-restart enabled. System will restart automatically.", "INFO")
            restart_system()
        elif not auto_confirm:  # Ask about restart only in interactive mode
            response = input(f"{COLORS['CYAN']}Would you like to restart now to apply "
                           f"changes? [y/n]: {COLORS['RESET']}").lower()
            if response in ['y', 'yes']:
                restart_system()
    elif success == "already_exists":
        log(f"Patches already exist in {config_path}", "TITLE")
        log("No changes needed. Your system is already patched.", "SUCCESS")
    else:
        log("Failed to apply patches.", "ERROR")


def mount_only_mode() -> None:
    """Mount EFI partitions without patching."""
    print_banner()
    log("EFI Mount Mode - Will only mount EFI partitions without patching", "TITLE")
    
    disk_info = get_disk_list()
    if not disk_info:
        log("Failed to get disk information.", "ERROR")
        sys.exit(1)
    
    efi_partitions = get_efi_partitions(disk_info)
    if not efi_partitions:
        log("No EFI partitions found.", "ERROR")
        sys.exit(1)
    
    log(f"Found {len(efi_partitions)} EFI partition(s)", "SUCCESS")
    
    for idx, partition in enumerate(efi_partitions):
        log(f"Attempting to mount {partition}...", "INFO")
        mount_point = mount_efi(partition)
        
        if mount_point:
            log(f"Successfully mounted {partition} at {mount_point}", "SUCCESS")
            log(f"When finished, unmount with: diskutil unmount {mount_point}", "INFO")
        else:
            log(f"Failed to mount {partition}", "ERROR")


if __name__ == "__main__":
    # Check if ANSI colors are supported in the terminal
    if "TERM" in os.environ and os.environ["TERM"] in ["xterm", "xterm-color", 
                                                    "xterm-256color", "screen", 
                                                    "screen-256color"]:
        pass  # Colors are supported
    else:
        # Strip out ANSI color codes for terminals that don't support them
        for key in COLORS:
            COLORS[key] = ""
    
    # Check if running as root
    if os.geteuid() != 0:
        log("This script requires administrative privileges.", "ERROR")
        log(f"Please run with sudo: {COLORS['CYAN']}sudo {sys.argv[0]}{COLORS['RESET']}", 
           "INFO")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(
        description="Apply Sonoma VM BT Enabler patches to OpenCore config.plist")
    parser.add_argument("config_path", nargs="?", 
                      help="Path to specific config.plist (optional)")
    parser.add_argument("--auto", "-a", action="store_true", 
                      help="Auto-confirm patches without prompting")
    parser.add_argument("--no-color", action="store_true", 
                      help="Disable colored output")
    parser.add_argument("--restart", "-r", action="store_true", 
                      help="Automatically restart after patching")
    parser.add_argument("--mount-only", "-m", action="store_true", 
                      help="Only mount EFI partitions without patching")
    parser.add_argument("--debug", "-d", action="store_true", 
                      help="Enable additional debug output")
    args = parser.parse_args()
    
    # Disable colors if requested
    if args.no_color:
        for key in COLORS:
            COLORS[key] = ""
    
    # Mount-only mode
    if args.mount_only:
        mount_only_mode()
        sys.exit(0)
    
    # If a specific config path is provided, use it directly
    if args.config_path:
        config_path = args.config_path
        if os.path.exists(config_path):
            process_specific_config(config_path, args.auto, args.restart)
        else:
            log(f"Error: File {config_path} does not exist", "ERROR")
    else:
        # Otherwise, use the automatic EFI partition detection
        main(auto_confirm=args.auto, auto_restart=args.restart)
