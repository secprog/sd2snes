#!/usr/bin/env python3
"""GitHub-only ST0018 source proof and unchanged-constraint timing evidence."""
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

BASE = "4d0199bf639629284546858b2b92abcd840b48a9"
IMAGE = "sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8"
MAC = "08:00:27:68:c9:35"
CPU = "verilog/sd2snes_st0018/st018_cpu.v"
MAKE = "verilog/sd2snes_st0018/Makefile"
SELF = ".github/scripts/validate-st0018-mask-timing.py"
WORKFLOW = ".github/workflows/validate-dspx-stack-timing.yml"
OLD = "    else                 ctl_mask[31-ci] = (ci >= ctl_n);"
NEW = """    // Assign the same constant-unrolled destination in both branches.
    // Mirroring the comparison preserves the original complete 32-bit mask
    // without asking XST to combine complementary partial-vector writes.
    else                 ctl_mask[ci] = (31-ci >= ctl_n);"""
MAKE_OLD = "XIL_IPCORE_DIR = ip/mk2\n"
MAKE_NEW = MAKE_OLD + """
# Keep the original catalog immutable while CoreGen writes its products.
XIL_IP_INPUT_DIR := $(XIL_IPCORE_DIR)
XIL_IPCORE_DIR := $(XIL_IP_INPUT_DIR)/build
"""
MAP = ("map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 2 "
       "-register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy "
       "-pr b -power off -o main_map.ncd main.ngd main.pcf")
PAR = "par -w -ol high -xe n -t 2 main_map.ncd main.ncd main.pcf"
REPORTS = {".syr", ".par", ".mrp", ".psr", ".bld", ".bgn", ".twr", ".unroutes",
           ".pcf", ".xst", ".prj", ".ut", ".tsi", ".ucf"}

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

def contract(out):
    out = Path(out)
    require(git("rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"], "Checkout head")
    require(git("rev-parse", "HEAD^").decode().strip() == BASE, "Exact accepted parent")
    require(set(git("diff", "--name-only", BASE, "HEAD").decode().splitlines()) ==
            {CPU, MAKE, SELF, WORKFLOW}, "Exact four-file scope")
    original = git("show", BASE+":"+CPU)
    require(hashlib.sha1(b"blob "+str(len(original)).encode()+b"\0"+original).hexdigest() ==
            "893e7a1090d89856fe348a03565b8b9d3cdfd6d5", "Original full CPU pin")
    require(original.decode().count(OLD) == 1, "Original loop boundary")
    require(read(CPU) == original.decode().replace(OLD, NEW, 1).encode(), "Only reviewed mask rewrite")
    make = git("show", BASE+":"+MAKE).decode()
    require(make.count(MAKE_OLD) == 1 and read(MAKE) == make.replace(MAKE_OLD, MAKE_NEW, 1).encode(),
            "Only isolated original IP catalog change")
    require(not Path("verilog/settings.local").exists(), "No settings override")
    for name in ("verilog/common.mk", ".github/scripts/build.sh",
                 "verilog/sd2snes_st0018/main.ucf", "verilog/sd2snes_st0018/main.sdc",
                 "verilog/sd2snes_st0018/sd2snes_st0018.xise"):
        require(read(name) == git("show", BASE+":"+name), "Unchanged native/constraint input: "+name)
    rows = [dict(path=n, bytes=len(read(n)), sha256=sha(read(n))) for n in sorted({CPU, MAKE, SELF, WORKFLOW})]
    write(out/"source-contract.json", dict(head=os.environ["GITHUB_SHA"], parent=BASE, files=rows,
          completeCpuInverseVerified=True, constraintsAndOriginalNativeRecipeUnchanged=True,
          noRemovedFeatures=True, secondIndependentReviewer=False))

def cut_state(source, output, model_name):
    design = json.loads(read(source))
    require(set(design["modules"]) == {"st018_cpu"}, "Complete flattened CPU, no blackboxes")
    module = design["modules"]["st018_cpu"]
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
                    and kind != "$ff" and "CLK" not in cell["connections"], "Unexpected hidden state: "+kind)
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
    require(len(states) >= 1000, "Complete CPU and register file state required")
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

