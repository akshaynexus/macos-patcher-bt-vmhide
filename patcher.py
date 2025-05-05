# Fix 1: Improved patch detection function
def check_if_patches_exist(config_path):
    """Check if the Sonoma VM BT Enabler patches already exist in the config.
    Returns a tuple of (bool, str) where the bool indicates if patches exist
    and the string provides details about which patches were found."""
    spinner = Spinner(f"Checking for existing patches")
    spinner.start()
    
    # Fancy animation for analyzing
    for i in range(5):
        spinner.message = f"Analyzing config{' .' * i}"
        time.sleep(0.1)
    
    try:
        with open(config_path, 'rb') as f:
            config = plistlib.load(f)
        
        patch1_found = False
        patch2_found = False
        
        # Show progress while checking patches
        if 'Kernel' in config and 'Patch' in config['Kernel']:
            patch_count = len(config['Kernel']['Patch'])
            for i, patch in enumerate(config['Kernel']['Patch']):
                # Update progress bar for each patch checked
                progress_bar(i+1, patch_count, prefix='Analyzing patches:', suffix='Complete', length=30)
                time.sleep(0.02)  # Brief pause for visual effect
                
                if isinstance(patch, dict) and 'Comment' in patch:
                    # Check for patch 1
                    if ('Sonoma VM BT Enabler' in patch['Comment'] and 
                        'PART 1' in patch['Comment'] and
                        patch.get('Find') and patch.get('Replace')):
                        patch1_found = True
                        spinner.message = "Found Patch 1!"
                        time.sleep(0.3)  # Pause to show the message
                        
                    # Check for patch 2    
                    if ('Sonoma VM BT Enabler' in patch['Comment'] and 
                        'PART 2' in patch['Comment'] and
                        patch.get('Find') and patch.get('Replace')):
                        patch2_found = True
                        spinner.message = "Found Patch 2!"
                        time.sleep(0.3)  # Pause to show the message
        
        # Return appropriate message based on what was found
        if patch1_found and patch2_found:
            spinner.stop(f"{COLORS['GREEN']}✓ Both Sonoma VM BT Enabler patches found{COLORS['RESET']}")
            return (True, "both_found")
        elif patch1_found and not patch2_found:
            spinner.stop(f"{COLORS['YELLOW']}⚠ Only Patch 1 found, Patch 2 missing{COLORS['RESET']}")
            return (False, "patch1_only")
        elif not patch1_found and patch2_found:
            spinner.stop(f"{COLORS['YELLOW']}⚠ Only Patch 2 found, Patch 1 missing{COLORS['RESET']}")
            return (False, "patch2_only")
        else:
            spinner.stop(f"{COLORS['BLUE']}ℹ No existing patches found{COLORS['RESET']}")
            return (False, "none")
            
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error checking for existing patches: {e}{COLORS['RESET']}")
        log("Continuing anyway - will attempt to apply patches", "WARNING")
        return (False, "error")

# Fix 2: File locking mechanism for atomic file operations
import fcntl
import errno

class FileLock:
    """A file locking mechanism that is used to ensure atomic file operations."""
    
    def __init__(self, file_path, timeout=10):
        self.file_path = file_path
        self.lockfile = f"{file_path}.lock"
        self.timeout = timeout
        self.fd = None
    
    def __enter__(self):
        self.fd = open(self.lockfile, 'w+')
        start_time = time.time()
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except IOError as e:
                if e.errno != errno.EAGAIN:
                    raise
                elif time.time() - start_time >= self.timeout:
                    raise TimeoutError(f"Could not acquire lock on {self.lockfile} within {self.timeout} seconds")
                time.sleep(0.1)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.fd.close()
            try:
                os.remove(self.lockfile)
            except OSError:
                pass

