#!/usr/bin/env python3
"""GitHub-only complete BSX state proof and capture-aligned window timing."""
import copy,hashlib,json,os,re,shutil,stat,subprocess,sys,time,zipfile
from pathlib import Path,PurePosixPath
if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("GitHub-hosted execution only")
BASE="0e5e537c2ab67d9825d67925e6419c9fc4cd890d"
BASELINE_HEAD="724608f26ed19a605cf5477ac156c9d4f6373579"
SOURCE="verilog/sd2snes_base/bsx.v"
SELF=".github/scripts/validate-basex-window-predecode.py"
WORKFLOW=".github/workflows/validate-dspx-stack-timing.yml"
IMAGE="sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8"
MAC="08:00:27:68:c9:35"
MAP=("map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 46 "
     "-register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy "
     "-pr b -bp -power off -o main_map.ncd main.ngd main.pcf")
PAR="par -w -ol high -xe c -t 46 main_map.ncd main.ncd main.pcf"
REPORTS={".syr",".par",".mrp",".psr",".bld",".bgn",".twr",".unroutes",
         ".pcf",".xst",".prj",".ut",".tsi",".ucf"}
FRAGMENTS=json.loads(r'''{
  "base": "0e5e537c2ab67d9825d67925e6419c9fc4cd890d",
  "source": "verilog/sd2snes_base/bsx.v",
  "old": "wire base_enable = feat_bs_base_enable\n                   & (use_bsx) && (!snes_addr[22] && (snes_addr[15:0] >= 16'h2188)\n                                 && (snes_addr[15:0] <= 16'h219f));",
  "new": "`ifdef MK2\n`ifdef BASE_EXT\n// BASEX_WINDOW_PREDECODE_BEGIN\n// Capture the original window predicate alongside the original address.\n// Feature/use qualifiers stay after this stage and keep their original priority.\n(* KEEP=\"TRUE\" *) wire bsx_base_window_d = (!snes_addr_in[22] && (snes_addr_in[15:0] >= 16'h2188)\n                                 && (snes_addr_in[15:0] <= 16'h219f));\n(* KEEP=\"TRUE\" *) reg bsx_base_window_q;\nalways @(posedge clkin) bsx_base_window_q <= bsx_base_window_d;\nwire base_enable = feat_bs_base_enable & (use_bsx) && bsx_base_window_q;\n// BASEX_WINDOW_PREDECODE_END\n`else\nwire base_enable = feat_bs_base_enable\n                   & (use_bsx) && (!snes_addr[22] && (snes_addr[15:0] >= 16'h2188)\n                                 && (snes_addr[15:0] <= 16'h219f));\n`endif\n`else\nwire base_enable = feat_bs_base_enable\n                   & (use_bsx) && (!snes_addr[22] && (snes_addr[15:0] >= 16'h2188)\n                                 && (snes_addr[15:0] <= 16'h219f));\n`endif",
  "target": "// BASEX_WINDOW_PREDECODE_BEGIN\n// Capture the original window predicate alongside the original address.\n// Feature/use qualifiers stay after this stage and keep their original priority.\n(* KEEP=\"TRUE\" *) wire bsx_base_window_d = (!snes_addr_in[22] && (snes_addr_in[15:0] >= 16'h2188)\n                                 && (snes_addr_in[15:0] <= 16'h219f));\n(* KEEP=\"TRUE\" *) reg bsx_base_window_q;\nalways @(posedge clkin) bsx_base_window_q <= bsx_base_window_d;\nwire base_enable = feat_bs_base_enable & (use_bsx) && bsx_base_window_q;\n// BASEX_WINDOW_PREDECODE_END",
  "windowExpression": "(!snes_addr[22] && (snes_addr[15:0] >= 16'h2188)\n                                 && (snes_addr[15:0] <= 16'h219f))",
  "windowDataExpression": "(!snes_addr_in[22] && (snes_addr_in[15:0] >= 16'h2188)\n                                 && (snes_addr_in[15:0] <= 16'h219f))",
  "addressCapture": "reg [23:0] snes_addr; always @(posedge clkin) snes_addr <= snes_addr_in;",
  "originalSha256": "41c7a1a6cff15df59c8e872e8d9ff6ad1f4ce26d371e439e053875cafa23f100",
  "candidateSha256": "ee1ef0c621db82804fce9c6916a73e9453e9513d1395d52c4d3dc4ed5613f19b"
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

def tokens(text):
    text=re.sub(r"^\s*\x60line[^\n]*","",text,flags=re.M)
    items=re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|\s+|.',text,re.S)
    return [x for x in items if not x.isspace() and not x.startswith(("//","/*"))]

def require_sat_result(rc,transcript,witness,positive):
    require(rc==(0 if positive else 1),"Exact real SAT/verify exit")
    if positive:
        require(b"SAT proof finished - no model found: SUCCESS!" in transcript,
                "Actual positive SAT result, not a preparation/timeout error")
        return
    witness=Path(witness)
    require(witness.is_file() and witness.stat().st_size>0,"Real changed-source counterexample")
    data=json.loads(read(witness))
    output=[x for x in data["signal"] if x.get("name","").lstrip("\\")=="ok"]
    require(len(output)==1 and output[0].get("wave","").startswith("0"),
            "Counterexample records actual failed output ok=0")
    require(b"Solving problem with" in transcript and
            (b"SAT proof finished - model found: FAIL!" in transcript or
             b"ERROR: Called with -verify and proof did fail!" in transcript),
            "Actual solver counterexample/verify failure, never a generic tool error or timeout")

def native_spec(phase):
    require(phase=="native","Only one original native phase")
    return [".github/scripts/build.sh","mk2","basex"]

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

def parse_timing(par, twr):
    scores = re.findall(r"Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)",par)
    totals = re.findall(r"Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)",twr)
    require(len(scores)==len(totals)==1,"Exactly one complete timing summary")
    slack = {"setup":[],"hold":[],"other":[]}
    for line in twr.splitlines():
        if line.lstrip().startswith("Slack"):
            m = re.match(r"\s*Slack(?:\s+\((setup|hold) paths?\))?:\s*([+-]?\d+(?:\.\d+)?)ns\b",line)
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
    require(actual['traceErrors']==93 and actual['slack']['setup']['minimumNs']==-0.935 and
            actual['slack']['hold']['negative']==0 and not timing_clean(actual),
            "Actual adopted basex setup failure must reject")
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
    plural=twr.replace("(setup path)","(setup paths)").replace("(hold path)","(hold paths)")
    cases.extend([("plural-clean",par,plural,True),
                  ("plural-negative-setup",par,plural.replace("0.028ns","-0.001ns"),False),
                  ("plural-negative-hold",par,plural.replace("0.433ns","-0.001ns"),False),
                  ("malformed-plural",par,plural.replace("setup paths","setup pathsx"),False)])
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
    normalized_pcf=" ".join(pcf.split())
    periods=re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;',normalized_pcf)
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
      fewerSetupViolations=after["traceErrors"]<before["traceErrors"],
      betterWorstSetupSlack=after["slack"]["setup"]["minimumNs"]>before["slack"]["setup"]["minimumNs"],
      lowerTimingScore=after["parScore"]<before["parScore"],
      strictTimingPassed=strict,allOriginalOptionsAndTimingRequirementsVerified=True,
      externalIoQualified=False,hardwareQualified=False,secondIndependentReviewer=False,
      limits="Reported internal timing comparison only; no all-I/O nonregression or hardware qualification claim."))
    print(json.dumps(json.loads(read(out/"timing-result.json")),indent=2))
    require(strict,"Strict basex timing remains failed; actual improvement separately retained")

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


def baseline(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    artifact=14129330927;run_id=43631625384;job_id=132559457792
    metadata={}
    for kind,endpoint in(("run","actions/runs/"+str(run_id)),
                          ("jobs","actions/runs/"+str(run_id)+"/jobs?per_page=100"),
                          ("artifact","actions/artifacts/"+str(artifact))):
        raw=subprocess.check_output(["gh","api","repos/secprog/sd2snes/"+endpoint])
        write(out/(kind+"-api.json"),raw);metadata[kind]=json.loads(raw)
    a=metadata["artifact"];run=metadata["run"]
    require(a["id"]==artifact and a["name"]=="basex-normal-unshared-current-complete-native-reports"and
            a["size_in_bytes"]==1324287 and
            a["digest"]=="sha256:6371064285efff8fd15c297e387be763e1cf61583c64b1978cf66ceec02d1d38"and
            not a["expired"]and a["workflow_run"]["id"]==run_id and a["workflow_run"]["head_sha"]==BASELINE_HEAD,
            "Exact adopted baseline text artifact")
    require(run["head_sha"]==BASELINE_HEAD and run["run_attempt"]==1 and
            run["status"]=="completed"and run["conclusion"]=="failure","Preserve actual failed baseline status")
    job=next(x for x in metadata["jobs"]["jobs"]if x["id"]==job_id)
    require(job["status"]=="completed"and job["conclusion"]=="failure","Actual baseline timing job failed")
    require(git("rev-parse",BASE+":verilog")==git("rev-parse",BASELINE_HEAD+":verilog"),
            "Adopted baseline complete production Verilog identity")
    raw=subprocess.check_output(["gh","api","repos/secprog/sd2snes/actions/artifacts/"+str(artifact)+"/zip"])
    require(len(raw)==a["size_in_bytes"]and"sha256:"+sha(raw)==a["digest"],"Complete baseline ZIP identity")
    import io
    selected={"native-reports/"+name:name for name in
              ("main.par","main.twr","main_map.mrp","main.pcf","main.xst","main.prj","main.syr")}
    selected.update({"native-exit.json":"baseline-native-exit.json",
                     "source-before.json":"baseline-source-before.json",
                     "source-before-index.txt":"baseline-source-before-index.txt",
                     "source-contract.json":"baseline-source-contract.json",
                     "ip-before.json":"baseline-ip-before.json",
                     "native-started.json":"baseline-native-started.json",
                     "native-finished.json":"baseline-native-finished.json",
                     "timing-result.json":"baseline-timing-result.json"})
    rows=[];seen=set();kept=set();total=0
    with zipfile.ZipFile(io.BytesIO(raw))as archive:
        entries=[x for x in archive.infolist()if not x.is_dir()]
        require(len(entries)==172,"Complete known baseline artifact file set")
        for entry in entries:
            name=entry.filename;p=PurePosixPath(name);mode=entry.external_attr>>16
            require(not p.is_absolute()and p.as_posix()==name and"\\"not in name and":"not in name and
                    all(x not in("..",".","")for x in p.parts)and(mode&0o170000)in(0,stat.S_IFREG),
                    "Safe regular baseline path")
            require(name.casefold()not in seen,"Unique baseline paths");seen.add(name.casefold())
            require(entry.file_size<=3_000_000,"Baseline text file cap");total+=entry.file_size
            require(total<=112_000_000,"Baseline complete text union cap")
            data=archive.read(entry);require(len(data)==entry.file_size and b"\0"not in data,"CRC and complete text")
            data.decode("utf-8")
            require(p.suffix.lower()not in(".ncd",".ngc",".ngd",".bit",".bi3",".bin",".rom",".xdl",".exe",".zip",".vvp"),
                    "Only baseline text reports")
            row=dict(path=name,bytes=len(data),sha256=sha(data),retained=name in selected)
            if name in selected:write(out/selected[name],data);kept.add(name)
            rows.append(row)
    require(kept==set(selected),"All declared baseline report/context bodies retained")
    source=json.loads(read(out/"baseline-source-before.json"));require(not source["differences"],"Canonical baseline source")
    bsx=next(x for x in source["files"]if x["path"]==SOURCE)
    require(bsx["sha256"]==sha(git("show",BASE+":"+SOURCE)),"Exact current unmodified BSX baseline source")
    require(json.loads(read(out/"baseline-native-exit.json"))["exit"]==2,"Original native failure preserved")
    result=json.loads(read(out/"baseline-timing-result.json"))
    require(result["current"]["traceErrors"]==93 and result["current"]["parScore"]==27981 and
            result["current"]["slack"]["setup"]["minimumNs"]==-0.935 and not result["strictTimingPassed"],
            "Exact current adopted partial baseline metrics")
    write(out/"baseline-reference-index.json",dict(files=rows,completeArchiveMembers=len(rows),
          declaredCompleteSelectedReports=selected,allOtherOriginalEvidenceRetainedInImmutableGitHubArtifact=artifact,
          originalFailureNotRelabeled=True))
    controls(out)


def candidate(original):
    require(sha(original.encode())==FRAGMENTS["originalSha256"],"Original complete BSX source")
    require(original.count(FRAGMENTS["old"])==1,"Unique original base window")
    text=original.replace(FRAGMENTS["old"],FRAGMENTS["new"],1)
    require(sha(text.encode())==FRAGMENTS["candidateSha256"],"Complete reviewed candidate")
    require(text.count(FRAGMENTS["new"])==1 and
            text.replace(FRAGMENTS["new"],FRAGMENTS["old"],1)==original,"Complete source inverse")
    return text

def contract(out):
    require(git("rev-parse","HEAD").decode().strip()==os.environ["GITHUB_SHA"],"Checkout head")
    require(git("rev-parse","HEAD^").decode().strip()in(BASE,"310fe8899dabe62347d5d0d0c716eb40c1405139"),"Exact reviewed source or proof-harness parent")
    paths={SOURCE,SELF,WORKFLOW}
    require(set(git("diff","--name-only",BASE,"HEAD").decode().splitlines())==paths,"Only BSX source/helper/workflow")
    require(read(SOURCE)==candidate(git("show",BASE+":"+SOURCE).decode()).encode(),"Complete source and scope")
    for name in ("verilog/common.mk","verilog/settings.mk",".github/scripts/build.sh",
                 "verilog/sd2snes_basex/Makefile","verilog/sd2snes_base/main.ucf",
                 "verilog/sd2snes_basex/sd2snes_basex.xise","verilog/sd2snes_base/main.v",
                 "verilog/sd2snes_base/cheat.v","verilog/sd2snes_base/address.v",
                 "verilog/sd2snes_st0018/st018_cpu.v","verilog/sd2snes_st0018/Makefile"):
        require(read(name)==git("show",BASE+":"+name),"Unchanged source/options/constraint: "+name)
    require(not Path("verilog/settings.local").exists() and not Path("verilog/sd2snes_basex/ucf.extra").exists(),
            "No local options or timing override")
    write(Path(out)/"source-contract.json",dict(head=os.environ["GITHUB_SHA"],base=BASE,
       files=[dict(path=n,bytes=len(read(n)),sha256=sha(read(n)))for n in sorted(paths)],
       onlyCaptureAlignedWindowPredicate=True,featureQualifiersAndGlobalStrobesUnchanged=True,
       featuresRemoved=False,constraintsRelaxed=False,secondIndependentReviewer=False))

def memory_init_audit(path, source):
    expected={}
    pattern=r"(base_regs|flash_vendor_data)\[\d+'h([0-9a-fA-F]+)\]\s*<=\s*(?:\d+'h([0-9a-fA-F]+)|([0-9]+))\s*;"
    for name,index,value,decimal in re.findall(pattern,source):
        key=(name,int(index,16));require(key not in expected,"Unique source memory initializer")
        expected[key]=int(value,16) if value else int(decimal)
    require(len(expected)==32 and sum(x[0]=="base_regs" for x in expected)==24,"All source memory initializers")
    design=json.loads(read(path));require(set(design["modules"])=={"bsx"},"Complete original BSX graph")
    actual={}
    def value(bits):
        require(bits and all(x in("0","1")for x in bits),"Fully constant init address/data")
        return int("".join(reversed(bits)),2)
    for cell in design["modules"]["bsx"]["cells"].values():
        if cell["type"] not in("$meminit","$meminit_v2"):continue
        params=cell["parameters"];name=params["MEMID"].lstrip("\\")
        require(name in("base_regs","flash_vendor_data"),"No unexpected initialized memory")
        width=int(params["WIDTH"],2);words=int(params["WORDS"],2)
        require(width==8 and words>=1,"Actual byte memory dimensions")
        con=cell["connections"];address=value(con["ADDR"])
        if "EN" in con:require(con["EN"] and all(x=="1"for x in con["EN"]),"Every actual initializer enabled")
        require(len(con["DATA"])==width*words,"Whole initializer data")
        for i in range(words):
            key=(name,address+i);require(key not in actual,"No overlapping memory init")
            actual[key]=value(con["DATA"][i*width:(i+1)*width])
    require(actual==expected,"All256 source memory-init bits match actual graph")
    return dict(bits=256,clockedBaseRegisterBits=192,constantVendorRomBits=64,
        words=[dict(memory=n,index=i,valueHex="%02x"%v)for(n,i),v in sorted(actual.items())])

def cut_bsx(source, output, model_name, expect_private):
    design=json.loads(read(source));require(set(design["modules"])=={"bsx"},"Complete flattened BSX, no blackboxes")
    module=design["modules"]["bsx"];aliases={};initial={}
    for name,net in module["netnames"].items():
        for index,bit in enumerate(net["bits"]):
            if not name.startswith("$"):aliases.setdefault(bit,[]).append((name,index))
        value=net.get("attributes",{}).get("init")
        if value is not None:
            require(isinstance(value,str)and len(value)==len(net["bits"]),"Full init width")
            for bit,letter in zip(net["bits"],reversed(value)):initial.setdefault(bit,set()).add(letter)
    private_net=module["netnames"].get("bsx_base_window_q")
    require((private_net is not None)==expect_private,"Exactly declared private predicate")
    private_bit=None
    if private_net is not None:
        require(len(private_net["bits"])==1,"One private state bit");private_bit=private_net["bits"][0]
    states=[];private=[];remove=[];used=set()
    for name,cell in module["cells"].items():
        kind=cell["type"]
        if kind!="$dff":
            require(kind.startswith("$") and not any(x in kind.lower()for x in("dff","latch","mem"))
                    and kind!="$ff"and not kind.startswith("$any")and kind!="$initstate"
                    and"CLK"not in cell["connections"],"No hidden state: "+kind)
            continue
        require(cell["connections"]["CLK"]==module["ports"]["clkin"]["bits"]and
                int(cell["parameters"]["CLK_POLARITY"],2)==1,"Original positive clkin clock")
        q,d=cell["connections"]["Q"],cell["connections"]["D"]
        require(len(q)==len(d),"Whole Q/D relation")
        for qb,db in zip(q,d):
            labels=sorted(aliases.get(qb,[]))
            require(isinstance(qb,int)and qb not in used and labels and len(initial.get(qb,set()))<=1,"Named state/init bijection")
            used.add(qb);item=dict(identity=labels,init=next(iter(initial.get(qb,set())),"x"),q=qb,d=db)
            (private if qb==private_bit else states).append(item)
        remove.append(name)
    require(len(private)==int(expect_private)and len(states)>=192,"All original state plus exactly one new predicate")
    states.sort(key=lambda x:json.dumps(x["identity"]))
    require(len({json.dumps(x["identity"])for x in states})==len(states),"Unique original state identities")
    for name in remove:del module["cells"][name]
    module["ports"]["__state"]=dict(direction="input",bits=[x["q"]for x in states])
    module["ports"]["__next"]=dict(direction="output",bits=[x["d"]for x in states])
    if expect_private:
        module["ports"]["__window_state"]=dict(direction="input",bits=[private[0]["q"]])
        module["ports"]["__window_next"]=dict(direction="output",bits=[private[0]["d"]])
    for net in module["netnames"].values():net.get("attributes",{}).pop("init",None)
    design["modules"]={model_name:module};write(output,design)
    return ([dict(identity=x["identity"],init=x["init"])for x in states],module["ports"],
            dict(identity=private[0]["identity"],init=private[0]["init"])if expect_private else None)

def bsx_miter(ports, inventory, private_init):
    inputs=[(n,len(p["bits"]))for n,p in ports.items()if p["direction"]=="input"and n!="__state"]
    outputs=[(n,len(p["bits"]))for n,p in ports.items()if p["direction"]=="output"]
    require(all(p["direction"]in("input","output")for p in ports.values()),"Full ordinary BSX interface")
    slots=[]
    for bit in range(24):
        positions=[i for i,state in enumerate(inventory)if any(label[0]=="snes_addr"and label[1]==bit for label in state["identity"])]
        require(len(positions)==1,"Every original address state bit located");slots.append(positions[0])
    init="".join(inventory[i]["init"]for i in reversed(slots))
    require(all(x in"01x"for x in init)and private_init in"01x","Actual source initial values")
    text="module miter(input ["+str(sum(b for n,b in inputs)-1)+":0] common_inputs, input ["+str(len(inventory)-1)+":0] common_state, output ok);\n"
    text+="function window_of(input [23:0] snes_addr);\nbegin window_of = "+FRAGMENTS["windowExpression"]+"; end\nendfunction\n"
    connections=[];offset=0
    for n,b in inputs:
        connections.append("."+n+"(common_inputs["+str(offset+b-1)+":"+str(offset)+"])");offset+=b
    comparisons=[]
    for n,b in outputs:
        require(re.fullmatch("[A-Za-z_][A-Za-z0-9_]*",n),"Ordinary output identifiers")
        text+="wire ["+str(b-1)+":0] gold_"+n+", gate_"+n+";\n";comparisons.append("(gold_"+n+" === gate_"+n+")")
    text+="wire [23:0] original_address_now = {"+",".join("common_state["+str(i)+"]"for i in reversed(slots))+"};\n"
    text+="wire [23:0] original_address_next = {"+",".join("gold___next["+str(i)+"]"for i in reversed(slots))+"};\n"
    text+="wire gate_window_next;\n"
    for side in("gold","gate"):
        con=connections+[".__state(common_state)"]+["."+n+"("+side+"_"+n+")"for n,b in outputs]
        if side=="gate":con+=[".__window_state(window_of(original_address_now))",".__window_next(gate_window_next)"]
        text+=side+" u_"+side+"("+", ".join(con)+");\n"
    comparisons+=["(gate_window_next === window_of(original_address_next))",
                  "(window_of(24'b"+init+") === 1'b"+private_init+")"]
    text+="assign ok = "+" & ".join(comparisons)+";\nendmodule\n"
    return text

def projected_window_unit(source, name, private):
    require(source.count(FRAGMENTS["addressCapture"])==1,"Actual original address capture")
    if private:
        begin="// BASEX_WINDOW_PREDECODE_BEGIN";end="// BASEX_WINDOW_PREDECODE_END"
        require(source.count(begin)==source.count(end)==1,"Actual private capture boundary")
        body=source[source.index(begin)+len(begin):source.index(end)]
    else:
        require(source.count(FRAGMENTS["old"])==1,"Actual original window")
        body=FRAGMENTS["old"]
    return ("module "+name+"(input clkin,input [23:0] snes_addr_in,input feat_bs_base_enable,input use_bsx);\n"+
            FRAGMENTS["addressCapture"]+"\n"+body+"\nendmodule\n")

def proof(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    original=git("show",BASE+":"+SOURCE).decode();gate=read(SOURCE).decode();require(gate==candidate(original),"Complete actual source candidate")
    write(out/"original.v",original);write(out/"candidate.v",gate)
    profiles={"mk2-basex":["MK2","BASE_EXT"],"mk2-base":["MK2"],"mk2-bootleg":["MK2","BOOTLEG"],
              "mk2-atari":["MK2","ATARI"],"mk3-base":["MK3"],"mk3-basex":["MK3","BASE_EXT"],"mk3-bootleg":["MK3","BOOTLEG"]}
    scope=[]
    for profile,defines in profiles.items():
        versions={}
        for side,file in(("gold","original.v"),("gate","candidate.v")):
            target=out/(side+"-"+profile+".v")
            command(["iverilog","-g2012","-E",*["-D"+x for x in defines],"-o",str(target),str(out/file)],out/(side+"-"+profile+"-preprocess"))
            versions[side]=tokens(read(target).decode())
        equal=versions["gold"]==versions["gate"];require(equal==(profile!="mk2-basex"),"All actual preprocessor profiles")
        scope.append(dict(profile=profile,equalOriginalTokens=equal))
    write(out/"preprocessor-scope.json",scope)
    require(gate.count("reg bsx_base_window_q;")==1,"Actual private initialization boundary")
    require(gate.count("wire bsx_base_window_d = "+FRAGMENTS["windowDataExpression"]+";")==1,"Actual private data expression")
    bad_x_expression="(!snes_addr_in[22] && (snes_addr_in[15:5] == 11'h10c) && (|snes_addr_in[4:3]))"
    variants={"gold":original,"gate":gate,
      "bad-init":gate.replace("reg bsx_base_window_q;","reg bsx_base_window_q = 1'b1;",1),
      "bad-late":gate.replace("wire bsx_base_window_d = "+FRAGMENTS["windowDataExpression"]+";",
                            "wire bsx_base_window_d = "+FRAGMENTS["windowExpression"]+";",1),
      "bad-data":gate.replace("bs_page1 <= {reg_data_in[1:0], base_regs[8'h0e]};",
                             "bs_page1 <= {reg_data_in[1:0], base_regs[8'h0e]} ^ 10'h001;",1),
      "bad-x":gate.replace("wire bsx_base_window_d = "+FRAGMENTS["windowDataExpression"]+";",
                          "wire bsx_base_window_d = "+bad_x_expression+";",1)}
    for name,source in variants.items():require(name in("gold","gate")or source!=gate,"Real changed-source negative control")
    tb="""module tb;
reg clkin=0;reg [23:0] snes_addr_in=0;
reg feat_bs_base_enable=1;reg use_bsx=1;
integer i,checks;
window_gold gold(clkin,snes_addr_in,feat_bs_base_enable,use_bsx);
window_gate gate(clkin,snes_addr_in,feat_bs_base_enable,use_bsx);
task check;begin #1;
if(gold.base_enable !== gate.base_enable)
$fatal(1,"WINDOW_MISMATCH check=%0d old=%b new=%b",checks,gold.base_enable,gate.base_enable);
checks=checks+1;end endtask
initial begin checks=0;check;
for(i=0;i<1024;i=i+1)begin
case(i%8)
0:snes_addr_in=24'h002188;1:snes_addr_in=24'h00219f;
2:snes_addr_in=24'h002187;3:snes_addr_in=24'h0021a0;
4:snes_addr_in=24'h402188;5:snes_addr_in=24'h002180;
6:begin snes_addr_in=24'h002188;snes_addr_in[0]=1'bx;end
7:begin snes_addr_in=24'h002188;snes_addr_in[0]=1'bz;end
endcase
if(i<8)begin feat_bs_base_enable=1;use_bsx=1;end
else begin
case(i%4)0:feat_bs_base_enable=0;1:feat_bs_base_enable=1;2:feat_bs_base_enable=1'bx;3:feat_bs_base_enable=1'bz;endcase
case((i/4)%4)0:use_bsx=0;1:use_bsx=1;2:use_bsx=1'bx;3:use_bsx=1'bz;endcase
end
check;clkin=1;check;clkin=0;
end
if(checks!=2049)$fatal(1,"Missing startup or clock checks");
$display("PASS window checks=2049 initial before-edge and after-edge");$finish;
end
endmodule
"""
    write(out/"window-tb.v",tb);write(out/"window-gold.v",projected_window_unit(original,"window_gold",False))
    for variant in("gate","bad-init","bad-late","bad-x"):
        source=variants[variant];prefix=out/("window-"+variant)
        write(str(prefix)+".source.v",source);write(str(prefix)+".v",projected_window_unit(source,"window_gate",True))
        exe=str(prefix)+".vvp"
        command(["iverilog","-g2012","-s","tb","-o",exe,str(out/"window-gold.v"),str(prefix)+".v",str(out/"window-tb.v")],str(prefix)+"-compile")
        rc=command(["vvp",exe],str(prefix)+"-run",allowed=(0,1));Path(exe).unlink()
        transcript=read(str(prefix)+"-run.stdout.log")+read(str(prefix)+"-run.stderr.log")
        require((rc==0)==(variant=="gate"),"Actual source projected startup simulation")
        require((b"PASS window checks=2049"if variant=="gate"else b"WINDOW_MISMATCH")in transcript,"Actual startup/edge result")
        if variant=="bad-init":require(b"check=0"in transcript,"Bad initialization rejected before first edge")
    reference,ports=None,None;private_info={}
    for variant,source in variants.items():
        folder=out/variant;folder.mkdir();write(folder/"source.v",source)
        command(["iverilog","-g2012","-E","-DMK2","-DBASE_EXT","-o",str(folder/"preprocessed.v"),str(folder/"source.v")],folder/"preprocess")
        script=("read_verilog -sv -formal "+str(folder/"preprocessed.v")+
          "; hierarchy -check -top bsx; setattr -unset keep -unset KEEP; flatten; proc -ifx -noopt; check -assert; write_json "+
          str(folder/"post-proc.json")+"; opt_expr -keepdc; write_json "+str(folder/"constant-init.json")+
          "; memory_memx; memory_collect; memory_map; dffunmap; setundef -undriven -undef; opt_clean; "+
          "check -assert; write_json "+str(folder/"state.json"))
        command(["yosys","-p",script],folder/"prepare")
        write(folder/"initial-memory-audit.json",memory_init_audit(folder/"constant-init.json",source))
        inventory,current,private=cut_bsx(folder/"state.json",folder/"transition.json","gold"if variant=="gold"else"gate",variant!="gold")
        write(folder/"state-inventory.json",inventory);write(folder/"private-state.json",private)
        for word in range(8,32):
            indices=[label[1]for state in inventory for label in state["identity"]if label[0]=="base_regs["+str(word)+"]"]
            require(sorted(indices)==list(range(8)),"All192base register state bits retained")
        if variant=="gold":reference,ports=inventory,current
        else:
            require(inventory==reference,"All original state/init/clock identities preserved")
            require({k:(v["direction"],len(v["bits"]))for k,v in current.items()if not k.startswith("__window_")}==
                    {k:(v["direction"],len(v["bits"]))for k,v in ports.items()},"All original ports/next-state compared")
            private_info[variant]=private
            write(folder/"miter.v",bsx_miter(ports,reference,private["init"]))
    results=[]
    for variant,modes in(("gate",("binary","xstate")),("bad-init",("binary",)),("bad-late",("binary",)),
                         ("bad-data",("binary",)),("bad-x",("binary","xstate"))):
        for mode in modes:
            folder=out/variant;witness=folder/("counterexample-"+mode+".json")
            script=("read_json "+str(out/"gold/transition.json")+"; read_json "+str(folder/"transition.json")+
               "; read_verilog -sv -formal "+str(folder/"miter.v")+"; hierarchy -check -top miter; proc -ifx -noopt; flatten; "+
               "opt_clean; check -assert; write_json "+str(folder/("miter-before-"+mode+".json"))+"; "+
               ("opt_merge -share_all -keepdc; opt_clean; "*16)+"check -assert; write_json "+
               str(folder/("miter-"+mode+".json"))+"; sat -verify -enable_undef "+
               ("-set-def-inputs "if mode=="binary"else"")+"-prove ok 1 -show-inputs -show-outputs -dump_json "+
               str(witness)+" -timeout 600")
            prefix=folder/("proof-"+mode);rc=command(["yosys","-p",script],prefix,timeout=1200,allowed=(0,1))
            expected=variant=="gate"or(variant=="bad-x"and mode=="binary")
            require_sat_result(rc,read(str(prefix)+".stdout.log")+read(str(prefix)+".stderr.log"),witness,expected)
            results.append(dict(variant=variant,mode=mode,exit=rc,expectedPass=expected,actualSatResult=True))
    write(out/"proof-result.json",dict(head=os.environ["GITHUB_SHA"],completeBsxStateAndAllOutputs=True,
       originalStateBits=len(reference),baseRegisterStateBits=192,allMemoryInitializerBitsAudited=256,
       oneNewPrivatePredicateBit=True,privateInitializationAndStepInvariantProved=True,
       strictBinaryAndXEquality=True,arbitraryOriginalSharedState=True,noResetEnableOrAlignmentAssumptions=True,
       originalFeatureQualifiersAndGlobalStrobesPreserved=True,startupSimulationChecks=2049,noStartupCyclesSkipped=True,
       allSixNonTargetProfilesUnchanged=True,preprocessorProfiles=7,sat=results,
       fullMappedEquivalenceNotClaimed=True,hardwareQualified=False,secondIndependentReviewer=False))


if __name__=="__main__":
    mode,*args=sys.argv[1:]
    {"contract":contract,"proof":proof,"baseline":baseline,"freeze-ip":freeze_ip,
     "container":container,"collect":collect,"analyze":analyze,"union":union,"proof-design":proof_design}[mode](*args)
