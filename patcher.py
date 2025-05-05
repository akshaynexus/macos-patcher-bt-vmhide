#!/usr/bin/env python3
"""
Ultra-Simple EFI Mounter and Patcher - Resolves Resource Busy issues
"""

import os
import sys
import subprocess
import base64
import plistlib
import time

# ANSI color codes
BLUE = '\033[34m'
GREEN = '\033[32m'
RED = '\033[31m'
YELLOW = '\033[33m'
CYAN = '\033[36m'
RESET = '\033[0m'

def log(message, color=BLUE):
    """Simple colorful logging"""
    timestamp = time.strftime('%H:%M:%S')
    print(f"{color}[{timestamp}] {message}{RESET}")

def print_banner():
    """Display the script banner"""
    banner = """
    ╔═══════════════════════════════════════════════╗
    ║                                               ║
    ║   ███████╗ ██████╗ ███╗   ██╗ ██████╗ ███╗   ███╗ █████╗   ║
    ║   ██╔════╝██╔═══██╗████╗  ██║██╔═══██╗████╗ ████║██╔══██╗  ║
    ║   ███████╗██║   ██║██╔██╗ ██║██║   ██║██╔████╔██║███████║  ║
    ║   ╚════██║██║   ██║██║╚██╗██║██║   ██║██║╚██╔╝██║██╔══██║  ║
    ║   ███████║╚██████╔╝██║ ╚████║╚██████╔╝██║ ╚═╝ ██║██║  ██║  ║
    ║   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝  ║
    ║                                               ║
    ║   VM Bluetooth Enabler - Ultra Simple Mode    ║
    ║                                               ║
    ╚═══════════════════════════════════════════════╝
    """
    print(f"{CYAN}{banner}{RESET}")

