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
├── extras/
│   ├── docs/
│   │   ├── diskman-detailed-guide.md
│   │   └── diskman-detailed-guide.pdf
│   ├── systemd/
│   │   ├── diskman-automount.service
│   │   └── diskman-automount.timer
│   └── packaging/
│       └── aur/
│           ├── PKGBUILD
│           └── .SRCINFO
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

## Installation

### From PyPI (Recommended)

Anyone can install `diskman` directly with:

```bash
python3 -m pip install --upgrade diskman
```

Then run:

```bash
diskman --help
```

### From Source

```bash
git clone https://github.com/gaffer/disk-manager
cd disk-manager
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
- `u`: async unlock selected LUKS device
- `l`: async lock selected LUKS device
- `p`: toggle persistent reboot auto-mount
- `q`: quit

## systemd Integration

Install units:

```bash
sudo install -Dm644 extras/systemd/diskman-automount.service /etc/systemd/system/diskman-automount.service
sudo install -Dm644 extras/systemd/diskman-automount.timer /etc/systemd/system/diskman-automount.timer
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

Files are in `extras/packaging/aur/`:
- `extras/packaging/aur/PKGBUILD`
- `extras/packaging/aur/.SRCINFO`

If you publish tags (for example `v0.2.1`), users can build via `makepkg -si` from the AUR package directory.

## Build Standalone Binary

```bash
./scripts/build_binary.sh
./bin/diskman
```

## Development & Publishing

### 0. Prepare environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### 1. Publish to PyPI

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD='pypi-xxxxxxxxxxxxxxxx'
./scripts/publish_pypi.sh
```

TestPyPI publish (recommended first):

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD='pypi-xxxxxxxxxxxxxxxx'
export REPOSITORY_URL='https://test.pypi.org/legacy/'
./scripts/publish_pypi.sh
```

### 2. Build release binary asset

```bash
./scripts/package_release_binary.sh 0.2.1
```

This creates:

- `release/diskman-linux-x86_64`
- `release/diskman-linux-x86_64-v0.2.1.tar.gz`
- sha256 files for both artifacts

Upload `diskman-linux-x86_64` (or tar.gz) to GitHub Release tag `v0.2.1`.

### 3. End-user direct binary install

Anyone can install your binary without Python project setup:

```bash
curl -fsSL https://raw.githubusercontent.com/gaffer/disk-manager/main/scripts/install_binary.sh -o /tmp/install_diskman.sh
bash /tmp/install_diskman.sh 0.2.1 gaffer/disk-manager
```

Or locally:

```bash
./scripts/install_binary.sh 0.2.1 gaffer/disk-manager
```
