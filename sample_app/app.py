#!/usr/bin/env python3
import os, sys

greeting = os.environ.get("GREETING", "Hello")
app_env = os.environ.get("APP_ENV", "unknown")

print("=" * 40)
print("  Docksmith Sample App")
print("=" * 40)
print(f"  Greeting : {greeting}")
print(f"  APP_ENV  : {app_env}")
print(f"  Python   : {sys.version.split()[0]}")
print(f"  CWD      : {os.getcwd()}")
print()
print("Files in /app:")
for f in sorted(os.listdir("/app")):
    print(f"  {f}")
print()
print("Isolated from host. Done.")
# changed