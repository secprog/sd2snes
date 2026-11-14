#!/usr/bin/env python3
"""GitHub-only private-history basex source proof and strict timing evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("GitHub-hosted execution only")
BASE="4d0199bf639629284546858b2b92abcd840b48a9"
IMAGE="sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8"
MAC="08:00:27:68:c9:35"
SELF=".github/scripts/validate-basex-private-history.py"
WORKFLOW=".github/workflows/validate-dspx-stack-timing.yml"
MAP=("map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 46 "
     "-register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy "
     "-pr b -bp -power off -o main_map.ncd main.ngd main.pcf")
PAR="par -w -ol high -xe c -t 46 main_map.ncd main.ncd main.pcf"
REPORTS={".syr",".par",".mrp",".psr",".bld",".bgn",".twr",".unroutes",
         ".pcf",".xst",".prj",".ut",".tsi",".ucf"}
FRAGMENTS=json.loads(r'''{
  "main": [
    {
      "old": "wire SNES_WR_end = (SNES_WRITEr[6:1] == 6'b000001);\n",
      "new": "wire SNES_WR_end = (SNES_WRITEr[6:1] == 6'b000001);\n`ifdef MK2\n`ifdef BASE_EXT\n// Private predicates for the programming priority path only. After each edge\n// they equal the two halves of the original current write history.\nreg [1:0] basex_wr_halves = 2'b00;\nalways @(posedge CLK2) begin\n  basex_wr_halves[0] <= (SNES_WRITEr[2:0] == 3'b001);\n  basex_wr_halves[1] <= (SNES_WRITEr[5:3] == 3'b000);\nend\n`endif\n`endif\n"
    },
    {
      "old": "  .SNES_wr_strobe(SNES_WR_end),\n",
      "new": "  .SNES_wr_strobe(SNES_WR_end),\n`ifdef MK2\n`ifdef BASE_EXT\n  .basex_wr_halves(basex_wr_halves),\n`endif\n`endif\n"
    }
  ],
  "cheat": [
    {
      "old": "  input feat_cmd_unlock_in,\n",
      "new": "  input feat_cmd_unlock_in,\n`ifdef MK2\n`ifdef BASE_EXT\n  input [1:0] basex_wr_halves,\n`endif\n`endif\n"
    },
    {
      "old": "reg [5:0] cheat_enable_mask;\n",
      "new": "reg [5:0] cheat_enable_mask;\n`ifdef MK2\n`ifdef BASE_EXT\nwire basex_program_permit;\nwire [5:0] basex_program_selected, basex_program_write;\nbasex_cheat_program_permit program_permit(\n  .low_half(basex_wr_halves[0]), .high_half(basex_wr_halves[1]),\n  .unlocked(snescmd_unlock), .enabled(snescmd_enable), .permit(basex_program_permit)\n);\nbasex_cheat_program_select #(.WORD(3'd0)) program_select_0(\n  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),\n  .selected(basex_program_selected[0])\n);\nbasex_cheat_program_join program_join_0(\n  .selected(basex_program_selected[0]), .permit(basex_program_permit),\n  .write(basex_program_write[0])\n);\nalways @(posedge clk) begin\n  if (basex_program_write[0]) begin\n    cheat_addr[0] <= pgm_in[31:8];\n    cheat_data[0] <= pgm_in[7:0];\n  end\nend\nbasex_cheat_program_select #(.WORD(3'd1)) program_select_1(\n  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),\n  .selected(basex_program_selected[1])\n);\nbasex_cheat_program_join program_join_1(\n  .selected(basex_program_selected[1]), .permit(basex_program_permit),\n  .write(basex_program_write[1])\n);\nalways @(posedge clk) begin\n  if (basex_program_write[1]) begin\n    cheat_addr[1] <= pgm_in[31:8];\n    cheat_data[1] <= pgm_in[7:0];\n  end\nend\nbasex_cheat_program_select #(.WORD(3'd2)) program_select_2(\n  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),\n  .selected(basex_program_selected[2])\n);\nbasex_cheat_program_join program_join_2(\n  .selected(basex_program_selected[2]), .permit(basex_program_permit),\n  .write(basex_program_write[2])\n);\nalways @(posedge clk) begin\n  if (basex_program_write[2]) begin\n    cheat_addr[2] <= pgm_in[31:8];\n    cheat_data[2] <= pgm_in[7:0];\n  end\nend\nbasex_cheat_program_select #(.WORD(3'd3)) program_select_3(\n  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),\n  .selected(basex_program_selected[3])\n);\nbasex_cheat_program_join program_join_3(\n  .selected(basex_program_selected[3]), .permit(basex_program_permit),\n  .write(basex_program_write[3])\n);\nalways @(posedge clk) begin\n  if (basex_program_write[3]) begin\n    cheat_addr[3] <= pgm_in[31:8];\n    cheat_data[3] <= pgm_in[7:0];\n  end\nend\nbasex_cheat_program_select #(.WORD(3'd4)) program_select_4(\n  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),\n  .selected(basex_program_selected[4])\n);\nbasex_cheat_program_join program_join_4(\n  .selected(basex_program_selected[4]), .permit(basex_program_permit),\n  .write(basex_program_write[4])\n);\nalways @(posedge clk) begin\n  if (basex_program_write[4]) begin\n    cheat_addr[4] <= pgm_in[31:8];\n    cheat_data[4] <= pgm_in[7:0];\n  end\nend\nbasex_cheat_program_select #(.WORD(3'd5)) program_select_5(\n  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),\n  .selected(basex_program_selected[5])\n);\nbasex_cheat_program_join program_join_5(\n  .selected(basex_program_selected[5]), .permit(basex_program_permit),\n  .write(basex_program_write[5])\n);\nalways @(posedge clk) begin\n  if (basex_program_write[5]) begin\n    cheat_addr[5] <= pgm_in[31:8];\n    cheat_data[5] <= pgm_in[7:0];\n  end\nend\n\n`endif\n`endif\n"
    },
    {
      "old": "        cheat_addr[pgm_idx] <= pgm_in[31:8];\n        cheat_data[pgm_idx] <= pgm_in[7:0];",
      "new": "`ifdef MK2\n`ifdef BASE_EXT\n        // Private word blocks above retain the complete original programming priority.\n`else\n        cheat_addr[pgm_idx] <= pgm_in[31:8];\n        cheat_data[pgm_idx] <= pgm_in[7:0];\n`endif\n`else\n        cheat_addr[pgm_idx] <= pgm_in[31:8];\n        cheat_data[pgm_idx] <= pgm_in[7:0];\n`endif"
    }
  ],
  "cheatSuffix": "\n`ifdef MK2\n`ifdef BASE_EXT\n// These four inputs are the private registered write-history halves and the\n// original combined unlock and command-enable signals. Procedural priority\n// keeps an unknown command predicate on the original programming branch.\n(* LUT_MAP=\"yes\" *)\nmodule basex_cheat_program_permit(\n  input low_half, high_half, unlocked, enabled,\n  output reg permit\n);\nalways @* begin\n  permit = 1'b1;\n  if (low_half & high_half & unlocked & enabled) permit = 1'b0;\nend\nendmodule\n\nmodule basex_cheat_program_select #(parameter [2:0] WORD = 3'd0)(\n  input reset, pgm_we, input [2:0] index,\n  output reg selected\n);\nalways @* begin\n  selected = 1'b0;\n  if (reset) begin\n  end else if (pgm_we) begin\n    if (index == WORD) selected = 1'b1;\n  end\nend\nendmodule\n\n(* LUT_MAP=\"yes\" *)\nmodule basex_cheat_program_join(input selected, permit, output write);\nassign write = selected & permit;\nendmodule\n\n`endif\n`endif\n",
  "scope": "MK2 && BASE_EXT only"
}''')


def require(ok, why):
    if not ok:
        raise ValueError(why)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    raw = Path(path).read_bytes()
    require(b"\0" not in raw, "NUL in text")
    raw.decode("utf-8")
    return raw

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), "Refuse evidence overwrite: " + str(path))
    raw = value if isinstance(value, bytes) else (value.encode() if isinstance(value, str)
          else (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    raw.decode("utf-8")
    require(b"\0" not in raw, "NUL in output")
    path.write_bytes(raw)

def git(*args):
    return subprocess.check_output(["git", *args])

def command(argv, prefix, timeout=1800, allowed=(0,)):
    """Keep complete stdout, stderr, argv and the actual direct process status."""
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    write(str(prefix)+".argv.json", argv)
    start = time.monotonic()
    with open(str(prefix)+".stdout.log", "xb") as out, open(str(prefix)+".stderr.log", "xb") as err:
        process = subprocess.run(argv, stdout=out, stderr=err, timeout=timeout)
    streams = {}
    for kind in ("stdout", "stderr"):
        raw = read(str(prefix)+"."+kind+".log")
        streams[kind] = dict(bytes=len(raw), sha256=sha(raw))
        if raw:
            sys.stdout.write(raw.decode())
            sys.stdout.flush()
    write(str(prefix)+".status.json", dict(argv=argv, exit=process.returncode,
          elapsedSeconds=time.monotonic()-start, streams=streams))
    require(process.returncode in allowed, "Unexpected direct process exit: " + repr(argv))
    return process.returncode

def cut_state(source, output, model_name):
    design = json.loads(read(source))
    require(set(design["modules"]) == {"cheat"}, "Complete flattened CPU, no blackboxes")
    module = design["modules"]["cheat"]
    aliases, init = {}, {}
    for name, net in module["netnames"].items():
        for index, bit in enumerate(net["bits"]):
            if not name.startswith("$"):
                aliases.setdefault(bit, []).append((name, index))
        values = net.get("attributes", {}).get("init")
        if values is not None:
            require(isinstance(values, str) and len(values) == len(net["bits"]), "Lossless init width")
            for bit, value in zip(net["bits"], reversed(values)):
                init.setdefault(bit, set()).add(value)
    states = []
    used = set()
    remove = []
    for name, cell in module["cells"].items():
        kind = cell["type"]
        if kind != "$dff":
            require(kind.startswith("$") and not any(s in kind.lower() for s in ("dff", "latch", "mem"))
                    and kind != "$ff" and not kind.startswith("$any") and kind != "$initstate"
                    and "CLK" not in cell["connections"], "Unexpected hidden state: "+kind)
            continue
        require(cell["connections"]["CLK"] == module["ports"]["clk"]["bits"] and
                int(cell["parameters"]["CLK_POLARITY"], 2) == 1, "Original positive clock")
        q, d = cell["connections"]["Q"], cell["connections"]["D"]
        require(len(q) == len(d), "State Q/D width")
        for qb, db in zip(q, d):
            labels = sorted(aliases.get(qb, []))
            require(isinstance(qb, int) and qb not in used and labels and len(init.get(qb, set())) <= 1,
                    "State identity/init bijection")
            used.add(qb)
            states.append(dict(identity=labels, init=next(iter(init.get(qb, set())), "x"), q=qb, d=db))
        remove.append(name)
    require(len(states) >= 192, "Complete cheat state required")
    states.sort(key=lambda x: json.dumps(x["identity"]))
    identities = [json.dumps(x["identity"]) for x in states]
    require(len(set(identities)) == len(states), "Unique named state identities")
    for name in remove:
        del module["cells"][name]
    module["ports"]["__state"] = dict(direction="input", bits=[x["q"] for x in states])
    module["ports"]["__next"] = dict(direction="output", bits=[x["d"] for x in states])
    # Initial attributes are recorded above, not turned into assumptions on the cut state.
    for net in module["netnames"].values():
        net.get("attributes", {}).pop("init", None)
    design["modules"] = {model_name: module}
    write(output, design)
    return [dict(identity=x["identity"], init=x["init"]) for x in states], module["ports"]

def inspect_container(info, name, phase, running=None):
    require(len(info) == 1, "One owned container")
    c = info[0]; expected = native_spec(phase)
    require(c["Name"] == "/"+name and c["Image"] == IMAGE and
            c["Config"]["Entrypoint"] == ["/bin/bash"] and c["Config"]["Cmd"] == expected and
            c["Config"]["User"] == "0:0" and c["Config"]["WorkingDir"] == "/work", "Exact owned native command")
    require(c["HostConfig"]["NetworkMode"] == "bridge", "Native license bridge")
    if c["State"]["Running"]:
        require(c["NetworkSettings"]["Networks"]["bridge"]["MacAddress"] == MAC, "Actual live licensed MAC")
    mounts = c["Mounts"]
    require(len(mounts) == 1 and mounts[0]["Destination"] == "/work" and mounts[0]["RW"] is True and
            mounts[0]["Source"] == os.environ["GITHUB_WORKSPACE"], "Only exact checkout mount")
    env = dict(x.split("=",1) for x in c["Config"]["Env"])
    require(env["IGNORE_TIMING"] == "0" and env["ISE_CTABLE"] == "" and
            not any(x.startswith("MAKE") or x == "XILINX_PART" for x in env), "No inherited build controls")
    require(env.get("XIL_TIMING_HOLDCHECKING") == ("YES" if phase=="hold" else None), "Explicit separate hold analysis")
    if running is not None:
        require(c["State"]["Running"] is running, "Actual process lifecycle")
    return c

def container(out, phase):
    out = Path(out); name = "basex-"+phase+"-"+os.environ["GITHUB_RUN_ID"]+"-"+os.environ["GITHUB_RUN_ATTEMPT"]
    require(re.fullmatch("[a-z0-9-]+", name), "Owned name")
    require(not subprocess.check_output(["docker","ps","-aq","--filter","name=^/"+name+"$"]).strip(),
            "No duplicate owned container")
    command(["docker","image","inspect",IMAGE],out/(phase+"-image"))
    argv = ["docker","create","--name",name,"--user","0:0","--network","bridge","--mac-address",MAC,
            "--volume",os.environ["GITHUB_WORKSPACE"]+":/work","--workdir","/work",
            "--env","IGNORE_TIMING=0","--env","ISE_CTABLE=","--entrypoint","/bin/bash"]
    if phase=="hold": argv += ["--env","XIL_TIMING_HOLDCHECKING=YES"]
    argv += [IMAGE,*native_spec(phase)]
    command(argv,out/(phase+"-create"))
    command(["docker","start",name],out/(phase+"-start"))
    # Observe the actual licensed interface while this owned process is live.
    live = json.loads(subprocess.check_output(["docker","inspect",name]))
    write(out/(phase+"-started.json"),live)
    inspect_container(live,name,phase,True)
    command(["docker","logs","--follow",name],out/(phase+"-build"),timeout=21600)
    command(["docker","wait",name],out/(phase+"-wait"))
    done = json.loads(subprocess.check_output(["docker","inspect",name]))
    write(out/(phase+"-finished.json"),done)
    c = inspect_container(done,name,phase,False)
    require(not c["State"]["OOMKilled"] and not c["State"]["Error"], "No native OOM/runtime error")
    rc = c["State"]["ExitCode"]
    require(read(out/(phase+"-wait.stdout.log")).strip() == str(rc).encode(), "Docker wait/native status binding")
    write(out/(phase+"-exit.json"),dict(exit=rc,phase=phase,name=name,originalFailurePreserved=True))
    # Keep the complete inspect evidence and remove only this completed exact container.
    command(["docker","rm",name],out/(phase+"-remove"))
    require(rc == 0, "Actual "+phase+" process failed with exit "+str(rc))

def collect(out):
    out = Path(out); root = Path("verilog/sd2snes_basex")
    target = out/"native-reports";target.mkdir()
    rows = []
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix in REPORTS:
            require(not f.is_symlink(), "Regular native report")
            b = read(f); require(len(b) <= 3_000_000,"Native text cap")
            write(target/f.name,b)
            rows.append(dict(path=f.name,bytes=len(b),sha256=sha(b)))
    write(target/"report-index.json",rows)

def parse_timing(par, twr):
    scores = re.findall(r"Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)",par)
    totals = re.findall(r"Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)",twr)
    require(len(scores)==len(totals)==1,"Exactly one complete timing summary")
    slack = {"setup":[],"hold":[],"other":[]}
    for line in twr.splitlines():
        if line.lstrip().startswith("Slack"):
            m = re.match(r"\s*Slack(?:\s+\((setup|hold) path\))?:\s*([+-]?\d+(?:\.\d+)?)ns\b",line)
            require(m is not None,"Every displayed slack parsed")
            slack[m[1] or "other"].append(float(m[2]))
    require(slack["setup"] and slack["hold"],"Actual setup and hold records")
    return dict(parScore=int(scores[0][0]),setupScore=int(scores[0][1]),holdScore=int(scores[0][2]),
                componentScore=int(scores[0][3]),traceErrors=int(totals[0][0]),traceScore=int(totals[0][1]),
                traceSetupScore=int(totals[0][2]),traceHoldScore=int(totals[0][3]),
                fullyRouted="All signals are completely routed." in par,
                slack={k:dict(records=len(v),negative=sum(x<0 for x in v),minimumNs=min(v) if v else None)
                       for k,v in slack.items()})

def timing_clean(parsed):
    return (parsed["fullyRouted"] and all(parsed[k]==0 for k in
            ("parScore","setupScore","holdScore","componentScore","traceErrors","traceScore",
             "traceSetupScore","traceHoldScore")) and
            all(v["negative"]==0 for v in parsed["slack"].values()))

def union(out):
    root=Path(out);seen=set();rows=[];total=0
    # Preserve large generated proof JSON losslessly as bounded text parts.
    # Original byte count and SHA bind the complete ordered reconstruction.
    for path in sorted(x for x in root.rglob("*") if x.is_file() and x.suffix in (".json", ".log")):
        if path.stat().st_size > 3_000_000:
            raw=read(path);require(len(raw)<=32_000_000,"Generated proof JSON cap")
            parts=[]
            for offset in range(0,len(raw),1_000_000):
                part=path.with_name(path.name+".part-%03d.txt"%(offset//1_000_000))
                data=raw[offset:offset+1_000_000]
                write(part,data);parts.append(dict(path=part.name,bytes=len(data),sha256=sha(data)))
            write(path.with_name(path.name+".parts-index.json"),
                  dict(original=path.name,bytes=len(raw),sha256=sha(raw),orderedParts=parts))
            require(b"".join(read(path.with_name(x["path"])) for x in parts)==raw,"Lossless JSON parts")
            path.unlink()
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(),"No evidence symlinks")
        if path.is_file():
            rel=path.relative_to(root).as_posix();require(rel.casefold() not in seen,"Unique safe paths")
            seen.add(rel.casefold());raw=read(path)
            require(path.suffix not in (".vvp",".ncd",".ngc",".ngd",".bit",".bin",".rom",".xdl",".zip"),
                    "No native executable/design in text artifact")
            require(len(raw)<=3_000_000,"Per-text-file cap")
            total+=len(raw);require(total<=112_000_000 and len(rows)<1024,"Aggregate/count evidence cap")
            rows.append(dict(path=rel,bytes=len(raw),sha256=sha(raw)))
    write(root/"text-union.json",dict(files=rows,bytes=total,fileCount=len(rows)))

def proof_design(out, destination):
    root=Path(out);dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
    names={"post-proc.json","constant-init.json","state.json","transition.json",
           "miter-binary.json","miter-xstate.json","miter-before-binary.json","miter-before-xstate.json"}
    rows=[];total=0
    for path in sorted(root.rglob("*.json")):
        if path.name not in names:continue
        require(not path.is_symlink(),"Regular formal graph")
        raw=read(path);require(len(raw)<=64_000_000,"Per-formal-graph bound")
        total+=len(raw);require(total<=1_000_000_000 and len(rows)<64,"Formal graph union bound")
        rel=path.relative_to(root);target=dest/rel
        target.parent.mkdir(parents=True,exist_ok=True);require(not target.exists(),"Unique formal graph")
        shutil.move(str(path),str(target))
        require(sha(read(target))==sha(raw),"Byte-exact retained formal graph")
        rows.append(dict(path=rel.as_posix(),bytes=len(raw),sha256=sha(raw),retainedOnGitHubOnly=True))
    write(root/"formal-graph-index.json",dict(files=rows,bytes=total,completeGraphsRetainedOnGitHub=True))
    write(dest/"formal-graph-index.json",dict(files=rows,bytes=total))


def candidate(original, kind):
    text=original
    for piece in FRAGMENTS[kind]:
        require(text.count(piece["old"])==1,"Unique reviewed "+kind+" source boundary")
        text=text.replace(piece["old"],piece["new"],1)
    if kind=="cheat":text+=FRAGMENTS["cheatSuffix"]
    recovered=text
    if kind=="cheat":
        require(recovered.endswith(FRAGMENTS["cheatSuffix"]),"Exact private helper suffix")
        recovered=recovered[:-len(FRAGMENTS["cheatSuffix"])]
    for piece in reversed(FRAGMENTS[kind]):
        require(recovered.count(piece["new"])==1,"Unique full-source inverse")
        recovered=recovered.replace(piece["new"],piece["old"],1)
    require(recovered==original,"Complete source inverse")
    return text

def contract(out):
    out=Path(out)
    require(git("rev-parse","HEAD").decode().strip()==os.environ["GITHUB_SHA"],"Source head")
    require(git("rev-parse","HEAD^").decode().strip()==BASE,"Exact accepted production parent")
    paths={"verilog/sd2snes_base/main.v","verilog/sd2snes_base/cheat.v",SELF,WORKFLOW}
    require(set(git("diff","--name-only",BASE,"HEAD").decode().splitlines())==paths,"Exact four-file scope")
    pins={"main":"5775ff4f4ef3b0118e2a347b17c386c208f5618c","cheat":"dfc2f4fe2dc21fdd07da735fa1cd57a7aa6f4f3f"}
    for kind,pin in pins.items():
        name="verilog/sd2snes_base/"+kind+".v"
        raw=git("show",BASE+":"+name)
        require(hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==pin,"Original source pin")
        require(read(name)==candidate(raw.decode(),kind).encode(),"Exact source and private scope")
    for name in ("verilog/common.mk",".github/scripts/build.sh","verilog/sd2snes_basex/Makefile",
                 "verilog/sd2snes_base/main.ucf","verilog/sd2snes_basex/sd2snes_basex.xise",
                 "verilog/sd2snes_base/config.vh"):
        require(read(name)==git("show",BASE+":"+name),"Unchanged native/constraint input: "+name)
    require(not Path("verilog/settings.local").exists() and not Path("verilog/sd2snes_basex/ucf.extra").exists(),
            "No settings or timing override")
    write(out/"source-contract.json",dict(head=os.environ["GITHUB_SHA"],base=BASE,
          files=[dict(path=n,bytes=len(read(n)),sha256=sha(read(n)))for n in sorted(paths)],
          fullMainAndCheatInverse=True,scope="MK2 && BASE_EXT only",featuresRemoved=False,
          constraintsRelaxed=False,secondIndependentReviewer=False))

def tokens(text):
    text=re.sub(r"^\s*\x60line[^\n]*","",text,flags=re.M)
    items=re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|\s+|.',text,re.S)
    return [x for x in items if not x.isspace() and not x.startswith(("//","/*"))]

def history_expressions(source):
    forms={
        "initial_history":r"reg \[7:0\] SNES_WRITEr = ([^;]+);",
        "shift":r"SNES_WRITEr <= ([^;]+);",
        "initial_flags":r"reg \[1:0\] basex_wr_halves = ([^;]+);",
        "low_next":r"basex_wr_halves\[0\] <= ([^;]+);",
        "high_next":r"basex_wr_halves\[1\] <= ([^;]+);",
        "old_strobe":r"wire SNES_WR_end = ([^;]+);"}
    result={}
    for name,pattern in forms.items():
        values=re.findall(pattern,source)
        require(len(values)==1,"Unique actual history source expression: "+name)
        result[name]=values[0]
    return result

def history_unit(expr):
    low=expr["low_next"].replace("SNES_WRITEr","history")
    high=expr["high_next"].replace("SNES_WRITEr","history")
    shift=expr["shift"].replace("SNES_WRITEr","history")
    old=expr["old_strobe"].replace("SNES_WRITEr","history")
    return """module relation(input [7:0] history,input SNES_WRITE_IN,output ok);
