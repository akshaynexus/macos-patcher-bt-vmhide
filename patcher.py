#!/usr/bin/env python3
"""
Sonoma VM Bluetooth Enabler Patch Tool.

This script patches OpenCore config.plist files to enable Bluetooth functionality
in macOS Sonoma virtual machines.
"""

import plistlib
import base64
import os
import sys
import subprocess
import re
import time
import argparse
from datetime import datetime

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

def log(message, level="INFO", timestamp=True):
    """Log a message with color formatting."""
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

def get_disk_list():
    """Get a list of all disks in the system."""
    try:
        result = subprocess.run(['diskutil', 'list'], 
                             capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        log(f"Error getting disk list: {e}", "ERROR")
        return ""

def get_efi_partitions(disk_info):
    """Extract EFI partition information from diskutil output."""
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
            # Parse the partition number
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

def check_if_mounted(partition):
    """Check if the partition is already mounted."""
    try:
        result = subprocess.run(['diskutil', 'info', partition], 
                             capture_output=True, text=True)
        
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

def mount_efi(partition):
    """Mount an EFI partition and return the mount point."""
    log(f"Mounting {partition}", "INFO")
    
    # First check if already mounted
    mount_point = check_if_mounted(partition)
    if mount_point:
        log(f"Partition {partition} is already mounted at {mount_point}", "SUCCESS")
        return mount_point
    
    # Try standard mount
    try:
        result = subprocess.run(['diskutil', 'mount', partition], 
                            capture_output=True, text=True)
        
        # Parse mount point from output
        if result.returncode == 0:
            match = re.search(r'mounted at (.*)', result.stdout)
            if match:
                mount_point = match.group(1).strip()
                log(f"Successfully mounted {partition} at {mount_point}", "SUCCESS")
                return mount_point
    except Exception as e:
        log(f"Error mounting partition: {e}", "WARNING")
    
    # If that failed, try mounting by volume name
    try:
        # Create a temporary directory for mounting
        efi_mount_dir = '/Volumes/EFI'
        if not os.path.exists(efi_mount_dir):
            os.makedirs(efi_mount_dir, exist_ok=True)
        
        # Try to mount by volume name
        result = subprocess.run(['diskutil', 'mount', 'EFI'], 
                            capture_output=True, text=True)
        
        if result.returncode == 0:
            # Check if the correct partition was mounted
            info_result = subprocess.run(['diskutil', 'info', '/Volumes/EFI'], 
                                    capture_output=True, text=True)
            if partition in info_result.stdout:
                log(f"Successfully mounted {partition} at /Volumes/EFI", "SUCCESS")
                return '/Volumes/EFI'
            else:
                # Wrong partition mounted, try to unmount it
                log("Wrong EFI partition mounted, unmounting...", "WARNING")
                subprocess.run(['diskutil', 'unmount', '/Volumes/EFI'], 
                            capture_output=True, text=True)
    except Exception as e:
        log(f"Error in alternative mount method: {e}", "WARNING")
    
    # If all else fails, try mount_msdos
    try:
        efi_mount_dir = '/Volumes/EFI'
        if not os.path.exists(efi_mount_dir):
            os.makedirs(efi_mount_dir, exist_ok=True)
        
        result = subprocess.run(['sudo', 'mount_msdos', partition, efi_mount_dir], 
                            capture_output=True, text=True)
        
        if result.returncode == 0 or os.path.exists(os.path.join(efi_mount_dir, 'EFI')):
            log(f"Successfully mounted {partition} at {efi_mount_dir} using mount_msdos", "SUCCESS")
            return efi_mount_dir
        else:
            log(f"mount_msdos: {result.stderr or result.stdout}", "ERROR")
    except Exception as e:
        log(f"Error in mount_msdos: {e}", "ERROR")
    
    log(f"Failed to mount {partition} after trying multiple methods", "ERROR")
    return None

def unmount_efi(partition):
    """Unmount an EFI partition."""
    log(f"Unmounting {partition}", "INFO")
    
    # Check if the partition is mounted
    mount_point = check_if_mounted(partition)
    if not mount_point:
        log(f"Partition {partition} is not mounted", "INFO")
        return True
    
    # Try unmounting by mount point first
    try:
        result = subprocess.run(['diskutil', 'unmount', mount_point], 
                            capture_output=True, text=True)
        
        if result.returncode == 0:
            log(f"Successfully unmounted {mount_point}", "SUCCESS")
            return True
    except Exception as e:
        log(f"Error unmounting by mount point: {e}", "WARNING")
    
    # If that failed, try unmounting by partition
    try:
        result = subprocess.run(['diskutil', 'unmount', partition], 
                            capture_output=True, text=True)
        
        if result.returncode == 0:
            log(f"Successfully unmounted {partition}", "SUCCESS")
            return True
    except Exception as e:
        log(f"Error unmounting by partition: {e}", "WARNING")
    
    # If both methods failed, try force unmounting
    try:
        result = subprocess.run(['diskutil', 'unmount', 'force', mount_point], 
                            capture_output=True, text=True)
        
        if result.returncode == 0:
            log(f"Successfully force unmounted {mount_point}", "SUCCESS")
            return True
    except Exception as e:
        log(f"Error force unmounting: {e}", "WARNING")
    
    log(f"Failed to unmount {partition}", "ERROR")
    log("Please unmount the partition manually using Disk Utility.", "WARNING")
    return False

def find_config_plist(mount_point):
    """Find OpenCore config.plist in the mounted EFI partition."""
    # Common paths for OpenCore config.plist
    possible_paths = [
        os.path.join(mount_point, 'EFI', 'OC', 'config.plist'),
        os.path.join(mount_point, 'OC', 'config.plist'),
        os.path.join(mount_point, 'config.plist'),
        os.path.join(mount_point, 'EFI', 'CLOVER', 'config.plist')
    ]
    
    log(f"Searching for OpenCore config.plist", "INFO")
    
    for path in possible_paths:
        if os.path.exists(path):
            if 'CLOVER' in path:
                log(f"Found Clover config.plist at {path} - may not be compatible", "WARNING")
            else:
                log(f"Found OpenCore config.plist at {path}", "SUCCESS")
            return path
    
    # Additional deep search
    try:
        find_result = subprocess.run(['find', mount_point, '-name', 'config.plist'], 
                                  capture_output=True, text=True)
        
        if find_result.returncode == 0 and find_result.stdout.strip():
            paths = find_result.stdout.strip().split('\n')
            for path in paths:
                if os.path.exists(path):
                    log(f"Found config.plist at {path}", "SUCCESS")
                    return path
    except Exception:
        pass
    
    log("No OpenCore config.plist found", "WARNING")
    return None

def check_if_patches_exist(config_path):
    """Check if the Sonoma VM BT Enabler patches already exist in the config."""
    log(f"Checking for existing patches", "INFO")
    
    try:
        # Simple direct file read with minimal processing
        with open(config_path, 'rb') as f:
            config = plistlib.load(f)
        
        if 'Kernel' in config and 'Patch' in config['Kernel']:
            for patch in config['Kernel']['Patch']:
                if isinstance(patch, dict) and 'Comment' in patch:
                    if 'Sonoma VM BT Enabler' in patch['Comment']:
                        log(f"Found existing patch: {patch['Comment']}", "INFO")
                        return True
        
        log("No existing patches found", "INFO")
        return False
    except Exception as e:
        log(f"Error checking for existing patches: {e}", "ERROR")
        log("Continuing anyway - will attempt to apply patches", "WARNING")
        return False

def add_kernel_patches(config_path):
    """Add Sonoma VM BT Enabler kernel patches to config.plist."""
    log("Starting patch process...", "INFO")
    
    # Make a backup of the original file (using simple copy command for maximum compatibility)
    backup_path = config_path + '.backup'
    try:
        os.system(f'cp "{config_path}" "{backup_path}"')
        log(f"Backup created at {backup_path}", "SUCCESS")
    except Exception as e:
        log(f"Error creating backup: {e}", "ERROR")
        return "error"
    
    # Read the plist file - simple direct read
    try:
        with open(config_path, 'rb') as f:
            config = plistlib.load(f)
        log("Config file loaded successfully", "SUCCESS")
    except Exception as e:
        log(f"Error reading config file: {e}", "ERROR")
        log(f"Error details: {str(e)}", "ERROR")
        return "error"
    
    # Prepare the patch entries
    log("Preparing patch data...", "INFO")
    
    # Use the exact same patches from the working example
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
    
    # Add patches to the kernel patch section
    if 'Kernel' in config and 'Patch' in config['Kernel']:
        # Check if patches already exist
        patch_exists = False
        for patch in config['Kernel']['Patch']:
            if isinstance(patch, dict) and 'Comment' in patch:
                if 'Sonoma VM BT Enabler' in patch['Comment']:
                    patch_exists = True
                    log(f"Patch already exists: {patch['Comment']}", "INFO")
        
        if not patch_exists:
            # Make sure Patch is a list
            if not isinstance(config['Kernel']['Patch'], list):
                config['Kernel']['Patch'] = []
                
            config['Kernel']['Patch'].append(patch1)
            config['Kernel']['Patch'].append(patch2)
            log("Added both Sonoma VM BT Enabler patches to config.plist", "SUCCESS")
        else:
            log("Patches already exist in config.plist", "INFO")
            return "already_exists"
    else:
        # Create Kernel->Patch if it doesn't exist
        if 'Kernel' not in config:
            config['Kernel'] = {}
        
        if 'Patch' not in config['Kernel']:
            config['Kernel']['Patch'] = []
        
        config['Kernel']['Patch'].append(patch1)
        config['Kernel']['Patch'].append(patch2)
        log("Created Kernel->Patch section and added patches", "SUCCESS")
    
    # Write the updated plist file
    try:
        with open(config_path, 'wb') as f:
            plistlib.dump(config, f)
        
        log(f"Successfully updated {config_path}", "SUCCESS")
        return "success"
    except Exception as e:
        log(f"Error writing config file: {e}", "ERROR")
        log(f"Attempting to restore from backup...", "WARNING")
        
        try:
            os.system(f'cp "{backup_path}" "{config_path}"')
            log("Successfully restored from backup", "SUCCESS")
        except Exception as restore_e:
            log(f"Failed to restore from backup: {str(restore_e)}", "ERROR")
        
        return "error"

def main(auto_confirm=False, auto_restart=False):
    """Main function to run the patching process."""
    print_banner()
    log("Starting automatic OpenCore config.plist patching...", "TITLE")
    
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
    
    # Check each EFI partition
    for idx, partition in enumerate(efi_partitions):
        partition_progress = f"[{idx+1}/{len(efi_partitions)}]"
        log(f"{partition_progress} Processing partition {partition}", "INFO")
        
        # Mount the EFI partition
        mount_point = mount_efi(partition)
        if not mount_point:
            log(f"{partition_progress} Failed to mount {partition}, skipping...", 
               "WARNING")
            continue
        
        try:
            # Look for config.plist
            config_path = find_config_plist(mount_point)
            if config_path:
                # Check if patches already exist
                if check_if_patches_exist(config_path):
                    log(f"Patches already exist in {config_path}", "TITLE")
                    log("No changes needed. Your system is already patched.", "SUCCESS")
                    unmount_efi(partition)
                    return
                
                # Ask for confirmation before applying patch
                log(f"OpenCore configuration found", "TITLE")
                log(f"Path: {config_path}", "INFO")
                
                proceed = True
                if not auto_confirm:
                    response = input(f"{COLORS['CYAN']}Do you want to apply the "
                                   f"Sonoma VM BT Enabler patch? [y/n/skip]: "
                                   f"{COLORS['RESET']}").lower()
                    if response in ['y', 'yes']:
                        pass
                    elif response in ['n', 'no']:
                        log("Operation cancelled by user.", "WARNING")
                        proceed = False
                    elif response == 'skip':
                        log(f"Skipping {config_path}. Looking for other configs...", 
                           "INFO")
                        proceed = False
                    else:
                        log("Invalid response. Skipping this partition.", "WARNING")
                        proceed = False
                
                if proceed:
                    # Apply patches
                    success = add_kernel_patches(config_path)
                    if success == "success":
                        log(f"Successfully patched OpenCore config at {config_path}", 
                           "SUCCESS")
                        log("Please reboot your system to apply the changes.", "INFO")
                        
                        # Offer restart
                        if auto_restart:
                            log("Auto-restart enabled. System will restart automatically.", "INFO")
                            subprocess.run(['shutdown', '-r', 'now'])
                        elif not auto_confirm:
                            response = input(f"{COLORS['CYAN']}Would you like to restart now to "
                                           f"apply changes? [y/n]: {COLORS['RESET']}").lower()
                            if response in ['y', 'yes']:
                                subprocess.run(['shutdown', '-r', 'now'])
                        
                        unmount_efi(partition)
                        return
                    elif success == "already_exists":
                        log(f"Patches already exist in {config_path}", "TITLE")
                        log("No changes needed. Your system is already patched.", "SUCCESS")
                        unmount_efi(partition)
                        return
                    else:
                        log(f"Failed to patch config at {config_path}", "ERROR")
            else:
                log(f"{partition_progress} No OpenCore config.plist found on {partition}", 
                   "WARNING")
        finally:
            # Always unmount the partition when done
            time.sleep(1)
            unmount_efi(partition)
    
    log("No suitable OpenCore config.plist found or all patching attempts failed", "ERROR")
    log("If you know the location of your config.plist, try running this script "
        "with that path:", "INFO")
    log(f"  sudo python3 {sys.argv[0]} /path/to/config.plist", "INFO")

def process_specific_config(config_path, auto_confirm=False, auto_restart=False):
    """Process a specific config.plist file."""
    log(f"Using provided config path: {config_path}", "HEADER")
    
    # Check if patches already exist
    if check_if_patches_exist(config_path):
        log(f"Patches already exist in {config_path}", "TITLE")
        log("No changes needed. Your system is already patched.", "SUCCESS")
        return
    
    # Ask for confirmation unless auto_confirm
    if not auto_confirm:
        response = input(f"{COLORS['CYAN']}Apply Sonoma VM BT Enabler patch to "
                       f"{config_path}? [y/n]: {COLORS['RESET']}").lower()
        if response not in ['y', 'yes']:
            log("Operation cancelled.", "WARNING")
            return
                
    success = add_kernel_patches(config_path)
    if success == "success":
        log("Patches applied successfully. Please reboot to apply changes.", "SUCCESS")
        
        # Handle restart
        if auto_restart:
            log("Auto-restart enabled. System will restart automatically.", "INFO")
            subprocess.run(['shutdown', '-r', 'now'])
        elif not auto_confirm:
            response = input(f"{COLORS['CYAN']}Would you like to restart now to apply "
                           f"changes? [y/n]: {COLORS['RESET']}").lower()
            if response in ['y', 'yes']:
                subprocess.run(['shutdown', '-r', 'now'])
    elif success == "already_exists":
        log(f"Patches already exist in {config_path}", "TITLE")
        log("No changes needed. Your system is already patched.", "SUCCESS")
    else:
        log("Failed to apply patches.", "ERROR")

if __name__ == "__main__":
    # Check if ANSI colors are supported
    if "TERM" not in os.environ or os.environ["TERM"] in ["dumb", "cons25"]:
        for key in COLORS:
            COLORS[key] = ""
    
    # Check if running as root
    if os.geteuid() != 0:
        log("This script requires administrative privileges.", "ERROR")
        log(f"Please run with sudo: sudo python3 {sys.argv[0]}", "INFO")
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
    args = parser.parse_args()
    
    # Disable colors if requested
    if args.no_color:
        for key in COLORS:
            COLORS[key] = ""
    
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
