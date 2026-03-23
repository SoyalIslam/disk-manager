from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from re import sub
from typing import List, Tuple

LSBLK_COLUMNS = "NAME,KNAME,PATH,TYPE,PKNAME,FSTYPE,LABEL,UUID,SIZE,MOUNTPOINT,ROTA"
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


SUPPORTED_MKFS = {
    "btrfs",
    "exfat",
    "ext2",
    "ext3",
    "ext4",
    "f2fs",
    "nilfs2",
    "ntfs3",
    "reiserfs",
    "udf",
    "vfat",
    "xfs",
}


def _invoking_username() -> str:
    user = (os.environ.get("SUDO_USER") or os.environ.get("USER") or "").strip()
    return user or "root"


def _invoking_uid_gid() -> Tuple[int, int]:
    sudo_uid = (os.environ.get("SUDO_UID") or "").strip()
    sudo_gid = (os.environ.get("SUDO_GID") or "").strip()
    if sudo_uid.isdigit() and sudo_gid.isdigit():
        return int(sudo_uid), int(sudo_gid)
    return os.getuid(), os.getgid()


def default_base_dir() -> Path:
    return Path("/run/media") / _invoking_username()


DEFAULT_BASE_DIR = default_base_dir()


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
    uid, gid = _invoking_uid_gid()
    opts = ["defaults", "nofail", "noatime"]
    if read_only:
        opts.append("ro")

    fs = part.fstype.lower()
    if fs in {"ext4", "xfs", "btrfs", "f2fs", "ext3", "ext2"} and part.disk_kind == "SSD":
        opts.append("discard")
    if fs in {"vfat", "fat", "fat32", "exfat", "fat16", "fat12"}:
        opts.extend([f"uid={uid}", f"gid={gid}", "umask=022"])
    if fs == "ntfs3":
        opts.extend([f"uid={uid}", f"gid={gid}", "windows_names"])
    if fs in {"udf", "iso9660"}:
        opts.append("ro")
    if fs == "reiserfs":
        opts.append("nobarrier")

    # Keep order stable and unique.
    return ",".join(dict.fromkeys(opts))