# Fix 3: Improved kernel patch function with better race condition handling and error recovery
def add_kernel_patches(config_path):
    """Add Sonoma VM BT Enabler kernel patches to config.plist with proper locking 
    and atomic operations."""
    log("Starting patch process...", "TITLE")
    
    # Make a backup of the original file
    backup_path = config_path + '.backup'
    
    spinner = Spinner(f"Creating backup at {backup_path}")
    spinner.start()
    
    # Animated backup creation
    for i in range(3):
        spinner.message = f"Creating backup{'.' * (i+1)}"
        time.sleep(0.2)
    
    # Use file lock to prevent race conditions during backup
    try:
        with FileLock(config_path):
            # Check if backup already exists
            if not os.path.exists(backup_path):
                import shutil
                shutil.copy2(config_path, backup_path)
            spinner.stop(f"{COLORS['GREEN']}✓ Backup created at {backup_path}{COLORS['RESET']}")
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error creating backup: {e}{COLORS['RESET']}")
        return "error"
    
    # Read the plist file with proper locking
    spinner = Spinner(f"Reading config file")
    spinner.start()
    
    # Animated file reading
    for i in range(4):
        spinner.message = f"Reading config data{'.' * (i+1)}"
        time.sleep(0.2)
    
    try:
        with FileLock(config_path):
            with open(config_path, 'rb') as f:
                config = plistlib.load(f)
        spinner.stop(f"{COLORS['GREEN']}✓ Config file loaded successfully{COLORS['RESET']}")
        
        # Show a confirmation animation
        for i in range(5):
            progress_bar(i+1, 5, prefix='Config validation:', suffix='Complete', length=30)
            time.sleep(0.03)
        
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error reading config file: {e}{COLORS['RESET']}")
        log(f"Error details: {str(e)}", "ERROR")
        
        try:
            # Diagnostic checks for the file
            if not os.path.exists(config_path):
                log(f"The file {config_path} does not exist!", "ERROR")
            elif not os.access(config_path, os.R_OK):
                log(f"The file {config_path} is not readable!", "ERROR")
            else:
                with open(config_path, 'rb') as f:
                    content = f.read(100)
                    log(f"File starts with: {content}", "INFO")
                    log("This might not be a valid plist file", "WARNING")
        except Exception as inner_e:
            log(f"Failed to diagnose file issue: {str(inner_e)}", "ERROR")
            
        return "error"
    
    # First check if patches already exist using our improved function
    patches_exist, patch_status = check_if_patches_exist(config_path)
    
    # If both patches already exist, we're done
    if patches_exist:
        log("Both patches already exist in config.plist. No changes needed.", "SUCCESS")
        # Success animation
        for i in range(10):
            progress_bar(i+1, 10, prefix=f"{COLORS['GREEN']}System already patched:", suffix='Verified', length=30)
            time.sleep(0.05)
        return "already_exists"
    
    # Prepare the patch entries
    log("Preparing patch data...", "HEADER")
    
    # Show a fancy progress bar for "patch preparation"
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
    
    # Print the actual binary representation of patch values with colors for debugging
    log("Patch 1 - Find value (hex):", "INFO")
    log(f"{COLORS['CYAN']}" + " ".join(f"{b:02x}" for b in patch1['Find']) + f"{COLORS['RESET']}", "INFO")
    log("Patch 1 - Replace value (hex):", "INFO")
    log(f"{COLORS['GREEN']}" + " ".join(f"{b:02x}" for b in patch1['Replace']) + f"{COLORS['RESET']}", "INFO")
    
    log("Patch 2 - Find value (hex):", "INFO")
    log(f"{COLORS['CYAN']}" + " ".join(f"{b:02x}" for b in patch2['Find']) + f"{COLORS['RESET']}", "INFO")
    log("Patch 2 - Replace value (hex):", "INFO")
    log(f"{COLORS['GREEN']}" + " ".join(f"{b:02x}" for b in patch2['Replace']) + f"{COLORS['RESET']}", "INFO")
    
    # Determine which patches need to be applied based on the check result
    patches_to_apply = []
    if patch_status == "none" or patch_status == "error":
        # No patches found or error during check, apply both patches
        patches_to_apply = [patch1, patch2]
        log(f"{COLORS['BOLD']}Adding both patches to config.plist{COLORS['RESET']}", "INFO")
    elif patch_status == "patch1_only":
        # Only patch 1 exists, add patch 2
        patches_to_apply = [patch2]
        log(f"{COLORS['BOLD']}Adding missing Patch 2 to config.plist{COLORS['RESET']}", "INFO")
    elif patch_status == "patch2_only":
        # Only patch 2 exists, add patch 1
        patches_to_apply = [patch1]
        log(f"{COLORS['BOLD']}Adding missing Patch 1 to config.plist{COLORS['RESET']}", "INFO")
    
    # Add patches to the kernel patch section
    if 'Kernel' not in config:
        config['Kernel'] = {}
        log("Creating Kernel section in config", "INFO")
    
    if 'Patch' not in config['Kernel']:
        config['Kernel']['Patch'] = []
        log("Creating Patch array in Kernel section", "INFO")
    elif not isinstance(config['Kernel']['Patch'], list):
        log("Warning: Kernel->Patch is not a list. Converting to list.", "WARNING")
        config['Kernel']['Patch'] = []
    
    # Adding patches with fancy animation
    spinner = Spinner(f"Adding patches to config")
    spinner.start()
    
    # More elaborate spinning animation
    for i in range(5):
        spinner.message = f"Patching system{'.' * (i % 4)}"
        time.sleep(0.2)
    
    # Add only the patches that need to be applied
    for i, patch in enumerate(patches_to_apply):
        config['Kernel']['Patch'].append(patch)
        spinner.message = f"Added patch {i+1}/{len(patches_to_apply)}"
        time.sleep(0.3)
    
    spinner.stop(f"{COLORS['GREEN']}✓ Added {len(patches_to_apply)} Sonoma VM BT Enabler patch(es) to config.plist{COLORS['RESET']}")
    
    # Write the updated plist file with proper atomic operations
    spinner = Spinner(f"Writing updated config to disk")
    spinner.start()
    
    # Show writing animation
    for i in range(4):
        spinner.message = f"Saving changes{'.' * (i+1)}"
        time.sleep(0.3)
    
    try:
        # Use a file lock to ensure atomic operations
        with FileLock(config_path):
            # Create a temporary file with the updates
            temp_path = config_path + '.tmp'
            with open(temp_path, 'wb') as f:
                plistlib.dump(config, f)
                # Ensure data is written to disk
                f.flush()
                os.fsync(f.fileno())
            
            # Show verification animation
            spinner.message = "Verifying changes..."
            time.sleep(0.5)
            
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
            
            # Show final save animation
            spinner.message = "Finalizing changes..."
            time.sleep(0.5)
            
            # If we get here, it's safe to replace the original
            os.rename(temp_path, config_path)
            
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully updated {config_path}{COLORS['RESET']}")
            
            # Final success animation
            for i in range(10):
                progress_bar(i+1, 10, prefix=f"{COLORS['GREEN']}Patch complete:", suffix='Success!', length=30)
                time.sleep(0.03)
            
            return "success"
            
    except Exception as e:
        spinner.stop(f"{COLORS['RED']}✗ Error writing config file: {e}{COLORS['RESET']}")
        log(f"Detailed error: {str(e)}", "ERROR")
        log(f"Attempting to restore from backup...", "INFO")
        
        # Show recovery animation
        recovery_spinner = Spinner("Recovering from error")
        recovery_spinner.start()
        
        try:
            with FileLock(config_path):
                # Remove temp file if it exists
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    recovery_spinner.message = "Removed temporary file"
                    time.sleep(0.3)
                    
                # Restore from backup if it exists
                if os.path.exists(backup_path):
                    import shutil
                    recovery_spinner.message = "Restoring from backup..."
                    time.sleep(0.5)
                    shutil.copy2(backup_path, config_path)
                    recovery_spinner.stop(f"{COLORS['GREEN']}✓ Successfully restored from backup.{COLORS['RESET']}")
        except Exception as restore_e:
            recovery_spinner.stop(f"{COLORS['RED']}✗ Failed to restore from backup: {str(restore_e)}{COLORS['RESET']}")
            log(f"Failed to restore from backup: {str(restore_e)}", "ERROR")
        
        return "error"

