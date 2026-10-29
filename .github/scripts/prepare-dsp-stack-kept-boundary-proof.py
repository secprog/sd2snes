#!/usr/bin/env python3
"""Prepare a hosted-only attribute-boundary experiment from the pinned proof.

This script never modifies production RTL. Run only on a GitHub-hosted runner.
The two shared permits and three 16-bit early-select vectors receive KEEP=TRUE.
No promise about actual mapping, resource use, timing or input integrity follows.
"""

import hashlib
import importlib.util
import sys
from pathlib import Path


BASE_BLOB = "0244d752e67f6cc5119b62bd49efb4cc32312022"
UNKEPT_SHA256 = "6e4c897d25083e4d6849c173ccec6f8efad7c8b1ce3de8453145a4dc3d667b76"
CANDIDATE_BLOB = "68ffd77e08dae78cb7cbeba5e3214c83b4dd8718"
CANDIDATE_SHA256 = "d32e7dbcae9870753215b59e7f35da7f5046ed8956fbf299c0cdd3996de2d21f"
KEEP = '(* KEEP="TRUE" *) '
DECLARATIONS = (
    "wire stack_late_run, stack_late_restore;",
    "wire [15:0] stack_early_push, stack_early_low, stack_early_high;",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


base_path = Path(__file__).with_name("prepare-dsp-stack-late-permit-proof.py")
if blob(base_path.read_bytes()) != BASE_BLOB:
    raise SystemExit("Previously reviewed source/model generator changed")
spec = importlib.util.spec_from_file_location("base", base_path)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
original_writes = base.writes


def kept_writes():
    original = original_writes()
    changed = original
    for declaration in DECLARATIONS:
        changed = base.once(changed, declaration, KEEP + declaration)
    if changed.count(KEEP) != 2 or changed.replace(KEEP, "") != original:
        raise SystemExit("Change is not exactly the two declared KEEP attributes")
    return changed


if __name__ == "__main__":
    base.writes = kept_writes
    base.main()
    output = Path(sys.argv[2])
    candidate = (output / "candidate-upd77c25.v").read_bytes()
    if blob(candidate) != CANDIDATE_BLOB or digest(candidate) != CANDIDATE_SHA256:
        raise SystemExit("Complete kept candidate differs from independent source pin")
    text = candidate.decode("utf-8")
    if text.count(KEEP) != 2 or digest(text.replace(KEEP, "").encode()) != UNKEPT_SHA256:
        raise SystemExit("Complete unkept-source inverse differs from reviewed candidate")
    gate = (output / "gate.v").read_text(encoding="utf-8")
    if gate.count(KEEP) != 2 or digest(gate.replace(KEEP, "").encode()) != "18c99cda1bc0b12c8bed4a76b64a617d216a1727aaa2fbab21dcaba70937d55e":
        raise SystemExit("Proof transition source differs beyond the KEEP attributes")
    if digest((output / "gold.v").read_bytes()) != "4a167b7b4efe8252d33bf2c437c494509c77aadfe6dc407a437be0030c2d2d2e":
        raise SystemExit("Pinned original transition source changed")
    report = (
        "Exact attribute-only inverse to independently reviewed unkept candidate passed.\n"
        "KEEP=TRUE applies to 2 shared permit bits and 3x16 early qualification bits.\n"
        "No clock, state, guard, read expression, data or cycle change.\n"
        "Fresh all176 state/read binary and unrestricted-X proof remains mandatory.\n"
        "Actual ISE recognition, mapped pins/LUTs/muxes, capacity and timing are unproved.\n"
        "No native source/input/timing gate is changed; failed unkept candidate stays rejected.\n"
    )
    (output / "kept-boundary-audit.txt").write_text(report, encoding="utf-8")
    (output / "base-generator.py.txt").write_bytes(base_path.read_bytes())
    (output / "kept-generator.py.txt").write_bytes(Path(__file__).read_bytes())
    (output / "SHA256SUMS").write_text("".join(
        f"{digest(path.read_bytes())}  {path.name}\n"
        for path in sorted(output.iterdir()) if path.is_file() and path.name != "SHA256SUMS"
    ), encoding="utf-8")
    print(report, end="")