def _mount_once(
    path: str,
    mountpoint: str,
    fstype: str | None = None,
    options: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["mount"]
    if fstype:
        cmd.extend(["-t", fstype])
    if options:
        cmd.extend(["-o", options])
    cmd.extend([path, mountpoint])
    return run_cmd_proc(cmd)


def _mount_with_read_only_fallback(part: Partition, mountpoint: Path) -> Tuple[bool, str]:
    fstype = canonical_fstype(part.fstype)
    rw_opts = _pick_mount_options(part, read_only=False)
    proc = _mount_once(part.path, str(mountpoint), fstype=fstype, options=rw_opts)
    if proc.returncode == 0:
        return True, f"Mounted {part.path} -> {mountpoint} ({fstype or 'auto'}; {rw_opts})"

    ro_opts = _pick_mount_options(part, read_only=True)
    ro_proc = _mount_once(part.path, str(mountpoint), fstype=fstype, options=ro_opts)
    if ro_proc.returncode == 0:
        reason = (proc.stderr or proc.stdout or "rw mount failed").strip()
        return True, f"Mounted read-only {part.path} -> {mountpoint} ({fstype or 'auto'}; {ro_opts}); reason: {reason}"

    err = (ro_proc.stderr or ro_proc.stdout or proc.stderr or proc.stdout or "mount failed").strip()
    return False, f"Mount failed for {part.path}: {err}"


def _detect_filesystem_type(path: str) -> str:
    probe = run_cmd_proc(["blkid", "-o", "value", "-s", "TYPE", path])
    fs = (probe.stdout or "").strip()
    if fs:
        return canonical_fstype(fs)

    lsblk_probe = run_cmd_proc(["lsblk", "-n", "-o", "FSTYPE", path])
    fs = (lsblk_probe.stdout or "").strip()
    if fs:
        return canonical_fstype(fs)
    return ""


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


def canonical_fstype(fstype: str) -> str:
    raw = (fstype or "").strip().lower()
    if raw in {"ntfs", "ntfs3g", "fuseblk"}:
        return "ntfs3"
    if raw in {"fat", "fat16", "fat32"}:
        return "vfat"
    if raw in {"exfat", "fat12"}:
        return "exfat"
    if raw == "udf":
        return "udf"
    return raw


def _mkfs_target_for(fs: str) -> str:
    canonical = canonical_fstype(fs)
    if canonical == "ntfs3":
        return "ntfs3"
    return canonical


def _mkfs_cmd_for(fs: str, device: str, label: str | None = None) -> List[str]:
    mkfs_target = _mkfs_target_for(fs)
    if mkfs_target not in SUPPORTED_MKFS:
        raise CommandError(f"Unsupported filesystem '{fs}'. Supported: {', '.join(sorted(SUPPORTED_MKFS))}")

    if mkfs_target == "ntfs3":
        cmd = ["mkfs.ntfs", "-F"]
        if label:
            cmd.extend(["-L", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "btrfs":
        cmd = ["mkfs.btrfs", "-f"]
        if label:
            cmd.extend(["-L", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "exfat":
        cmd = ["mkfs.exfat"]
        if label:
            cmd.extend(["-n", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "vfat":
        cmd = ["mkfs.vfat", "-F", "32"]
        if label:
            cmd.extend(["-n", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "ext2":
        cmd = ["mkfs.ext2"]
        if label:
            cmd.extend(["-L", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "ext3":
        cmd = ["mkfs.ext3"]
        if label:
            cmd.extend(["-L", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "nilfs2":
        cmd = ["mkfs.nilfs2"]
        if label:
            cmd.extend(["-n", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "reiserfs":
        cmd = ["mkfs.reiserfs", "-f"]
        if label:
            cmd.extend(["-l", label])
        cmd.append(device)
        return cmd

    if mkfs_target == "udf":
        cmd = ["mkudffs"]
        if label:
            cmd.extend(["--lvid", label])
        cmd.append(device)
        return cmd

    cmd = ["mkfs", "-t", mkfs_target]
    if label:
        cmd.extend(["-L", label])
    cmd.append(device)
    return cmd


def _partition_number(device: str) -> str:
    partn = run_cmd(["lsblk", "-n", "-o", "PARTN", device]).strip()
    if not partn:
        raise CommandError(f"Unable to determine partition number for {device}")
    return partn


def _partition_number_int(device: str) -> int:
    return int(_partition_number(device))


def _device_type(device: str) -> str:
    return run_cmd(["lsblk", "-n", "-o", "TYPE", device]).strip().lower()


def _rescan_partition_table(disk: str) -> None:
    run_cmd_proc(["partprobe", disk])
    run_cmd_proc(["udevadm", "settle"])


def _largest_free_span_mib(disk: str) -> Tuple[float, float]:
    out = run_cmd(["parted", "-m", "-s", disk, "unit", "MiB", "print", "free"])
    best: Tuple[float, float] | None = None
    best_size = 0.0
    for line in out.splitlines():
        fields = [f.strip() for f in line.split(":")]
        if len(fields) < 5:
            continue
        kind = fields[4].rstrip(";").lower()
        if kind != "free":
            continue
        start_raw = fields[1].removesuffix("MiB")
        end_raw = fields[2].removesuffix("MiB")
        try:
            start = float(start_raw)
            end = float(end_raw)
        except ValueError:
            continue
        size = max(0.0, end - start)
        if size > best_size:
            best_size = size
            best = (start, end)
    if not best:
        raise CommandError(f"No free space found on {disk}")
    return best


def _parted_rows_mib(disk: str) -> List[dict]:
    out = run_cmd(["parted", "-m", "-s", disk, "unit", "MiB", "print", "free"])
    rows: List[dict] = []
    for line in out.splitlines():
        fields = [f.strip() for f in line.split(":")]
        if len(fields) < 5:
            continue
        start_raw = fields[1].removesuffix("MiB")
        end_raw = fields[2].removesuffix("MiB")
        try:
            start = float(start_raw)
            end = float(end_raw)
        except ValueError:
            continue
        partn = int(fields[0]) if fields[0].isdigit() else None
        kind = fields[4].rstrip(";").lower()
        rows.append({"partn": partn, "start": start, "end": end, "kind": kind})
    return rows


def _mib_spec(value: float) -> str:
    return f"{value:.2f}MiB"


def _resolve_create_range(disk: str, size: str | None, start_mib: float | None) -> Tuple[str, str]:
    free_start, free_end = _largest_free_span_mib(disk)
    start = free_start if start_mib is None else start_mib
    if start < free_start or start >= free_end:
        raise CommandError(f"Start MiB {start} is outside free space {free_start:.2f}..{free_end:.2f} on {disk}")

    if size:
        try:
            size_bytes = int(run_cmd(["numfmt", "--from=iec", size]))
        except Exception as exc:
            raise CommandError(f"Invalid --size value '{size}' (examples: 10G, 512M)") from exc
        size_mib = size_bytes / (1024 * 1024)
        end = start + size_mib
        if end > free_end:
            raise CommandError(
                f"Requested size {size} does not fit free space from {_mib_spec(start)} to {_mib_spec(free_end)}"
            )
        return _mib_spec(start), _mib_spec(end)
    return _mib_spec(start), _mib_spec(free_end)


def create_partition(
    disk: str,
    filesystem: str,
    label: str | None = None,
    size: str | None = None,
    start_mib: float | None = None,
) -> str:
    fs = canonical_fstype(filesystem)
    if fs not in SUPPORTED_MKFS:
        raise CommandError(f"Unsupported filesystem '{filesystem}'. Supported: {', '.join(sorted(SUPPORTED_MKFS))}")
    if not Path(disk).exists():
        raise CommandError(f"Disk not found: {disk}")
    if _device_type(disk) != "disk":
        raise CommandError(f"Not a disk device: {disk}")

    start_spec, end_spec = _resolve_create_range(disk, size=size, start_mib=start_mib)
    run_cmd(["parted", "-s", disk, "--", "mkpart", "primary", start_spec, end_spec])
    _rescan_partition_table(disk)

    parts = collect_partitions()
    candidates = [p for p in parts if p.disk_path == disk]
    if not candidates:
        raise CommandError(f"Partition creation appears to have succeeded, but no partitions were discovered on {disk}")
    created = max(candidates, key=lambda p: _partition_number_int(p.path))

    run_cmd(_mkfs_cmd_for(fs, created.path, label=label))
    _rescan_partition_table(disk)
    return f"Created {created.path} on {disk} with fs={fs}" + (f" label={label}" if label else "")


def delete_partition(device: str, wipe_signatures: bool = False) -> str:
    if not Path(device).exists():
        raise CommandError(f"Device not found: {device}")

    part = find_partition(collect_partitions(), device)
    if not part:
        raise CommandError(f"Partition not found: {device}")
    if part.mounted:
        raise CommandError(f"Partition is mounted, unmount first: {device}")

    if wipe_signatures:
        run_cmd(["wipefs", "-a", device])

    partn = _partition_number(device)
    run_cmd(["parted", "-s", part.disk_path, "rm", partn])
    _rescan_partition_table(part.disk_path)

    return f"Deleted partition {device} from {part.disk_path}"


def merge_with_unallocated(device: str) -> str:
    if not Path(device).exists():
        raise CommandError(f"Device not found: {device}")

    part = find_partition(collect_partitions(), device)
    if not part:
        raise CommandError(f"Partition not found: {device}")
    if is_root_partition(part, root_sources()):
        raise CommandError(f"Refusing to resize root partition: {device}")
    if part.mounted:
        raise CommandError(f"Partition is mounted, unmount first: {device}")

    partn = _partition_number_int(device)
    rows = _parted_rows_mib(part.disk_path)
    idx = next((i for i, row in enumerate(rows) if row.get("partn") == partn), -1)
    if idx < 0:
        raise CommandError(f"Unable to locate partition layout row for {device}")
    if idx + 1 >= len(rows):
        raise CommandError(f"No adjacent unallocated space after {device}")

    current = rows[idx]
    right = rows[idx + 1]
    if right.get("kind") != "free":
        raise CommandError(f"No adjacent unallocated space after {device}")

    new_end = float(right["end"])
    old_end = float(current["end"])
    if new_end <= old_end:
        raise CommandError(f"No additional unallocated space to merge after {device}")

    run_cmd(["parted", "-s", part.disk_path, "unit", "MiB", "resizepart", str(partn), _mib_spec(new_end)])
    _rescan_partition_table(part.disk_path)
    return f"Merged unallocated space into {device}; new end at {_mib_spec(new_end)}"


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
                    fstype=canonical_fstype((node.get("fstype") or "").strip()),
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
    # Use the actual drive label if available, otherwise fall back to device name.
    preferred = (part.label or part.name or Path(part.path).name).strip()
    # Only sanitize characters that are invalid in Linux paths (null byte and forward slash).
    # Preserve the actual drive label name as-is for better user experience.
    mount_name = preferred.replace("/", "_").replace("\x00", "")
    if not mount_name:
        mount_name = Path(part.path).name
    return base_dir / mount_name


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


def is_mount_read_only(part: Partition) -> bool:
    if not part.mountpoint:
        return False
    proc = run_cmd_proc(["findmnt", "-n", "-o", "OPTIONS", "--target", part.mountpoint])
    if proc.returncode != 0:
        return False
    options = (proc.stdout or "").strip().split(",")
    return "ro" in options


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

    resolved_fstype = _detect_filesystem_type(mount_source) or canonical_fstype(part.fstype)
    if resolved_fstype in {"", "crypto_luks"}:
        return False, f"Unable to detect mountable filesystem for {mount_source}"

    mnt = target_mount_point(part, base_dir)
    ensure_dir(mnt)

    # Try filesystem-aware rw mount first; fallback to read-only.
    effective = Partition(**{**part.__dict__, "path": mount_source, "fstype": resolved_fstype})
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


def unlock_luks_async(part: Partition, passphrase: str) -> Future[str]:
    return _executor.submit(unlock_luks, part, passphrase)


def lock_luks_async(part: Partition) -> Future[str]:
    return _executor.submit(lock_luks, part)


def create_partition_async(
    disk: str,
    filesystem: str,
    label: str | None = None,
    size: str | None = None,
    start_mib: float | None = None,
) -> Future[str]:
    return _executor.submit(create_partition, disk, filesystem, label, size, start_mib)


def delete_partition_async(device: str, wipe_signatures: bool = False) -> Future[str]:
    return _executor.submit(delete_partition, device, wipe_signatures)


def merge_with_unallocated_async(device: str) -> Future[str]:
    return _executor.submit(merge_with_unallocated, device)


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
    fstype = canonical_fstype(part.fstype)
    return f"UUID={part.uuid} {mnt} {fstype} {opts} 0 2 # {DISKMAN_FSTAB_TAG} {part.path}"


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
