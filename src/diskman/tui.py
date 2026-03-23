from __future__ import annotations

import curses
from concurrent.futures import Future
from pathlib import Path

from .core import (
    automount_async,
    collect_partitions,
    create_partition_async,
    delete_partition_async,
    disable_persistent_mount,
    enable_persistent_mount,
    is_mount_read_only,
    is_luks_open,
    is_mountable,
    is_root_partition,
    lock_luks_async,
    mount_partition_async,
    merge_with_unallocated_async,
    persistent_mount_map,
    require_root,
    root_sources,
    smart_health,
    unlock_luks_async,
    umount_partition_async,
)


def _prompt_hidden(stdscr, y: int, x: int, prompt: str) -> str:
    curses.noecho()
    stdscr.addstr(y, x, prompt)
    stdscr.refresh()
    buf = []
    while True:
        key = stdscr.getch()
        if key in (10, 13):
            break
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if buf:
                buf.pop()
                stdscr.addstr(y, x + len(prompt) + len(buf), " ")
                stdscr.move(y, x + len(prompt) + len(buf))
                stdscr.refresh()
            continue
        if 32 <= key <= 126:
            buf.append(chr(key))
            stdscr.addstr(y, x + len(prompt) + len(buf) - 1, "*")
            stdscr.refresh()
    return "".join(buf)


def _prompt_line(stdscr, y: int, x: int, prompt: str) -> str:
    curses.echo()
    curses.curs_set(1)
    stdscr.nodelay(False)
    try:
        stdscr.move(y, x)
        stdscr.clrtoeol()
        stdscr.addstr(y, x, prompt)
        stdscr.refresh()
        raw = stdscr.getstr(y, x + len(prompt), 256)
        return raw.decode("utf-8", errors="ignore").strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
        stdscr.nodelay(True)


def _select_menu(stdscr, title: str, options: list[str]) -> str | None:
    if not options:
        return None

    idx = 0
    stdscr.nodelay(False)
    try:
        while True:
            h, w = stdscr.getmaxyx()
            start_row = min(h - 2, 4)
            stdscr.move(start_row - 1, 0)
            stdscr.clrtoeol()
            stdscr.addnstr(start_row - 1, 0, f"{title} (Enter=select, q/Esc=cancel)", w - 1)
            for i, opt in enumerate(options):
                row = start_row + i
                if row >= h:
                    break
                marker = ">" if i == idx else " "
                stdscr.move(row, 0)
                stdscr.clrtoeol()
                stdscr.addnstr(row, 0, f"{marker} {opt}", w - 1)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (10, 13):
                return options[idx]
            if key in (27, ord("q")):
                return None
            if key in (curses.KEY_DOWN, ord("j")):
                idx = min(idx + 1, len(options) - 1)
            elif key in (curses.KEY_UP, ord("k")):
                idx = max(idx - 1, 0)
    finally:
        stdscr.nodelay(True)


