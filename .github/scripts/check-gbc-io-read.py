"""Hosted SAT proof: the MkII IO mux equals the original register-read case.

All address and register bits are unconstrained. Preprocessing and declaration
extraction retain production widths; an inverted-output control must fail.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-io-proof-") as tmp:
    work = Path(tmp)
    preprocessed = work / "cpu.v"
    subprocess.run(["iverilog", "-E", "-DMK2", "-I",
                    str(root / "verilog/sd2snes_gbc"), "-o", str(preprocessed),
                    str(root / "verilog/sd2snes_gbc/sgb_cpu.v")], check=True)
    cpu = preprocessed.read_text()
    original = cpu.split("case (reg_addr_r)", 1)[1].split("endcase", 1)[0]
    entries = re.findall(
        r"8'h([0-9A-Fa-f]{2}):\s*(?:begin\s*)?reg_mdr_r(?:\[7:0\])?\s*<=\s*(.*?);",
        original, re.S)
    if len(entries) != 76 or len({a for a, _ in entries}) != 76:
        raise RuntimeError("Original read case changed; review the proof extraction")
    if not re.search(r"default:\s*reg_mdr_r\s*<=\s*8'hFF;", original):
        raise RuntimeError("Original unmapped-register behavior changed")
    actual = re.search(r"wire \[7:0\] mk2_io_read_data =\s*(.*?);", cpu, re.S)[1]
    if not re.search(r"endcase\s+reg_mdr_r <= mk2_io_read_data;\s+"
                     r"reg_state_r <= ST_REG_END;", cpu):
        raise RuntimeError("Production mux no longer overrides the same read state")
    expressions = actual + " " + " ".join(expr for _, expr in entries)
    # Strip sized numeric literals before collecting the referenced signals.
    expressions = re.sub(r"\d+'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ]+", "", expressions)
    names = sorted(set(re.findall(r"\b[A-Za-z_]\w*\b", expressions)))
    declarations = {}
    for match in re.finditer(r"^\s*(?:reg|wire|input|output)\s+(?:signed\s+)?"
                             r"(\[[^\]]+\]\s*)?([A-Za-z_]\w*)\b", cpu, re.M):
        name = match[2]
        if name in names:
            width = (match[1] or "").strip()
            if width and not re.fullmatch(r"\[\s*\d+\s*:\s*\d+\s*\]", width):
                raise RuntimeError("Unsupported production width: " + match[0])
            if name in declarations and declarations[name] != width:
                raise RuntimeError("Conflicting production declarations: " + name)
            declarations[name] = width
    if set(names) != set(declarations):
        raise RuntimeError("Missing signal widths: " + str(set(names) - declarations.keys()))
    ports = ",\n".join("input " + declarations[n] + " " + n for n in names)
    ref_case = "\n".join("8'h" + a + ": expected = " + e + ";" for a, e in entries)
    body = ("module check(" + ports + ", output equivalent);\n"
            "wire [7:0] actual = " + actual + ";\nreg [7:0] expected;\n"
            "always @* begin case (reg_addr_r)\n" + ref_case +
            "\ndefault: expected = 8'hff;\nendcase end\n")
    for negative in (False, True):
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(body + "assign equivalent = (actual ^ 8'h" +
                          ("01" if negative else "00") + ") == expected;\nendmodule\n")
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT did not reject the inverted-output control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("IO register-read equivalence failed\n" + log)
    print("PASS: MkII IO reads equal the original for all addresses and register states; "
          "SAT rejects the inverted-output control")
