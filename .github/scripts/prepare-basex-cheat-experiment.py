#!/usr/bin/env python3
"""Prepare diagnostic inputs on a hosted runner; never edit production RTL."""

import difflib
import hashlib
import sys
from pathlib import Path


EXPECTED_SOURCE_BLOB = "dfc2f4fe2dc21fdd07da735fa1cd57a7aa6f4f3f"
OLD = """      if(pgm_idx < 6) begin
        cheat_addr[pgm_idx] <= pgm_in[31:8];
        cheat_data[pgm_idx] <= pgm_in[7:0];
      end else if(pgm_idx == 6) begin // set rom patch enable
        cheat_enable_mask <= pgm_in[5:0];
      end else if(pgm_idx == 7) begin // set/reset global enable / hooks
      // pgm_in[15:8] are reset bit flags
      // pgm_in[7:0] are set bit flags
        {savestate_enable, wram_present, buttons_enable, holdoff_enable, irq_enable, nmi_enable, cheat_enable}
         <= ({savestate_enable, wram_present, buttons_enable, holdoff_enable, irq_enable, nmi_enable, cheat_enable}
          & ~pgm_in[14:8])
          | pgm_in[6:0];
      end
"""


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    source_blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if source_blob != EXPECTED_SOURCE_BLOB:
        raise SystemExit(f"Unexpected reference RTL blob: {source_blob}")
    original = raw.decode("utf-8")
    if original.count(OLD) != 1:
        raise SystemExit("Expected exactly one original programming decoder")

    # Keep the surrounding reset, command-write and pgm_we priority untouched.
    # Each explicit case replaces one address of the same six register words.
    cases = ["      case(pgm_idx)\n"]
    for index in range(6):
        cases.append(
            f"        3'd{index}: begin\n"
            f"          cheat_addr[{index}] <= pgm_in[31:8];\n"
            f"          cheat_data[{index}] <= pgm_in[7:0];\n"
            "        end\n"
        )
    cases.append("""        3'd6: cheat_enable_mask <= pgm_in[5:0];
        3'd7: begin
          {savestate_enable, wram_present, buttons_enable, holdoff_enable, irq_enable, nmi_enable, cheat_enable}
           <= ({savestate_enable, wram_present, buttons_enable, holdoff_enable, irq_enable, nmi_enable, cheat_enable}
            & ~pgm_in[14:8])
            | pgm_in[6:0];
        end
      endcase
""")
    candidate = original.replace(OLD, "".join(cases))
    mutant = candidate.replace(
        "cheat_data[0] <= pgm_in[7:0];",
        "cheat_data[0] <= pgm_in[7:0] ^ 8'h01;",
        1,
    )
    if mutant == candidate:
        raise SystemExit("Negative-control mutation was not applied")

    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for filename, text in (("gold.v", original), ("gate.v", candidate), ("mutant.v", mutant)):
        data = text.encode("utf-8")
        (output / filename).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {filename}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True), "gold.v", "gate.v")),
        encoding="utf-8",
    )
    print(f"Verified original cheat.v Git blob: {source_blob}")
    print("Prepared diagnostic case decoder and deliberately incorrect negative control.")


if __name__ == "__main__":
    main()
