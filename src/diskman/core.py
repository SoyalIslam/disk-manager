from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

LSBLK_COLUMNS = "NAME,KNAME,PATH,TYPE,PKNAME,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT,ROTA"
DEFAULT_BASE_DIR = Path("/mnt/auto")
DEFAULT_FSTAB_PATH = Path("/etc/fstab")
DISKMAN_FSTAB_TAG = "diskman:auto"

_smart_cache: dict[str, str] = {}
_executor = ThreadPoolExecutor(max_workers=4)


@dataclass
class Partition:
    name: str
    kname: str
    path: str
    devtype: str
    pkname: str
    disk_path: str
    disk_kind: str
    fstype: str
    label: str
    uuid: str
    size: str
    mountpoint: str

    @property
    def mounted(self) -> bool:
        return bool(self.mountpoint)

    @property
    def is_luks(self) -> bool:
        return self.fstype.lower() == "crypto_luks"


class CommandError(RuntimeError):
    pass


def run_cmd(cmd: List[str], check: bool = True, input_text: str | None = None) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, input=input_text)
    if check and proc.returncode != 0:
        raise CommandError((proc.stderr or proc.stdout or "command failed").strip())
    return proc.stdout.strip()


def run_cmd_proc(cmd: List[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, input=input_text)


def lsblk_json() -> dict:
    out = run_cmd(["lsblk", "-J", "-p", "-o", LSBLK_COLUMNS])
    return json.loads(out)


def iter_nodes(node: dict):
    yield node
    for child in node.get("children", []):
        yield from iter_nodes(child)


def _rota_to_kind(rota: object) -> str:
    if rota is True or str(rota).strip() == "1":
        return "HDD"
    if rota is False or str(rota).strip() == "0":
        return "SSD"
    return "UNKNOWN"


def _pick_mount_options(part: Partition, read_only: bool = False) -> str:
    opts = ["defaults", "nofail", "noatime"]
    if read_only:
        opts.append("ro")

    fs = part.fstype.lower()
    if fs in {"ext4", "xfs", "btrfs", "f2fs"} and part.disk_kind == "SSD":
        opts.append("discard")
    if fs in {"vfat", "fat", "fat32", "exfat"}:
        opts.extend([f"uid={os.getuid()}", f"gid={os.getgid()}", "umask=022"])
    if fs == "ntfs3":
        opts.extend([f"uid={os.getuid()}", f"gid={os.getgid()}", "windows_names"])

    # Keep order stable and unique.
    return ",".join(dict.fromkeys(opts))


def _mount_once(path: str, mountpoint: str, options: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["mount"]
    if options:
        cmd.extend(["-o", options])
    cmd.extend([path, mountpoint])
    return run_cmd_proc(cmd)


def _mount_with_read_only_fallback(part: Partition, mountpoint: Path) -> Tuple[bool, str]:
    rw_opts = _pick_mount_options(part, read_only=False)
    proc = _mount_once(part.path, str(mountpoint), rw_opts)
    if proc.returncode == 0:
        return True, f"Mounted {part.path} -> {mountpoint} ({rw_opts})"

    ro_opts = _pick_mount_options(part, read_only=True)
    ro_proc = _mount_once(part.path, str(mountpoint), ro_opts)
    if ro_proc.returncode == 0:
        reason = (proc.stderr or proc.stdout or "rw mount failed").strip()
        return True, f"Mounted read-only {part.path} -> {mountpoint} ({ro_opts}); reason: {reason}"

    err = (ro_proc.stderr or ro_proc.stdout or proc.stderr or proc.stdout or "mount failed").strip()
    return False, f"Mount failed for {part.path}: {err}"


def _luks_mapper_name(part: Partition) -> str:
    safe = Path(part.kname).name.replace("/", "-")
    return f"diskman-{safe}"


def _luks_mapper_path(mapper_name: str) -> str:
    return f"/dev/mapper/{mapper_name}"


def is_luks_open(part: Partition) -> bool:
    mapper_name = _luks_mapper_name(part)
    mapper_path = _luks_mapper_path(mapper_name)
    return Path(mapper_path).exists()


def unlock_luks(part: Partition, passphrase: str) -> str:
    if not part.is_luks:
        raise CommandError(f"Not a LUKS device: {part.path}")

    mapper_name = _luks_mapper_name(part)
    proc = run_cmd_proc(["cryptsetup", "open", part.path, mapper_name, "--key-file", "-"], input_text=passphrase)
    if proc.returncode != 0:
        raise CommandError((proc.stderr or proc.stdout or "cryptsetup open failed").strip())
    return _luks_mapper_path(mapper_name)


def lock_luks(part: Partition) -> str:
    if not part.is_luks:
        raise CommandError(f"Not a LUKS device: {part.path}")
    mapper_name = _luks_mapper_name(part)
    run_cmd(["cryptsetup", "close", mapper_name])
    return f"Closed LUKS mapper: {mapper_name}"


def _resolve_luks_inner(part: Partition) -> str:
    mapper_name = _luks_mapper_name(part)
    mapper_path = _luks_mapper_path(mapper_name)
    if not Path(mapper_path).exists():
        raise CommandError(f"LUKS device is locked: {part.path}. Unlock first.")

    out = run_cmd(["lsblk", "-J", "-p", "-o", "PATH,FSTYPE", mapper_path])
    data = json.loads(out)
    nodes = data.get("blockdevices", [])
    if not nodes:
        return mapper_path
    node = nodes[0]
    children = node.get("children", [])
    if children:
        child_path = (children[0].get("path") or "").strip()
        if child_path.startswith("/dev/"):
            return child_path
    return mapper_path


def _physical_disk_path(node: dict, top_path: str) -> str:
    pkname = (node.get("pkname") or "").strip()
    if pkname:
        if pkname.startswith("/dev/"):
            return pkname
        return f"/dev/{pkname}"
    return top_path


def collect_partitions() -> List[Partition]:
    data = lsblk_json()
    partitions: List[Partition] = []
    for top in data.get("blockdevices", []):
        top_path = (top.get("path") or "").strip()
        top_kind = _rota_to_kind(top.get("rota"))
        for node in iter_nodes(top):
            devtype = (node.get("type") or "").strip()
            path = (node.get("path") or "").strip()
            if not path.startswith("/dev/"):
                continue
            if devtype in {"disk", "loop", "rom"}:
                continue

            disk_path = _physical_disk_path(node, top_path)
            partitions.append(
                Partition(
                    name=(node.get("name") or "").strip(),
                    kname=(node.get("kname") or "").strip(),
                    path=path,
                    devtype=devtype,
                    pkname=(node.get("pkname") or "").strip(),
                    disk_path=disk_path,
                    disk_kind=top_kind,
                    fstype=(node.get("fstype") or "").strip(),
                    label=(node.get("label") or "").strip(),
                    uuid=(node.get("uuid") or "").strip(),
                    size=(node.get("size") or "").strip(),
                    mountpoint=(node.get("mountpoint") or "").strip(),
                )
            )

    partitions.sort(key=lambda p: p.path)
    return partitions


def root_sources() -> set[str]:
    source = run_cmd(["findmnt", "-n", "-o", "SOURCE", "/"])
    source = source.strip()
    if not source:
        return set()
    if source.startswith("/dev/"):
        return {source.split("[", 1)[0]}
    return set()


def is_root_partition(part: Partition, root_devs: set[str]) -> bool:
    return part.path in root_devs or part.mountpoint == "/"


def is_mountable(part: Partition) -> bool:
    if not part.fstype:
        return False
    if part.fstype.lower() == "swap":
        return False
    if part.is_luks:
        # LUKS container needs unlock before mount.
        return True
    return True


def target_mount_point(part: Partition, base_dir: Path) -> Path:
    return base_dir / Path(part.path).name


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise CommandError("This operation requires root. Re-run with sudo.")


def find_partition(parts: List[Partition], device: str) -> Partition | None:
    for part in parts:
        if part.path == device:
            return part
    return None


def _smart_health_for_disk(disk_path: str) -> str:
    if disk_path in _smart_cache:
        return _smart_cache[disk_path]

    # smartctl may require root and may not exist on all systems.
    try:
        proc = run_cmd_proc(["smartctl", "-H", "-j", disk_path])
    except FileNotFoundError:
        _smart_cache[disk_path] = "NO_SMARTCTL"
        return _smart_cache[disk_path]

    if proc.returncode != 0 and not proc.stdout:
        _smart_cache[disk_path] = "UNAVAILABLE"
        return _smart_cache[disk_path]

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        _smart_cache[disk_path] = "UNKNOWN"
        return _smart_cache[disk_path]

    smart_status = payload.get("smart_status") or {}
    passed = smart_status.get("passed")
    if passed is True:
        status = "PASSED"
    elif passed is False:
        status = "FAILED"
    else:
        # Fallback to short text status fields if present.
        status = (
            str(payload.get("ata_smart_data", {}).get("self_test", {}).get("status", {}).get("string") or "")
            .strip()
            .upper()
            or "UNKNOWN"
        )

    _smart_cache[disk_path] = status
    return status


def smart_health(part: Partition) -> str:
    return _smart_health_for_disk(part.disk_path)


def mount_partition(
    part: Partition,
    base_dir: Path,
    root_devs: set[str],
    luks_passphrase: str | None = None,
) -> Tuple[bool, str]:
    if is_root_partition(part, root_devs):
        return False, f"Skipping root partition: {part.path}"
    if not is_mountable(part):
        return False, f"Not mountable: {part.path}"
    if part.mounted:
        return False, f"Already mounted: {part.path} -> {part.mountpoint}"

    mount_source = part.path
    if part.is_luks:
        if not is_luks_open(part):
            if luks_passphrase is None:
                return False, f"LUKS device locked: {part.path}"
            unlock_luks(part, luks_passphrase)
        mount_source = _resolve_luks_inner(part)

    mnt = target_mount_point(part, base_dir)
    ensure_dir(mnt)

    # Try filesystem-aware rw mount first; fallback to read-only.
    effective = Partition(**{**part.__dict__, "path": mount_source, "fstype": part.fstype})
    ok, msg = _mount_with_read_only_fallback(effective, mnt)
    if ok:
        return True, msg
    return False, msg


def umount_partition(part: Partition, root_devs: set[str], lock_luks_after: bool = False) -> Tuple[bool, str]:
    if is_root_partition(part, root_devs):
        return False, f"Skipping root partition: {part.path}"
    if not part.mounted:
        if part.is_luks and lock_luks_after and is_luks_open(part):
            lock_msg = lock_luks(part)
            return True, f"Not mounted; {lock_msg}"
        return False, f"Not mounted: {part.path}"

    run_cmd(["umount", part.path])
    if part.is_luks and lock_luks_after and is_luks_open(part):
        lock_msg = lock_luks(part)
        return True, f"Unmounted {part.path}; {lock_msg}"
    return True, f"Unmounted {part.path}"


def automount(base_dir: Path, dry_run: bool = False) -> List[str]:
    logs: List[str] = []
    parts = collect_partitions()
    roots = root_sources()

    for part in parts:
        if is_root_partition(part, roots):
            logs.append(f"SKIP root: {part.path}")
            continue
        if not is_mountable(part):
            logs.append(f"SKIP unsupported: {part.path}")
            continue
        if part.mounted:
            logs.append(f"SKIP already mounted: {part.path} -> {part.mountpoint}")
            continue
        if part.is_luks and not is_luks_open(part):
            logs.append(f"SKIP locked LUKS: {part.path}")
            continue

        mnt = target_mount_point(part, base_dir)
        if dry_run:
            logs.append(f"DRY-RUN mount {part.path} -> {mnt}")
            continue

        try:
            ensure_dir(mnt)
            _, msg = mount_partition(part, base_dir, roots)
            logs.append(f"OK {msg}")
        except Exception as exc:
            logs.append(f"ERR mount {part.path}: {exc}")

    return logs


def automount_async(base_dir: Path, dry_run: bool = False) -> Future[List[str]]:
    return _executor.submit(automount, base_dir, dry_run)


def mount_partition_async(
    part: Partition,
    base_dir: Path,
    root_devs: set[str],
    luks_passphrase: str | None = None,
) -> Future[Tuple[bool, str]]:
    return _executor.submit(mount_partition, part, base_dir, root_devs, luks_passphrase)


def umount_partition_async(
    part: Partition,
    root_devs: set[str],
    lock_luks_after: bool = False,
) -> Future[Tuple[bool, str]]:
    return _executor.submit(umount_partition, part, root_devs, lock_luks_after)


def persistent_mount_map(fstab_path: Path = DEFAULT_FSTAB_PATH) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = fstab_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return entries

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if DISKMAN_FSTAB_TAG not in stripped:
            continue

        fields = stripped.split()
        if len(fields) < 2:
            continue
        spec = fields[0]
        mountpoint = fields[1]
        if spec.startswith("UUID="):
            entries[spec.removeprefix("UUID=")] = mountpoint

    return entries


def fstab_line_for_partition(part: Partition, base_dir: Path) -> str:
    if not part.uuid:
        raise CommandError(f"Missing UUID for {part.path}; cannot persist in fstab safely.")
    if not is_mountable(part):
        raise CommandError(f"Partition is not mountable: {part.path}")
    if part.is_luks:
        raise CommandError(f"Refusing to persist raw LUKS container in fstab: {part.path}")
    mnt = target_mount_point(part, base_dir)
    opts = _pick_mount_options(part, read_only=False)
    return f"UUID={part.uuid} {mnt} {part.fstype} {opts} 0 2 # {DISKMAN_FSTAB_TAG} {part.path}"


def enable_persistent_mount(
    part: Partition, base_dir: Path, root_devs: set[str], fstab_path: Path = DEFAULT_FSTAB_PATH
) -> str:
    if is_root_partition(part, root_devs):
        raise CommandError(f"Refusing to persist root partition: {part.path}")
    ensure_dir(target_mount_point(part, base_dir))
    existing = persistent_mount_map(fstab_path)
    if part.uuid in existing:
        return f"Persistent mount already enabled for {part.path} -> {existing[part.uuid]}"

    line = fstab_line_for_partition(part, base_dir)
    with fstab_path.open("a", encoding="utf-8") as f:
        f.write("\n" + line + "\n")
    return f"Enabled reboot auto-mount for {part.path}"


def disable_persistent_mount(part: Partition, fstab_path: Path = DEFAULT_FSTAB_PATH) -> str:
    if not part.uuid:
        raise CommandError(f"Missing UUID for {part.path}; cannot remove from fstab safely.")
    try:
        lines = fstab_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise CommandError(f"fstab not found: {fstab_path}")

    kept: List[str] = []
    removed = False
    uuid_key = f"UUID={part.uuid}"
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and DISKMAN_FSTAB_TAG in stripped and uuid_key in stripped:
            removed = True
            continue
        kept.append(line)

    if not removed:
        return f"Persistent mount was not enabled for {part.path}"

    fstab_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return f"Disabled reboot auto-mount for {part.path}"
