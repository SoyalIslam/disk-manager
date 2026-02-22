# diskman

`diskman` is a Linux disk/partition manager with:
- CLI commands and terminal TUI
- Filesystem-aware mount options (including SSD/HDD-aware tuning)
- SMART health visibility per device
- LUKS auto-detection and unlock support
- Read-only fallback when writable mount fails
- Non-blocking async mount/umount/automount operations
- Reboot auto-mount selection (persistent via `/etc/fstab`)
- systemd service/timer integration
- AUR packaging metadata

## Project Structure

```text
disk-manager/
├── pyproject.toml
├── README.md
├── systemd/
│   ├── diskman-automount.service
│   └── diskman-automount.timer
├── packaging/
│   └── aur/
│       ├── PKGBUILD
│       └── .SRCINFO
├── scripts/
│   └── build_binary.sh
└── src/
    └── diskman/
        ├── __init__.py
        ├── cli.py
        ├── core.py
        └── tui.py
```

## Requirements

- Linux
- Python 3.9+
- System tools: `lsblk`, `findmnt`, `mount`, `umount`
- For LUKS: `cryptsetup`
- For SMART: `smartctl` from `smartmontools`
- `sudo` for mount/unmount/crypt actions

## Install

```bash
cd /home/gaffer/Documents/disk-manager
python3 -m pip install .
```

## CLI Usage

```bash
diskman list
diskman automount --dry-run
sudo diskman automount
sudo diskman automount --async
sudo diskman mount /dev/sdb1
sudo diskman mount /dev/sdb1 --async
sudo diskman umount /dev/sdb1
sudo diskman umount /dev/sdb1 --lock-luks
sudo diskman luks-unlock /dev/sdb2
sudo diskman luks-lock /dev/sdb2
diskman boot-list
sudo diskman boot-add /dev/sdb1
sudo diskman boot-remove /dev/sdb1
sudo diskman tui
```

## TUI Controls

- `j`/`k` or arrow keys: select device
- `r`: refresh
- `a`: async automount
- `m`: async mount/unmount (prompts for LUKS passphrase when needed)
- `p`: toggle persistent reboot auto-mount
- `q`: quit

## systemd Integration

Install units:

```bash
sudo install -Dm644 systemd/diskman-automount.service /etc/systemd/system/diskman-automount.service
sudo install -Dm644 systemd/diskman-automount.timer /etc/systemd/system/diskman-automount.timer
```

Enable periodic automount:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now diskman-automount.timer
```

Optional one-shot run:

```bash
sudo systemctl start diskman-automount.service
```

## AUR Packaging

Files are in `packaging/aur/`:
- `packaging/aur/PKGBUILD`
- `packaging/aur/.SRCINFO`

If you publish tags (for example `v0.2.0`), users can build via `makepkg -si` from the AUR package directory.

## Build Standalone Binary

```bash
cd /home/gaffer/Documents/disk-manager
./scripts/build_binary.sh
./dist/diskman
```
