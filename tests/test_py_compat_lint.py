# Viva 09-17: the Railway runtime is Python 3.11 while local dev runs 3.13.
# Two real outages came from syntax that only behaves on 3.12+:
#   1) multi-line f-string expressions (PEP 701) -> SyntaxError crash-loop;
#   2) walrus `:=` inside f-strings -> silently parsed as a format spec and
#      raises NameError at runtime (killed the whole TLBREAK detector).
# These lints keep the repo deployable on the ACTUAL production interpreter.
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent

# {name := ...} or {obj.attr := ...} anywhere on a line containing an f-string
_WALRUS_IN_FSTRING = re.compile(r"""(?<![A-Za-z0-9_])f["'][^"']*\{[^{}()]*:=""")


def _py_files():
    for p in REPO.rglob("*.py"):
        parts = set(p.relative_to(REPO).parts)
        if ".git" in parts or "__pycache__" in parts:
            continue
        yield p


def test_no_walrus_inside_fstrings():
    offenders = []
    for p in _py_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _WALRUS_IN_FSTRING.search(line):
                offenders.append(f"{p.relative_to(REPO)}:{i}")
    assert not offenders, (
        "walrus ':=' inside an f-string parses as a format spec before Python "
        "3.12 and raises NameError at runtime: " + ", ".join(offenders)
    )


def test_no_multiline_fstring_expressions():
    """An f-string opened on one line and closed on a later line while its
    expression spans the break is PEP 701 (3.12+) only. Heuristic: a line
    ending inside an unbalanced f-string brace expression."""
    offenders = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8")
        # cheap check: find f"..." strings whose { has no } before a newline
        for m in re.finditer(r"""(?<![A-Za-z0-9_])f(["'])""", src):
            start = m.end()
            depth = 0
            i = start
            while i < len(src):
                ch = src[i]
                if ch == "\\":
                    i += 2
                    continue
                if depth == 0 and ch == m.group(1):
                    break
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth = max(0, depth - 1)
                elif ch == "\n" and depth > 0:
                    line_no = src.count("\n", 0, m.start()) + 1
                    offenders.append(f"{p.relative_to(REPO)}:{line_no}")
                    break
                i += 1
    assert not offenders, (
        "multi-line f-string expressions require Python 3.12+ (PEP 701); "
        "Railway runs 3.11: " + ", ".join(offenders)
    )
