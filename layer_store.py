import hashlib
import io
import os
import tarfile
from pathlib import Path

DOCKSMITH_DIR = Path.home() / ".docksmith"
LAYERS_DIR = DOCKSMITH_DIR / "layers"

def init_dirs():
    LAYERS_DIR.mkdir(parents=True, exist_ok=True)

def _hash_bytes(data):
    return hashlib.sha256(data).hexdigest()

def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

hash_file_content = hash_file

def create_layer_from_directory(src_dir, created_by):
    init_dirs()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        all_entries = []
        for root, dirs, files in os.walk(src_dir):
            dirs.sort()
            for fname in sorted(files):
                full_path = os.path.join(root, fname)
                arcname = os.path.relpath(full_path, src_dir)
                all_entries.append((arcname, full_path))
            for dname in sorted(dirs):
                full_path = os.path.join(root, dname)
                arcname = os.path.relpath(full_path, src_dir)
                all_entries.append((arcname, full_path))
        all_entries.sort(key=lambda x: x[0])
        for arcname, full_path in all_entries:
            tinfo = tar.gettarinfo(full_path, arcname=arcname)
            tinfo.mtime = 0
            tinfo.uid = 0
            tinfo.gid = 0
            tinfo.uname = ""
            tinfo.gname = ""
            if tinfo.isreg():
                with open(full_path, "rb") as f:
                    tar.addfile(tinfo, f)
            else:
                tar.addfile(tinfo)
    raw_bytes = buf.getvalue()
    digest_hex = _hash_bytes(raw_bytes)
    digest = f"sha256:{digest_hex}"
    layer_path = LAYERS_DIR / f"{digest_hex}.tar"
    if not layer_path.exists():
        layer_path.write_bytes(raw_bytes)
    return {"digest": digest, "size": len(raw_bytes), "createdBy": created_by}

def create_layer_from_files(file_map, created_by):
    init_dirs()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for arcname in sorted(file_map.keys()):
            src_path = file_map[arcname]
            tinfo = tar.gettarinfo(src_path, arcname=arcname)
            tinfo.mtime = 0
            tinfo.uid = 0
            tinfo.gid = 0
            tinfo.uname = ""
            tinfo.gname = ""
            if tinfo.isreg():
                with open(src_path, "rb") as f:
                    tar.addfile(tinfo, f)
            else:
                tar.addfile(tinfo)
    raw_bytes = buf.getvalue()
    digest_hex = _hash_bytes(raw_bytes)
    digest = f"sha256:{digest_hex}"
    layer_path = LAYERS_DIR / f"{digest_hex}.tar"
    if not layer_path.exists():
        layer_path.write_bytes(raw_bytes)
    return {"digest": digest, "size": len(raw_bytes), "createdBy": created_by}

def store_layer_bytes(raw_bytes, created_by):
    init_dirs()
    digest_hex = _hash_bytes(raw_bytes)
    digest = f"sha256:{digest_hex}"
    layer_path = LAYERS_DIR / f"{digest_hex}.tar"
    if not layer_path.exists():
        layer_path.write_bytes(raw_bytes)
    return {"digest": digest, "size": len(raw_bytes), "createdBy": created_by}

def layer_exists(digest):
    digest_hex = digest.replace("sha256:", "")
    return (LAYERS_DIR / f"{digest_hex}.tar").exists()

def get_layer_path(digest):
    digest_hex = digest.replace("sha256:", "")
    return LAYERS_DIR / f"{digest_hex}.tar"

def extract_layer(digest, dest_dir):
    path = get_layer_path(digest)
    if not path.exists():
        raise FileNotFoundError(f"Layer not found: {digest}")
    with tarfile.open(str(path), "r") as tar:
        members = []
        for m in tar.getmembers():
            m.name = m.name.lstrip("/")
            if ".." in m.name.split(os.sep):
                continue
            members.append(m)
        tar.extractall(dest_dir, members=members)

def delete_layer(digest):
    path = get_layer_path(digest)
    if path.exists():
        path.unlink()