def force_clear_mounts():
    """Clear all EFI mounts and processes that might block mounting"""
    # Kill any processes that might be using the disk
    for proc in ["fsck_hfs", "diskimages-helper", "diskmanagementd"]:
        try:
            subprocess.run(["sudo", "killall", proc], 
                          stderr=subprocess.DEVNULL, 
                          stdout=subprocess.DEVNULL)
            log(f"Killed {proc} processes", YELLOW)
        except:
            pass

    # Force unmount any EFI volumes
    try:
        result = subprocess.run(["mount"], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if '/dev/' in line and '/Volumes/EFI' in line:
                device = line.split(' on ')[0]
                log(f"Unmounting: {device}", YELLOW)
                subprocess.run(["sudo", "umount", "-f", device], 
                              stderr=subprocess.DEVNULL, 
                              stdout=subprocess.DEVNULL)
    except:
        pass

    # Clear any stale mount points
    for directory in ["/Volumes/EFI", "/Volumes/EFI-1", "/Volumes/EFI-2"]:
        if os.path.exists(directory):
            try:
                subprocess.run(["sudo", "rmdir", directory], 
                              stderr=subprocess.DEVNULL, 
                              stdout=subprocess.DEVNULL)
                log(f"Removed stale mount point: {directory}", YELLOW)
            except:
                pass
                
    # Create a clean mount point
    try:
        os.makedirs("/Volumes/EFI", exist_ok=True)
    except:
        subprocess.run(["sudo", "mkdir", "-p", "/Volumes/EFI"])

    # Sync disks to flush any pending I/O
    subprocess.run(["sudo", "sync"])

def get_efi_partitions():
    """Get a list of EFI partitions in the system"""
    partitions = []
    
    try:
        result = subprocess.run(['diskutil', 'list'], capture_output=True, text=True)
        
        for line in result.stdout.split('\n'):
            if "EFI" in line and not "Recovery" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "EFI" and i > 0 and parts[i-1].startswith("disk"):
                        partitions.append(parts[i-1])
    except Exception as e:
        log(f"Error getting EFI partitions: {e}", RED)
    
    return partitions

def mount_partition(partition):
    """Try multiple methods to mount an EFI partition"""
    # Ensure we have a clean slate
    force_clear_mounts()
    
    log(f"Mounting {partition} - Attempt with direct system mount...", YELLOW)
    
    # Ultra-direct mount approach
    try:
        # Use direct mount command with options to prevent resource busy
        cmd = ["sudo", "mount", "-t", "msdos", "-o", "sync,noatime", f"/dev/{partition}", "/Volumes/EFI"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if "busy" in result.stderr.lower():
            log("Resource busy error encountered", RED)
            # Wait and try again
            time.sleep(2)
            subprocess.run(["sudo", "sync"])
            result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Check if mount succeeded
        mount_result = subprocess.run(["mount"], capture_output=True, text=True)
        if f"/dev/{partition}" in mount_result.stdout and "/Volumes/EFI" in mount_result.stdout:
            log(f"Successfully mounted {partition} at /Volumes/EFI", GREEN)
            return "/Volumes/EFI"
        
        log(f"System mount failed. Trying diskutil...", YELLOW)
    except Exception as e:
        log(f"Error in system mount: {e}", RED)
    
    # Try diskutil method
    try:
        cmd = ["sudo", "diskutil", "mount", f"/dev/{partition}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if "mounted" in result.stdout:
            mount_point = result.stdout.split("mounted at")[-1].strip()
            log(f"Successfully mounted {partition} at {mount_point}", GREEN)
            return mount_point
        
        log(f"Diskutil mount failed, output: {result.stderr}", RED)
    except Exception as e:
        log(f"Error in diskutil mount: {e}", RED)
    
    # Final attempt with diskutil undocumented options
    try:
        cmd = ["sudo", "diskutil", "mount", "readOnly", f"/dev/{partition}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if "mounted" in result.stdout:
            mount_point = result.stdout.split("mounted at")[-1].strip()
            log(f"Successfully mounted {partition} read-only at {mount_point}", GREEN)
            return mount_point
    except Exception as e:
        log(f"Error in diskutil read-only mount: {e}", RED)
    
    log(f"All mount attempts failed for {partition}", RED)
    return None

def find_config_plist(mount_point):
    """Find OpenCore config.plist"""
    possible_paths = [
        os.path.join(mount_point, 'EFI', 'OC', 'config.plist'),
        os.path.join(mount_point, 'OC', 'config.plist'),
        os.path.join(mount_point, 'config.plist')
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            log(f"Found config.plist at {path}", GREEN)
            return path
    
    # Try find command for a more thorough search
    try:
        result = subprocess.run(
            ['sudo', 'find', mount_point, '-name', 'config.plist'],
            capture_output=True, text=True
        )
        
        if result.stdout.strip():
            path = result.stdout.strip().split('\n')[0]
            log(f"Found config.plist at {path}", GREEN)
            return path
    except:
        pass
    
    log("No config.plist found", RED)
    return None

def add_patches(config_path):
    """Add Sonoma VM BT Enabler patches to config.plist"""
    log(f"Adding patches to {config_path}", BLUE)
    
    # Make backup
    backup_path = f"{config_path}.backup"
    try:
        subprocess.run(['sudo', 'cp', config_path, backup_path], check=True)
        log(f"Created backup at {backup_path}", GREEN)
    except Exception as e:
        log(f"Error creating backup: {e}", RED)
        return False
    
    # Read the file directly with cat
    try:
        result = subprocess.run(['sudo', 'cat', config_path], capture_output=True, check=True)
        plist_data = result.stdout
        config = plistlib.loads(plist_data)
    except Exception as e:
        log(f"Error reading config: {e}", RED)
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
                    log("Patches already exist in config.plist", GREEN)
                    return True
    
    # Create Kernel->Patch if needed
    if 'Kernel' not in config:
        config['Kernel'] = {}
    
    if 'Patch' not in config['Kernel']:
        config['Kernel']['Patch'] = []
    elif not isinstance(config['Kernel']['Patch'], list):
        config['Kernel']['Patch'] = []
    
    # Add patches
    config['Kernel']['Patch'].append(patch1)
    config['Kernel']['Patch'].append(patch2)
    
    # Write the config directly to a temporary file
    try:
        with open('/tmp/config.plist.new', 'wb') as f:
            plistlib.dump(config, f)
        
        # Copy the temporary file to the destination
        subprocess.run(['sudo', 'cp', '/tmp/config.plist.new', config_path], check=True)
        log("Successfully added patches to config.plist", GREEN)
        return True
    except Exception as e:
        log(f"Error writing config: {e}", RED)
        return False

def main():
    """Main function"""
    print_banner()
    log("Starting in ultra-simple mode to resolve mounting issues", BLUE)
    
    # Check for root
    if os.geteuid() != 0:
        log("This script must be run with sudo privileges", RED)
        sys.exit(1)
    
    # Check for direct config path
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        log(f"Using provided config file: {sys.argv[1]}", BLUE)
        if add_patches(sys.argv[1]):
            log("Patches applied successfully. Please restart to apply changes", GREEN)
        else:
            log("Failed to apply patches", RED)
        return
    
    # Force clear mounts before beginning
    force_clear_mounts()
    
    # Get EFI partitions
    partitions = get_efi_partitions()
    if not partitions:
        log("No EFI partitions found", RED)
        return
    
    log(f"Found {len(partitions)} EFI partitions: {', '.join(partitions)}", GREEN)
    
    # Process each partition
    for partition in partitions:
        log(f"Processing partition {partition}", BLUE)
        
        # Mount partition
        mount_point = mount_partition(partition)
        if not mount_point:
            log(f"Skipping {partition} - could not mount", RED)
            continue
        
        # Find config.plist
        config_path = find_config_plist(mount_point)
        if not config_path:
            log(f"No config.plist found on {partition}", YELLOW)
            # Unmount
            subprocess.run(['sudo', 'umount', mount_point], 
                          stderr=subprocess.DEVNULL, 
                          stdout=subprocess.DEVNULL)
            continue
        
        # Ask for confirmation
        response = input(f"Apply Sonoma VM BT Enabler patch to {config_path}? [y/n]: ")
        if response.lower() != 'y':
            log("Skipping this config file", YELLOW)
            # Unmount
            subprocess.run(['sudo', 'umount', mount_point], 
                          stderr=subprocess.DEVNULL, 
                          stdout=subprocess.DEVNULL)
            continue
        
        # Apply patches
        if add_patches(config_path):
            log("Patches applied successfully", GREEN)
            # Unmount
            subprocess.run(['sudo', 'umount', mount_point], 
                          stderr=subprocess.DEVNULL, 
                          stdout=subprocess.DEVNULL)
            
            # Ask for restart
            response = input("Would you like to restart now to apply changes? [y/n]: ")
            if response.lower() == 'y':
                log("Restarting system...", GREEN)
                subprocess.run(['sudo', 'shutdown', '-r', 'now'])
            
            return
        else:
            log("Failed to apply patches", RED)
            # Unmount
            subprocess.run(['sudo', 'umount', mount_point], 
                          stderr=subprocess.DEVNULL, 
                          stdout=subprocess.DEVNULL)
    
    log("No suitable OpenCore config.plist found or all patching attempts failed", RED)
    log("Try specifying the path directly: sudo python3 patcher.py /path/to/config.plist", YELLOW)

if __name__ == "__main__":
    main()