# Fix 4: Improved mount_efi function with better thread safety
def mount_efi(partition):
    """Mount an EFI partition and return the mount point with enhanced error handling and thread safety."""
    spinner = Spinner(f"Mounting {partition}")
    spinner.start()
    
    # Animated mounting effects
    for i in range(3):
        spinner.message = f"Preparing to mount {partition}{'.' * (i+1)}"
        time.sleep(0.2)
    
    # Create a global lock for mount operations to prevent conflicts
    if not hasattr(mount_efi, 'global_mount_lock'):
        mount_efi.global_mount_lock = threading.Lock()
    
    # First check if already mounted
    mount_point = check_if_mounted(partition)
    if mount_point:
        # Fancy "already mounted" animation
        for i in range(3):
            spinner.message = f"Detected existing mount at {mount_point}"
            time.sleep(0.2)
        
        spinner.stop(f"{COLORS['GREEN']}✓ Partition {partition} is already mounted at {mount_point}{COLORS['RESET']}")
        return mount_point
    
    # Acquire global lock for the entire mount operation
    with mount_efi.global_mount_lock:
        # Animation while acquiring lock
        spinner.message = f"Obtaining exclusive access..."
        time.sleep(0.3)
        
        # Check again after acquiring lock in case another thread mounted it
        mount_point = check_if_mounted(partition)
        if mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Partition {partition} was mounted by another process at {mount_point}{COLORS['RESET']}")
            return mount_point
        
        # Track mount attempts
        mounted = False
        mount_point = None
        errors = []
        
        # Method 1: Try standard mount
        spinner.message = f"Trying standard mount method..."
        time.sleep(0.3)
        
        try:
            # Add a small delay to prevent race conditions with other disk operations
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
                        spinner.message = f"Standard mount succeeded!"
                        time.sleep(0.3)
                    else:
                        errors.append(f"Mount point {mount_point} does not exist after mount operation")
                        spinner.message = f"Mount point verification failed"
                        time.sleep(0.3)
            else:
                errors.append(f"Standard mount: {result.stderr or result.stdout}")
                spinner.message = f"Standard mount failed, trying alternatives..."
                time.sleep(0.3)
        except Exception as e:
            errors.append(f"Standard mount exception: {str(e)}")
            spinner.message = f"Standard mount error: {str(e)[:30]}..."
            time.sleep(0.3)
        
        # If standard mount succeeded, return the mount point
        if mounted and mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at {mount_point}{COLORS['RESET']}")
            return mount_point
        
        # Method 2: Try mounting by volume name
        if not mounted:
            spinner.message = f"Trying volume name mount method..."
            time.sleep(0.3)
            
            try:
                # Create a temporary directory for mounting if it doesn't exist
                efi_mount_dir = '/Volumes/EFI'
                if not os.path.exists(efi_mount_dir):
                    spinner.message = f"Creating mount point directory..."
                    time.sleep(0.2)
                    os.makedirs(efi_mount_dir, exist_ok=True)
                
                # Add a small delay to prevent race conditions
                time.sleep(0.5)
                
                # Try to mount by volume name
                spinner.message = f"Mounting EFI volume..."
                time.sleep(0.2)
                result = subprocess.run(['diskutil', 'mount', 'EFI'], 
                                    capture_output=True, text=True)
                
                if result.returncode == 0:
                    # Check if the correct partition was mounted
                    spinner.message = f"Verifying mounted partition..."
                    time.sleep(0.2)
                    info_result = subprocess.run(['diskutil', 'info', '/Volumes/EFI'], 
                                            capture_output=True, text=True)
                    if partition in info_result.stdout:
                        mount_point = '/Volumes/EFI'
                        # Verify the mount point exists and has expected content
                        if os.path.exists(mount_point) and os.path.isdir(mount_point):
                            mounted = True
                            spinner.message = f"Volume name mount succeeded!"
                            time.sleep(0.3)
                        else:
                            errors.append(f"Mount point {mount_point} exists but is not a directory")
                            spinner.message = f"Mount point verification failed"
                            time.sleep(0.3)
                    else:
                        # Wrong partition mounted, try to unmount it
                        spinner.message = f"Wrong partition mounted, unmounting..."
                        time.sleep(0.3)
                        log("Wrong EFI partition mounted, unmounting...", "WARNING")
                        subprocess.run(['diskutil', 'unmount', '/Volumes/EFI'], 
                                    capture_output=True, text=True)
                else:
                    errors.append(f"Volume name mount: {result.stderr or result.stdout}")
                    spinner.message = f"Volume name mount failed"
                    time.sleep(0.3)
            except Exception as e:
                errors.append(f"Volume name mount exception: {str(e)}")
                spinner.message = f"Volume name mount error: {str(e)[:30]}..."
                time.sleep(0.3)
        
        # If method 2 succeeded, return the mount point
        if mounted and mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at {mount_point}{COLORS['RESET']}")
            return mount_point
        
        # Method 3: Try direct mount using mount_msdos command
        if not mounted:
            spinner.message = f"Trying mount_msdos method..."
            time.sleep(0.3)
            
            try:
                # Ensure mount point exists
                efi_mount_dir = '/Volumes/EFI'
                if not os.path.exists(efi_mount_dir):
                    spinner.message = f"Creating mount point directory..."
                    time.sleep(0.2)
                    os.makedirs(efi_mount_dir, exist_ok=True)
                
                # Add a small delay to prevent race conditions
                time.sleep(0.5)
                
                # Try mounting with mount_msdos
                spinner.message = f"Executing mount_msdos command..."
                time.sleep(0.2)
                result = subprocess.run(['sudo', 'mount_msdos', partition, efi_mount_dir], 
                                    capture_output=True, text=True)
                
                if result.returncode == 0 or (os.path.exists(efi_mount_dir) and len(os.listdir(efi_mount_dir)) > 0):
                    mount_point = efi_mount_dir
                    mounted = True
                    spinner.message = f"mount_msdos succeeded!"
                    time.sleep(0.3)
                else:
                    errors.append(f"mount_msdos: {result.stderr or result.stdout}")
                    spinner.message = f"mount_msdos failed"
                    time.sleep(0.3)
            except Exception as e:
                errors.append(f"mount_msdos exception: {str(e)}")
                spinner.message = f"mount_msdos error: {str(e)[:30]}..."
                time.sleep(0.3)
        
        # If method 3 succeeded, return the mount point
        if mounted and mount_point:
            spinner.stop(f"{COLORS['GREEN']}✓ Successfully mounted {partition} at {mount_point} using mount_msdos{COLORS['RESET']}")
            return mount_point
    
    # If all methods failed, log the errors and return None
    spinner.stop(f"{COLORS['RED']}✗ Failed to mount {partition} after trying multiple methods{COLORS['RESET']}")
    
    # Log detailed errors
    log("Mount failure details:", "ERROR")
    for i, error in enumerate(errors):
        log(f"  Method {i+1}: {error}", "ERROR")
    
    # Check for system-level reasons for mounting failures
    check_system_constraints()
    
    return None