localparam [7:0] initial_history = @INIT@;
localparam [1:0] initial_flags = @FLAGS@;
wire [7:0] next_history = @SHIFT@;
wire [1:0] next_flags = {@HIGH@,@LOW@};
wire [1:0] current_flags = {(history[6:4] == 3'b000),(history[3:1] == 3'b001)};
wire init_ok=(initial_flags === {(initial_history[6:4] == 3'b000),(initial_history[3:1] == 3'b001)});
wire step_ok=(next_flags === {(next_history[6:4] == 3'b000),(next_history[3:1] == 3'b001)});
wire observation_ok=(((&current_flags) === 1'b1) === ((@STROBE@) === 1'b1));
assign ok=init_ok & step_ok & observation_ok;
endmodule
""".replace("@INIT@",expr["initial_history"]).replace("@FLAGS@",expr["initial_flags"]).replace(
        "@SHIFT@",shift).replace("@HIGH@",high).replace("@LOW@",low).replace("@STROBE@",old)

def history_simulation(expr):
    return """module history(input CLK2,input SNES_WRITE_IN,output SNES_WR_end,
output [1:0] flags,output [7:0] hist);
reg [7:0] SNES_WRITEr = @INIT@;
reg [1:0] basex_wr_halves = @FLAGS@;
always @(posedge CLK2) begin
 SNES_WRITEr <= @SHIFT@;
 basex_wr_halves[0] <= @LOW@;
 basex_wr_halves[1] <= @HIGH@;
