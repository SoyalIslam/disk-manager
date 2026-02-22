from __future__ import annotations

import curses
from pathlib import Path

from .core import (
    automount,
    collect_partitions,
    disable_persistent_mount,
    enable_persistent_mount,
    is_mountable,
    is_root_partition,
    mount_partition,
    persistent_mount_map,
    require_root,
    root_sources,
    umount_partition,
)


def run_tui(base_dir: Path) -> None:
    def tui(stdscr) -> None:
        curses.curs_set(0)
        stdscr.nodelay(False)
        stdscr.keypad(True)
        index = 0
        nav = "r:refresh  a:auto-mount  m:mount/unmount  p:toggle boot mount  q:quit"
        status = "Ready"
        parts = collect_partitions()

        while True:
            roots = root_sources()
            boot_map = persistent_mount_map()
            h, w = stdscr.getmaxyx()
            stdscr.erase()
            stdscr.addnstr(0, 0, "diskman TUI", w - 1)
            stdscr.addnstr(1, 0, nav, w - 1)
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
                if not is_mountable(part):
                    flags.append("SKIP")
                if part.uuid and part.uuid in boot_map:
                    flags.append("AUTOBOOT")
                line = (
                    f"{marker} {part.path:<16} {part.fstype or '-':<7} "
                    f"{part.size or '-':<7} {part.mountpoint or '-':<18} {','.join(flags) or '-'}"
                )
                stdscr.addnstr(row, 0, line, w - 1)

            key = stdscr.getch()
            if key in (ord("q"), 27):
                status = "Exiting..."
                stdscr.addnstr(2, 0, f"Result: {status}", w - 1)
                stdscr.refresh()
                curses.napms(250)
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
            elif key == ord("a"):
                try:
                    require_root()
                    logs = automount(base_dir=base_dir)
                    status = logs[-1] if logs else "No changes"
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
                index = min(index, max(len(parts) - 1, 0))
            elif key == ord("m") and parts:
                part = parts[index]
                try:
                    require_root()
                    if part.mounted:
                        _, status = umount_partition(part, roots)
                    else:
                        _, status = mount_partition(part, base_dir, roots)
                except Exception as exc:
                    status = f"Error: {exc}"
                parts = collect_partitions()
            elif key == ord("p") and parts:
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

    curses.wrapper(tui)
