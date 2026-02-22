# diskman

[![PyPI version](https://img.shields.io/pypi/v/diskman.svg)](https://pypi.org/project/diskman/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**diskman** is a lightweight, terminal-first Linux disk and partition manager. It provides a powerful CLI and an interactive TUI for day-to-day storage administration, featuring SMART health monitoring, LUKS encryption support, and filesystem-aware automounting.

---

## 🚀 Key Features

- **Dual Interface:** Full-featured Command Line Interface (CLI) and an interactive Terminal User Interface (TUI).
- **Smart Automount:** Filesystem-aware mount options (e.g., `discard` for SSDs, UID/GID mapping for FAT/NTFS).
- **LUKS Support:** Auto-detection, unlocking, and locking of encrypted partitions.
- **Health Monitoring:** Real-time SMART health status visibility (via `smartmontools`).
- **Safety First:** Automatically excludes root partitions from destructive operations and provides a **read-only fallback** if a writable mount fails.
- **Partition Management:** Create and delete partitions from CLI with explicit filesystem selection (`ntfs3`, `btrfs`, `exfat`, `vfat`, etc.) and optional custom volume labels.
- **Non-Blocking Ops:** Asynchronous mount, unmount, and LUKS operations to keep the TUI responsive.
- **Persistence:** Easily toggle reboot-persistent mounts via tagged `/etc/fstab` entries.
- **System Integration:** Ready-to-use `systemd` service and timer for periodic automounting.

---

## 📦 Installation

### From PyPI (Recommended)

Install the latest stable version directly from PyPI:

```bash
python3 -m pip install --upgrade diskman
```

### From Source

```bash
git clone https://github.com/SoyalIslam/disk-manager.git
cd disk-manager
python3 -m pip install .
```

### Requirements

- **OS:** Linux
- **Python:** 3.9+
- **System Tools:** `util-linux` (`lsblk`, `findmnt`, `mount`, `umount`)
- **Partitioning Tools:** `parted`, `partprobe`, `udevadm`
- **Filesystem Tools:** `mkfs.ntfs`, `mkfs.btrfs`, `mkfs.exfat`, `mkfs.vfat` (or `mkfs` for `ext4`/`xfs`/`f2fs`)
- **Optional Tools:**
  - `cryptsetup` (for LUKS support)
  - `smartmontools` (for SMART health monitoring)

---

## 🛠 Usage

### CLI Reference

| Command | Description |
| :--- | :--- |
| `diskman list` | List all partitions, filesystems, and mount status. |
| `diskman tui` | Launch the interactive Terminal User Interface. |
| `sudo diskman automount` | Auto-mount all available partitions (excluding root). |
| `sudo diskman mount /dev/sdb1` | Mount a specific device (prompts for LUKS if needed). |
| `sudo diskman umount /dev/sdb1` | Unmount a specific device. |
| `sudo diskman luks-unlock /dev/sdb2` | Unlock a LUKS encrypted partition. |
| `sudo diskman part-create /dev/sdb --fs ntfs --label DATA --size 100G` | Create and format a new partition in free disk space. |
| `sudo diskman part-delete /dev/sdb3` | Delete an existing partition. |
| `sudo diskman part-merge /dev/sdb2` | Merge adjacent right-side unallocated space into a partition. |
| `sudo diskman boot-add /dev/sdb1` | Enable reboot-persistent mount in `/etc/fstab`. |

*Note: Operations that modify system state (mount/unmount/LUKS/partition create-delete-merge/fstab) require `sudo`.*

### TUI Controls

Launch with `diskman tui` (or `sudo diskman tui` for full functionality):

- **`j` / `k`** or **Arrow Keys**: Navigate device list.
- **`m`**: Mount or unmount the selected partition.
- **`u` / `l`**: Unlock or lock a LUKS partition.
- **`a`**: Trigger a background automount of all devices.
- **`p`**: Toggle persistence (`/etc/fstab`) for the selected device.
- **`c`**: Create a new partition (prompts for disk, menu-select filesystem, label, size).
- **`d`**: Delete the selected partition (with confirmation prompt).
- **`g`**: Merge adjacent right-side unallocated space into the selected partition.
- **`r`**: Refresh the device list.
- **`q`**: Exit.

---

## ⚙️ System Integration

### Periodic Automount (systemd)

You can automate mounting of external drives using the provided systemd units:

1. **Install Units:**
   ```bash
   sudo install -Dm644 extras/systemd/diskman-automount.service /etc/systemd/system/
   sudo install -Dm644 extras/systemd/diskman-automount.timer /etc/systemd/system/
   ```

2. **Enable Timer:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now diskman-automount.timer
   ```

---

## 🏗 Development

### Setup Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

### Build & Package

```bash
# Build distribution archives
python3 -m build

# Build standalone binary (via PyInstaller)
./scripts/build_binary.sh
```

### GitHub Actions: Publish to PyPI

This repo includes:

- `.github/workflows/publish-pypi.yml`

Set these repository secrets in GitHub:

- `PYPI_API_TOKEN`
- `TEST_PYPI_API_TOKEN`

Workflow usage:

1. Manual publish to TestPyPI:
   - Actions -> `Publish Python Package` -> `Run workflow` -> target `testpypi`
2. Manual publish to PyPI:
   - Actions -> `Publish Python Package` -> `Run workflow` -> target `pypi`
3. Auto publish to PyPI on tag:
   - Push tag `vX.Y.Z` matching `pyproject.toml` version

```bash
git tag v0.2.1
git push origin v0.2.1
```

---

## 📄 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/SoyalIslam/disk-manager/issues).