end
assign SNES_WR_end = @STROBE@;
assign flags=basex_wr_halves;assign hist=SNES_WRITEr;
endmodule
""".replace("@INIT@",expr["initial_history"]).replace("@FLAGS@",expr["initial_flags"]).replace(
        "@SHIFT@",expr["shift"]).replace("@LOW@",expr["low_next"]).replace(
        "@HIGH@",expr["high_next"]).replace("@STROBE@",expr["old_strobe"])

def cheat_miter(ports):
    ins=["input [7:0] __history"];wires=[];outputs=[];arguments={"gold":[],"gate":[]}
    for name,port in ports.items():
        dim="" if len(port["bits"])==1 else "["+str(len(port["bits"])-1)+":0] "
        if port["direction"]=="input":
            if name=="SNES_wr_strobe":
                for side in arguments:arguments[side].append("."+name+"(__original_strobe)")
            else:
                ins.append("input "+dim+name)
                for side in arguments:arguments[side].append("."+name+"("+name+")")
        else:
            require(port["direction"]=="output","No inout at complete cheat boundary")
            outputs.append(name)
            for side in arguments:
                wires.append("wire "+dim+side+"_"+name+";")
                arguments[side].append("."+name+"("+side+"_"+name+")")
    arguments["gate"].append(".basex_wr_halves(__current_halves)")
    return ("module miter("+",".join(ins+["output ok"])+");\n"+
      "wire __original_strobe=(__history[6:1]==6'b000001);\n"+
      "wire [1:0] __current_halves={(__history[6:4]==3'b000),(__history[3:1]==3'b001)};\n"+
      "\n".join(wires)+"\ngold g("+",".join(arguments["gold"])+");\ngate c("+
      ",".join(arguments["gate"])+");\nassign ok=({"+",".join("gold_"+x for x in outputs)+
      "} === {"+",".join("gate_"+x for x in outputs)+"});\nendmodule\n")

def proof(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    originals={kind:git("show",BASE+":verilog/sd2snes_base/"+kind+".v").decode()for kind in ("main","cheat")}
    gates={kind:read("verilog/sd2snes_base/"+kind+".v").decode()for kind in ("main","cheat")}
    for kind in originals:require(gates[kind]==candidate(originals[kind],kind),"Actual complete candidate")
    for side,sources in (("gold",originals),("gate",gates)):
        for kind,source in sources.items():write(out/(side+"-"+kind+".v"),source)
    profiles={"mk2-basex":["MK2","BASE_EXT"],"mk2-base":["MK2"],"mk2-bootleg":["MK2","BOOTLEG"],
              "mk2-atari":["MK2","ATARI"],"mk3-base":["MK3"],"mk3-basex":["MK3","BASE_EXT"],
              "mk3-bootleg":["MK3","BOOTLEG"]}
    scope=[]
    for profile,defines in profiles.items():
        for kind in ("main","cheat"):
            versions={}
            for side in ("gold","gate"):
                dest=out/(side+"-"+kind+"-"+profile+".v")
                argv=["iverilog","-g2012","-E","-Iverilog/sd2snes_base"]
                argv+=["-D"+x for x in defines]+["-o",str(dest),str(out/(side+"-"+kind+".v"))]
                command(argv,out/(side+"-"+kind+"-"+profile+"-preprocess"))
                versions[side]=tokens(read(dest).decode())
            equal=versions["gold"]==versions["gate"]
            require(equal==(profile!="mk2-basex"),"Actual target/non-target preprocessor scope")
            scope.append(dict(profile=profile,kind=kind,equalOriginalTokens=equal))
    write(out/"preprocessor-scope.json",scope)
    history_variants={"gate":gates["main"],
      "bad-init":gates["main"].replace("reg [1:0] basex_wr_halves = 2'b00;",
                                    "reg [1:0] basex_wr_halves = 2'b11;",1),
      "bad-shift":gates["main"].replace("basex_wr_halves[0] <= (SNES_WRITEr[2:0]",
                                      "basex_wr_halves[0] <= (SNES_WRITEr[3:1]",1)}
    hresults=[]
    tb="""module tb;
