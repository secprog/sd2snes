#!/usr/bin/env python3
"""Hosted-only inspection of the retained 40698939687 CoreGen samples.

This checks evidence identity and recorded inputs; it does not establish that
different binary netlists have the same function or permit a timing waiver.
"""

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path


HASHES = {
    "basex": {
        "dac_buf": ["0867378688188449336d5c0605fa6ab4ea45cbebc542e2966b08381c06d05fb2", "b24722da35c0d32851f330cae8be6e7dbaa45116f6845f23e1d762e4449a1873", "5e91c2e4dd16e94ed9f589a1c2e00981b09739e956858e3f0cfdcf2f32fa3a7e"],
        "msu_databuf": ["b12c09895344adbf30e8d82382abe9acc94a4b0d9ac13ba74be3e53b8e75aa29", "c7fa0953f6b441d18496fc9cc2fa522b3ab0152599395847dca8884e52fdcdfc", "5c9f5fe3ee2a532f7e8ae914db9718f316dfd9ec50c40a47c1036a1474c8ee50"],
        "snescmd_buf": ["16c57a7b62200205a75a6c59b7e313322b2fc5c64cb627fcf687815b5e0f4b92", "070ed657748f90f6cae2e3f4ff0420d58669dc1321cd1ea476a10f1472f54d9b", "ff18420fec08ccfa35a18414366fc0e4eeda35ba1df6e476a74d692dec7bc1d6"],
    },
    "dspx": {
        "dac_buf": ["33d0d2d73d85dfde0ec43526e96d991abcd844c67c9e9c45ab545b0972a59010", "bbbc84396a270d01fbf252dcc772d8e59c036a2e2151ac683f551681b6cf7a3a", "777c8fc34d9eb335ad86e6ea3d13598c73c66cea6ecd8a26d54d951c4a35c65d"],
        "msu_databuf": ["33cc817f6cff51993f6aeb6aef65b037055c4e1720d3424723f987fbba6c2411", "f0f69237718ac8c83e3dadf10817aca59efcfb65b1fac275ae02fe82f0ab5d5e", "a790b87ee5ca6f718d3c1d744e0d80b1346e13d7e7f619a6b015465d672e89ec"],
        "snescmd_buf": ["d0e5d8e05a14fcdb5ce2355187de1a1ba561efb008e23f7f80202c0ce81dc35a", "33cb636a0fc3d1b46ceedebbe24f6a32951d49259dcd9f296ed1ab9a84316b79", "12b81fed7f9ed395733265c5c6b4619eab43546477549aae9d1ac8468f0a9c22"],
        "upd77c25_datram": ["a9e66a1eb8e1b80586bbe6f7c6748d08c001b7229628eb5ce3d4d76d9f48ccbf", "c6c4547ffe38a22b7cfd39f11a31cdd5ed8686d0481ec498b4e326a9827f35c2", "0650e3744adec66ed2baa0b2cb697f8b32c72e1058491f37aaa11f97a9810a84"],
        "upd77c25_datrom": ["e063d308f05cc2e0339be2a3ce7a003317074d89a6ee6a80192fff831d8c124f", "84dece36b4be7952925138dc9aac652f8290173ffd9a63e1cf7beade06d39e6d", "eb84a452eb46f3de1563d0b1c95a769cb40c158ac78674b65d483be7078eaee6"],
        "upd77c25_pgmrom": ["0de999b148c5cd714bda9b2b59647823967c911a2b6de47d18269f4e2ada4bec", "bf6c2a74ce23b269d935cedfaea4b6fcb88700ec5abd4052f73c830e2510bddc", "582cfd3108b1ca8f64c0d13f2be152d581303359df7ab1930412da246a0af3b5"],
    },
}
SAMPLES = ("a1", "a2", "b")


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    require(len(sys.argv) == 3, "usage: inspect-mk2-coregen-retained.py CORE ARTIFACT_DIR")
    core, artifact = sys.argv[1], Path(sys.argv[2])
    require(core in HASHES, f"unknown core: {core}")
    source = "sd2snes_base" if core == "basex" else "sd2snes_dsp"
    ips = HASHES[core]
    expected_tree = "4e50365f59f38217b67c5126276873a29be737d5"
    tree = subprocess.check_output(["git", "rev-parse", "HEAD:verilog"], text=True).strip()
    require(tree == expected_tree, f"unexpected Verilog tree {tree}")

    identity = (artifact / "identity.txt").read_text()
    project, ucf = (("5338e8fa5fef0af0c526ff99563b17a0763ed34a", "e582e03059fbbcf21b4124e5dd7aa9ac8792fd6b")
                    if core == "basex" else
                    ("2822b63c005bce73e8e7aaf332bcdbd983d1492d", "4f34c4cf9e475ac171a216c3f15fff74918fd03c"))
    for expected in ("Checkout: 2f412c3874e515054150d92d7cb72f4786c8d1b9", f"Core: {core}",
                     f"Verilog tree: {expected_tree}", f"Project: {project}", f"UCF: {ucf}",
                     "ISE image ID: sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8"):
        require(expected in identity, f"identity missing {expected}")

    # Recompute the canonical tracked tree from Git independently of the
    # retained manifests. Git archive leaves worktree filters out of the check.
    archive = subprocess.check_output(["git", "archive", "HEAD", "verilog"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        canonical = {m.name: digest(tar.extractfile(m).read()) for m in tar if m.isfile()}
    manifests = {}
    for sample in SAMPLES:
        for phase in ("archive", "before", "after"):
            path = artifact / f"{sample}-{phase}.json"
            manifests[f"{sample}-{phase}"] = json.loads(path.read_text())
            print(f"{path.name} sha256 {digest(path.read_bytes())}")
    updated = json.loads((artifact / "b-updated-input.json").read_text())
    require(manifests["a1-archive"] == canonical, "archive manifest differs from canonical Git tree")
    for key in ("a2-archive", "b-archive", "a1-before", "a2-before"):
        require(manifests[key] == canonical, f"{key} differs from canonical Git tree")
    require(updated == manifests["a1-after"] == manifests["b-before"], "B input is not A1's complete post-generation tracked tree")
    prefix = f"verilog/{source}/ip/mk2/"
    expected_changes = {prefix + "coregen.cgc"} | {
        prefix + ip + ext for ip in ips for ext in (".xco", ".xise")
    }
    for sample in SAMPLES:
        before, after = manifests[f"{sample}-before"], manifests[f"{sample}-after"]
        require(before.keys() == after.keys() == canonical.keys(), f"{sample} tracked path set changed")
        changes = {name for name in before if before[name] != after[name]}
        require(changes == expected_changes if sample != "b" else changes <= expected_changes,
                f"unexpected {sample} tracked changes: {sorted(changes ^ expected_changes)}")
        print(f"{sample}: {len(changes)} changed tracked files")
        for name in sorted(changes):
            print(f"  {name}: {before[name]} -> {after[name]}")
        file_names = {"coregen.cgc"} | {ip + ext for ip in ips for ext in (".xco", ".xise", ".v")}
        for phase, manifest in (("inputs", before), ("outputs", after)):
            directory = artifact / f"{sample}-{phase}"
            expected_names = file_names | ({ip + ".ngc" for ip in ips} if phase == "outputs" else set())
            entries = list(directory.iterdir())
            require({p.name for p in entries} == expected_names and all(p.is_file() and not p.is_symlink() for p in entries),
                    f"unexpected/missing {sample}-{phase} files")
            for name in sorted(file_names):
                require(digest((directory / name).read_bytes()) == manifest[prefix + name],
                        f"{sample}-{phase}/{name} does not match tracked manifest")
        log = (artifact / f"{sample}-coregen.log").read_text()
        for ip in ips:
            command = f"coregen -p ../{source}/ip/mk2 -b ../{source}/ip/mk2/{ip}.xco -r"
            require(log.count(command) == 1, f"missing or duplicate {sample} command {ip}")
            generated = f"Generating implementation netlist for '{ip}'..."
            require(log.count(generated) == 1, f"missing or duplicate {sample} netlist generation {ip}")
        print(f"{sample}: exact captured tracked inputs/outputs and all {len(ips)} generation log markers verified")

    for ip, expected_hashes in ips.items():
        samples = [(artifact / f"{sample}-outputs" / f"{ip}.ngc").read_bytes() for sample in SAMPLES]
        for sample, data, expected in zip(SAMPLES, samples, expected_hashes):
            require(digest(data) == expected, f"{sample}/{ip} hash differs from the original hosted job log")
            print(f"{sample}/{ip}.ngc: {expected}, {len(data)} bytes")
        require(samples[0] != samples[1] and samples[0] != samples[2], f"unexpected binary comparison for {ip}")
        require(samples[0] == samples[0] and samples[0] != samples[0] + b"\x01", "binary comparator control failed")
        print(f"{ip}: A1/A2 differ; A1/B differ; same-file and appended-byte controls passed")
    print("Tracked input identity and retained bytes checked. Binary difference is not proof of functional difference.")
    print("No historical netlist, whole-FPGA timing, hardware or input-gate waiver is established.")


if __name__ == "__main__":
    main()
