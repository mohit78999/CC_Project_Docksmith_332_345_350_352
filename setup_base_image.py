#!/usr/bin/env python3
import hashlib, json, os, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image_store, layer_store

def import_image_from_docker(image_ref, name, tag):
    print(f"Pulling {image_ref} via docker...")
    r = subprocess.run(["docker", "pull", image_ref], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"docker pull failed: {r.stderr}")
        return False
    tmpdir = tempfile.mkdtemp()
    tar_path = os.path.join(tmpdir, "image.tar")
    try:
        print(f"Exporting to tar...")
        r = subprocess.run(["docker", "save", "-o", tar_path, image_ref], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"docker save failed: {r.stderr}")
            return False
        _import_from_tar(tar_path, name, tag)
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def _import_from_tar(tar_path, name, tag):
    tmpdir = tempfile.mkdtemp()
    try:
        with tarfile.open(tar_path, "r") as tar:
            tar.extractall(tmpdir)
        with open(os.path.join(tmpdir, "manifest.json")) as f:
            docker_manifest = json.load(f)
        entry = docker_manifest[0]
        layer_paths = entry.get("Layers", [])
        config_file = entry.get("Config", "")
        config = {"Env": [], "Cmd": [], "WorkingDir": ""}
        if config_file:
            cfg_path = os.path.join(tmpdir, config_file)
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    dc = json.load(f)
                cc = dc.get("config", dc.get("Config", {}))
                config["Env"] = cc.get("Env", []) or []
                config["Cmd"] = cc.get("Cmd", []) or []
                config["WorkingDir"] = cc.get("WorkingDir", "") or ""
        imported_layers = []
        for i, lp in enumerate(layer_paths):
            ltar = os.path.join(tmpdir, lp)
            if not os.path.exists(ltar):
                ltar = os.path.join(tmpdir, lp.replace("/", os.sep))
            with open(ltar, "rb") as f:
                raw = f.read()
            info = layer_store.store_layer_bytes(raw, f"imported layer {i+1}/{len(layer_paths)}")
            imported_layers.append(info)
            print(f"  Layer {i+1}/{len(layer_paths)}: {info['digest'][:19]} ({info['size']} bytes)")
        manifest = image_store.save_image(name, tag, imported_layers, config)
        print(f"Manifest saved: {manifest['digest'][:19]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--from-tar", metavar="TAR_PATH")
parser.add_argument("--image", default="alpine:3.18")
parser.add_argument("--name", default="alpine")
parser.add_argument("--tag", default="3.18")
args = parser.parse_args()

if args.from_tar:
    _import_from_tar(args.from_tar, args.name, args.tag)
else:
    if not import_image_from_docker(args.image, args.name, args.tag):
        sys.exit(1)

print("\nImages in local store:")
for img in image_store.list_images():
    print(f"  {img['name']}:{img['tag']}  {img.get('digest','')[:19]}")