reg CLK2=0;reg SNES_WRITE_IN=0;wire strobe;wire [1:0] flags;wire [7:0] hist;
integer i,checks;history dut(CLK2,SNES_WRITE_IN,strobe,flags,hist);
task check;begin #1;
if(flags !== {(hist[6:4]==3'b000),(hist[3:1]==3'b001)} ||
((strobe === 1'b1) !== ((&flags) === 1'b1))) $fatal(1,"HISTORY_RELATION_MISMATCH check=%0d hist=%b flags=%b",checks,hist,flags);
checks=checks+1;end endtask
initial begin checks=0;check;
for(i=0;i<1024;i=i+1)begin
case(i%8)0,1,2:SNES_WRITE_IN=0;3,4,5:SNES_WRITE_IN=1;6:SNES_WRITE_IN=1'bx;7:SNES_WRITE_IN=1'bz;endcase
#1;CLK2=1;check;CLK2=0;
end
if(checks!=1025)$fatal(1,"Missing startup/edge checks");
$display("PASS history checks=1025 including initial state");$finish;end
endmodule
"""
    write(out/"history-tb.v",tb)
    for name,source in history_variants.items():
        require(name=="gate" or source!=gates["main"],"Real actual-source history mutation")
        prefix=out/("history-"+name)
        expr=history_expressions(source)
        write(str(prefix)+".source.v",source)
        write(str(prefix)+".expressions.json",expr)
        write(str(prefix)+".v",history_unit(expr))
        for mode in (("binary","xstate") if name=="gate" else ("binary",)):
            script=("read_verilog -sv -formal "+str(prefix)+".v; hierarchy -check -top relation; "
              "proc -ifx -noopt; opt_clean; check -assert; sat -verify -enable_undef "+
              ("-set-def-inputs " if mode=="binary" else "")+
              "-prove ok 1 -show-inputs -show-outputs -dump_json "+str(prefix)+"-"+mode+"-counterexample.json -timeout 180")
            rc=command(["yosys","-p",script],str(prefix)+"-"+mode,allowed=(0,1))
            log=read(str(prefix)+"-"+mode+".stdout.log")+read(str(prefix)+"-"+mode+".stderr.log")
            expected=name=="gate";require((rc==0)==expected,"Actual history SAT result")
            marker=b"SAT proof finished - no model found: SUCCESS!" if expected else b"SAT proof finished - model found: FAIL!"
            require(marker in log,"Real history SAT result, not preparation failure")
            if not expected:require(Path(str(prefix)+"-"+mode+"-counterexample.json").is_file(),"History witness")
            hresults.append(dict(variant=name,mode=mode,exit=rc,actualSatResult=True))
        write(str(prefix)+"-simulation.v",history_simulation(expr))
        executable=str(prefix)+".vvp"
        command(["iverilog","-g2012","-s","tb","-o",executable,str(prefix)+"-simulation.v",str(out/"history-tb.v")],
                str(prefix)+"-compile")
        rc=command(["vvp",executable],str(prefix)+"-run",allowed=(0,1));Path(executable).unlink()
        transcript=read(str(prefix)+"-run.stdout.log")+read(str(prefix)+"-run.stderr.log")
        require((rc==0)==(name=="gate"),"Actual startup simulation result")
        require((b"PASS history checks=1025 including initial state" if name=="gate" else
                 b"HISTORY_RELATION_MISMATCH")in transcript,"Complete actual startup checks/counterexample")
        if name=="bad-init":require(b"check=0" in transcript,"Bad initialization must fail at startup")
    write(out/"history-proof-result.json",dict(sat=hresults,actualGoodSimulationChecks=1025,
          noStartupCyclesSkipped=True,actualBadInitAndShiftSimulationRejected=True))

    source=gates["cheat"]
    bad_data=source.replace("cheat_data[0] <= pgm_in[7:0];","cheat_data[0] <= pgm_in[7:0] ^ 8'h01;",1)
    bad_reset=source.replace("if (reset) begin","if (1'b0) begin",1)
    bad_command=source.replace(" & unlocked & enabled) permit"," & unlocked) permit",1)
    old_permit="  permit = 1'b1;\n  if (low_half & high_half & unlocked & enabled) permit = 1'b0;"
    require(source.count(old_permit)==1,"Actual unknown-sensitive procedural guard")
    bad_x=source.replace(old_permit,
       "  permit = (low_half & high_half & unlocked & enabled) ? 1'b0 : 1'b1;",1)
    variants={"gold":originals["cheat"],"gate":source,"bad-data":bad_data,"bad-reset":bad_reset,
              "bad-command":bad_command,"bad-x":bad_x}
    for name,text in variants.items():require(name in ("gold","gate") or text!=source,"Real changed-source cheat mutation")
    reference,ports=None,None
    for name,text in variants.items():
        folder=out/name;folder.mkdir()
        write(folder/"source.v",text)
        argv=["iverilog","-g2012","-E","-DMK2","-DBASE_EXT","-o",str(folder/"preprocessed.v"),str(folder/"source.v")]
        command(argv,folder/"preprocess")
        script=("read_verilog -sv -formal "+str(folder/"preprocessed.v")+
           "; hierarchy -check -top cheat; flatten; proc -ifx -noopt; check -assert; "
           "write_json "+str(folder/"post-proc.json")+"; opt_expr -keepdc; "
           "write_json "+str(folder/"constant-init.json")+"; memory_memx; memory_collect; memory_map; "
           "dffunmap; setundef -undriven -undef; opt_clean; check -assert; write_json "+str(folder/"state.json"))
        command(["yosys","-p",script],folder/"prepare")
        inventory,current_ports=cut_state(folder/"state.json",folder/"transition.json","gold"if name=="gold"else"gate")
        write(folder/"state-inventory.json",inventory)
        for word in range(6):
            for field,width in (("cheat_addr",24),("cheat_data",8)):
                indices=[]
                for state in inventory:
                    indices += [label[1]for label in state["identity"]if label[0]==field+"["+str(word)+"]"]
                require(sorted(indices)==list(range(width)),"Every actual cheat array state bit retained")
        if name=="gold":reference,ports=inventory,current_ports
        else:
            require(inventory==reference,"Full cheat named Q/D/init/clock relation")
            filtered={k:v for k,v in current_ports.items()if k!="basex_wr_halves"}
            require({k:(v["direction"],len(v["bits"]))for k,v in filtered.items()}==
                    {k:(v["direction"],len(v["bits"]))for k,v in ports.items()},"Complete unchanged component interface")
            require(current_ports["basex_wr_halves"]["direction"]=="input"and
                    len(current_ports["basex_wr_halves"]["bits"])==2,"Only new private history port")
    write(out/"miter.v",cheat_miter(ports))
    results=[]
    for variant,modes in (("gate",("binary","xstate")),("bad-data",("binary",)),("bad-reset",("binary",)),
                          ("bad-command",("binary",)),("bad-x",("binary","xstate"))):
        for mode in modes:
            folder=out/variant;witness=folder/("counterexample-"+mode+".json")
            script=("read_json "+str(out/"gold/transition.json")+"; read_json "+str(folder/"transition.json")+
                    "; read_verilog -sv -formal "+str(out/"miter.v")+
                    "; hierarchy -check -top miter; flatten; opt_clean; check -assert; write_json "+
                    str(folder/("miter-before-"+mode+".json"))+"; "+
                    ("opt_merge -share_all -keepdc; opt_clean; "*16)+
                    "check -assert; write_json "+str(folder/("miter-"+mode+".json"))+
                    "; sat -verify -enable_undef "+("-set-def-inputs "if mode=="binary"else"")+
                    "-prove ok 1 -show-inputs -show-outputs -dump_json "+str(witness)+" -timeout 600")
            prefix=folder/("proof-"+mode);rc=command(["yosys","-p",script],prefix,timeout=1200,allowed=(0,1))
            expected=variant=="gate"or(variant=="bad-x"and mode=="binary")
            log=read(str(prefix)+".stdout.log")+read(str(prefix)+".stderr.log")
            require((rc==0)==expected,"Actual full-state proof/control status")
            require((b"SAT proof finished - no model found: SUCCESS!"if expected else
                     b"SAT proof finished - model found: FAIL!")in log,"Actual SAT proof/counterexample")
            if not expected:require(witness.exists()and witness.stat().st_size>0,"Real changed-source witness")
            results.append(dict(variant=variant,mode=mode,exit=rc,actualSatResult=True,expectedPass=expected))
    write(out/"proof-result.json",dict(head=os.environ["GITHUB_SHA"],fullCheatStateBits=len(reference),
          cheatArrayStateBits=192,completeCheatModuleAndOutputs=True,allNamedInitAndPosedgeClocksPreserved=True,
          strictBinaryAndXEquality=True,arbitrarySharedState=True,noResetEnableAlignmentAssumptions=True,
          historyInductiveRelationProved=True,actualHistorySimulationChecks=1025,noStartupCyclesSkipped=True,
          preprocessorProfiles=len(profiles),nonTargetTokensUnchanged=True,sat=results,
          historySat=hresults,hardwareQualified=False,mappedEquivalenceNotClaimed=True,secondIndependentReviewer=False))


def baseline(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    artifact = 13629706369
    for kind, endpoint in (("run","actions/runs/42507318034"),
                           ("jobs","actions/runs/42507318034/jobs?per_page=100"),
                           ("artifact","actions/artifacts/"+str(artifact))):
        raw = subprocess.check_output(["gh","api","repos/secprog/sd2snes/"+endpoint])
        write(out/(kind+"-api.json"), raw)
    a = json.loads(read(out/"artifact-api.json"))
    require(a["id"] == artifact and a["size_in_bytes"] == 206808 and
            a["digest"] == "sha256:5b7c04346bc5282b9aa573dcc6d01f22ee821ff9adf8952b93367f0ecf36b90f" and
            not a["expired"] and a["workflow_run"]["id"] == 42507318034, "Exact original report artifact")
    run = json.loads(read(out/"run-api.json"))
    require(run["head_sha"] == "31cecdc00d200691afe8a85a5ec6f8cc2924e92e" and run["run_attempt"] == 1
            and run["status"] == "completed", "Original build identity")
    jobs = json.loads(read(out/"jobs-api.json"))
    job = next(x for x in jobs["jobs"] if x["id"] == 128814120555)
    require(job["status"] == "completed" and job["conclusion"] == "success", "Original basex job remains success")
    raw = subprocess.check_output(["gh","api","repos/secprog/sd2snes/actions/artifacts/"+str(artifact)+"/zip"])
    require(len(raw) == a["size_in_bytes"] and "sha256:"+sha(raw) == a["digest"], "Complete original ZIP hash")
    import io
    total, seen, rows = 0, set(), []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [x for x in archive.infolist() if not x.is_dir()]
        expected_names={"_temp/fpga-build.log"}|{
            "sd2snes/sd2snes/verilog/sd2snes_basex/"+n for n in
            ("main.bld","main.bgn","main.par","main.syr","main.unroutes","main.twr","main_map.mrp","main_map.psr")}
        require(len(members)==9 and {x.filename for x in members}==expected_names,
                "Exact complete nine-file original report and build-log union")
        for entry in members:
            name = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            require(not name.is_absolute() and "\\" not in entry.filename and ":" not in entry.filename and
                    all(x not in ("",".","..") for x in name.parts) and
                    (mode & 0o170000) in (0, stat.S_IFREG), "Safe original regular path")
            require((name.suffix in REPORTS or entry.filename=="_temp/fpga-build.log") and
                    name.name.casefold() not in seen, "Expected unique original report/build log")
            seen.add(name.name.casefold())
            require(entry.file_size <= 3_000_000, "Original file cap")
            b = archive.read(entry)
            require(len(b) == entry.file_size and b"\0" not in b, "Original CRC/size/text")
            b.decode("utf-8")
            total += len(b); require(total <= 8_000_000, "Original aggregate cap")
            write(out/name.name, b)
            rows.append(dict(path=name.name,originalPath=entry.filename,bytes=len(b),sha256=sha(b)))
    pins = {"main.par":"18e44aed3bf134ec4e4f94932dadc9d36416e9b74f53f04073b181cf01cd2cb6",
            "main.twr":"fe84fb2699cae633c7ae0b3c7d8ab68fcae7f16518f189eb88530b3c81dc1db6",
            "main_map.mrp":"62570644ee0288e823573528463f83ba62412386cc4e8a1da29fd99e0e51d479"}
    pins["fpga-build.log"]="e5b46fc84355fada65583fbf3fef6270cce3093acdc016905bb61a993debd0f0"
    for name, pin in pins.items():
        require(sha(read(out/name)) == pin, "Byte-exact original report: "+name)
    write(out/"baseline-index.json",rows)
    controls(out)

def controls(out):
    out=Path(out)
    actual=parse_timing(read(out/"main.par").decode(),read(out/"main.twr").decode())
    require(actual['traceErrors']==124 and actual['slack']['setup']['minimumNs']==-0.827 and
            actual['slack']['hold']['negative']==0 and not timing_clean(actual),
            "Actual original basex setup failure must reject")
    par="All signals are completely routed.\nTiming Score: 0 (Setup: 0, Hold: 0, Component Switching Limit: 0)\n"
    twr="Slack (setup path): 0.028ns\nSlack (hold path): 0.433ns\nSlack: 0.000ns\nTiming errors: 0 Score: 0 (Setup/Max: 0, Hold: 0)\n"
    cases=[("synthetic-clean",par,twr,True),("actual-original-setup-failure",read(out/"main.par").decode(),read(out/"main.twr").decode(),False)]
    for name,key,old,new in [
      ("negative-setup","twr","0.028ns","-0.001ns"),
      ("negative-hold-with-zero-summary","twr","0.433ns","-3.216ns"),
      ("negative-plain","twr","0.000ns","-0.001ns"),
      ("par-setup","par","Setup: 0,","Setup: 1,"),
      ("par-hold","par","Hold: 0,","Hold: 1,"),
      ("par-component","par","Limit: 0","Limit: 1"),
      ("trace-errors","twr","Timing errors: 0","Timing errors: 1"),
      ("trace-score","twr","Score: 0 (","Score: 1 ("),
      ("trace-hold","twr","Hold: 0)","Hold: 1)"),
      ("unrouted","par","All signals are completely routed.","Not completely routed."),
      ("unknown-slack","twr","Slack: 0.000ns","Slack changed: 0.000ns"),
      ("missing-hold","twr","Slack (hold path): 0.433ns\n",""),
      ("missing-setup","twr","Slack (setup path): 0.028ns\n","")]:
        original=par if key=="par" else twr
        require(original.count(old)==1,"Unique report mutation")
        replacement=original.replace(old,new,1)
        cases.append((name,replacement if key=="par" else par,replacement if key=="twr" else twr,False))
    cases.extend([("duplicate-par",par+par,twr,False),("duplicate-trace",par,twr+twr,False)])
    rows=[]
    for name,p,t,expected in cases:
        error=None
        try: accepted=timing_clean(parse_timing(p,t))
        except ValueError as failure: accepted=False;error=str(failure)
        rows.append(dict(name=name,expected=expected,accepted=accepted,error=error,passed=accepted==expected))
    write(out/"strict-report-controls.json",dict(controls=rows,passed=all(x["passed"] for x in rows),
          actualOriginalReportIncluded=True,syntheticReportsAreNotTimingEvidence=True))
    require(all(x["passed"] for x in rows),"Adversarial strict report controls")


def native_spec(phase):
    require(phase=="native","Only one original native phase")
    return [".github/scripts/build.sh","mk2","basex"]

def freeze_ip(out,label):
    root=Path("verilog/sd2snes_base/ip/mk2/build")
    require(root.is_dir(),"Original isolated base IP products")
    rows=[]
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(),"Regular IP product")
        if path.is_file():
            raw=path.read_bytes()
            rows.append(dict(path=path.as_posix(),bytes=len(raw),sha256=sha(raw),mtimeNs=path.stat().st_mtime_ns))
    ips=("dac_buf","msu_databuf","snescmd_buf")
    require(all((root/(name+suffix)).is_file()for name in ips for suffix in (".ngc",".v")),"All three original base IPs")
    prj=read("verilog/sd2snes_basex/main.prj").decode()
    for name in ips:
        require(prj.count('verilog work "../sd2snes_base/ip/mk2/build/'+name+'.v"')==1,
                "Actual basex canonical isolated wrapper binding")
    write(Path(out)/("ip-"+label+".json"),rows)
    if label!="before":
        require(rows==json.loads(read(Path(out)/"ip-before.json")),"All base IP bytes/mtimes immutable")

def analyze(out,baseline_dir):
    out=Path(out);root=out/"native-reports"
    par,twr,mrp,pcf=(read(root/name).decode()for name in ("main.par","main.twr","main_map.mrp","main.pcf"))
    require([" ".join(x.split())for x in re.findall(r"^par .+$",par,re.M)]==[PAR],"Original single PAR/seed46")
    match=re.search(r"Command Line\s*:\s*(.*?)\s*Target Device",mrp,re.S)
    require(match and " ".join(match[1].split())==MAP,"Exact original MAP options/seed46")
    require(len(re.findall(r"/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr",twr))==1,
            "Original single TRACE invocation")
    expected={"TS_CLKIN":("CLKIN","24.01"),"TS_SPI_SCK":("SPI_SCK","48.1"),
              "TS_SNES_SYSCLK":("SNES_SYSCLK","21.5"),"TS_CLK21":("CLK21","96.04")}
    periods=re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;',pcf)
    require(len(periods)==4 and {n:(g,v)for n,g,v in periods}==expected,"All four original period requirements")
    require(set(re.findall(r"^(TS_\w+)\s*=",pcf,re.M))==set(expected),"No new/removed timing specification")
    require("SYSTEM_JITTER"not in pcf,"Preserve original basex PCF jitter specification")
    before=parse_timing(read(Path(baseline_dir)/"main.par").decode(),read(Path(baseline_dir)/"main.twr").decode())
    after=parse_timing(par,twr);native=json.loads(read(out/"native-exit.json"))
    native_log=read(out/"native-build.stdout.log")+read(out/"native-build.stderr.log")
    timing_only=(native["exit"]==2 and re.search(rb"\bError 55\b",native_log)is not None and after["fullyRouted"])
    no_worse=(after["fullyRouted"] and after["traceErrors"]<=before["traceErrors"] and
       after["slack"]["setup"]["minimumNs"]>=before["slack"]["setup"]["minimumNs"] and
       after["parScore"]<=before["parScore"] and after["holdScore"]==after["componentScore"]==0 and
       after["traceHoldScore"]==0 and after["slack"]["hold"]["negative"]==0 and
       after["slack"]["other"]["negative"]==0)
    better=(after["traceErrors"]<before["traceErrors"] or
       after["slack"]["setup"]["minimumNs"]>before["slack"]["setup"]["minimumNs"] or
       after["parScore"]<before["parScore"])
    improvement=no_worse and better and(native["exit"]==0 or timing_only)
    strict=native["exit"]==0 and timing_clean(after)
    write(out/"timing-result.json",dict(head=os.environ["GITHUB_SHA"],baseline=before,current=after,
      nativeExit=native["exit"],onlyOriginalTimingGateFailed=timing_only,measuredImprovement=improvement,
      strictTimingPassed=strict,allOriginalOptionsAndTimingRequirementsVerified=True,
      externalIoQualified=False,hardwareQualified=False,secondIndependentReviewer=False,
      limits="Reported internal timing comparison only; no all-I/O nonregression or hardware qualification claim."))
    print(json.dumps(json.loads(read(out/"timing-result.json")),indent=2))
    require(strict,"Strict basex timing remains failed; actual improvement separately retained")


if __name__=="__main__":
    mode,*args=sys.argv[1:]
    {"contract":contract,"proof":proof,"baseline":baseline,"freeze-ip":freeze_ip,
     "container":container,"collect":collect,"analyze":analyze,"union":union,
     "proof-design":proof_design}[mode](*args)
