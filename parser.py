import json
import re
import shlex

VALID_INSTRUCTIONS = {"FROM", "COPY", "RUN", "WORKDIR", "ENV", "CMD"}

class ParseError(Exception):
    pass

class Instruction:
    def __init__(self, name, args, line_number, raw):
        self.name = name
        self.args = args
        self.line_number = line_number
        self.raw = raw
    def __repr__(self):
        return f"Instruction({self.name}, {self.args!r}, line={self.line_number})"

def parse_docksmithfile(path):
    try:
        with open(path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        raise ParseError(f"Docksmithfile not found: {path}")
    instructions = []
    i = 0
    while i < len(lines):
        line_number = i + 1
        line = lines[i].rstrip("\n")
        while line.endswith("\\"):
            line = line[:-1]
            i += 1
            if i < len(lines):
                line += lines[i].rstrip("\n").lstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        parts = stripped.split(None, 1)
        if not parts:
            i += 1
            continue
        name = parts[0].upper()
        rest = parts[1] if len(parts) > 1 else ""
        if name not in VALID_INSTRUCTIONS:
            raise ParseError(f"Line {line_number}: Unknown instruction '{name}'. Valid: {', '.join(sorted(VALID_INSTRUCTIONS))}")
        args = _parse_args(name, rest, line_number)
        instructions.append(Instruction(name, args, line_number, stripped))
        i += 1
    if not instructions or instructions[0].name != "FROM":
        raise ParseError("Docksmithfile must start with FROM")
    return instructions

def _parse_args(name, rest, line_number):
    if name == "FROM":
        rest = rest.strip()
        if not rest:
            raise ParseError(f"Line {line_number}: FROM requires an image argument")
        if ":" in rest:
            image, tag = rest.rsplit(":", 1)
        else:
            image, tag = rest, "latest"
        return {"image": image, "tag": tag}
    elif name == "COPY":
        parts = shlex.split(rest)
        if len(parts) < 2:
            raise ParseError(f"Line {line_number}: COPY requires <src> and <dest>")
        return {"src": parts[:-1], "dest": parts[-1]}
    elif name == "RUN":
        rest = rest.strip()
        if not rest:
            raise ParseError(f"Line {line_number}: RUN requires a command")
        return {"command": rest}
    elif name == "WORKDIR":
        rest = rest.strip()
        if not rest:
            raise ParseError(f"Line {line_number}: WORKDIR requires a path")
        return {"path": rest}
    elif name == "ENV":
        rest = rest.strip()
        if "=" not in rest:
            raise ParseError(f"Line {line_number}: ENV requires KEY=VALUE format")
        key, _, value = rest.partition("=")
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return {"key": key, "value": value}
    elif name == "CMD":
        rest = rest.strip()
        if not rest.startswith("["):
            raise ParseError(f"Line {line_number}: CMD requires JSON array format")
        try:
            cmd_list = json.loads(rest)
        except json.JSONDecodeError as e:
            raise ParseError(f"Line {line_number}: CMD has invalid JSON: {e}")
        if not isinstance(cmd_list, list) or not all(isinstance(x, str) for x in cmd_list):
            raise ParseError(f"Line {line_number}: CMD must be a JSON array of strings")
        if not cmd_list:
            raise ParseError(f"Line {line_number}: CMD array cannot be empty")
        return {"cmd": cmd_list}
    return rest
