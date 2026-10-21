#!/usr/bin/env python3
"""Compare AnyPS5's exported prototypes with the ones public PS5 sources declare.

AnyPS5 exports every function of a system library under its NID.  The prototype
it declares for an export is the only place the library records what the
console's function takes, and a wrong one is invisible: the callee ignores the
arguments, so a guest call that passes the wrong values raises nothing and no
test notices.

The public PS5 homebrew repositories call the console's libraries directly and
declare the prototypes they call.  A call site settles the arguments, so a
disagreement between a PS5 declaration and an AnyPS5 prototype is a defect in
AnyPS5.  This tool finds those disagreements.

The PS4 sources (OpenOrbis, shadPS4) declare the PS4 libraries and settle
nothing; only PS5 sources count.  The ps5-payload-dev SDK's `sce_stubs` are
assembly link stubs: they name the exports and say nothing about their
parameters, so they are not a source of prototypes either.

The tool reads a directory of cloned PS5 sources; it fetches nothing itself.
See the module docstring of `tools/README` for the list.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SOURCE_EXTENSIONS = {".c", ".h", ".cpp", ".hpp", ".cc"}
SKIP_DIRECTORIES = {".git", "build", "3rdparty", "node_modules", "subprojects", "external"}

EXPORT = re.compile(r"\bAPS5_VABI\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
DECLARATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_ \*]*?\b(?P<name>sce[A-Z][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
CALL = re.compile(r"\b(?P<name>sce[A-Z][A-Za-z0-9_]*)\s*\(")
TYPE_WORDS = {"const", "unsigned", "signed", "struct", "enum", "union", "volatile", "long", "short"}
TYPE_NAMES = {"void", "char", "short", "int", "long", "float", "double", "signed", "unsigned",
              "bool", "const", "volatile", "struct", "union", "enum", "size_t", "ssize_t",
              "uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t", "int16_t", "int32_t",
              "int64_t", "uintptr_t", "intptr_t", "FILE"}
KEYWORDS = {"return", "if", "else", "while", "for", "do", "switch", "case", "break", "continue",
            "sizeof", "goto", "default", "new", "delete", "and", "or", "not"}
FUNCTION_POINTER = re.compile(r"typedef[^;{}]*\(\s*\*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\(")
FUNCTION_POINTER_ALIAS = re.compile(
    r"\busing\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=[^;{}]*?"
    r"\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)*\*\s*\)\s*\(")


class Parameters:
    """The parameters of one prototype or the arguments of one call."""

    def __init__(self, pieces, named):
        self.pieces = pieces
        self.named = named

    def __len__(self):
        return len(self.pieces)

    @property
    def arity(self):
        return len(self.pieces)

    def pointers(self, function_pointers=()):
        """Whether each parameter is a pointer.

        A parameter written through a typedef of a function pointer is a
        pointer even when the type name carries no `*` of its own.
        """
        return [is_pointer(piece, function_pointers) for piece in self.pieces]

    def types(self):
        return [type_of(piece) for piece in self.pieces]


class Export:
    """One export of an AnyPS5 library and the prototype it declares."""

    def __init__(self, name, library, path, line, parameters):
        self.name = name
        self.library = library
        self.path = path
        self.line = line
        self.parameters = parameters


class Observation:
    """A prototype a PS5 source declares, or a call it makes."""

    def __init__(self, name, source, path, line, kind, parameters, text):
        self.name = name
        self.source = source
        self.path = path
        self.line = line
        self.kind = kind
        self.parameters = parameters
        self.text = text

    def evidence(self):
        return f"{self.source}:{self.path}:{self.line}"


class Mismatch:
    """An export whose AnyPS5 prototype disagrees with a PS5 source."""

    def __init__(self, export, observation, reason):
        self.export = export
        self.observation = observation
        self.reason = reason

    def describe(self):
        return (f"{self.export.name}: AnyPS5 declares {describe(self.export.parameters)}, "
                f"the PS5 source {self.observation.kind} has {describe(self.observation.parameters)}"
                f" ({self.reason})")


class Source:
    """A cloned PS5 source tree and the revision it is at."""

    def __init__(self, name, revision):
        self.name = name
        self.revision = revision


def is_pointer(piece, function_pointers=()):
    """Whether a parameter is a pointer."""
    if "*" in piece:
        return True
    name = type_of(piece).replace("*", "").strip()
    return name in function_pointers


def function_pointer_typedefs(root):
    """The names a tree gives to a typedef or alias of a function pointer."""
    names = set()
    for path in source_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in (FUNCTION_POINTER, FUNCTION_POINTER_ALIAS):
            for match in pattern.finditer(text):
                names.add(match.group("name"))
    return names


def type_of(piece):
    """The type of a parameter, without its name."""
    words = piece.strip().split()
    if len(words) > 1 and words[-1].isidentifier() and words[-1] not in TYPE_NAMES:
        words = words[:-1]
    return " ".join(words)


def describe(parameters):
    if parameters is None or parameters.arity == 0:
        return "no parameters"
    return ", ".join(type_of(piece) for piece in parameters.pieces)


def split_arguments(text):
    """Split a parameter or argument list at its top level commas."""
    pieces = []
    depth = 0
    current = []
    index = 0
    while index < len(text):
        character = text[index]
        if character in "\"'":
            quote = character
            current.append(character)
            index += 1
            while index < len(text) and text[index] != quote:
                if text[index] == "\\":
                    current.append(text[index])
                    index += 1
                if index < len(text):
                    current.append(text[index])
                    index += 1
            if index < len(text):
                current.append(text[index])
            index += 1
            continue
        if character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
        if character == "," and depth == 0:
            pieces.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    tail = "".join(current).strip()
    if tail:
        pieces.append(tail)
    return pieces


def matching_paren(text, opening):
    """The index of the parenthesis that closes the one at `opening`."""
    depth = 0
    index = opening
    while index < len(text):
        character = text[index]
        if character == '"' or character == "'":
            quote = character
            index += 1
            while index < len(text) and text[index] != quote:
                index += 2 if text[index] == "\\" else 1
        elif character == "/" and index + 1 < len(text) and text[index + 1] == "/":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        elif character == "/" and index + 1 < len(text) and text[index + 1] == "*":
            index = text.find("*/", index)
            if index < 0:
                return -1
            index += 1
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def source_files(root):
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.is_file():
            yield path


def library_of(path, root):
    """The library a source file belongs to."""
    relative = path.relative_to(root)
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == "core" and parts[1] == "libs" and parts[2] == "prx":
        return parts[3]
    return parts[0] if parts else ""


def anyps5_exports(root):
    """Every export AnyPS5 declares, with the prototype it declares."""
    prx = root / "core" / "libs" / "prx"
    exports = {}
    for path in source_files(prx):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in EXPORT.finditer(text):
            opening = match.end() - 1
            closing = matching_paren(text, opening)
            if closing < 0:
                continue
            pieces = split_arguments(text[opening + 1:closing])
            if len(pieces) == 1 and pieces[0] == "void":
                pieces = []
            parameters = Parameters(pieces, True)
            line = text.count("\n", 0, match.start()) + 1
            name = match.group("name")
            exports.setdefault(name, []).append(
                Export(name, library_of(path, root), path, line, parameters))
    return exports


def is_declaration(text, start):
    """Whether the name at `start` is preceded by a return type, not by a call.

    A declaration reads `type name(...)`; a call reads `name(...)` after an
    expression, a keyword or a statement end.
    """
    line_start = text.rfind("\n", 0, start) + 1
    prefix = text[line_start:start].strip()
    if not prefix:
        return False
    words = prefix.split()
    if prefix.endswith("*"):
        words = words[:-1]
        if not words or not words[-1].isidentifier() or words[-1] in KEYWORDS:
            return False
        return words[-1] in TYPE_NAMES or words[-1].endswith("_t")
    if prefix.endswith((";", "{", "}", ",", "(", "=", "[", "!", "&", "|", "+", "-", "/", "<", ">")):
        return False
    last = words[-1]
    return last.isidentifier() and last not in KEYWORDS


def observations(source, root):
    """The prototypes a PS5 source declares and the calls it makes."""
    found = []
    for path in source_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CALL.finditer(text):
            name = match.group("name")
            opening = match.end() - 1
            closing = matching_paren(text, opening)
            if closing < 0:
                continue
            line = text.count("\n", 0, match.start()) + 1
            body = text[opening + 1:closing]
            pieces = split_arguments(body)
            if is_declaration(text, match.start()):
                if len(pieces) == 1 and pieces[0] == "void":
                    found.append(Observation(name, source, path.name, line, "declaration",
                                             Parameters([], True), text[match.start():closing + 1]))
                    continue
                if not pieces:
                    found.append(Observation(name, source, path.name, line, "unspecified declaration",
                                             Parameters([], False), ""))
                    continue
                found.append(Observation(name, source, path.name, line, "declaration", Parameters(pieces, True),
                                          text[match.start():closing + 1]))
                continue
            if not pieces:
                continue
            found.append(Observation(name, source, path.name, line, "call", Parameters(pieces, True),
                                      text[match.start():closing + 1]))
    return found


def revision(source):
    """The revision a source tree is at, when it is a git checkout."""
    try:
        result = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def compare(exports, found, library=None, function_pointers=()):
    """The exports whose AnyPS5 prototype disagrees with a PS5 source."""
    by_name = {}
    for observation in found:
        by_name.setdefault(observation.name, []).append(observation)
    mismatches = []
    for name, candidates in exports.items():
        if library and candidates[0].library != library:
            continue
        for candidate in candidates:
            reasons = []
            for observation in by_name.get(name, []):
                reason = disagreement(candidate.parameters, observation, function_pointers)
                if reason:
                    reasons.append((observation, reason))
            if not reasons:
                continue
            reasons.sort(key=lambda item: 0 if item[0].kind == "call" else 1)
            observation, reason = reasons[0]
            mismatches.append(Mismatch(candidate, observation, reason))
    mismatches.sort(key=lambda item: (item.export.library, item.export.name))
    return mismatches


def disagreement(parameters, observation, function_pointers=()):
    """Why an AnyPS5 prototype and a PS5 observation disagree, or ""."""
    if observation.kind == "unspecified declaration":
        return ""
    if observation.kind == "call":
        if observation.parameters.arity > parameters.arity:
            return (f"the call passes {observation.parameters.arity} arguments, "
                    f"the prototype takes {parameters.arity}")
        return ""
    if observation.parameters.arity != parameters.arity:
        return (f"the prototype takes {observation.parameters.arity} parameters, "
                f"AnyPS5 declares {parameters.arity}")
    if observation.parameters.pointers(function_pointers) != parameters.pointers(function_pointers):
        return "the parameters differ in where they are pointers"
    return ""


def report(mismatches, sources, verbose=False):
    lines = []
    by_library = {}
    for mismatch in mismatches:
        by_library.setdefault(mismatch.export.library, []).append(mismatch)
    settled = sum(1 for mismatch in mismatches if mismatch.observation.kind == "call")
    lines.append(f"{len(by_library)} libraries, {len(mismatches)} exports disagree with a PS5 source")
    lines.append(f"  {settled} of them are settled by a PS5 call site, "
                 f"{len(mismatches) - settled} only by a declaration")
    for source in sources:
        lines.append(f"  source {source.name} @ {source.revision}")
    for library in sorted(by_library):
        lines.append("")
        lines.append(f"{library}")
        for mismatch in by_library[library]:
            lines.append(f"  {mismatch.describe()}")
            lines.append(f"    AnyPS5 {mismatch.export.path.name}:{mismatch.export.line}")
            lines.append(f"    PS5    {mismatch.observation.evidence()}")
            if verbose and mismatch.observation.text:
                lines.append(f"    {mismatch.observation.text}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=".", help="the AnyPS5 checkout to read")
    parser.add_argument("--ps5", action="append", default=[],
                        help="a directory of a cloned PS5 source tree; may be repeated")
    parser.add_argument("--ps5-root", default="", help="a directory of cloned PS5 source trees")
    parser.add_argument("--library", default="", help="only report this library")
    parser.add_argument("--json", default="", help="write the report as JSON")
    parser.add_argument("--verbose", action="store_true", help="print the PS5 source line")
    arguments = parser.parse_args()

    root = Path(arguments.source).resolve()
    if arguments.ps5_root:
        for entry in sorted(Path(arguments.ps5_root).iterdir()):
            if entry.is_dir():
                arguments.ps5.append(str(entry))
    if not arguments.ps5:
        parser.error("no PS5 source tree given; pass --ps5 or --ps5-root")

    exports = anyps5_exports(root)
    found = []
    sources = []
    function_pointers = set()
    for entry in arguments.ps5:
        tree = Path(entry).resolve()
        if not tree.is_dir():
            continue
        sources.append(Source(tree.name, revision(tree)))
        found.extend(observations(tree.name, tree))
        function_pointers |= function_pointer_typedefs(tree)
    function_pointers |= function_pointer_typedefs(root / "core" / "libs")

    mismatches = compare(exports, found, arguments.library or None, function_pointers)
    text = report(mismatches, sources, arguments.verbose)
    print(text)
    if arguments.json:
        Path(arguments.json).write_text(json.dumps({
            "sources": [{"name": source.name, "revision": source.revision} for source in sources],
            "mismatches": [{
                "library": mismatch.export.library,
                "export": mismatch.export.name,
                "anyps5": describe(mismatch.export.parameters),
                "anyps5_file": f"{mismatch.export.path.name}:{mismatch.export.line}",
                "ps5": describe(mismatch.observation.parameters),
                "ps5_kind": mismatch.observation.kind,
                "ps5_evidence": mismatch.observation.evidence(),
                "reason": mismatch.reason,
            } for mismatch in mismatches],
        }, indent=2), encoding="utf-8")
    return 0 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
