# diskman

`diskman` is a Linux disk/partition manager with:
- CLI commands
- TUI terminal mode
- Auto-mount for mountable partitions, excluding root (`/`)
- Reboot auto-mount selection (persistent via `/etc/fstab`)

## Project Structure

```text
disk-manager/
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
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
- `sudo` for mount/unmount operations

## Install With pip (Python package manager)

From this folder:

```bash
cd /home/gaffer/Documents/disk-manager
python3 -m pip install .
```

After install, command is available:

```bash
diskman --help
diskman list
```

## Update / Upgrade With pip

When you change code and want latest version installed:

```bash
cd /home/gaffer/Documents/disk-manager
python3 -m pip install --upgrade .
```

## CLI Usage

```bash
diskman list
diskman automount --dry-run
sudo diskman automount
sudo diskman mount /dev/sdb1
sudo diskman umount /dev/sdb1
diskman boot-list
sudo diskman boot-add /dev/sdb1
sudo diskman boot-remove /dev/sdb1
sudo diskman tui
```

In TUI:
- `p` toggles reboot auto-mount for selected partition.

## Build Standalone Binary

```bash
cd /home/gaffer/Documents/disk-manager
./scripts/build_binary.sh
```

Output binary:

```bash
./dist/diskman
```

You can copy it to a PATH location:

```bash
sudo cp ./dist/diskman /usr/local/bin/diskman
```
