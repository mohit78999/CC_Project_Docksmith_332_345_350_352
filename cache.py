import hashlib
import json
from pathlib import Path

DOCKSMITH_DIR = Path.home() / ".docksmith"
CACHE_DIR = DOCKSMITH_DIR / "cache"
CACHE_INDEX = CACHE_DIR / "index.json"

def init_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _load_index():
    if CACHE_INDEX.exists():
        with open(CACHE_INDEX) as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def _save_index(index):
    init_dirs()
    with open(CACHE_INDEX, "w") as f:
        json.dump(index, f, indent=2)

def compute_cache_key(prev_digest, instruction_text, workdir, env_state, copy_file_hashes=None):
    parts = []
    parts.append(f"prev:{prev_digest}")
    parts.append(f"instruction:{instruction_text}")
    parts.append(f"workdir:{workdir}")
    sorted_env = sorted(env_state.items(), key=lambda x: x[0])
    env_str = ",".join(f"{k}={v}" for k, v in sorted_env)
    parts.append(f"env:{env_str}")
    if copy_file_hashes is not None:
        file_hash_str = ",".join(f"{p}:{h}" for p, h in copy_file_hashes)
        parts.append(f"files:{file_hash_str}")
    combined = "\n".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()

def lookup(cache_key):
    index = _load_index()
    return index.get(cache_key)

def store(cache_key, layer_digest):
    index = _load_index()
    index[cache_key] = layer_digest
    _save_index(index)