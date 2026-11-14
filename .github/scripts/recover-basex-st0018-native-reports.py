#!/usr/bin/env python3
"""GitHub-only recovery of complete production text from two failed native jobs."""
import hashlib, io, json, os, stat, subprocess, sys, zipfile
from pathlib import Path, PurePosixPath
if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("GitHub-hosted collection only")
BASE = "41e225e9326caf7cee4b7de88fdf020ebaa070fb"
SELF = ".github/scripts/recover-basex-st0018-native-reports.py"
WF = ".github/workflows/validate-dspx-stack-timing.yml"
PINS = {
 "basex": dict(run=43626703591,job=132544253983,head="4cf8298725a995ed37ca91a43b74c213d43fc402",
               artifact=14126978622,bytes=1338687,sha256="f07c1b267d2209620262d296f368d5f36b10f7a2302149be869804a0a005567f",
               name="basex-private-history-complete-native-reports"),
 "st0018": dict(run=43627311028,job=132546475274,head="8902a8243a82efa7e3d51946d6e149b0297af8b4",
               artifact=14126557993,bytes=1196767,sha256="7e1e6f4d5ca7cb768342a65b042d49b6ab6722c8e57b3d84609140ca67ff21c9",
               name="st0018-mask-complete-native-reports")
}
NATIVE = {".ncd",".ngc",".ngd",".bit",".bin",".bi3",".rbf",".rdb",".xdl",".rom",".exe",".dll",".so",".vvp",".zip"}
def need(value, why):
    if not value: raise ValueError(why)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def safe_name(name):
    p=PurePosixPath(name)
    need(bool(name) and not p.is_absolute() and p.as_posix()==name and
         "\\" not in name and ":" not in name and
         all(x not in (".","..","") for x in p.parts) and
         not any(ord(c)<32 for c in name),"Unsafe ZIP member")
    return p
def production_text(name, raw):
    p=safe_name(name)
    need(p.parts[0]!="evidence-controls","Raw controls are not production text")
    need(p.suffix.lower() not in NATIVE,"Unexpected design or executable in production report")
    need(b"\0" not in raw,"NUL in production text")
    raw.decode("utf-8")
    need(len(raw)<=32_000_000,"Complete typed text bound")
def put(path, raw):
    need(not path.exists(),"Refuse evidence overwrite")
    raw.decode("utf-8");need(b"\0" not in raw,"Only UTF8 text")
    need(len(raw)<=3_000_000,"Safe text file bound")
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
def js(path, data): put(path,(json.dumps(data,indent=2,sort_keys=True)+"\n").encode())
def controls(out):
    rows=[]
    cases=[("ordinary","native-reports/main.twr",b"Slack: -0.001ns\n",True),
           ("json","native-exit.json",b'{"exit":2}\n',True),
           ("invalid-utf8","native-reports/a.txt",b"\xff",False),
           ("nul","native-reports/a.txt",b"\0",False),
           ("native","native-reports/main.ncd",b"text",False),
           ("rom","main.rom",b"text",False),
           ("raw-sandbox","evidence-controls/control.txt",b"text",False),
           ("escape","../main.twr",b"text",False),
           ("absolute","/main.twr",b"text",False),
           ("windows","C:main.twr",b"text",False),
           ("backslash","a\\main.twr",b"text",False)]
    for label,name,raw,expected in cases:
        try: production_text(name,raw);accepted=True
        except (ValueError,UnicodeError): accepted=False
        rows.append(dict(label=label,expected=expected,accepted=accepted,passed=expected==accepted))
    js(out/"hosted-recovery-controls.json",dict(controls=rows,complete=all(x["passed"] for x in rows)))
    need(all(x["passed"] for x in rows),"Recovery controls")
def gh(endpoint):
    return subprocess.check_output(["gh","api","repos/secprog/sd2snes/"+endpoint])
def retain_complete(out, name, raw):
    if len(raw)<=3_000_000:
        put(out/name,raw);return
    parts=[];offset=0
    while offset<len(raw):
        end=min(offset+1_000_000,len(raw))
        while end<len(raw) and raw[end]&0xC0==0x80:end-=1
        need(end>offset,"UTF8 part boundary")
        data=raw[offset:end];target=name+".part-%03d.txt"%len(parts)
        put(out/target,data);parts.append(dict(path=target,bytes=len(data),sha256=sha(data)));offset=end
    need(b"".join((out/x["path"]).read_bytes() for x in parts)==raw,"Lossless ordered text parts")
    js(out/(name+".parts-index.json"),dict(original=name,bytes=len(raw),sha256=sha(raw),orderedParts=parts))
