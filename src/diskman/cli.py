from __future__ import annotations

import argparse
import getpass
import io
import sys
from pathlib import Path

from diskman.core import (
    DEFAULT_BASE_DIR,
    CommandError,
    automount,
    automount_async,
    collect_partitions,
    disable_persistent_mount,
    enable_persistent_mount,
    find_partition,
    is_luks_open,
    is_mountable,
    is_root_partition,
    lock_luks,
    mount_partition,
    mount_partition_async,
    persistent_mount_map,
    require_root,
    root_sources,
    smart_health,
    umount_partition,
    umount_partition_async,
    unlock_luks,
)
from diskman.tui import run_tui


def _flags_for_part(p, roots, boot_map):
    flags = []
    if is_root_partition(p, roots):
        flags.append("ROOT")
    if p.mounted:
        flags.append("MOUNTED")
    if not is_mountable(p):
        flags.append("SKIP")
    if p.is_luks:
        flags.append("LUKS_OPEN" if is_luks_open(p) else "LUKS_LOCKED")
    if p.uuid and p.uuid in boot_map:
        flags.append("AUTOBOOT")
    return flags


def render_table(parts) -> str:
    roots = root_sources()
    boot_map = persistent_mount_map()

    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(title="diskman partitions")
        table.add_column("Device")
        table.add_column("Type")
        table.add_column("Disk")
        table.add_column("FS")
        table.add_column("Size")
        table.add_column("Mountpoint")
        table.add_column("SMART")
        table.add_column("Flags")

        for p in parts:
            flags = _flags_for_part(p, roots, boot_map)
            table.add_row(
                p.path,
                p.devtype or "-",
                p.disk_kind or "-",
                p.fstype or "-",
                p.size or "-",
                p.mountpoint or "-",
                smart_health(p),
                ",".join(flags) or "-",
            )

        out = io.StringIO()
        console = Console(file=out, force_terminal=False, color_system=None)
        console.print(table)
        return out.getvalue()
    except Exception:
        header = (
            f"{'DEVICE':<18} {'TYPE':<7} {'DISK':<5} {'FS':<10} {'SIZE':<8} "
            f"{'MOUNTPOINT':<22} {'SMART':<12} {'FLAGS'}"
        )
        lines = [header, "-" * len(header)]
        for p in parts:
            flags = _flags_for_part(p, roots, boot_map)
            lines.append(
                f"{p.path:<18} {p.devtype:<7} {p.disk_kind:<5} {p.fstype or '-':<10} {p.size or '-':<8} "
                f"{p.mountpoint or '-':<22} {smart_health(p):<12} {','.join(flags) or '-'}"
            )
        return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diskman",
        description="CLI + TUI disk/partition manager with auto-mount (excluding root).",
    )
    parser.add_argument(
        "--base-dir",
        default=str(DEFAULT_BASE_DIR),
        help="Base mount directory for auto/manual mounts (default: /mnt/auto)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List partitions and mount status")

    auto = sub.add_parser("automount", help="Auto-mount all mountable partitions except root")
    auto.add_argument("--dry-run", action="store_true", help="Show what would be mounted")
    auto.add_argument("--async", dest="is_async", action="store_true", help="Run automount in a background worker")

    mount_p = sub.add_parser("mount", help="Mount one device")
    mount_p.add_argument("device", help="Device path, e.g. /dev/sdb1")
    mount_p.add_argument("--async", dest="is_async", action="store_true", help="Run mount in a background worker")

    umount_p = sub.add_parser("umount", help="Unmount one device")
    umount_p.add_argument("device", help="Device path, e.g. /dev/sdb1")
    umount_p.add_argument("--lock-luks", action="store_true", help="If device is LUKS, close mapper after unmount")
    umount_p.add_argument("--async", dest="is_async", action="store_true", help="Run unmount in a background worker")

    sub.add_parser("boot-list", help="List diskman reboot auto-mount entries in fstab")

    boot_add = sub.add_parser("boot-add", help="Enable reboot auto-mount for one device")
    boot_add.add_argument("device", help="Device path, e.g. /dev/sdb1")

    boot_rm = sub.add_parser("boot-remove", help="Disable reboot auto-mount for one device")
    boot_rm.add_argument("device", help="Device path, e.g. /dev/sdb1")

    luks_unlock = sub.add_parser("luks-unlock", help="Unlock a LUKS device")
    luks_unlock.add_argument("device", help="LUKS device path, e.g. /dev/sdb2")

    luks_lock = sub.add_parser("luks-lock", help="Lock a LUKS device mapper")
    luks_lock.add_argument("device", help="LUKS device path, e.g. /dev/sdb2")

    sub.add_parser("tui", help="Start terminal UI")
    return parser


def _prompt_luks_passphrase() -> str:
    return getpass.getpass("LUKS passphrase: ")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    base_dir = Path(args.base_dir)

    try:
        if args.cmd == "list":
            print(render_table(collect_partitions()))
            return 0

        if args.cmd == "automount":
            if not args.dry_run:
                require_root()
            if args.is_async:
                logs = automount_async(base_dir=base_dir, dry_run=args.dry_run).result()
            else:
                logs = automount(base_dir=base_dir, dry_run=args.dry_run)
            for line in logs:
                print(line)
            return 0

        if args.cmd == "mount":
            require_root()
            part = find_partition(collect_partitions(), args.device)
            if not part:
                raise CommandError(f"Device not found: {args.device}")

            passphrase = None
            if part.is_luks and not is_luks_open(part):
                passphrase = _prompt_luks_passphrase()

            if args.is_async:
                _, msg = mount_partition_async(part, base_dir, root_sources(), passphrase).result()
            else:
                _, msg = mount_partition(part, base_dir, root_sources(), passphrase)
            print(msg)
            return 0

        if args.cmd == "umount":
            require_root()
            part = find_partition(collect_partitions(), args.device)
            if not part:
                raise CommandError(f"Device not found: {args.device}")
            if args.is_async:
                _, msg = umount_partition_async(part, root_sources(), args.lock_luks).result()
            else:
                _, msg = umount_partition(part, root_sources(), args.lock_luks)
            print(msg)
            return 0

        if args.cmd == "tui":
            run_tui(base_dir)
            return 0

        if args.cmd == "boot-list":
            boot_map = persistent_mount_map()
            if not boot_map:
                print("No diskman reboot auto-mount entries found.")
                return 0
            for uuid, mnt in boot_map.items():
                print(f"UUID={uuid} -> {mnt}")
            return 0

        if args.cmd == "boot-add":
            require_root()
            part = find_partition(collect_partitions(), args.device)
            if not part:
                raise CommandError(f"Device not found: {args.device}")
            print(enable_persistent_mount(part, base_dir, root_sources()))
            return 0

        if args.cmd == "boot-remove":
            require_root()
            part = find_partition(collect_partitions(), args.device)
            if not part:
                raise CommandError(f"Device not found: {args.device}")
            print(disable_persistent_mount(part))
            return 0

        if args.cmd == "luks-unlock":
            require_root()
            part = find_partition(collect_partitions(), args.device)
            if not part:
                raise CommandError(f"Device not found: {args.device}")
            passphrase = _prompt_luks_passphrase()
            mapper = unlock_luks(part, passphrase)
            print(f"Unlocked {part.path} -> {mapper}")
            return 0

        if args.cmd == "luks-lock":
            require_root()
            part = find_partition(collect_partitions(), args.device)
            if not part:
                raise CommandError(f"Device not found: {args.device}")
            print(lock_luks(part))
            return 0

        raise CommandError(f"Unknown command: {args.cmd}")
    except CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
