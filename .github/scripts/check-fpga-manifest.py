#!/usr/bin/env python3
"""Check board coverage and packaged images on the GitHub runner."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
# These exclusions follow the firmware's CONFIG_MK2 guards and the variant
# project files. Legacy NES/SMS .xise files do not make their MCU loaders work
# on MkII. New core directories require an explicit board-support audit here.
EXCLUDED = {
    "mk2": {"a26", "gbc", "nes", "nes_k", "nes_mmc3", "nes_mmc5", "sms"},
    "mk3": {"basex", "dspx", "sgb_msu"},
}
EXT = {"mk2": "bit", "mk3": "bi3"}
FIRMWARE = {"mk2": "firmware.img", "mk3": "firmware.im3", "mk3-stm32": "firmware.stm"}


def cores(board):
    names = subprocess.check_output(
        ["make", "--no-print-directory", "-s", f"list-fpga-{board}"],
        cwd=ROOT, text=True,
    ).split()
    inventory = {p.parent.name.removeprefix("sd2snes_")
                 for p in (ROOT / "verilog").glob("sd2snes_*/Makefile")}
    expected = inventory - EXCLUDED[board]
    if len(names) != len(set(names)) or set(names) != expected:
        raise RuntimeError(f"{board} core list: missing {sorted(expected - set(names))}; "
                           f"unexpected {sorted(set(names) - expected)}; check duplicates too")
    for name in names:
        project = ROOT / "verilog" / f"sd2snes_{name}"
        required = ([f"sd2snes_{name}.xise"] if board == "mk2"
                    else [f"sd2snes_{name}.qpf", "main.qsf"])
        for filename in required:
            if not (project / filename).is_file():
                raise RuntimeError(f"Missing {board} project: {project / filename}")
    return names


def images(board):
    return {f"verilog/sd2snes_{name}/fpga_{name}.{EXT[board]}" for name in cores(board)}


def check_equal(actual, expected, label):
    if actual != expected:
        raise RuntimeError(f"{label}: missing {sorted(expected - actual)}; "
                           f"unexpected {sorted(actual - expected)}")


def main():
    mode = sys.argv[1]
    if mode == "matrix":
        matrix = [{"board": board, "core": name, "extension": EXT[board]}
                  for board in EXT for name in cores(board)]
        print("matrix=" + json.dumps({"include": matrix}, separators=(",", ":")))
        return
    board = sys.argv[2]
    fpga_board = "mk2" if board == "mk2" else "mk3"
    expected = images(fpga_board)
    if mode == "artifact":
        actual = {str(p.relative_to(ROOT)).replace("\\", "/")
                  for p in (ROOT / "verilog").glob("*/fpga_*") if p.is_file()
                  and p.suffix in {".bit", ".bi3"}}
        check_equal(actual, expected, f"{board} FPGA artifact")
        for filename in expected:
            if (ROOT / filename).stat().st_size == 0:
                raise RuntimeError(f"Empty FPGA image: {filename}")
    elif mode == "package":
        if board not in FIRMWARE or len(sys.argv) != 4:
            raise RuntimeError("Expected one board and exactly one release ZIP")
        with zipfile.ZipFile(sys.argv[3]) as archive:
            entries = {Path(n).name: n for n in archive.namelist() if not n.endswith("/")}
            actual = {n for n in entries if n.startswith("fpga_")
                      and Path(n).suffix in {".bit", ".bi3"}}
            check_equal(actual, {Path(n).name for n in expected}, f"{board} packaged cores")
            check_equal(set(entries) & set(FIRMWARE.values()), {FIRMWARE[board]},
                        f"{board} packaged MCU firmware")
            menu = "menu.bin" if board == "mk2" else "m3nu.bin"
            check_equal(set(entries) & {"menu.bin", "m3nu.bin"}, {menu}, f"{board} menu")
            for filename in actual | {FIRMWARE[board], menu, "igmenu.bin", "onboarding.bin",
                                      "xc_soc.bin", "memtest.bin", "fileops.bin", "rmdir.bin"}:
                if archive.getinfo(entries[filename]).file_size == 0:
                    raise RuntimeError(f"Empty packaged file: {filename}")
            if archive.testzip() is not None:
                raise RuntimeError("Release ZIP CRC validation failed")
    else:
        raise RuntimeError(f"Unknown check: {mode}")
    print(f"{board}: verified {len(expected)} FPGA images ({mode})")


if __name__ == "__main__":
    main()
