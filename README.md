# macOS OpenCore Bluetooth Patcher ⚙️

[![Python Version](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/akshaynexus/macos-patcher-bt-vmhide)
[![GitHub stars](https://img.shields.io/github/stars/akshaynexus/macos-patcher-bt-vmhide?style=social)](https://github.com/akshaynexus/macos-patcher-bt-vmhide/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/akshaynexus/macos-patcher-bt-vmhide?style=social)](https://github.com/akshaynexus/macos-patcher-bt-vmhide/network/members)

Automatically patch OpenCore `config.plist` to enable Bluetooth in macOS Sonoma VMs and Hackintosh setups by applying `kern.hv_vmm_present=0`.

## 🚀 Quick Start

```bash
# Clone and run
git clone https://github.com/akshaynexus/macos-patcher-bt-vmhide.git
cd macos-patcher-bt-vmhide
sudo python3 patcher.py

# Auto-confirm and restart
sudo python3 patcher.py -y -r
```

## ✨ Features

- **Auto-detection** of EFI partitions and OpenCore configs
- **Safe patching** with automatic backups and validation
- **Idempotent operation** that skips if already patched
- **Command-line options** for automation and debugging

## ⚡ Commands

```bash
# Show help
sudo python3 patcher.py --help

# Specify config path
sudo python3 patcher.py /Volumes/EFI/EFI/OC/config.plist

# Debug mode
sudo python3 patcher.py -d

# Mount EFI partitions without patching
sudo python3 patcher.py -m
```

## 🛠️ How It Works

1. **Finds** EFI partitions on your system
2. **Mounts** them and locates OpenCore configurations
3. **Backs up** your existing config
4. **Applies** virtualization detection bypass patches
5. **Validates** changes and restores backup if needed

## ⚠️ Requirements

- macOS Sonoma or newer
- Python 3.6+
- Existing OpenCore setup
- Admin privileges

## 🔍 Troubleshooting

- **Requires sudo** for mounting EFI partitions
- **Still no Bluetooth?** Check USB mapping, kexts, and hardware compatibility
- **Mount issues?** Check SIP status or try manual mounting with Disk Utility

## 📜 License

This project is licensed under the MIT License. Use at your own risk.
