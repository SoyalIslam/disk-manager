from __future__ import annotations

import curses
from concurrent.futures import Future
from pathlib import Path

from .core import (
    automount_async,
    collect_partitions,
    disable_persistent_mount,
    enable_persistent_mount,
    is_luks_open,
    is_mountable,
    is_root_partition,
    mount_partition_async,
    persistent_mount_map,
    require_root,
    root_sources,
    smart_health,
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


def run_tui(base_dir: Path) -> None:
    def tui(stdscr) -> None:
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.keypad(True)
        index = 0
        nav = "r:refresh  a:auto-mount  m:mount/unmount  p:toggle boot mount  q:quit"
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

    curses.wrapper(tui)
