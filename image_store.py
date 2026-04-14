import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DOCKSMITH_DIR = Path.home() / ".docksmith"
IMAGES_DIR = DOCKSMITH_DIR / "images"

def init_dirs():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

def _manifest_path(name, tag):
    safe = f"{name}_{tag}".replace("/", "_").replace(":", "_")
    return IMAGES_DIR / f"{safe}.json"

def _compute_manifest_digest(manifest):
    m = dict(manifest)
    m["digest"] = ""
    canonical = json.dumps(m, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

def save_image(name, tag, layers, config, created=None):
    init_dirs()
    if created is None:
        created = datetime.now(timezone.utc).isoformat()
    manifest = {"name": name, "tag": tag, "digest": "", "created": created, "config": config, "layers": layers}
    manifest["digest"] = _compute_manifest_digest(manifest)
    path = _manifest_path(name, tag)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest

def load_image(name, tag):
    path = _manifest_path(name, tag)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {name}:{tag}")
    with open(path) as f:
        return json.load(f)

def image_exists(name, tag):
    return _manifest_path(name, tag).exists()

def list_images():
    init_dirs()
    images = []
    for p in sorted(IMAGES_DIR.glob("*.json")):
        try:
            with open(p) as f:
                images.append(json.load(f))
        except Exception:
            pass
    return images

def delete_image(name, tag):
    path = _manifest_path(name, tag)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {name}:{tag}")
    path.unlink()

def parse_name_tag(name_tag):
    if ":" in name_tag:
        name, tag = name_tag.rsplit(":", 1)
    else:
        name, tag = name_tag, "latest"
    return name, tag