def run_tui(base_dir: Path) -> None:
    def tui(stdscr) -> None:
        # Check root permission at TUI startup
        try:
            require_root()
        except Exception as exc:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            error_msg = f"Error: {exc}"
            stdscr.addnstr(0, 0, error_msg, w - 1)
            stdscr.addnstr(1, 0, "Please run with sudo: sudo diskman tui", w - 1)
            stdscr.refresh()
            curses.napms(2000)
            raise

        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.keypad(True)
        index = 0
        nav = "r:refresh a:auto m:mount/unmount u:unlock l:lock p:boot c:create d:delete g:merge-free q:quit"
        status = "Ready"
        parts = collect_partitions()
        pending: Future | None = None
        pending_action = ""

        while True:
            if pending and pending.done():
                try:
                    result = pending.result()
                    if isinstance(result, tuple):
                        _, status = result
                    elif isinstance(result, list):
                        status = result[-1] if result else "No changes"
                    else:
                        status = str(result)
                except Exception as exc:
                    status = f"Error: {exc}"
                pending = None
                pending_action = ""
                parts = collect_partitions()
                index = min(index, max(len(parts) - 1, 0))

            roots = root_sources()
            boot_map = persistent_mount_map()
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            stdscr.addnstr(0, 0, "diskman TUI", w - 1)
            stdscr.addnstr(1, 0, nav, w - 1)
            if pending:
                stdscr.addnstr(2, 0, f"Result: {status} (running: {pending_action})", w - 1)
            else:
                stdscr.addnstr(2, 0, f"Result: {status}", w - 1)
            stdscr.addnstr(3, 0, "-" * max(0, w - 1), w - 1)

            for row, part in enumerate(parts[: max(0, h - 5)], start=4):
                i = row - 4
                if i >= len(parts):
                    break
                marker = ">" if i == index else " "
                flags = []
                if is_root_partition(part, roots):
                    flags.append("ROOT")
                if part.mounted:
                    flags.append("MOUNTED")
                    if is_mount_read_only(part):
                        flags.append("RO")
                if not is_mountable(part):
                    flags.append("SKIP")
                if part.is_luks:
                    flags.append("LUKS_OPEN" if is_luks_open(part) else "LUKS_LOCKED")
                if part.uuid and part.uuid in boot_map:
                    flags.append("AUTOBOOT")
                line = (
                    f"{marker} {part.path:<16} {part.disk_kind:<3} {part.fstype or '-':<10} {part.size or '-':<7} "
                    f"{smart_health(part):<8} {part.mountpoint or '-':<16} {','.join(flags) or '-'}"
                )
                stdscr.addnstr(row, 0, line, w - 1)

            key = stdscr.getch()
            if key == -1:
                curses.napms(40)
                continue

            if key in (ord("q"), 27):
                status = "Exiting..."
                stdscr.addnstr(2, 0, f"Result: {status}", w - 1)
                stdscr.refresh()
                curses.napms(200)
                break

            if key in (curses.KEY_DOWN, ord("j")):
                index = min(index + 1, max(len(parts) - 1, 0))
                status = f"Selected {parts[index].path}" if parts else "Ready"
            elif key in (curses.KEY_UP, ord("k")):
                index = max(index - 1, 0)
                status = f"Selected {parts[index].path}" if parts else "Ready"
            elif key == ord("r"):
                parts = collect_partitions()
                status = "Refreshed"
                index = min(index, max(len(parts) - 1, 0))
            elif key == ord("a") and not pending:
                try:
                    require_root()
                    pending = automount_async(base_dir=base_dir)
                    pending_action = "automount"
                    status = "Automount started"
                except Exception as exc:
                    status = f"Error: {exc}"
            elif key == ord("m") and parts and not pending:
                part = parts[index]
                try:
                    require_root()
                    if part.mounted:
                        pending = umount_partition_async(part, roots)
                        pending_action = f"unmount {part.path}"
                    else:
                        passphrase = None
                        if part.is_luks and not is_luks_open(part):
                            status = "Enter LUKS passphrase"
                            stdscr.addnstr(2, 0, f"Result: {status}", w - 1)
                            stdscr.refresh()
                            passphrase = _prompt_hidden(stdscr, min(h - 1, 3), 0, "LUKS passphrase: ")
                        pending = mount_partition_async(part, base_dir, roots, passphrase)
                        pending_action = f"mount {part.path}"
                    status = f"Started {pending_action}"
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
            elif key == ord("u") and parts and not pending:
                part = parts[index]
                try:
                    require_root()
                    if not part.is_luks:
                        status = f"Not LUKS: {part.path}"
                    elif is_luks_open(part):
                        status = f"Already unlocked: {part.path}"
                    else:
                        status = "Enter LUKS passphrase"
                        stdscr.addnstr(2, 0, f"Result: {status}", w - 1)
                        stdscr.refresh()
                        passphrase = _prompt_hidden(stdscr, min(h - 1, 3), 0, "LUKS passphrase: ")
                        pending = unlock_luks_async(part, passphrase)
                        pending_action = f"unlock {part.path}"
                        status = f"Started {pending_action}"
                except Exception as exc:
                    status = f"Error: {exc}"
            elif key == ord("l") and parts and not pending:
                part = parts[index]
                try:
                    require_root()
                    if not part.is_luks:
                        status = f"Not LUKS: {part.path}"
                    elif not is_luks_open(part):
                        status = f"Already locked: {part.path}"
                    else:
                        pending = lock_luks_async(part)
                        pending_action = f"lock {part.path}"
                        status = f"Started {pending_action}"
                except Exception as exc:
                    status = f"Error: {exc}"
            elif key == ord("p") and parts and not pending:
                part = parts[index]
                try:
                    require_root()
                    if not part.uuid:
                        status = f"Error: missing UUID for {part.path}"
                    elif part.uuid in boot_map:
                        status = disable_persistent_mount(part)
                    else:
                        status = enable_persistent_mount(part, base_dir, roots)
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
            elif key == ord("c") and not pending:
                try:
                    require_root()
                    status = "Create partition: provide disk and filesystem"
                    stdscr.addnstr(2, 0, f"Result: {status}", w - 1)
                    stdscr.refresh()

                    disk = _prompt_line(stdscr, min(h - 1, 3), 0, "Disk path (/dev/sdX or /dev/nvmeXnY): ")
                    fs = _select_menu(stdscr, "Select filesystem", ["ntfs", "btrfs", "exfat", "vfat", "ext2", "ext3", "ext4", "xfs", "f2fs", "nilfs2", "reiserfs", "udf"])
                    if not fs:
                        status = "Create canceled"
                        parts = collect_partitions()
                        index = min(index, max(len(parts) - 1, 0))
                        continue
                    label = _prompt_line(stdscr, min(h - 1, 3), 0, "Label (optional): ")
                    size = _prompt_line(stdscr, min(h - 1, 3), 0, "Size (optional, e.g. 100G): ")
                    start_mib_raw = _prompt_line(stdscr, min(h - 1, 3), 0, "Start MiB (optional): ")

                    start_mib = None
                    if start_mib_raw:
                        try:
                            start_mib = float(start_mib_raw)
                        except ValueError:
                            raise ValueError(f"Invalid Start MiB value: {start_mib_raw}")

                    pending = create_partition_async(
                        disk=disk,
                        filesystem=fs,
                        label=label or None,
                        size=size or None,
                        start_mib=start_mib,
                    )
                    pending_action = f"create partition on {disk}"
                    status = f"Started {pending_action}"
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
                index = min(index, max(len(parts) - 1, 0))
            elif key == ord("d") and parts and not pending:
                part = parts[index]
                try:
                    require_root()
                    confirm = _prompt_line(stdscr, min(h - 1, 3), 0, f"Type DELETE to remove {part.path}: ")
                    if confirm != "DELETE":
                        status = "Delete canceled"
                    else:
                        wipe = _prompt_line(stdscr, min(h - 1, 3), 0, "Wipe signatures first? (y/N): ")
                        wipe_signatures = wipe.strip().lower() in {"y", "yes"}
                        pending = delete_partition_async(part.path, wipe_signatures=wipe_signatures)
                        pending_action = f"delete {part.path}"
                        status = f"Started {pending_action}"
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
                index = min(index, max(len(parts) - 1, 0))
            elif key == ord("g") and parts and not pending:
                part = parts[index]
                try:
                    require_root()
                    confirm = _prompt_line(stdscr, min(h - 1, 3), 0, f"Type MERGE to expand {part.path}: ")
                    if confirm != "MERGE":
                        status = "Merge canceled"
                    else:
                        pending = merge_with_unallocated_async(part.path)
                        pending_action = f"merge-free {part.path}"
                        status = f"Started {pending_action}"
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
                index = min(index, max(len(parts) - 1, 0))

    curses.wrapper(tui)
