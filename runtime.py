import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from layer_store import extract_layer

def _assemble_rootfs(layers, dest_dir):
    for layer in layers:
        extract_layer(layer["digest"], dest_dir)

def _ensure_base_dirs(rootfs):
    for d in ["proc", "sys", "dev", "tmp", "etc", "root"]:
        os.makedirs(os.path.join(rootfs, d), exist_ok=True)
    resolv = os.path.join(rootfs, "etc", "resolv.conf")
    if not os.path.exists(resolv):
        with open(resolv, "w") as f:
            f.write("nameserver 8.8.8.8\n")

def _shell_escape(s):
    return "'" + s.replace("'", "'\\''") + "'"

def run_in_container(layers, command, env=None, workdir="/", interactive=False, rootfs_dir=None):
    cleanup = rootfs_dir is None
    if rootfs_dir is None:
        rootfs_dir = tempfile.mkdtemp(prefix="docksmith_rootfs_")
    try:
        _assemble_rootfs(layers, rootfs_dir)
        _ensure_base_dirs(rootfs_dir)
        if workdir and workdir != "/":
            abs_workdir = os.path.join(rootfs_dir, workdir.lstrip("/"))
            os.makedirs(abs_workdir, exist_ok=True)
        if isinstance(command, list):
            import shlex
            shell_cmd = " ".join(shlex.quote(c) for c in command)
        else:
            shell_cmd = command
        full_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root",
            "TERM": os.environ.get("TERM", "xterm"),
        }
        if env:
            full_env.update(env)
        chroot_cmd = [
            "unshare", "--mount", "--uts", "--ipc", "--pid", "--fork", "--kill-child",
            "chroot", rootfs_dir,
            "/bin/sh", "-c",
            f"cd {_shell_escape(workdir or '/')} && {shell_cmd}",
        ]
        result = subprocess.run(
            chroot_cmd, env=full_env,
            stdin=sys.stdin if interactive else subprocess.DEVNULL,
            stdout=sys.stdout if interactive else None,
            stderr=sys.stderr if interactive else None,
        )
        return result.returncode
    finally:
        if cleanup and os.path.exists(rootfs_dir):
            shutil.rmtree(rootfs_dir, ignore_errors=True)

def run_build_command(layers, command, env=None, workdir="/"):
    rootfs_dir = tempfile.mkdtemp(prefix="docksmith_build_rootfs_")
    delta_dir = tempfile.mkdtemp(prefix="docksmith_build_delta_")
    try:
        _assemble_rootfs(layers, rootfs_dir)
        _ensure_base_dirs(rootfs_dir)
        if workdir and workdir != "/":
            abs_workdir = os.path.join(rootfs_dir, workdir.lstrip("/"))
            os.makedirs(abs_workdir, exist_ok=True)
        before_snapshot = _snapshot(rootfs_dir)
        process_env = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/root",
            "TERM": "xterm",
        }
        if env:
            process_env.update(env)
        chroot_cmd = [
            "unshare", "--mount", "--uts", "--ipc", "--pid", "--fork", "--kill-child",
            "chroot", rootfs_dir,
            "/bin/sh", "-c",
            f"cd {_shell_escape(workdir or '/')} && {command}",
        ]
        result = subprocess.run(chroot_cmd, env=process_env, stdout=sys.stdout, stderr=sys.stderr)
        exit_code = result.returncode
        after_snapshot = _snapshot(rootfs_dir)
        changed_files = _diff_snapshots(before_snapshot, after_snapshot)
        for rel_path in changed_files:
            src = os.path.join(rootfs_dir, rel_path)
            dst = os.path.join(delta_dir, rel_path)
            if os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.isdir(src):
                    os.makedirs(dst, exist_ok=True)
                elif os.path.islink(src):
                    link_target = os.readlink(src)
                    if os.path.exists(dst) or os.path.islink(dst):
                        os.remove(dst)
                    os.symlink(link_target, dst)
                else:
                    shutil.copy2(src, dst)
        return exit_code, delta_dir
    finally:
        shutil.rmtree(rootfs_dir, ignore_errors=True)

def _snapshot(rootfs_dir):
    snap = {}
    for root, dirs, files in os.walk(rootfs_dir):
        dirs.sort()
        for fname in sorted(files + dirs):
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, rootfs_dir)
            try:
                st = os.lstat(full)
                snap[rel] = (st.st_mtime, st.st_size)
            except OSError:
                pass
    return snap

def _diff_snapshots(before, after):
    changed = []
    for path, vals in after.items():
        if path not in before or before[path] != vals:
            changed.append(path)
    return sorted(changed)