def miter_text(ports):
    ins, outs, wires, args = [], [], [], {"gold": [], "gate": []}
    for name, port in ports.items():
        require(re.fullmatch("[a-zA-Z_][a-zA-Z_0-9]*", name), "Simple top-level port")
        width = len(port["bits"])
        dimension = "" if width == 1 else "["+str(width-1)+":0] "
        if port["direction"] == "input":
            ins.append("input "+dimension+name)
            for side in args:
                args[side].append("."+name+"("+name+")")
        else:
            require(port["direction"] == "output", "No inout in CPU proof")
            outs.append(name)
            for side in args:
                wires.append("wire "+dimension+side+"_"+name+";")
                args[side].append("."+name+"("+side+"_"+name+")")
    return ("module miter("+", ".join(ins+["output ok"])+");\n"+"\n".join(wires)+"\n"+
            "gold g("+",".join(args["gold"])+");\ngate c("+",".join(args["gate"])+");\n"+
            "assign ok = ({"+",".join("gold_"+n for n in outs)+"} === {"+
            ",".join("gate_"+n for n in outs)+"});\nendmodule\n")

def proof(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    gold = git("show", BASE+":"+CPU).decode()
    gate = read(CPU).decode()
    require(gate == gold.replace(OLD, NEW, 1), "Exact complete source binding")
    bad_mask = gate.replace("ctl_mask[ci] = (31-ci >= ctl_n);", "ctl_mask[ci] = (30-ci >= ctl_n);", 1)
    require(bad_mask != gate, "Real mask corruption")
    bad_ce = gate.replace("always @(posedge clk) if (ce) begin",
                          "always @(posedge clk) if (1'b1) begin", 1)
    require(bad_ce != gate, "Real CPU enable corruption")
    variants = {"gold": gold, "gate": gate, "bad-mask": bad_mask, "bad-ce": bad_ce}
    reference, ports = None, None
    results = []
    for name, source in variants.items():
        folder = out/name
        folder.mkdir()
        write(folder/"source.v", source)
        prep = ("read_verilog -sv -formal "+str(folder/"source.v")+"; hierarchy -check -top st018_cpu; "
                "flatten; proc -ifx -noopt; check -assert; memory_memx; memory_collect; memory_map; "
                "dffunmap; setundef -undriven -undef; opt_clean; check -assert; write_json "+str(folder/"state.json"))
        command(["yosys", "-p", prep], folder/"prepare")
        inventory, current_ports = cut_state(folder/"state.json", folder/"transition.json",
                                              "gold" if name == "gold" else "gate")
        write(folder/"state-inventory.json", inventory)
        if reference is None:
            reference, ports = inventory, current_ports
        else:
            require(inventory == reference, "All named state/init/clock identities must match")
            require({k:(v["direction"],len(v["bits"])) for k,v in current_ports.items()} ==
                    {k:(v["direction"],len(v["bits"])) for k,v in ports.items()}, "Complete top-level ports")
    write(out/"miter.v", miter_text(ports))
    for variant, modes in (("gate", ("binary", "xstate")), ("bad-mask", ("binary",)), ("bad-ce", ("binary",))):
        for mode in modes:
            folder = out/variant
            witness = folder/("counterexample-"+mode+".json")
            script = ("read_json "+str(out/"gold/transition.json")+"; read_json "+str(folder/"transition.json")+
                      "; read_verilog -sv -formal "+str(out/"miter.v")+
                      "; hierarchy -check -top miter; flatten; opt_clean; check -assert; write_json "+
                      str(folder/("miter-"+mode+".json"))+
                      "; sat -verify -enable_undef "+("-set-def-inputs " if mode=="binary" else "")+
                      "-prove ok 1 -show-inputs -show-outputs -dump_json "+str(witness)+" -timeout 600")
            prefix = folder/("proof-"+mode)
            rc = command(["yosys", "-p", script], prefix, timeout=1200, allowed=(0,1))
            transcript = read(str(prefix)+".stdout.log")+read(str(prefix)+".stderr.log")
            positive = variant == "gate"
            require((rc == 0) == positive, "Expected real proof/negative status")
            marker = b"SAT proof finished - no model found: SUCCESS!" if positive else b"SAT proof finished - model found: FAIL!"
            require(marker in transcript, "Actual SAT result, not a tool/timeout failure")
            if not positive:
                require(witness.exists() and witness.stat().st_size > 0, "Real counterexample required")
            results.append(dict(variant=variant, mode=mode, exit=rc, expectedPass=positive,
                                actualSatResult=True, witness=not positive))
    # Exercise every binary mask input and each single-X/Z input bit in real Icarus.
    def loop(src):
        start = src.index("  for (ci = 0; ci < 32; ci = ci + 1) begin")
        end = src.index("\n  end", start)+len("\n  end")
        return src[start:end]
    bodies = {}
    for name in ("gold", "gate"):
        bodies[name] = ("module "+name+"(input [1:0] ctl_typ,input [5:0] ctl_n,output reg [31:0] ctl_mask);"
                        "integer ci; always @* begin\n"+loop(variants[name])+"\nend\nendmodule\n")
    write(out/"mask-models.v", bodies["gold"]+bodies["gate"])
    tb = """module tb;
reg [7:0] drive; wire [31:0] g,c; integer v,i,s,checks;
gold g0(drive[7:6],drive[5:0],g); gate c0(drive[7:6],drive[5:0],c);
task check; begin #1; checks=checks+1; if (g !== c) $fatal(1,"mask mismatch %b %b %b",drive,g,c); end endtask
initial begin checks=0;
for(v=0;v<256;v=v+1) begin
drive=v;check;
for(i=0;i<8;i=i+1) begin drive=v;drive[i]=1'bx;check;drive=v;drive[i]=1'bz;check;end
end
$display("PASS all %0d actual mask comparisons, binary and single X/Z perturbations",checks);$finish;end
endmodule
"""
    write(out/"mask-tb.v", tb)
    command(["iverilog","-g2012","-s","tb","-o",str(out/"mask-test.vvp"),
             str(out/"mask-models.v"),str(out/"mask-tb.v")], out/"mask-compile")
    command(["vvp",str(out/"mask-test.vvp")], out/"mask-run")
    require(b"PASS all 4352 actual mask comparisons" in read(out/"mask-run.stdout.log"), "All mask comparisons")
    # Do not upload executable simulation products in the text evidence.
    (out/"mask-test.vvp").unlink()
    write(out/"proof-result.json", dict(head=os.environ["GITHUB_SHA"], completeCpuStateBits=len(reference),
          completeCpuAndRegfile=True, arbitrarySharedState=True, strictXEquality=True, noResetOrEnableAssumptions=True,
          sat=results, actualMaskComparisons=4352, featuresPreservedAtSourceTransitionBoundary=True,
          mappedAndHardwareEquivalenceNotClaimed=True, secondIndependentReviewer=False))

def baseline(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    artifact = 13629075571
    for kind, endpoint in (("run","actions/runs/42507318034"),
                           ("jobs","actions/runs/42507318034/jobs?per_page=100"),
                           ("artifact","actions/artifacts/"+str(artifact))):
        raw = subprocess.check_output(["gh","api","repos/secprog/sd2snes/"+endpoint])
        write(out/(kind+"-api.json"), raw)
    a = json.loads(read(out/"artifact-api.json"))
    require(a["id"] == artifact and a["size_in_bytes"] == 196442 and
            a["digest"] == "sha256:0f2f4166e7c4aa19f67c73a38534359b4b4b540d4acade227124dbb2fa0b0dd3" and
            not a["expired"] and a["workflow_run"]["id"] == 42507318034, "Exact original report artifact")
    run = json.loads(read(out/"run-api.json"))
    require(run["head_sha"] == "31cecdc00d200691afe8a85a5ec6f8cc2924e92e" and run["run_attempt"] == 1
            and run["status"] == "completed", "Original build identity")
    jobs = json.loads(read(out/"jobs-api.json"))
    job = next(x for x in jobs["jobs"] if x["id"] == 128814120617)
    require(job["status"] == "completed" and job["conclusion"] == "success", "Original ST0018 job remains success")
    raw = subprocess.check_output(["gh","api","repos/secprog/sd2snes/actions/artifacts/"+str(artifact)+"/zip"])
    require(len(raw) == a["size_in_bytes"] and "sha256:"+sha(raw) == a["digest"], "Complete original ZIP hash")
    import io
    total, seen, rows = 0, set(), []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [x for x in archive.infolist() if not x.is_dir()]
        require(0 < len(members) <= 128, "Original bounded text files")
        for entry in members:
            name = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            require(not name.is_absolute() and "\\" not in entry.filename and ":" not in entry.filename and
                    all(x not in ("",".","..") for x in name.parts) and
                    (mode & 0o170000) in (0, stat.S_IFREG), "Safe original regular path")
            require(name.suffix in REPORTS and name.name.casefold() not in seen, "Expected unique text report")
            seen.add(name.name.casefold())
            require(entry.file_size <= 3_000_000, "Original file cap")
            b = archive.read(entry)
            require(len(b) == entry.file_size and b"\0" not in b, "Original CRC/size/text")
            b.decode("utf-8")
            total += len(b); require(total <= 8_000_000, "Original aggregate cap")
            write(out/name.name, b)
            rows.append(dict(path=name.name,bytes=len(b),sha256=sha(b)))
    pins = {"main.par":"008681226fa4aeac64678e2c834706cb7f9a184afe5de102acf884b85ab623aa",
            "main.twr":"bce081d7f76fd76ba24190aa5d4f63803a140fbe79310ace4cfaf9a3609ec832",
            "main_map.mrp":"774892db062fec77ec40caef448b2dbba01317b1db5c22b4544ddcefe6a2de5f"}
    for name, pin in pins.items():
        require(sha(read(out/name)) == pin, "Byte-exact original report: "+name)
    write(out/"baseline-index.json",rows)
    controls(out)

def freeze_ip(out, label):
    root = Path("verilog/sd2snes_st0018/ip/mk2/build")
    require(root.is_dir(), "Isolated original IP directory")
    rows = []
    for f in sorted(root.rglob("*")):
        require(not f.is_symlink(), "No product symlinks")
        if f.is_file():
            b = f.read_bytes()
            rows.append(dict(path=f.as_posix(),bytes=len(b),sha256=sha(b),mtimeNs=f.stat().st_mtime_ns))
    require(all((root/n).is_file() for n in ("snescmd_buf.ngc","snescmd_buf.v","coregen.cgc")), "Original single ST0018 IP")
    prj = read("verilog/sd2snes_st0018/main.prj").decode()
    require(prj.count('verilog work "ip/mk2/build/snescmd_buf.v"') == 1 and
            'verilog work "ip/mk2/snescmd_buf.v"' not in prj, "Actual generated wrapper binding")
    dest = Path(out)/("ip-"+label+".json")
    write(dest, rows)
    if label != "before":
        require(rows == json.loads(read(Path(out)/"ip-before.json")), "All original IP bytes and mtimes immutable")

def native_spec(phase):
    if phase == "ip":
        return ["-c","exec make -j2 -C verilog/sd2snes_st0018 main.prj HOST=LINUX XILINX_ENV= IGNORE_TIMING=0"]
    if phase == "native":
        return [".github/scripts/build.sh","mk2","st0018"]
    if phase == "hold":
        return ["-c","cd verilog/sd2snes_st0018 && exec /opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64/trce "
                "-v 10 -n 10 -u 10 -fastpaths main.ncd main.pcf -o main-hold-audit.twr"]
    raise ValueError("Fixed phase required")

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
    out = Path(out); name = "st0018-"+phase+"-"+os.environ["GITHUB_RUN_ID"]+"-"+os.environ["GITHUB_RUN_ATTEMPT"]
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
    out = Path(out); root = Path("verilog/sd2snes_st0018")
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

def controls(out):
    out=Path(out)
    actual=parse_timing(read(out/"main.par").decode(),read(out/"main.twr").decode())
    require(actual["parScore"]==actual["traceErrors"]==0 and
            actual["slack"]["hold"]["negative"]==97 and
            actual["slack"]["hold"]["minimumNs"]==-3.216 and not timing_clean(actual),
            "Real original unscored hold failure must reject")
    par="All signals are completely routed.\nTiming Score: 0 (Setup: 0, Hold: 0, Component Switching Limit: 0)\n"
    twr="Slack (setup path): 0.028ns\nSlack (hold path): 0.433ns\nSlack: 0.000ns\nTiming errors: 0 Score: 0 (Setup/Max: 0, Hold: 0)\n"
    cases=[("synthetic-clean",par,twr,True),("actual-original-unscored-hold",read(out/"main.par").decode(),read(out/"main.twr").decode(),False)]
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

def analyze(out, baseline_dir):
    out = Path(out); root = out/"native-reports"
    par,twr,mrp,pcf=(read(root/n).decode() for n in ("main.par","main.twr","main_map.mrp","main.pcf"))
    require([" ".join(x.split()) for x in re.findall(r"^par .+$",par,re.M)]==[PAR],
            "Original one PAR command/cost table")
    cmd = re.search(r"Command Line\s*:\s*(.*?)\s*Target Device",mrp,re.S)
    require(cmd and " ".join(cmd[1].split())==MAP, "Original MAP options")
    require(len(re.findall(r"/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr",twr))==1,
            "Original single TRACE command")
    expected={"TS_CLKIN":("CLKIN","24.01"),"TS_SPI_SCK":("SPI_SCK","48.1"),
              "TS_SNES_SYSCLK":("SNES_SYSCLK","21.5"),"TS_CLK21":("CLK21","96.04")}
    periods=re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;',pcf)
    require(len(periods)==4 and {n:(g,v) for n,g,v in periods}==expected,"All original period values")
    require(set(re.findall(r"^(TS_\w+)\s*=",pcf,re.M))==set(expected)|{"TS_ST018_CORE"},"All original timing groups")
    require(re.search(r'TS_ST018_CORE = MAXDELAY FROM TIMEGRP "ST018_CORE" TO TIMEGRP "ST018_CORE" TS_CLKIN \* 2;',pcf),
            "Unchanged original ST018 half-rate exception")
    require("SYSTEM_JITTER" not in pcf,"Original ST0018 has no SYSTEM_JITTER statement")
    b = Path(baseline_dir)
    before=parse_timing(read(b/"main.par").decode(),read(b/"main.twr").decode())
    after=parse_timing(par,twr)
    native=json.loads(read(out/"native-exit.json"))
    totals=re.search(r"Number of Slice Flip Flops:\s*([\d,]+)",mrp)
    ff=re.search(r"Number used as Flip Flops:\s*([\d,]+)",mrp)
    latch=re.findall(r"Number used as Latches:\s*([\d,]+)",mrp)
    no_latches=bool(totals and ff and totals[1]==ff[1] and all(int(x.replace(",",""))==0 for x in latch))
    hold = None
    if (root/"main-hold-audit.twr").exists():
        hold=parse_timing(par,read(root/"main-hold-audit.twr").decode())
        require(json.loads(read(out/"hold-exit.json"))["exit"]==0,"Direct separate hold TRACE exit")
    improvement=(after["fullyRouted"] and no_latches and after["traceErrors"]<=before["traceErrors"] and
                 after["parScore"]<=before["parScore"] and after["holdScore"]<=before["holdScore"] and
                 after["componentScore"]==0 and after["slack"]["setup"]["negative"]==0 and
                 after["slack"]["other"]["negative"]==0 and
                 after["slack"]["hold"]["minimumNs"]>before["slack"]["hold"]["minimumNs"])
    strict=(native["exit"]==0 and no_latches and timing_clean(after) and
            hold is not None and timing_clean(hold))
    write(out/"timing-result.json",dict(head=os.environ["GITHUB_SHA"],baseline=before,current=after,
          additionalHoldAnalysis=hold,nativeExit=native["exit"],allOriginalConstraintsVerified=True,
          completeMappedLatchCountZero=no_latches,measuredImprovement=improvement,strictTimingPassed=strict,
          setupPositiveMarginMayChange=after["slack"]["setup"]["minimumNs"],
          externalIoQualified=False,hardwareQualified=False,secondIndependentReviewer=False))
    print(json.dumps(json.loads(read(out/"timing-result.json")),indent=2))
    require(strict,"Strict timing remains failed; actual improvement retained separately")

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

if __name__ == "__main__":
    mode,*args=sys.argv[1:]
    {"contract":contract,"proof":proof,"baseline":baseline,"freeze-ip":freeze_ip,
     "container":container,"collect":collect,"analyze":analyze,"union":union}[mode](*args)

