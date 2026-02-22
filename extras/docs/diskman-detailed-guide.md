# Diskman Detailed Technical Guide

## 1. What Diskman Is

Diskman is a Linux disk and partition manager built for terminal environments. It provides:

- A command-line interface (CLI)
- A terminal user interface (TUI)
- Smart default mount behavior
- Partition create/delete/merge operations
- LUKS encrypted device detection and unlock flow
- SMART health visibility
- Reboot-persistent mount toggling via `/etc/fstab`
- Optional systemd timer/service integration

It is designed for practical administration workflows where users want a lightweight but capable tool without a full desktop disk manager.

## 2. Core Architecture

Diskman is structured into three main modules:

- `src/diskman/core.py`: system integration and operation logic
- `src/diskman/cli.py`: CLI commands and argument parsing
- `src/diskman/tui.py`: interactive curses-based TUI

### 2.1 Device Discovery

Diskman reads device metadata from `lsblk` JSON output using:

- `NAME`, `KNAME`, `PATH`, `TYPE`, `PKNAME`
- `FSTYPE`, `LABEL`, `UUID`
- `SIZE`, `MOUNTPOINT`
- `ROTA` (rotational flag)

It then builds in-memory `Partition` objects for non-disk block devices (usually partitions).

### 2.2 Root Safety

Diskman resolves the root filesystem source with `findmnt` and excludes root partitions from destructive or mount-changing actions by default.

## 3. Feature-by-Feature Behavior

## 3.1 Filesystem-Aware Mount Options

When mounting, Diskman builds mount options based on filesystem and disk characteristics:

- Base options: `defaults,nofail,noatime`
- SSD for supported Linux filesystems (`ext4`, `xfs`, `btrfs`, `f2fs`): adds `discard`
- FAT/exFAT family: sets `uid`, `gid`, and `umask=022`
- `ntfs3`: sets `uid`, `gid`, and `windows_names`

This keeps mount behavior more useful than generic `mount /dev/xyz /mnt/foo` defaults.

Filesystem normalization and explicit mount type behavior:

- `fuseblk`, `ntfs`, `ntfs3g` -> `ntfs3`
- `fat`, `fat16`, `fat32` -> `vfat`
- Filesystem is detected from the real mount source (`blkid`, fallback `lsblk`) and mounted with `mount -t <fstype>`

## 3.2 SSD/HDD Detection

Disk type is inferred from `lsblk` `ROTA`:

- `ROTA=false` or `0` -> `SSD`
- `ROTA=true` or `1` -> `HDD`
- Unknown values -> `UNKNOWN`

Disk type is shown in both CLI list output and TUI rows.

## 3.3 SMART Health Column

Diskman calls `smartctl -H -j <disk>` per physical disk and caches results.

Displayed states may include:

- `PASSED`
- `FAILED`
- `UNKNOWN`
- `UNAVAILABLE`
- `NO_SMARTCTL`

Notes:

- SMART data often requires root privileges.
- Some devices/controllers do not expose SMART cleanly.

## 3.4 LUKS Auto-Detection + Unlock

Partitions with `fstype=crypto_luks` are treated as LUKS containers.

Available actions:

- CLI:
  - `diskman luks-unlock /dev/xyz`
  - `diskman luks-lock /dev/xyz`
- TUI:
  - `u` key to unlock selected LUKS device (hidden passphrase prompt)
  - `l` key to lock selected LUKS device

Mount path for locked LUKS partitions:

1. Device detected as LUKS
2. If locked, prompt passphrase (CLI/TUI)
3. Run `cryptsetup open`
4. Resolve mapper child block device
5. Mount resolved target

## 3.5 Read-Only Fallback

Mount flow is two-stage:

1. Attempt read-write mount with computed options
2. If that fails, retry with `ro` appended

If fallback succeeds, status explicitly indicates read-only mount and includes initial failure reason.

Read-only mounts are marked `RO` in TUI flags.

## 3.6 Async Non-Blocking Operations

Diskman uses a thread pool for background operations:

- `automount_async`
- `mount_partition_async`
- `umount_partition_async`
- `unlock_luks_async`
- `lock_luks_async`
- `create_partition_async`
- `delete_partition_async`
- `merge_with_unallocated_async`

TUI remains responsive while operations run. Current action is shown in status line.

## 3.7 AUR Packaging

AUR metadata is provided in:

- `extras/packaging/aur/PKGBUILD`
- `extras/packaging/aur/.SRCINFO`

Dependencies include:

- `python`
- `python-rich`
- `util-linux`
- `cryptsetup`
- `smartmontools`

## 3.8 systemd Integration

