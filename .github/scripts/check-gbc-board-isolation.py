"""Actions-only source identity check for the two GBC board implementations.

MkIII must preprocess to the original core, including MSU-1 and its DAC.
MkII must preprocess to the user's accepted layout source. This checks source
identity, not timing closure or whether the original core models hardware.
"""
from pathlib import Path
import difflib
import hashlib
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CORE = Path("verilog/sd2snes_gbc")
REFERENCES = {
    "MK2": "0cd924f1d50c7a026499fc3a69dd2379e5972b17",
    "MK3": "274d52c8aa9c1970df2f04e39da1b5ddca8e6e25",
}
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|[A-Za-z_$][\w$]*|[^\s]', re.S)


def tokens(text):
    text = re.sub(r"^\s*`line[^\n]*", "", text, flags=re.M)
    return [m[0] for m in TOKEN.finditer(text) if not m[0].startswith(("//", "/*"))]


def preprocess(folder, board, name, output):
    subprocess.run(["iverilog", "-E", "-D" + board, "-I", str(folder),
                    "-o", str(output), str(folder / name)], check=True)
    return tokens(output.read_text())


with tempfile.TemporaryDirectory(prefix="gbc-board-identity-") as temp:
    work = Path(temp)
    for board, ref in REFERENCES.items():
        reference = work / board
        names = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", ref, "--", str(CORE)],
            cwd=ROOT, text=True).splitlines()
        for name in names:
            target = reference / Path(name).relative_to(CORE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(["git", "show", ref + ":" + name], cwd=ROOT))
        files = sorted(p.name for p in reference.glob("*.v"))
        for name in files:
            expected = preprocess(reference, board, name, work / "expected.v")
            actual = preprocess(ROOT / CORE, board, name, work / "actual.v")
            if actual != expected:
                diff = "\n".join(list(difflib.unified_diff(expected, actual,
                    fromfile=ref + ":" + name, tofile=board + ":" + name))[:100])
                raise RuntimeError("Active source changed\n" + diff)
        if board == "MK3":
            for name in names:
                relative = Path(name).relative_to(CORE)
                if relative.parts[0] == "ip" or relative.suffix in (".qsf", ".sdc"):
                    if (ROOT / name).read_bytes().replace(b"\r\n", b"\n") != (
                            reference / relative).read_bytes().replace(b"\r\n", b"\n"):
                        raise RuntimeError("MkIII project/IP changed: " + name)
        digest = hashlib.sha256("\n".join(files).encode()).hexdigest()
        print(f"PASS: {board} active RTL matches {ref} ({len(files)} files; list SHA256 {digest})")
