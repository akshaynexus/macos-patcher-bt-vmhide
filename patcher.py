#!/usr/bin/env python3
"""
Simple Sonoma VM BT Patcher
A minimalist script to patch OpenCore config.plist for Bluetooth support in Sonoma VMs.
"""

import os
import sys
import subprocess
import base64
import plistlib
import time

# Basic colored output
GREEN = "\033[32m"
RED = "\033[31m"
BLUE = "\033[34m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"

def print_step(message):
    """Print a step in the process with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"{BLUE}[{timestamp}] {message}{RESET}")

def print_success(message):
    """Print a success message"""
    print(f"{GREEN}✓ {message}{RESET}")

def print_error(message):
    """Print an error message"""
    print(f"{RED}✗ {message}{RESET}")

def print_warning(message):
    """Print a warning message"""
    print(f"{YELLOW}! {message}{RESET}")

def print_banner():
    """Display a simple banner"""
    banner = f"""
{CYAN}╔════════════════════════════════════════════════════╗
║                                                    ║
║  Sonoma VM Bluetooth Patcher                       ║
║  Simple and Direct Version                         ║
║                                                    ║
╚════════════════════════════════════════════════════╝{RESET}
"""
    print(banner)

def run_command(cmd, silent=False):
    """Run a command and return the output and success status"""
    if not silent:
        print_step(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        success = result.returncode == 0
        return success, result.stdout, result.stderr
    except Exception as e:
        if not silent:
            print_error(f"Command failed: {e}")
        return False, "", str(e)

def kill_blocking_processes():
    """Kill processes that might block EFI mounting"""
    print_step("Killing processes that might block EFI mounting")
    
    # List of processes known to cause "resource busy" errors
    processes = ["fsck_hfs", "diskimages-helper", "diskmanagementd"]
    
    for proc in processes:
        run_command(["sudo", "killall", proc], silent=True)
    
    # Force unmount any existing EFI volumes
    success, mount_output, _ = run_command(["mount"], silent=True)
    if success:
        for line in mount_output.split('\n'):
            if "/Volumes/EFI" in line and "/dev/" in line:
                device = line.split()[0]
                print_step(f"Force unmounting {device}")
                run_command(["sudo", "umount", "-f", device], silent=True)

def find_efi_partitions():
    """Find all EFI partitions in the system"""
    print_step("Finding EFI partitions")
    
    success, output, _ = run_command(["diskutil", "list"])
    if not success:
        print_error("Failed to list disks")
        return []
    
    efi_partitions = []
    current_disk = None
    
    for line in output.split('\n'):
        # Track current disk
        if line.startswith("/dev/disk"):
            current_disk = line.split()[0]
        
        # Look for EFI partitions
        if "EFI" in line and current_disk:
            parts = line.split()
            for i, part in enumerate(parts):
                # Format is typically: 1: EFI EFI 209.7 MB disk0s1
                if part == "EFI" and i > 0:
                    try:
                        disk_id = parts[-1]  # Last part is usually the identifier
                        if disk_id.startswith("disk"):
                            efi_partitions.append(disk_id)
                    except IndexError:
                        pass
    
    if efi_partitions:
        print_success(f"Found EFI partitions: {', '.join(efi_partitions)}")
    else:
        print_error("No EFI partitions found")
    
    return efi_partitions

def mount_efi(partition):
    """Mount an EFI partition using direct mount command"""
    print_step(f"Mounting EFI partition: {partition}")
    
    # Ensure /Volumes/EFI exists
    if not os.path.exists("/Volumes/EFI"):
        run_command(["sudo", "mkdir", "-p", "/Volumes/EFI"], silent=True)
    
    # Force sync to flush pending disk operations
    run_command(["sudo", "sync"], silent=True)
    
    # Approach 1: Use diskutil directly
    success, output, error = run_command(["sudo", "diskutil", "mount", partition])
    if success and "mounted" in output:
        # Extract mount point from output
        for line in output.split('\n'):
            if "mounted at" in line:
                mount_point = line.split("mounted at")[-1].strip()
                print_success(f"Mounted at {mount_point}")
                return mount_point
        
        # If mount point not found in output but command succeeded
        print_success(f"Mounted at /Volumes/EFI")
        return "/Volumes/EFI"
    
    # If we got a resource busy error, try to recover
    if "resource busy" in error.lower():
        print_warning("Resource busy error detected, trying to recover...")
        kill_blocking_processes()
        time.sleep(1)  # Give system time to clean up
        
        # Approach 2: Try direct mount command
        print_step("Trying direct mount command")
        success, _, error = run_command([
            "sudo", "mount", "-t", "msdos", 
            f"/dev/{partition}", "/Volumes/EFI"
        ])
        
        if success:
            print_success("Mounted at /Volumes/EFI")
            return "/Volumes/EFI"
    
    # Approach 3: Try mount with readonly option
    print_step("Trying read-only mount")
    success, output, _ = run_command([
        "sudo", "diskutil", "mount", "readOnly", partition
    ])
    
    if success and "mounted" in output:
        for line in output.split('\n'):
            if "mounted at" in line:
                mount_point = line.split("mounted at")[-1].strip()
                print_success(f"Mounted read-only at {mount_point}")
                return mount_point
    
    print_error(f"Failed to mount {partition}")
    return None

def unmount_efi(partition):
    """Unmount an EFI partition"""
    print_step(f"Unmounting {partition}")
    
    # First try normal unmount
    success, _, _ = run_command(["sudo", "diskutil", "unmount", partition])
    if success:
        print_success(f"Unmounted {partition}")
        return True
    
    # If that fails, try force unmount
    print_warning("Normal unmount failed, trying force unmount")
    success, _, _ = run_command(["sudo", "diskutil", "unmount", "force", partition])
    if success:
        print_success(f"Force unmounted {partition}")
        return True
    
    print_error(f"Failed to unmount {partition}")
    return False

def find_config_plist(mount_point):
    """Find OpenCore config.plist file"""
    print_step(f"Searching for config.plist in {mount_point}")
    
    # Common locations
    possible_paths = [
        os.path.join(mount_point, "EFI", "OC", "config.plist"),
        os.path.join(mount_point, "OC", "config.plist"),
        os.path.join(mount_point, "config.plist")
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            print_success(f"Found config.plist at {path}")
            return path
    
    # If not found in common locations, try find command
    print_step("Searching with find command")
    success, output, _ = run_command([
        "sudo", "find", mount_point, "-name", "config.plist"
    ])
    
    if success and output.strip():
        path = output.strip().split('\n')[0]
        print_success(f"Found config.plist at {path}")
        return path
    
    print_error("No config.plist found")
    return None

def apply_patches(config_path):
    """Apply Sonoma VM BT Enabler patches to config.plist"""
    print_step(f"Applying patches to {config_path}")
    
    # Create backup
    backup_path = f"{config_path}.backup"
    success, _, _ = run_command(["sudo", "cp", config_path, backup_path])
    if not success:
        print_error("Failed to create backup")
        return False
    
    print_success(f"Created backup at {backup_path}")
    
    # Read config.plist
    success, output, _ = run_command(["sudo", "cat", config_path])
    if not success:
        print_error("Failed to read config.plist")
        return False
    
    try:
        config = plistlib.loads(output.encode('utf-8'))
    except Exception as e:
        print_error(f"Failed to parse config.plist: {e}")
        return False
    
    # Create patches
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
    if 'Kernel' in config and 'Patch' in config['Kernel']:
        for patch in config['Kernel']['Patch']:
            if isinstance(patch, dict) and 'Comment' in patch:
                if 'Sonoma VM BT Enabler' in patch['Comment']:
                    print_success("Patches already exist in config.plist")
                    return True
    
    # Create or update Kernel -> Patch
    if 'Kernel' not in config:
        config['Kernel'] = {}
    
    if 'Patch' not in config['Kernel']:
        config['Kernel']['Patch'] = []
    
    # Add patches
    config['Kernel']['Patch'].append(patch1)
    config['Kernel']['Patch'].append(patch2)
    
    # Write to temporary file first
    try:
        with open('/tmp/config.plist', 'wb') as f:
            plistlib.dump(config, f)
    except Exception as e:
        print_error(f"Failed to write temporary config: {e}")
        return False
    
    # Copy temporary file to destination
    success, _, _ = run_command([
        "sudo", "cp", "/tmp/config.plist", config_path
    ])
    
    if success:
        print_success("Successfully applied patches")
        return True
    else:
        print_error("Failed to write updated config.plist")
        # Restore backup
        run_command(["sudo", "cp", backup_path, config_path])
        return False

def main():
    """Main function with linear execution flow"""
    print_banner()
    
    # Check if running as root
    if os.geteuid() != 0:
        print_error("This script must be run with sudo privileges")
        print(f"Please run: sudo python3 {sys.argv[0]}")
        return
    
    # Clear any blocking processes
    kill_blocking_processes()
    
    # Check for direct config path
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        print_step(f"Using provided config path: {sys.argv[1]}")
        if apply_patches(sys.argv[1]):
            print_success("Patches applied successfully")
        else:
            print_error("Failed to apply patches")
        return
    
    # Find EFI partitions
    efi_partitions = find_efi_partitions()
    if not efi_partitions:
        return
    
    # Process each partition
    for partition in efi_partitions:
        print_step(f"Processing partition: {partition}")
        
        # Mount EFI
        mount_point = mount_efi(partition)
        if not mount_point:
            print_warning(f"Skipping {partition} - could not mount")
            continue
        
        # Find config.plist
        config_path = find_config_plist(mount_point)
        if not config_path:
            print_warning(f"No config.plist found on {partition}")
            unmount_efi(partition)
            continue
        
        # Ask for confirmation
        response = input(f"Apply Sonoma VM BT Enabler patches to {config_path}? [y/n]: ")
        if response.lower() != 'y':
            print_warning(f"Skipping {config_path}")
            unmount_efi(partition)
            continue
        
        # Apply patches
        success = apply_patches(config_path)
        
        # Unmount
        unmount_efi(partition)
        
        if success:
            print_success("Patching completed successfully")
            response = input("Would you like to restart now to apply changes? [y/n]: ")
            if response.lower() == 'y':
                print_step("Restarting system...")
                run_command(["sudo", "shutdown", "-r", "now"])
            return
    
    print_warning("No suitable OpenCore config.plist found or all patching attempts failed")
    print(f"Try running with a direct path: sudo python3 {sys.argv[0]} /path/to/config.plist")

if __name__ == "__main__":
    main()