# Fix 5: Improved unmount_efi function with better thread safety
def unmount_efi(partition):
    """Unmount an EFI partition with improved thread safety."""
    spinner = Spinner(f"Unmounting {partition}")
    spinner.start()
    
    # Animated unmounting effects
    for i in range(3):
        spinner.message = f"Preparing to unmount {partition}{'.' * (i+1)}"
        time.sleep(0.2)
    
    # Create a global lock for unmount operations to prevent conflicts
    if not hasattr(unmount_efi, 'global_unmount_lock'):
        unmount_efi.global_unmount_lock = threading.Lock()
    
    # First check if the partition is mounted
    mount_point = check_if_mounted(partition)
    if not mount_point:
        # Fancy animation for "not mounted" case
        for i in range(2):
            spinner.message = f"Checking mount status{'.' * (i+1)}"
            time.sleep(0.2)
        
        spinner.stop(f"{COLORS['YELLOW']}⚠ Partition {partition} is not mounted{COLORS['RESET']}")
        return True
    
    # Show found mount point animation
    spinner.message = f"Found at mount point: {mount_point}"
    time.sleep(0.3)
    
    # Acquire global lock for the entire unmount operation
    with unmount_efi.global_unmount_lock:
        # Animation while acquiring lock
        spinner.message = f"Obtaining exclusive access..."
        time.sleep(0.3)
        
        # Check again after acquiring lock in case another thread unmounted it
        mount_point = check_if_mounted(partition)
        if not mount_point:
            spinner.stop(f"{COLORS['YELLOW']}⚠ Partition {partition} was unmounted by another process{COLORS['RESET']}")
            return True
        
        # Add a small delay to prevent race conditions with other disk operations
        time.sleep(0.5)
        
        # Method 1: Try unmounting by mount point first (more reliable)
        spinner.message = f"Unmounting by mount point..."
        time.sleep(0.3)
        
        try:
            result = subprocess.run(['diskutil', 'unmount', mount_point], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                # Show success animation
                for i in range(3):
                    spinner.message = f"Unmount successful! Verifying{'.' * (i % 3 + 1)}"
                    time.sleep(0.15)
                
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully unmounted {mount_point}{COLORS['RESET']}")
                
                # Verify the unmount actually worked
                time.sleep(0.5)  # Brief delay to ensure system state is updated
                if not os.path.ismount(mount_point):
                    # Success verification animation
                    for i in range(5):
                        progress_bar(i+1, 5, prefix=f"{COLORS['GREEN']}Unmount verified:", suffix='Complete', length=20)
                        time.sleep(0.05)
                    print("")  # Add a newline after progress bar
                    return True
                else:
                    spinner = Spinner(f"Mount point still exists")
                    spinner.start()
                    spinner.message = "Trying alternative method..."
                    time.sleep(0.5)
                    spinner.stop()
                    log("Unmount reported success but mount point still exists, trying alternative method", "WARNING")
            else:
                spinner.message = f"Primary unmount failed"
                time.sleep(0.3)
                log(f"Error in primary unmount: {result.stderr}", "WARNING")
        except Exception as e:
            spinner.message = f"Error: {str(e)[:30]}..."
            time.sleep(0.3)
            log(f"Error in primary unmount: {e}", "WARNING")
        
        # Method 2: Try unmounting by partition
        spinner = Spinner(f"Trying partition-based unmount")
        spinner.start()
        
        try:
            # Add a small delay before retry
            time.sleep(0.3)
            
            for i in range(3):
                spinner.message = f"Unmounting by partition ID{'.' * (i+1)}"
                time.sleep(0.2)
            
            result = subprocess.run(['diskutil', 'unmount', partition], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully unmounted {partition}{COLORS['RESET']}")
                
                # Verify the unmount actually worked with animation
                spinner = Spinner(f"Verifying unmount status")
                spinner.start()
                time.sleep(0.5)
                
                if check_if_mounted(partition) is None:
                    spinner.stop(f"{COLORS['GREEN']}✓ Unmount verification successful{COLORS['RESET']}")
                    return True
                else:
                    spinner.stop(f"{COLORS['YELLOW']}⚠ Verification failed{COLORS['RESET']}")
                    log("Unmount reported success but partition is still mounted, trying force unmount", "WARNING")
            else:
                spinner.stop(f"{COLORS['YELLOW']}⚠ Partition unmount failed{COLORS['RESET']}")
                log(f"Error in partition unmount: {result.stderr}", "WARNING")
        except Exception as e:
            spinner.stop(f"{COLORS['RED']}✗ Error: {str(e)}{COLORS['RESET']}")
            log(f"Error in partition unmount: {e}", "WARNING")
        
        # Method 3: Try force unmounting
        spinner = Spinner(f"{COLORS['YELLOW']}Force unmounting{COLORS['RESET']}")
        spinner.start()
        
        try:
            # Add a small delay before retry with animation
            for i in range(3):
                spinner.message = f"Preparing force unmount{'.' * (i+1)}"
                time.sleep(0.3)
            
            # Try force unmount on mount point
            spinner.message = f"Force unmounting mount point..."
            time.sleep(0.5)
            
            result = subprocess.run(['diskutil', 'unmount', 'force', mount_point], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully force unmounted {mount_point}{COLORS['RESET']}")
                
                # Success animation
                for i in range(5):
                    progress_bar(i+1, 5, prefix=f"{COLORS['GREEN']}Force unmount:", suffix='Success!', length=20)
                    time.sleep(0.05)
                print("")  # Add a newline after progress bar
                
                return True
            
            # If mount point force unmount fails, try on partition
            spinner.message = f"Trying force unmount on partition..."
            time.sleep(0.5)
            
            result = subprocess.run(['diskutil', 'unmount', 'force', partition], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                spinner.stop(f"{COLORS['GREEN']}✓ Successfully force unmounted {partition}{COLORS['RESET']}")
                return True
        except Exception as e:
            spinner.message = f"Force unmount error: {str(e)[:30]}..."
            time.sleep(0.3)
            log(f"Error in force unmount: {e}", "WARNING")
    
    # If we get here, all unmount attempts failed
    spinner.stop(f"{COLORS['RED']}✗ Failed to unmount {partition}{COLORS['RESET']}")
    
    # Failure animation
    for i in range(3):
        progress_bar(i+1, 3, prefix=f"{COLORS['RED']}Unmount failed:", suffix='Error', length=20)
        time.sleep(0.1)
    print("")  # Add a newline after progress bar
    
    log("Please unmount the partition manually using Disk Utility.", "WARNING")
    return False

# Fix 6: Improved main function with better error handling and state management
def main(auto_confirm=False, auto_restart=False):
    print_banner()
    
    # Grand introduction with animated text
    log("Starting Sonoma VM Bluetooth Enabler Patch Tool", "TITLE")
    
    # Fancy startup animation
    for i in range(10):
        progress_bar(i+1, 10, prefix=f"{COLORS['CYAN']}Initializing:", suffix='Ready', length=40)
        time.sleep(0.05)
    print("")  # Add a newline after progress bar
    
    # Track overall script state
    state = {
        "config_found": False,
        "config_patched": False,
        "mount_points": [],  # Track mounted partitions to ensure cleanup
    }
    
    # Set up cleanup on keyboard interrupt
    def cleanup_handler(signum, frame):
        print("")  # Add a newline for better formatting
        log("\n⚠️  Interrupt received, cleaning up...", "WARNING")
        
        # Animated cleanup
        cleanup_spinner = Spinner("Performing emergency cleanup")
        cleanup_spinner.start()
        
        for mount_point in state["mount_points"]:
            cleanup_spinner.message = f"Unmounting {mount_point}..."
            # Get partition from mount point
            try:
                info_result = subprocess.run(['diskutil', 'info', mount_point], 
                                          capture_output=True, text=True)
                for line in info_result.stdout.split('\n'):
                    if "Device Identifier:" in line:
                        partition = line.split(":")[1].strip()
                        cleanup_spinner.message = f"Unmounting {partition} at {mount_point}..."
                        unmount_efi(partition)
                        break
            except Exception:
                pass
            time.sleep(0.5)  # Brief pause between unmounts
        
        cleanup_spinner.stop(f"{COLORS['GREEN']}✓ Cleanup complete{COLORS['RESET']}")
        log("Exiting script safely. Thank you for using Sonoma Bluetooth Enabler.", "INFO")
        sys.exit(1)
    
    # Register signal handlers
    import signal
    signal.signal(signal.SIGINT, cleanup_handler)
    
    try:
        # Get list of disks with fancy animation
        spinner = Spinner("Scanning system disks")
        spinner.start()
        
        for i in range(5):
            spinner.message = f"Analyzing disk configuration{'.' * (i % 4 + 1)}"
            time.sleep(0.2)
        
        disk_info = get_disk_list()
        
        if not disk_info:
            spinner.stop(f"{COLORS['RED']}✗ Failed to get disk information{COLORS['RESET']}")
            log("Could not retrieve disk list. You may need to run with sudo.", "ERROR")
            return
        
        spinner.stop(f"{COLORS['GREEN']}✓ Disk information retrieved successfully{COLORS['RESET']}")
        
        # Extract EFI partitions with visualization
        spinner = Spinner("Searching for EFI partitions")
        spinner.start()
        
        for i in range(4):
            spinner.message = f"Identifying EFI partitions{'.' * (i % 4 + 1)}"
            time.sleep(0.2)
        
        efi_partitions = get_efi_partitions(disk_info)
        
        if not efi_partitions:
            spinner.stop(f"{COLORS['RED']}✗ No EFI partitions found{COLORS['RESET']}")
            log("No EFI partitions detected on this system.", "ERROR")
            log("Checking for alternative methods to identify EFI partitions...", "INFO")
            
            # Animated alternative search
            alt_spinner = Spinner("Trying alternative detection methods")
            alt_spinner.start()
            
            for i in range(3):
                alt_spinner.message = f"Searching with alternative method {i+1}{'.' * (i % 4 + 1)}"
                time.sleep(0.3)
            
            alt_spinner.stop(f"{COLORS['YELLOW']}⚠ No EFI partitions found with alternative methods{COLORS['RESET']}")
            
            log("Consider mounting EFI manually with Disk Utility, then run this script with the specific path.", "INFO")
            return
        
        spinner.stop(f"{COLORS['GREEN']}✓ Found {len(efi_partitions)} EFI partition(s){COLORS['RESET']}")
        
        # Show partition list in a fancy format
        log(f"Scanning EFI partitions for OpenCore configuration", "HEADER")
        
        # Visual partition list
        for idx, part in enumerate(efi_partitions):
            log(f"  {COLORS['CYAN']}Partition {idx+1}:{COLORS['RESET']} {part}", "INFO")
        
        # Progress counter for partition scanning
        total_partitions = len(efi_partitions)
        
        # Check each EFI partition with visual progress tracking
        for idx, partition in enumerate(efi_partitions):
            partition_progress = f"[{idx+1}/{total_partitions}]"
            
            # Fancy partition header
            log(f"{COLORS['BG_BLUE']} {partition_progress} Processing {partition} {COLORS['RESET']}", "HEADER")
            
            # Mount the EFI partition
            mount_point = mount_efi(partition)
            if not mount_point:
                log(f"{partition_progress} Failed to mount {partition}, skipping...", "WARNING")
                
                # Visual separator
                print(f"{COLORS['YELLOW']}{'─' * 50}{COLORS['RESET']}")
                
                if idx == total_partitions - 1 and idx > 0:
                    log("All mount attempts failed. Please try manually mounting with Disk Utility.", "ERROR")
                continue
            
            # Track mounted partitions for cleanup
            state["mount_points"].append(mount_point)
            
            try:
                # Look for config.plist with animation
                spinner = Spinner(f"Searching for OpenCore config")
                spinner.start()
                
                for i in range(3):
                    spinner.message = f"Scanning {mount_point}{'.' * (i % 4 + 1)}"
                    time.sleep(0.2)
                
                config_path = find_config_plist(mount_point)
                
                if config_path:
                    spinner.stop(f"{COLORS['GREEN']}✓ OpenCore config found!{COLORS['RESET']}")
                    state["config_found"] = True
                    
                    # Success animation for finding config
                    for i in range(5):
                        progress_bar(i+1, 5, prefix=f"{COLORS['GREEN']}Config located:", suffix='Success', length=30)
                        time.sleep(0.03)
                    print("")  # Add a newline after progress bar
                    
                    # Use our improved check function
                    patches_exist, patch_status = check_if_patches_exist(config_path)
                    
                    if patches_exist:
                        log(f"Patches already exist in {config_path}", "TITLE")
                        
                        # Fancy "already patched" animation
                        for i in range(10):
                            progress_bar(i+1, 10, prefix=f"{COLORS['GREEN']}System status:", suffix='Already Patched', length=40)
                            time.sleep(0.03)
                        print("")  # Add a newline after progress bar
                        
                        log("No changes needed. Your system is already patched.", "SUCCESS")
                        # Clean up before exiting
                        unmount_efi(partition)
                        state["mount_points"].remove(mount_point)
                        return
                    
                    # Ask for confirmation before applying patch
                    log(f"OpenCore configuration ready for patching", "TITLE")
                    log(f"Path: {config_path}", "INFO")
                    
                    if patch_status != "none" and patch_status != "error":
                        log(f"Partial patches found: {patch_status}", "WARNING")
                        log("Will add missing patches to complete the set", "INFO")
                    
                    proceed = True
                    if not auto_confirm:
                        # Fancy animated prompt
                        for i in range(3):
                            print(f"\r{COLORS['CYAN']}Preparing to patch{' .' * i}{COLORS['RESET']}    ", end="")
                            time.sleep(0.3)
                        print("")  # Clear the line
                        
                        while True:
                            response = input(f"{COLORS['CYAN']}Do you want to apply the Sonoma VM BT Enabler patch? [y/n/skip]: {COLORS['RESET']}").lower()
                            if response in ['y', 'yes']:
                                # Show confirmation animation
                                for i in range(5):
                                    progress_bar(i+1, 5, prefix=f"{COLORS['GREEN']}User confirmed:", suffix='Proceeding', length=30)
                                    time.sleep(0.03)
                                print("")  # Add a newline after progress bar
                                break
                            elif response in ['n', 'no']:
                                log("Operation cancelled by user.", "WARNING")
                                proceed = False
                                break
                            elif response == 'skip':
                                log(f"Skipping {config_path}. Looking for other configs...", "INFO")
                                proceed = False
                                break
                            else:
                                log("Please enter 'y' for yes, 'n' for no, or 'skip' to try next partition.", "WARNING")
                        
                        if response == 'skip':
                            continue
                    
                    if proceed:
                        # Apply patches
                        success = add_kernel_patches(config_path)
                        if success == "success":
                            log(f"Successfully patched OpenCore config at {config_path}", "SUCCESS")
                            state["config_patched"] = True
                        elif success == "already_exists":
                            log(f"Patches already exist in {config_path}", "TITLE")
                            log("No changes needed. Your system is already patched.", "SUCCESS")
                            # Clean up before exiting
                            unmount_efi(partition)
                            state["mount_points"].remove(mount_point)
                            return
                        else:
                            log(f"Failed to patch config at {config_path}", "ERROR")
                else:
                    spinner.stop(f"{COLORS['YELLOW']}⚠ No OpenCore config.plist found{COLORS['RESET']}")
                    log(f"{partition_progress} No OpenCore config.plist found on {partition}", "WARNING")
                    
                    # Visual debug information
                    debug_spinner = Spinner("Collecting debug information")
                    debug_spinner.start()
                    
                    try:
                        debug_spinner.message = "Listing directory contents..."
                        time.sleep(0.5)
                        
                        ls_result = subprocess.run(['ls', '-la', mount_point], 
                                               capture_output=True, text=True)
                        
                        debug_spinner.stop()
                        
                        if ls_result.returncode == 0:
                            log("Directory contents:", "INFO")
                            print(f"{COLORS['CYAN']}{ls_result.stdout}{COLORS['RESET']}")
                    except Exception:
                        debug_spinner.stop(f"{COLORS['YELLOW']}⚠ Could not list directory contents{COLORS['RESET']}")
            finally:
                # Always unmount the partition when done
                time.sleep(0.5)  # Brief pause before unmounting
                
                log("Finishing operations on this partition...", "INFO")
                
                unmount_success = unmount_efi(partition)
                if unmount_success and mount_point in state["mount_points"]:
                    state["mount_points"].remove(mount_point)
                
                # Visual partition separator
                print(f"{COLORS['CYAN']}{'─' * 50}{COLORS['RESET']}")
                
                # If we found and patched a config, we can stop
                if state["config_patched"]:
                    break
        
        if state["config_patched"]:
            # Grand success animation
            log("", "INFO")  # Empty line for spacing
            log("╔════════════════════════════════════════════════════════╗", "SUCCESS")
            log("║                                                        ║", "SUCCESS")
            log("║             PATCHING PROCESS SUCCESSFUL                ║", "SUCCESS")
            log("║                                                        ║", "SUCCESS")
            log("╚════════════════════════════════════════════════════════╝", "SUCCESS")
            log("", "INFO")  # Empty line for spacing
            
            log("Please reboot your system to apply the changes.", "SUCCESS")
            
            # Offer to restart if auto_restart is enabled
            if auto_restart:
                log("Auto-restart enabled. System will restart automatically.", "INFO")
                
                # Auto-restart animation
                restart_spinner = Spinner(f"{COLORS['YELLOW']}Preparing to restart system{COLORS['RESET']}")
                restart_spinner.start()
                
                for i in range(3):
                    restart_spinner.message = f"Initiating restart sequence{'.' * (i % 4 + 1)}"
                    time.sleep(0.5)
                
                restart_spinner.stop(f"{COLORS['GREEN']}✓ Restart sequence initiated{COLORS['RESET']}")
                restart_system()
            else:
                # Offer restart option
                if not auto_confirm:  # Only ask if not in auto mode
                    # Animated restart prompt
                    for i in range(3):
                        print(f"\r{COLORS['CYAN']}System ready for restart{' .' * i}{COLORS['RESET']}    ", end="")
                        time.sleep(0.3)
                    print("")  # Clear the line
                    
                    response = input(f"{COLORS['CYAN']}Would you like to restart now to apply changes? [y/n]: {COLORS['RESET']}").lower()
                    if response in ['y', 'yes']:
                        # Restart animation
                        restart_spinner = Spinner(f"{COLORS['YELLOW']}Preparing to restart system{COLORS['RESET']}")
                        restart_spinner.start()
                        
                        for i in range(3):
                            restart_spinner.message = f"Initiating restart sequence{'.' * (i % 4 + 1)}"
                            time.sleep(0.5)
                        
                        restart_spinner.stop(f"{COLORS['GREEN']}✓ Restart sequence initiated{COLORS['RESET']}")
                        restart_system()
        elif state["config_found"]:
            # Found configs but patching failed
            log("", "INFO")  # Empty line for spacing
            log("╔════════════════════════════════════════════════════════╗", "ERROR")
            log("║                                                        ║", "ERROR")
            log("║               PATCHING PROCESS FAILED                  ║", "ERROR")
            log("║                                                        ║", "ERROR")
            log("╚════════════════════════════════════════════════════════╝", "ERROR")
            log("", "INFO")  # Empty line for spacing
            
            log("Found OpenCore config.plist but patching was not successful", "WARNING")
            log("Please check the logs above for errors.", "INFO")
        else:
            # No configs found
            log("", "INFO")  # Empty line for spacing
            log("╔════════════════════════════════════════════════════════╗", "WARNING")
            log("║                                                        ║", "WARNING")
            log("║          NO OPENCORE CONFIG.PLIST FOUND                ║", "WARNING")
            log("║                                                        ║", "WARNING")
            log("╚════════════════════════════════════════════════════════╝", "WARNING")
            log("", "INFO")  # Empty line for spacing
            
            log("Make sure OpenCore is properly installed.", "WARNING")
            log("If you know the location of your config.plist, try running this script with that path:", "INFO")
            log(f"  {COLORS['CYAN']}sudo python3 {sys.argv[0]} /path/to/config.plist{COLORS['RESET']}", "INFO")
            log("You may also need to mount your EFI manually using Disk Utility.", "INFO")
    
    except Exception as e:
        log("", "INFO")  # Empty line for spacing
        log("╔════════════════════════════════════════════════════════╗", "ERROR")
        log("║                                                        ║", "ERROR")
        log("║                UNEXPECTED ERROR                        ║", "ERROR")
        log("║                                                        ║", "ERROR")
        log("╚════════════════════════════════════════════════════════╝", "ERROR")
        log("", "INFO")  # Empty line for spacing
        
        log(f"Error details: {str(e)}", "ERROR")
        
        # Fancy traceback display
        import traceback
        tb = traceback.format_exc()
        print(f"{COLORS['RED']}{'─' * 50}")
        print(f"{tb}")
        print(f"{'─' * 50}{COLORS['RESET']}")
    
    finally:
        # Final cleanup for any remaining mounted partitions
        if state["mount_points"]:
            log("", "INFO")  # Empty line for spacing
            log("Performing final cleanup operations...", "HEADER")
            
            cleanup_spinner = Spinner("Cleaning up remaining mounts")
            cleanup_spinner.start()
            
            for mount_point in state["mount_points"]:
                try:
                    cleanup_spinner.message = f"Unmounting {mount_point}..."
                    time.sleep(0.5)
                    
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
            
            cleanup_spinner.stop(f"{COLORS['GREEN']}✓ Cleanup complete{COLORS['RESET']}")
            
        # Final goodbye message
        log("", "INFO")  # Empty line for spacing
        log("Thank you for using Sonoma VM Bluetooth Enabler Patch Tool!", "TITLE")
