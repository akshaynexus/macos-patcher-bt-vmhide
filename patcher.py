#!/usr/bin/env python3
"""
EFI Partition Mounter and Patcher for macOS
A reliable tool to mount EFI partitions and apply Sonoma VM BT Enabler patch.
"""

import os
import sys
import subprocess
import base64
import plistlib
import re
import time
import argparse
from datetime import datetime

# ANSI color codes for better readability
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
    """Log a message with color and timestamp."""
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
    ║   (Fixed & Reliable version)                          ║
    ║                                                        ║
    ╚════════════════════════════════════════════════════════╝
    """
    print(f"{COLORS['CYAN']}{banner}{COLORS['RESET']}")

def kill_interfering_processes():
    """Kill processes that might interfere with disk mounting."""
    try:
        # Look for processes that might be keeping disks busy
        for process_name in ["fsck_hfs", "diskimages-helper", "diskmanagementd"]:
            result = subprocess.run(
                ['pgrep', process_name], 
                capture_output=True, 
                text=True
            )
            
            if result.returncode == 0:
                pids = result.stdout.strip().split('\n')
                log(f"Found process {process_name} with PIDs: {', '.join(pids)}", "INFO")
                
                # Ask for confirmation before killing
                response = input(f"Kill {process_name} process(es)? This might help with 'Resource busy' errors. [y/n]: ")
                
                if response.lower() in ['y', 'yes']:
                    for pid in pids:
                        subprocess.run(['sudo', 'kill', '-9', pid])
                    log(f"Killed {process_name} process(es)", "SUCCESS")
    except Exception as e:
        log(f"Error when trying to kill interfering processes: {e}", "ERROR")

def get_disk_list():
    """Get a list of all disks in the system."""
    try:
        result = subprocess.run(
            ['diskutil', 'list'], 
            capture_output=True, 
            text=True
        )
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
        # Track which disk we're examining
        if line.startswith("/dev/"):
            current_disk = line.split()[0]
        
        # Look for EFI partitions (multiple ways to identify them)
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
        result = subprocess.run(
            ['diskutil', 'info', partition], 
            capture_output=True, 
            text=True
        )
        
        # If the partition is mounted, output will contain "Mounted: Yes"
        if "Mounted: Yes" in result.stdout:
            # Extract the mount point
            match = re.search(r'Mount Point:\s+(.*)', result.stdout)
            if match:
                return match.group(1).strip()
        return None
    except Exception:
        return None

def force_unmount_all_efi():
    """Force unmount all EFI partitions to prevent resource busy errors."""
    try:
        # Get a list of all mounted volumes
        result = subprocess.run(['mount'], capture_output=True, text=True)
        
        # Look for EFI volumes
        for line in result.stdout.split('\n'):
            if '/dev/' in line and '/Volumes/EFI' in line:
                device = line.split(' on ')[0]
                log(f"Found mounted EFI: {device}", "INFO")
                
                # Try to unmount
                try:
                    subprocess.run(
                        ['sudo', 'diskutil', 'unmount', 'force', device],
                        capture_output=True
                    )
                    log(f"Forcefully unmounted {device}", "SUCCESS")
                except Exception:
                    log(f"Failed to unmount {device}", "WARNING")
        
        # Also try to remove any lingering mount points
        if os.path.exists('/Volumes/EFI'):
            try:
                subprocess.run(['sudo', 'rmdir', '/Volumes/EFI'], capture_output=True)
                log("Removed lingering /Volumes/EFI mount point", "SUCCESS")
            except Exception:
                pass
    except Exception as e:
        log(f"Error during force unmount: {e}", "ERROR")

def mount_efi(partition, retry=True):
    """Mount an EFI partition using multiple fallback methods.
    
    Args:
        partition: Partition identifier (e.g., /dev/disk0s1)
        retry: Whether to retry with alternative methods if first attempt fails
        
    Returns:
        Mount point if successful, None otherwise
    """
    log(f"Attempting to mount {partition}", "INFO")
    
    # First check if already mounted
    mount_point = check_if_mounted(partition)
    if mount_point:
        log(f"Partition {partition} is already mounted at {mount_point}", "SUCCESS")
        return mount_point
    
    # Before attempting to mount, make sure no EFI partitions are hanging around
    force_unmount_all_efi()
    
    # Create a mount point directory if it doesn't exist
    mount_dir = '/Volumes/EFI'
    if not os.path.exists(mount_dir):
        try:
            subprocess.run(['sudo', 'mkdir', '-p', mount_dir], check=True)
        except Exception:
            log(f"Failed to create mount point at {mount_dir}", "WARNING")
    
    # Method 1: Try with diskutil (requires sudo in newer macOS versions)
    try:
        log("Trying mount method 1: diskutil", "INFO")
        subprocess.run(
            ['sudo', 'diskutil', 'mount', partition], 
            capture_output=True,
            check=True
        )
        
        # Verify mount was successful
        mount_point = check_if_mounted(partition)
        if mount_point:
            log(f"Successfully mounted {partition} at {mount_point}", "SUCCESS")
            return mount_point
    except Exception:
        log("diskutil mount failed, trying alternative methods", "WARNING")
    
    # Method 2: Try direct mount with mount_msdos
    if retry:
        try:
            log("Trying mount method 2: mount_msdos", "INFO")
            subprocess.run(
                ['sudo', 'mount_msdos', partition, mount_dir],
                capture_output=True,
                check=True
            )
            
            # Verify mount was successful
            if os.path.ismount(mount_dir):
                log(f"Successfully mounted {partition} at {mount_dir} using mount_msdos", "SUCCESS")
                return mount_dir
        except Exception:
            log("mount_msdos failed, trying next method", "WARNING")
        
        # Method 3: Try direct mount with mount
        try:
            log("Trying mount method 3: mount", "INFO")
            subprocess.run(
                ['sudo', 'mount', '-t', 'msdos', partition, mount_dir],
                capture_output=True,
                check=True
            )
            
            # Verify mount was successful
            if os.path.ismount(mount_dir):
                log(f"Successfully mounted {partition} at {mount_dir} using mount", "SUCCESS")
                return mount_dir
        except Exception:
            log("mount command failed", "WARNING")
    
    # If we get here, all methods failed
    log(f"Failed to mount {partition} after trying multiple methods", "ERROR")
    
    # Give user some suggestions
    log("Suggestions to fix 'Resource busy' errors:", "INFO")
    log("1. Restart your computer and try again", "INFO")
    log("2. Check Activity Monitor for processes using the disk", "INFO")
    log("3. Try mounting manually: sudo diskutil mount /dev/diskXsY", "INFO")
    
    return None

def unmount_efi(partition):
    """Unmount an EFI partition."""
    log(f"Unmounting {partition}", "INFO")
    
    # Check if the partition is mounted
    mount_point = check_if_mounted(partition)
    if not mount_point:
        log(f"Partition {partition} is not mounted", "INFO")
        return True
    
    # Try force unmount - most reliable method
    try:
        subprocess.run(
            ['sudo', 'diskutil', 'unmount', 'force', partition],
            capture_output=True,
            check=True
        )
        log(f"Successfully unmounted {partition}", "SUCCESS")
        return True
    except Exception:
        log(f"Failed to unmount {partition}", "ERROR")
        log("You may need to restart your computer to unmount properly", "WARNING")
        return False

def find_config_plist(mount_point):
    """Find OpenCore config.plist in the mounted EFI partition."""
    log(f"Searching for OpenCore config.plist", "INFO")
    
    # Common paths for OpenCore config.plist
    possible_paths = [
        os.path.join(mount_point, 'EFI', 'OC', 'config.plist'),
        os.path.join(mount_point, 'OC', 'config.plist'),
        os.path.join(mount_point, 'config.plist')
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            log(f"Found OpenCore config.plist at {path}", "SUCCESS")
            return path
    
    # Additional deep search using system 'find' command
    try:
        find_result = subprocess.run(
            ['sudo', 'find', mount_point, '-name', 'config.plist'],
            capture_output=True,
            text=True
        )
        
        if find_result.returncode == 0 and find_result.stdout.strip():
            paths = find_result.stdout.strip().split('\n')
            for path in paths:
                if os.path.exists(path) and ('OC' in path or 'OpenCore' in path):
                    log(f"Found config.plist at {path}", "SUCCESS")
                    return path
    except Exception:
        pass
    
    log("No OpenCore config.plist found", "WARNING")
    return None

def add_kernel_patches(config_path):
    """Add Sonoma VM BT Enabler kernel patches to config.plist.
    
    This function follows the reliable approach from the working example.
    """
    log("Starting patch process...", "INFO")
    
    # Make a backup of the original file using simple copy command
    backup_path = config_path + '.backup'
    try:
        subprocess.run(['sudo', 'cp', config_path, backup_path], check=True)
        log(f"Backup created at {backup_path}", "SUCCESS")
    except Exception as e:
        log(f"Error creating backup: {e}", "ERROR")
        return False
    
    # Read the plist file with a clean, direct approach
    try:
        # Use subprocess to read the file with sudo privileges
        cat_result = subprocess.run(
            ['sudo', 'cat', config_path],
            capture_output=True,
            check=True
        )
        plist_data = cat_result.stdout
        
        # Parse the plist data
        config = plistlib.loads(plist_data)
        log("Config file loaded successfully", "SUCCESS")
    except Exception as e:
        log(f"Error reading config file: {e}", "ERROR")
        return False
    
    # Prepare the patch entries - using exactly the same data as the working script
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
    
    # Check if patches already exist
    patches_exist = False
    
    if 'Kernel' in config and 'Patch' in config['Kernel']:
        for patch in config['Kernel']['Patch']:
            if isinstance(patch, dict) and 'Comment' in patch:
                if 'Sonoma VM BT Enabler' in patch['Comment']:
                    patches_exist = True
                    log(f"Patch already exists: {patch['Comment']}", "INFO")
    
    if patches_exist:
        log("Patches already exist in config.plist", "SUCCESS")
        return True
    
    # Initialize Kernel->Patch section if needed
    if 'Kernel' not in config:
        config['Kernel'] = {}
    
    if 'Patch' not in config['Kernel']:
        config['Kernel']['Patch'] = []
    elif not isinstance(config['Kernel']['Patch'], list):
        config['Kernel']['Patch'] = []
        log("Warning: Kernel->Patch was not a list. Fixed.", "WARNING")
    
    # Add the patches
    config['Kernel']['Patch'].append(patch1)
    config['Kernel']['Patch'].append(patch2)
    log("Added both Sonoma VM BT Enabler patches to config.plist", "SUCCESS")
    
    # Write the updated plist file - using a two-step approach for reliability
    try:
        # First write to a temporary file
        with open('/tmp/temp_config.plist', 'wb') as f:
            plistlib.dump(config, f)
        
        # Then use sudo to copy it to the destination
        subprocess.run(['sudo', 'cp', '/tmp/temp_config.plist', config_path], check=True)
        log(f"Successfully updated {config_path}", "SUCCESS")
        
        # Clean up
        os.unlink('/tmp/temp_config.plist')
        return True
    except Exception as e:
        log(f"Error writing config file: {e}", "ERROR")
        log(f"Attempting to restore from backup...", "WARNING")
        
        try:
            # Restore from backup
            subprocess.run(['sudo', 'cp', backup_path, config_path], check=True)
            log("Successfully restored from backup", "SUCCESS")
        except Exception as restore_e:
            log(f"Failed to restore from backup: {str(restore_e)}", "ERROR")
        
        return False

def main():
    """Main function to run the patching process."""
    print_banner()
    log("Starting OpenCore config.plist patching for Sonoma VM BT Enabler", "TITLE")
    
    # Check if run with sudo
    if os.geteuid() != 0:
        log("This script requires administrative privileges.", "ERROR")
        log(f"Please run with sudo: sudo python3 {sys.argv[0]}", "INFO")
        sys.exit(1)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Apply Sonoma VM BT Enabler patches to OpenCore config.plist"
    )
    parser.add_argument("config_path", nargs="?", 
                      help="Path to specific config.plist (optional)")
    parser.add_argument("--auto", "-a", action="store_true", 
                      help="Auto-confirm patches without prompting")
    parser.add_argument("--fix-busy", "-f", action="store_true",
                      help="Try to fix 'Resource busy' errors by killing interfering processes")
    args = parser.parse_args()
    
    # Handle Resource Busy errors if requested
    if args.fix_busy:
        log("Attempting to fix 'Resource busy' errors...", "INFO")
        kill_interfering_processes()
        force_unmount_all_efi()
    
    # If a specific config path is provided, use it directly
    if args.config_path:
        if os.path.exists(args.config_path):
            log(f"Using provided config path: {args.config_path}", "INFO")
            
            # Apply patches directly to the specified file
            success = add_kernel_patches(args.config_path)
            if success:
                log("Patches applied successfully. Please reboot to apply changes.", "SUCCESS")
                
                # Ask about restart
                response = input("Would you like to restart now to apply changes? [y/n]: ")
                if response.lower() in ['y', 'yes']:
                    log("Restarting system...", "INFO")
                    subprocess.run(['shutdown', '-r', 'now'])
            else:
                log("Failed to apply patches.", "ERROR")
        else:
            log(f"Error: File {args.config_path} does not exist", "ERROR")
        return
    
    # Otherwise, search for EFI partitions
    disk_info = get_disk_list()
    if not disk_info:
        log("Failed to get disk information.", "ERROR")
        return
    
    # Extract EFI partitions
    efi_partitions = get_efi_partitions(disk_info)
    if not efi_partitions:
        log("No EFI partitions found.", "ERROR")
        log("Consider checking your disk format or try running in recovery mode.", "INFO")
        return
    
    log(f"Found {len(efi_partitions)} EFI partition(s). Checking for OpenCore configs...", "INFO")
    
    # Process each EFI partition
    for idx, partition in enumerate(efi_partitions):
        log(f"Processing partition {partition} ({idx+1}/{len(efi_partitions)})", "INFO")
        
        # Mount the EFI partition
        mount_point = mount_efi(partition)
        if not mount_point:
            log(f"Failed to mount {partition}, skipping...", "WARNING")
            continue
        
        try:
            # Look for config.plist
            config_path = find_config_plist(mount_point)
            if config_path:
                log(f"Found OpenCore config at {config_path}", "SUCCESS")
                
                # Ask for confirmation before patching
                if not args.auto:
                    response = input(f"Apply Sonoma VM BT Enabler patch to {config_path}? [y/n]: ")
                    if response.lower() not in ['y', 'yes']:
                        log("Skipping this config file.", "INFO")
                        continue
                
                # Apply patches
                success = add_kernel_patches(config_path)
                if success:
                    log(f"Successfully patched {config_path}", "SUCCESS")
                    log("Please reboot your system to apply the changes.", "INFO")
                    
                    # Unmount before asking about restart
                    unmount_efi(partition)
                    
                    # Ask about restart
                    if not args.auto:
                        response = input("Would you like to restart now to apply changes? [y/n]: ")
                        if response.lower() in ['y', 'yes']:
                            log("Restarting system...", "INFO")
                            subprocess.run(['shutdown', '-r', 'now'])
                    
                    return  # Exit after successful patching
                else:
                    log(f"Failed to patch {config_path}", "ERROR")
            else:
                log(f"No OpenCore config.plist found on {partition}", "WARNING")
        finally:
            # Always unmount when done
            unmount_efi(partition)
    
    log("No suitable OpenCore config.plist found or all patching attempts failed", "ERROR")
    log("If you know the location of your config.plist, try specifying it directly:", "INFO")
    log(f"  sudo python3 {sys.argv[0]} /path/to/config.plist", "INFO")

if __name__ == "__main__":
    main()
