import fnmatch
import glob as glob_module
import os
import shutil
import tempfile
import time
from pathlib import Path

import cache as cache_module
import image_store
import layer_store
from parser import parse_docksmithfile, ParseError
from runtime import run_build_command

class BuildError(Exception):
    pass

def build_image(context_dir, name, tag, no_cache=False):
    docksmithfile = os.path.join(context_dir, "Docksmithfile")
    if not os.path.exists(docksmithfile):
        raise BuildError(f"No Docksmithfile found in: {context_dir}")
    try:
        instructions = parse_docksmithfile(docksmithfile)
    except ParseError as e:
        raise BuildError(str(e))

    total_steps = len(instructions)
    layers = []
    config = {"Env": [], "Cmd": [], "WorkingDir": ""}
    env_state = {}
    workdir = ""
    prev_digest = None
    cache_cascade = False
    all_cache_hits = True
    preserved_created = None

    if image_store.image_exists(name, tag):
        try:
            existing = image_store.load_image(name, tag)
            preserved_created = existing.get("created")
        except Exception:
            pass

    build_start = time.time()

    for step_idx, instr in enumerate(instructions):
        step_num = step_idx + 1

        if instr.name == "FROM":
            img_name = instr.args["image"]
            img_tag = instr.args["tag"]
            print(f"Step {step_num}/{total_steps} : FROM {img_name}:{img_tag}")
            if not image_store.image_exists(img_name, img_tag):
                raise BuildError(f"Base image not found: {img_name}:{img_tag}\nRun: sudo python3 setup_base_image.py first")
            base_manifest = image_store.load_image(img_name, img_tag)
            layers = list(base_manifest["layers"])
            base_config = base_manifest.get("config", {})
            for env_entry in base_config.get("Env", []):
                if "=" in env_entry:
                    k, _, v = env_entry.partition("=")
                    env_state[k] = v
            if base_config.get("WorkingDir"):
                workdir = base_config["WorkingDir"]
            prev_digest = base_manifest["digest"]
            continue

        if instr.name == "WORKDIR":
            workdir = instr.args["path"]
            print(f"Step {step_num}/{total_steps} : WORKDIR {workdir}")
            continue

        if instr.name == "ENV":
            key = instr.args["key"]
            value = instr.args["value"]
            env_state[key] = value
            print(f"Step {step_num}/{total_steps} : ENV {key}={value}")
            continue

        if instr.name == "CMD":
            config["Cmd"] = instr.args["cmd"]
            print(f"Step {step_num}/{total_steps} : CMD {instr.args['cmd']}")
            continue

        if instr.name == "COPY":
            src_patterns = instr.args["src"]
            dest = instr.args["dest"]
            src_files = _resolve_sources(context_dir, src_patterns)
            if not src_files:
                raise BuildError(f"Step {step_num}: COPY found no files matching: {src_patterns}")
            file_hashes = sorted(
                (rel, layer_store.hash_file_content(abs_path))
                for rel, abs_path in src_files.items()
            )
            cache_key = cache_module.compute_cache_key(
                prev_digest=prev_digest, instruction_text=instr.raw,
                workdir=workdir, env_state=env_state, copy_file_hashes=file_hashes,
            )
            step_start = time.time()
            if not no_cache and not cache_cascade:
                cached_digest = cache_module.lookup(cache_key)
                if cached_digest and layer_store.layer_exists(cached_digest):
                    elapsed = time.time() - step_start
                    print(f"Step {step_num}/{total_steps} : COPY {' '.join(src_patterns)} {dest} [CACHE HIT] {elapsed:.2f}s")
                    layers.append({"digest": cached_digest, "size": layer_store.get_layer_path(cached_digest).stat().st_size, "createdBy": instr.raw})
                    prev_digest = cached_digest
                    continue
            all_cache_hits = False
            cache_cascade = True
            file_map = _build_copy_file_map(src_files, dest, workdir)
            layer_info = layer_store.create_layer_from_files(file_map, instr.raw)
            elapsed = time.time() - step_start
            print(f"Step {step_num}/{total_steps} : COPY {' '.join(src_patterns)} {dest} [CACHE MISS] {elapsed:.2f}s")
            if not no_cache:
                cache_module.store(cache_key, layer_info["digest"])
            layers.append(layer_info)
            prev_digest = layer_info["digest"]
            continue

        if instr.name == "RUN":
            command = instr.args["command"]
            cache_key = cache_module.compute_cache_key(
                prev_digest=prev_digest, instruction_text=instr.raw,
                workdir=workdir, env_state=env_state, copy_file_hashes=None,
            )
            step_start = time.time()
            if not no_cache and not cache_cascade:
                cached_digest = cache_module.lookup(cache_key)
                if cached_digest and layer_store.layer_exists(cached_digest):
                    elapsed = time.time() - step_start
                    print(f"Step {step_num}/{total_steps} : RUN {command} [CACHE HIT] {elapsed:.2f}s")
                    layers.append({"digest": cached_digest, "size": layer_store.get_layer_path(cached_digest).stat().st_size, "createdBy": instr.raw})
                    prev_digest = cached_digest
                    continue
            all_cache_hits = False
            cache_cascade = True
            run_env = dict(env_state)
            exit_code, delta_dir = run_build_command(layers=layers, command=command, env=run_env, workdir=workdir)
            if exit_code != 0:
                shutil.rmtree(delta_dir, ignore_errors=True)
                raise BuildError(f"Step {step_num}: RUN failed (exit {exit_code}): {command}")
            has_content = any(True for _ in Path(delta_dir).rglob("*"))
            if has_content:
                layer_info = layer_store.create_layer_from_directory(delta_dir, instr.raw)
            else:
                layer_info = layer_store.create_layer_from_files({}, instr.raw)
            shutil.rmtree(delta_dir, ignore_errors=True)
            elapsed = time.time() - step_start
            print(f"Step {step_num}/{total_steps} : RUN {command} [CACHE MISS] {elapsed:.2f}s")
            if not no_cache:
                cache_module.store(cache_key, layer_info["digest"])
            layers.append(layer_info)
            prev_digest = layer_info["digest"]
            continue

    config["WorkingDir"] = workdir
    config["Env"] = [f"{k}={v}" for k, v in sorted(env_state.items())]
    created = preserved_created if (all_cache_hits and preserved_created) else None
    total_elapsed = time.time() - build_start
    manifest = image_store.save_image(name, tag, layers, config, created=created)
    print(f"\nSuccessfully built {manifest['digest'][:19]} {name}:{tag} ({total_elapsed:.2f}s)")
    return manifest

def _resolve_sources(context_dir, patterns):
    result = {}
    for pattern in patterns:
        full_pattern = os.path.join(context_dir, pattern)
        matches = glob_module.glob(full_pattern, recursive=True)
        for abs_path in sorted(matches):
            if os.path.isfile(abs_path):
                rel = os.path.relpath(abs_path, context_dir)
                result[rel] = abs_path
    return result

def _build_copy_file_map(src_files, dest, workdir):
    file_map = {}
    dest_clean = dest.lstrip("/")
    if len(src_files) == 1 and not dest.endswith("/"):
        rel, abs_path = next(iter(src_files.items()))
        file_map[dest_clean] = abs_path
    else:
        for rel, abs_path in src_files.items():
            fname = os.path.basename(rel)
            target = os.path.join(dest_clean, rel) if "/" in rel else os.path.join(dest_clean, fname)
            file_map[target.lstrip("/")] = abs_path
    return file_map