#!/usr/bin/env python3
import os
import sys

def cmd_build(args):
    import argparse
    from builder import build_image, BuildError
    parser = argparse.ArgumentParser(prog="docksmith build")
    parser.add_argument("-t", required=True, dest="tag")
    parser.add_argument("--no-cache", action="store_true", dest="no_cache")
    parser.add_argument("context")
    opts = parser.parse_args(args)
    name, tag = opts.tag.rsplit(":", 1) if ":" in opts.tag else (opts.tag, "latest")
    context = os.path.abspath(opts.context)
    if not os.path.isdir(context):
        print(f"Error: context directory does not exist: {context}", file=sys.stderr)
        sys.exit(1)
    try:
        build_image(context, name, tag, no_cache=opts.no_cache)
    except BuildError as e:
        print(f"\nBuild failed: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print("Permission denied. Run with: sudo python3 docksmith.py build ...", file=sys.stderr)
        sys.exit(1)

def cmd_images(args):
    from image_store import list_images
    images = list_images()
    if not images:
        print("No images found.")
        return
    fmt = "{:<20} {:<12} {:<14} {:<30}"
    print(fmt.format("NAME", "TAG", "ID", "CREATED"))
    print("-" * 78)
    for img in images:
        digest = img.get("digest", "")
        short_id = digest.replace("sha256:", "")[:12]
        created = img.get("created", "")[:19].replace("T", " ")
        print(fmt.format(img.get("name",""), img.get("tag",""), short_id, created))

def cmd_rmi(args):
    if not args:
        print("Error: docksmith rmi requires a <name:tag> argument", file=sys.stderr)
        sys.exit(1)
    from image_store import load_image, delete_image, parse_name_tag, image_exists
    from layer_store import delete_layer, layer_exists
    name, tag = parse_name_tag(args[0])
    if not image_exists(name, tag):
        print(f"Error: Image not found: {args[0]}", file=sys.stderr)
        sys.exit(1)
    manifest = load_image(name, tag)
    for layer in manifest.get("layers", []):
        digest = layer.get("digest", "")
        if digest and layer_exists(digest):
            delete_layer(digest)
            print(f"Deleted layer: {digest[:19]}")
    delete_image(name, tag)
    print(f"Untagged: {name}:{tag}")
    print(f"Deleted: {manifest.get('digest','')[:19]}")

def cmd_run(args):
    import argparse
    from image_store import load_image, parse_name_tag, image_exists
    from layer_store import layer_exists
    from runtime import run_in_container
    parser = argparse.ArgumentParser(prog="docksmith run")
    parser.add_argument("-e", action="append", dest="env_overrides", default=[], metavar="KEY=VALUE")
    parser.add_argument("name_tag")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    opts = parser.parse_args(args)
    name, tag = parse_name_tag(opts.name_tag)
    if not image_exists(name, tag):
        print(f"Error: Image not found: {opts.name_tag}", file=sys.stderr)
        sys.exit(1)
    manifest = load_image(name, tag)
    layers = manifest.get("layers", [])
    config = manifest.get("config", {})
    for layer in layers:
        if not layer_exists(layer["digest"]):
            print(f"Error: Layer missing: {layer['digest'][:19]}", file=sys.stderr)
            sys.exit(1)
    if opts.cmd:
        command = opts.cmd
    elif config.get("Cmd"):
        command = config["Cmd"]
    else:
        print(f"Error: No CMD defined and no command provided.", file=sys.stderr)
        sys.exit(1)
    env = {}
    for entry in config.get("Env", []):
        if "=" in entry:
            k, _, v = entry.partition("=")
            env[k] = v
    for override in opts.env_overrides:
        if "=" not in override:
            print(f"Error: -e requires KEY=VALUE, got: {override}", file=sys.stderr)
            sys.exit(1)
        k, _, v = override.partition("=")
        env[k] = v
    workdir = config.get("WorkingDir") or "/"
    try:
        exit_code = run_in_container(layers=layers, command=command, env=env, workdir=workdir, interactive=True)
    except PermissionError:
        print("Permission denied. Run with: sudo python3 docksmith.py run ...", file=sys.stderr)
        sys.exit(1)
    print(f"\nContainer exited with code {exit_code}")
    sys.exit(exit_code)

def main():
    if len(sys.argv) < 2:
        print("Usage: docksmith <build|images|rmi|run> ...")
        sys.exit(0)
    subcmd = sys.argv[1]
    rest = sys.argv[2:]
    if subcmd == "build": cmd_build(rest)
    elif subcmd == "images": cmd_images(rest)
    elif subcmd == "rmi": cmd_rmi(rest)
    elif subcmd == "run": cmd_run(rest)
    else:
        print(f"Unknown command: {subcmd}. Use: build, images, rmi, run", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
