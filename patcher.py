#!/usr/bin/env python3
"""
Sonoma VM Bluetooth Enabler Patch Tool - Minimal Version
This script patches OpenCore config.plist files to enable Bluetooth in macOS Sonoma VMs.
"""

import plistlib
import base64
import os
import sys
import subprocess
import re
import time
from datetime import datetime

# ANSI color codes
COLORS = {
    'RESET': '\033[0m',
    'RED': '\033[31m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'BLUE': '\033[34m',
    'MAGENTA': '\033[35m',
    'CYAN': '\033[36m',
    'BOLD': '\033[1m'
}

def log(message, level="INFO"):
    """Simple logging function with colored output."""
    colors = {
        "INFO": COLORS['BLUE'],
        "ERROR": COLORS['RED'],
        "SUCCESS": COLORS['GREEN'],
        "WARNING": COLORS['YELLOW'],
        "TITLE": COLORS['MAGENTA'] + COLORS['BOLD']
    }
    
    time_str = f"[{datetime.now().strftime('%H:%M:%S')}]"
    color = colors.get(level, COLORS['RESET'])
    
    if level == "TITLE":
        print("\n" + "="*70)
        print(f"{color}{message.center(70)}{COLORS['RESET']}")
        print("="*70)
    else:
        print(f"{color}{time_str} [{level}] {message}{COLORS['RESET']}")

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
    ║   (Minimal version)                                   ║
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
        if line.startswith("/dev/"):
            current_disk = line.split()[0]
        
        if (("EFI" in line or "EF00" in line or 
             "C12A7328-F81F-11D2-BA4B-00A0C93EC93B" in line) and current_disk):
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
        
        if "Mounted: Yes" in result.stdout:
            match = re.search(r'Mount Point:\s+(.*)', result.stdout)
            if match:
                return match.group(1).strip()
        return None
    except Exception:
        return None

def mount_efi(partition):
    """Simple mount function that just tries to mount the partition."""
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
        
        if result.returncode == 0:
            # Get the mount point
            mount_point = check_if_mounted(partition)
            if mount_point:
                log(f"Successfully mounted {partition} at {mount_point}", "SUCCESS")
                return mount_point
    except Exception:
        pass
    
    log(f"Failed to mount {partition}", "ERROR")
    return None

def unmount_efi(partition):
    """Simple unmount function."""
    log(f"Unmounting {partition}", "INFO")
    
    mount_point = check_if_mounted(partition)
    if not mount_point:
        log(f"Partition {partition} is not mounted", "INFO")
        return True
    
    try:
        result = subprocess.run(['diskutil', 'unmount', partition], 
                            capture_output=True, text=True)
        
        if result.returncode == 0:
            log(f"Successfully unmounted {partition}", "SUCCESS")
            return True
    except Exception:
        pass
    
    # Try force unmount if normal unmount failed
    try:
        subprocess.run(['diskutil', 'unmount', 'force', partition], 
                    capture_output=True, text=True)
        return True
    except Exception:
        return False

def find_config_plist(mount_point):
    """Find OpenCore config.plist in the mounted EFI partition."""
    possible_paths = [
        os.path.join(mount_point, 'EFI', 'OC', 'config.plist'),
        os.path.join(mount_point, 'OC', 'config.plist')
    ]
    
    log(f"Searching for OpenCore config.plist", "INFO")
    
    for path in possible_paths:
        if os.path.exists(path):
            log(f"Found OpenCore config.plist at {path}", "SUCCESS")
            return path
    
    log("No OpenCore config.plist found", "WARNING")
    return None

def add_kernel_patches(config_path):
    """Add Sonoma VM BT Enabler kernel patches to config.plist."""
    # This function follows the working example exactly
    log("Starting patch process...", "INFO")
    
    # Make a backup of the original file
    backup_path = config_path + '.backup'
    os.system(f'cp "{config_path}" "{backup_path}"')
    log(f"Backup created at {backup_path}", "SUCCESS")
    
    # Read the plist file
    try:
        with open(config_path, 'rb') as f:
            config = plistlib.load(f)
    except Exception as e:
        log(f"Error reading config file: {e}", "ERROR")
        return False
    
    # Prepare the patch entries
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
            config['Kernel']['Patch'].append(patch1)
            config['Kernel']['Patch'].append(patch2)
            log("Added both Sonoma VM BT Enabler patches to config.plist", "SUCCESS")
        
    else:
        log("Error: Could not find Kernel -> Patch section in config.plist", "ERROR")
        return False
    
    # Write the updated plist file
    try:
        with open(config_path, 'wb') as f:
            plistlib.dump(config, f)
        
        log(f"Successfully updated {config_path}", "SUCCESS")
        return True
    except Exception as e:
        log(f"Error writing config file: {e}", "ERROR")
        return False

def main():
    """Main function to run the patching process."""
    print_banner()
    log("Starting automatic OpenCore config.plist patching...", "TITLE")
    
    # Check if a direct path was provided
    if len(sys.argv) == 2:
        config_path = sys.argv[1]
        if os.path.exists(config_path):
            log(f"Using provided config path: {config_path}", "INFO")
            success = add_kernel_patches(config_path)
            if success:
                log("Patches applied successfully. Please reboot to apply changes.", "SUCCESS")
            else:
                log("Failed to apply patches.", "ERROR")
            return
        else:
            log(f"Error: File {config_path} does not exist", "ERROR")
            return
    
    # Otherwise search for EFI partitions
    disk_info = get_disk_list()
    if not disk_info:
        log("Failed to get disk information.", "ERROR")
        return
    
    # Extract EFI partitions
    efi_partitions = get_efi_partitions(disk_info)
    if not efi_partitions:
        log("No EFI partitions found.", "ERROR")
        return
    
    log(f"Scanning {len(efi_partitions)} EFI partition(s) for OpenCore configuration", "INFO")
    
    # Check each EFI partition
    for idx, partition in enumerate(efi_partitions):
        log(f"[{idx+1}/{len(efi_partitions)}] Processing partition {partition}", "INFO")
        
        # Mount the EFI partition
        mount_point = mount_efi(partition)
        if not mount_point:
            log(f"Failed to mount {partition}, skipping...", "WARNING")
            continue
        
        try:
            # Look for config.plist
            config_path = find_config_plist(mount_point)
            if config_path:
                # Apply patches directly
                response = input(f"Apply Sonoma VM BT Enabler patch to {config_path}? [y/n]: ").lower()
                if response in ['y', 'yes']:
                    success = add_kernel_patches(config_path)
                    if success:
                        log(f"Successfully patched OpenCore config at {config_path}", "SUCCESS")
                        log("Please reboot your system to apply the changes.", "INFO")
                        
                        response = input("Would you like to restart now? [y/n]: ").lower()
                        if response in ['y', 'yes']:
                            subprocess.run(['shutdown', '-r', 'now'])
                        
                        unmount_efi(partition)
                        return
                    else:
                        log(f"Failed to patch config at {config_path}", "ERROR")
                else:
                    log("Operation cancelled by user.", "INFO")
            else:
                log(f"No OpenCore config.plist found on {partition}", "WARNING")
        finally:
            # Always unmount the partition when done
            unmount_efi(partition)
    
    log("No suitable OpenCore config.plist found or all patching attempts failed", "ERROR")
    log("If you know the location of your config.plist, try running this script "
        "with that path:", "INFO")
    log(f"  sudo python3 {sys.argv[0]} /path/to/config.plist", "INFO")

if __name__ == "__main__":
    # Check if running as root
    if os.geteuid() != 0:
        print(f"{COLORS['RED']}This script requires administrative privileges.{COLORS['RESET']}")
        print(f"Please run with sudo: sudo python3 {sys.argv[0]}")
        sys.exit(1)
    
    main()