Provided units:

- `extras/systemd/diskman-automount.service`
- `extras/systemd/diskman-automount.timer`

Typical flow:

1. Install unit files into `/etc/systemd/system` or package-managed unit directory
2. `systemctl daemon-reload`
3. `systemctl enable --now diskman-automount.timer`

Timer periodically triggers one-shot automount execution.

## 4. CLI Command Reference

- `diskman list`
- `diskman automount [--dry-run] [--async]`
- `diskman mount <device> [--async]`
- `diskman umount <device> [--lock-luks] [--async]`
- `diskman boot-list`
- `diskman boot-add <device>`
- `diskman boot-remove <device>`
- `diskman part-create <disk> --fs <fs> [--label <label>] [--size <size>] [--start-mib <offset>]`
- `diskman part-delete <device> [--wipefs]`
- `diskman part-merge <device>`
- `diskman luks-unlock <device>`
- `diskman luks-lock <device>`
- `diskman tui`

All state-changing actions (mount/umount/luks/partition create-delete-merge/fstab writes) require root.

## 5. TUI Interaction Model

Current keybindings:

- `j` / `k` or arrow keys: move selection
- `r`: refresh device list
- `a`: async automount
- `m`: async mount/unmount selected partition
- `u`: async unlock selected LUKS partition
- `l`: async lock selected LUKS partition
- `p`: toggle persistent reboot auto-mount
- `c`: create partition (disk prompt + filesystem mini-menu + params)
- `d`: delete selected partition
- `g`: merge selected partition with adjacent right-side unallocated space
- `q`: quit

Displayed columns include:

- Device path
- Disk type (`SSD/HDD/UNKNOWN`)
- Filesystem type
- Size
- SMART status
- Mountpoint
- Flags (`ROOT`, `MOUNTED`, `RO`, `LUKS_OPEN`, `LUKS_LOCKED`, `AUTOBOOT`, `SKIP`)

## 6. Persistent Boot Mount Logic

Diskman stores managed entries in `/etc/fstab` with an internal tag:

- Tag: `diskman:auto`

This enables safe add/remove operations for only Diskman-managed rows.

Safety restrictions:

- Refuses root partition persistence
- Refuses persistence for raw LUKS containers
- Requires UUID for reliable persistent mapping

## 7. Operational Examples

### 7.1 Inspect Current Device State

```bash
diskman list
```

### 7.2 Mount Everything Mountable (Without Applying)

```bash
diskman automount --dry-run
```

### 7.3 Perform Real Automount

```bash
sudo diskman automount
```

### 7.4 Mount a Locked LUKS Partition

```bash
sudo diskman mount /dev/sdb2
# prompts for LUKS passphrase when needed
```

### 7.5 Enable Reboot Auto-Mount for a Partition

```bash
sudo diskman boot-add /dev/sdb1
```

### 7.6 Create a New Partition

```bash
sudo diskman part-create /dev/sdb --fs ntfs --label DATA --size 100G
```

### 7.7 Delete a Partition

```bash
sudo diskman part-delete /dev/sdb3
```

### 7.8 Merge Adjacent Unallocated Space into a Partition

```bash
sudo diskman part-merge /dev/sdb2
```

## 8. Failure Handling and Diagnostics

Common conditions and behavior:

- Missing command (`smartctl`, `cryptsetup`) -> feature reports unavailable/error
- Read-write mount failure -> read-only fallback attempted
- Locked LUKS mount without passphrase -> explicit locked message
- Root partition selection -> operation refused for safety
- Partition merge without adjacent right-side free space -> operation refused

For deeper diagnostics, check:

- `dmesg`
- `journalctl -xe`
- `lsblk -f`
- `findmnt`
- `smartctl -H -j /dev/<disk>`

## 9. Security Model

- Root-required operations are explicitly gated
- Passphrases are requested interactively and not logged by Diskman
- Persistent fstab management only modifies tagged entries for removal
- Root filesystem is guarded from unsafe automation

## 10. Limitations and Practical Notes

- SMART availability depends on hardware/controller access
- Some encrypted layouts may require advanced mapper handling
- Read-only fallback is intentional and may occur on dirty or inconsistent filesystems
- `part-merge` changes partition boundaries; filesystem growth may require filesystem-specific tools
- TUI behavior depends on terminal capabilities (curses support)

## 11. Summary

Diskman now acts as a practical terminal-first storage utility with strong day-to-day features:

- Better mount defaults
- Storage health visibility
- Encryption-aware workflows
- Non-blocking interactive operations
- Packaging and system integration support

This makes it suitable for both manual administration and periodic automated mount routines.