def recover(out, core, pin):
    folder=out/core;folder.mkdir();metadata={}
    for kind,endpoint in (("run","actions/runs/"+str(pin["run"])),
                          ("jobs","actions/runs/"+str(pin["run"])+"/jobs?per_page=100"),
                          ("artifact","actions/artifacts/"+str(pin["artifact"]))):
        raw=gh(endpoint);data=json.loads(raw);metadata[kind]=data;put(folder/(kind+"-api.json"),raw)
    run=metadata["run"];a=metadata["artifact"]
    need(run["head_sha"]==pin["head"] and run["run_attempt"]==1 and run["status"]=="completed" and run["conclusion"]=="failure","Exact failed run")
    job=next(x for x in metadata["jobs"]["jobs"] if x["id"]==pin["job"])
    need(job["status"]=="completed" and job["conclusion"]=="failure","Exact failed native job")
    need(a["id"]==pin["artifact"] and a["name"]==pin["name"] and a["size_in_bytes"]==pin["bytes"] and
         a["digest"]=="sha256:"+pin["sha256"] and not a["expired"] and a["workflow_run"]["id"]==pin["run"] and
         a["workflow_run"]["head_sha"]==pin["head"],"Exact report artifact metadata")
    raw=gh("actions/artifacts/"+str(pin["artifact"])+"/zip")
    need(len(raw)==pin["bytes"] and sha(raw)==pin["sha256"],"Complete unchanged original ZIP")
    kept=[];excluded=[];seen=set();total=0;control_result=None
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members=[x for x in archive.infolist() if not x.is_dir()]
        need(len(members)<=1024,"Complete source archive count")
        for entry in members:
            name=entry.filename;p=safe_name(name);mode=entry.external_attr>>16
            need((mode&0o170000) in (0,stat.S_IFREG),"Only regular original members")
            need(name.casefold() not in seen,"Unique original member");seen.add(name.casefold())
            need(entry.file_size<=32_000_000,"Original member bound");total+=entry.file_size
            need(total<=112_000_000,"Complete original expanded bound")
            data=archive.read(entry);need(len(data)==entry.file_size,"CRC and original size")
            row=dict(path=name,bytes=len(data),sha256=sha(data),crc32=entry.CRC)
            if p.parts[0]=="evidence-controls":
                if name=="evidence-controls/self-test-results.json":
                    control_result=json.loads(data)
                    need(control_result["complete"] and len(control_result["controls"])==91 and
                         all(x["passed"] for x in control_result["controls"]),"All original hosted controls")
                    js(folder/"original-hosted-evidence-controls.json",control_result)
                    row["retainedAs"]="original-hosted-evidence-controls.json"
                else:
                    row["retainedOnGitHubOnly"]=True
                    row["classification"]="Intentional synthetic control sandbox; not production evidence"
                excluded.append(row)
            else:
                production_text(name,data);retain_complete(folder/"reports",name,data);kept.append(row)
    need(control_result is not None,"Original control receipt required")
    names={x["path"] for x in kept}
    need({"source-before.json","source-after.json","source-before-index.txt","source-after-index.txt",
          "native-exit.json","native-finished.json","native-started.json","native-build.status.json",
          "native-build.stdout.log","ip-before.json","ip-after.json",
          "native-reports/main.par","native-reports/main.twr","native-reports/main_map.mrp","native-reports/main.pcf"}<=names,
         "Every required actual report and immutable-input receipt retained")
    js(folder/"original-archive-inventory.json",dict(keptProductionFiles=kept,syntheticControlFiles=excluded,
       allOriginalMembersAccounted=True,originalExpandedBytes=total,originalZipSha256=sha(raw),
       noProductionFilesOmitted=True,originalArtifact=pin["artifact"],originalNativeFailurePreserved=True))
    return dict(core=core,source=pin,allProductionFilesRetained=len(kept),syntheticSandboxMembers=len(excluded),
                originalControlsPassed=91,originalNativeFailurePreserved=True)
def main():
    out=Path(sys.argv[1]);need(not out.exists(),"Fresh recovery directory");out.mkdir(parents=True)
    need(subprocess.check_output(["git","rev-parse","HEAD"]).decode().strip()==os.environ["GITHUB_SHA"],"Recovery checkout")
    need(subprocess.check_output(["git","rev-parse","HEAD^"]).decode().strip()==BASE,"Recovery-only parent")
    need(set(subprocess.check_output(["git","diff","--name-only",BASE,"HEAD"]).decode().splitlines())=={SELF,WF},"Only data collector and workflow")
    controls(out);results=[recover(out,core,pin) for core,pin in PINS.items()]
    js(out/"recovery-result.json",dict(results=results,collectionOnly=True,
        noBuildOrProofOrSimulation=True,noNativeInvocation=True,originalArchivesUnchanged=True,
        excludesOnlyKnownSyntheticControlSandbox=True,timingFailureNotRelabeled=True))
    rows=[];total=0
    for f in sorted(out.rglob("*")):
        if not f.is_file():continue
        need(not f.is_symlink(),"Regular recovery text")
        data=f.read_bytes();data.decode("utf8");need(b"\0" not in data and len(data)<=3_000_000,"Safe final file")
        total+=len(data);need(total<=112_000_000 and len(rows)<1024,"Safe complete final union")
        rows.append(dict(path=f.relative_to(out).as_posix(),bytes=len(data),sha256=sha(data)))
    js(out/"text-union.json",dict(files=rows,bytes=total,fileCount=len(rows),completeProductionText=True))
    print(json.dumps(dict(results=results,textFiles=len(rows)+1,textBytes=total)))
if __name__=="__main__":main()
