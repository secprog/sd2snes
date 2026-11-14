#!/usr/bin/env python3
"""GitHub-only, one bounded DMA4 placement trial; unchanged RTL and timing."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

BEST = '4d0199bf639629284546858b2b92abcd840b48a9'
SITE = 'SLICE_X31Y39'
DRIVER_SITE = 'SLICE_X31Y38'
DRIVER_LOGICAL = 'snes_dma/dma_r_4_not00012'
TARGETS = ['snes_dma/dma_r_4_1', 'snes_dma/dma_r_4_6']
EXTRA = (
    '# DSPX only: keep the worst DMA4 CE pair and its final enable LUT in adjacent slices.\n'
    '# Original RTL, parent pin/period/jitter constraints and seed 68 stay unchanged.\n'
    'INST "snes_dma/dma_r_4_1" LOC = SLICE_X31Y39;\n'
    'INST "snes_dma/dma_r_4_6" LOC = SLICE_X31Y39;\n'
    'INST "snes_dma/dma_r_4_not00012" LOC = SLICE_X31Y38;\n'
).encode()
MAP = ('map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 68 '
       '-register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy '
       '-pr b -bp -power off -o main_map.ncd main.ngd main.pcf')
PERIODS = {('TS_CLKIN','CLKIN','24.01'),('TS_SPI_SCK','SPI_SCK','48.1'),
           ('TS_SNES_SYSCLK','SNES_SYSCLK','21.5'),('TS_CLK21','CLK21','96.04')}
PIN = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')
LOC = re.compile(r'(?m)^COMP\s+"([^"\n]+)"\s+LOCATE\s*=\s*SITE\s+"([^"\n]+)"\s+LEVEL\s+1\s*;')
PRODUCTS = ['main.ngc','main.ngd','main_map.ncd','main.pcf','main.xst','main.prj','main.ucf']

def need(value, message):
    if not value:
        raise ValueError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')

def ucf(extra, parent, generated=None):
    need(extra == EXTRA, 'Only exact two FF and one final CE LUT LOC constraints allowed')
    if generated is not None:
        need(generated == extra + parent, 'Generated UCF must be exact extra followed by unchanged parent')

def source(root, output):
    root=Path(root)
    git=lambda *args: subprocess.check_output(['git','-c','safe.directory='+str(root),'-C',str(root),*args])
    wanted={'.github/scripts/validate-dspx-dma-placement.py',
            '.github/workflows/validate-dspx-stack-timing.yml','verilog/sd2snes_dspx/ucf.extra'}
    changed=set(git('diff','--name-only',BEST,'HEAD').decode().splitlines())
    need(changed==wanted,'Unexpected full source delta from adopted best')
    need(git('diff',BEST,'HEAD','--','verilog',':(exclude)verilog/sd2snes_dspx/ucf.extra')==b'',
         'Every older Verilog/constraint/project/IP/make input must remain byte-identical')
    need(git('diff','HEAD')==b'' and git('diff','--cached')==b'', 'Dirty canonical source/index')
    parent=git('show',BEST+':verilog/sd2snes_dsp/main.ucf')
    need((root/'verilog/sd2snes_dsp/main.ucf').read_bytes()==parent,'Parent UCF changed')
    ucf((root/'verilog/sd2snes_dspx/ucf.extra').read_bytes(),parent)
    manifest=[]
    for name in sorted(wanted):
        raw=(root/name).read_bytes()
        manifest.append(dict(path=name,bytes=len(raw),sha256=sha(raw)))
    save(output,dict(best=BEST,head=git('rev-parse','HEAD').decode().strip(),
        exactAllowedChangedFiles=manifest,parentUcfSha256=sha(parent),allOlderVerilogInputsUnchanged=True,
        rtlChanged=False,featuresRemoved=False,timingConstraintsRelaxed=False,physicalConstraintOnly=True,
        noNewBehaviorProofClaim=True))

def artifact(artifact_id, size, digest, wanted, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    meta=json.loads(subprocess.check_output(['gh','api','repos/secprog/sd2snes/actions/artifacts/'+str(artifact_id)]))
    need(meta['id']==artifact_id and meta['workflow_run']['id']==43467561223
         and meta['workflow_run']['head_sha']=='f4bcfe872f4c10f067fd1d6eca72882fa23b5b26'
         and meta['size_in_bytes']==size and meta['digest']=='sha256:'+digest and not meta['expired'],
         'Adopted best artifact API changed')
    raw=subprocess.check_output(['gh','api','repos/secprog/sd2snes/actions/artifacts/'+str(artifact_id)+'/zip'])
    need(len(raw)==size and sha(raw)==digest,'Adopted artifact ZIP changed')
    found=set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            key=info.filename if info.filename in wanted else PurePosixPath(info.filename).name
            if key not in wanted:
                continue
            need(key not in found and not info.is_dir() and info.file_size<=3000000,
                 'Duplicate/oversize baseline report')
            found.add(key);data=archive.read(info)
            need(sha(data)==wanted[key] and b'\0' not in data,'Baseline report changed')
            data.decode('utf-8');(output/PurePosixPath(info.filename).name).write_bytes(data)
    need(found==set(wanted),'Baseline reports missing')
    save(output/'artifact.json',meta)

def baseline(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    artifact(14062675697,1320091,'c49567c870dce5e5d162849f2df9907d08eab5c7c50a11b88426673dd1ad7cc6',
        {'native-reports/main.par':'2c98994def19078e17b2e1fda065d2863aa953a14d8cf0c3d2cdbcef56c45893',
         'native-reports/main.twr':'4c925afed46c3f520950a9b0711e89f2e6795dbbda696dc8e0e7bab09900b5a8'},output/'timing')
    artifact(14062690690,2520006,'fae12362d987524ba0f7713e563f82bd27940b3f8010e7e43d589a17fe3ae93c',
        {'main.pcf':'16985854878afc6eaa628da2d46bbf9102b73f12e38d6c7b14f36a308ccbf060'},output/'constraints')

def parse(text):
    starts=re.findall(r'(?m)^\s*(inst|net)\s+"',text)
    bodies=re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;',text)
    need(starts and len(starts)==len(bodies),'Incomplete mapped statements')
    instances={};nets={}
    for body in bodies:
        m=re.match(r'\s*(inst|net)\s+"([^"\n]+)"',body)
        need(m is not None,'Unrecognized mapped statement')
        kind,name=m.groups();target=instances if kind=='inst' else nets
        need(name not in target,'Duplicate mapped object');target[name]=body.strip()
    return instances,nets

def position(body):
    m=re.search(r',\s*placed\s+([^\s,]+)\s+([^\s,]+)\s*,',body)
    return (m[1],m[2]) if m else None

def physical(instances,nets,pcf,baseline_pcf):
    locs=LOC.findall(pcf);original_locs=LOC.findall(baseline_pcf)
    need(len(original_locs)==112 and len(set(original_locs))==112,'Original 112 I/O LOC declarations changed')
    need(all(site.startswith('P') for _,site in original_locs),'Unexpected baseline internal location')
    need(set(original_locs)<=set(locs),'Original I/O LOC missing or changed')
    need(len(re.findall(r'\bLOCATE\b',pcf))==len(locs),'Unknown/soft/range/duplicate unsupported LOCATE syntax')
    rows=[]
    for target in TARGETS:
        hits=[dict(component=c,slot=slot,logical=logical,position=position(raw))
            for c,raw in instances.items()
            for slot,logical in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)',raw) if logical==target]
        need(len(hits)==1,'Exact target FF alias missing/duplicate: '+target)
        row=hits[0];need(row['position']==('R13C16',SITE),'Target FF not at declared reviewed site')
        rows.append(row)
    comps={r['component'] for r in rows};need(len(comps)==1,'Two target FFs must share one actual slice')
    comp=next(iter(comps));raw=instances[comp];tokens=set(raw.split())
    ffslots=re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)',raw)
    need(set(ffslots)=={(r['slot'],r['logical']) for r in rows} and len(ffslots)==2,'Unexpected co-packed target state')
    need({'DXMUX::0','DYMUX::0','BXINV::BX','BYINV::BY','CEINV::CE','CLKINV::CLK','SRINV::SR','SYNC_ATTR::SYNC',
          'FFX_INIT_ATTR::INIT0','FFY_INIT_ATTR::INIT0','FFX_SR_ATTR::SRLOW','FFY_SR_ATTR::SRLOW','REVUSED::#OFF'}<=tokens,
         'Direct data/clock/enable/reset/polarity/init semantics changed')
    def incoming(pin):
        found=[n for n,body in nets.items() if ('inpin',comp,pin) in PIN.findall(body)]
        need(len(found)==1,'Missing/ambiguous target pin '+pin);return found[0]
    expected={'CLK':'CLK2','CE':'snes_dma/dma_r_4_not0001','SR':'SNES_reset_strobe'}
    for row in rows:
        expected['BX' if row['slot']=='FFX' else 'BY']='BUS_DATA<'+('1' if row['logical']==TARGETS[0] else '6')+'>'
    for pin,name in expected.items():
        need(incoming(pin)==name,'Target pin binding changed: '+pin)
    for row in rows:
        pin='XQ' if row['slot']=='FFX' else 'YQ'
        names=[n for n,body in nets.items() if ('outpin',comp,pin) in PIN.findall(body)]
        need(names==[row['logical']],'Target Q output net changed')
    hard={(c,site) for c,site in locs if (c,site) not in set(original_locs)}
    ce=nets[expected['CE']];drivers=[(c,pin) for direction,c,pin in PIN.findall(ce) if direction=='outpin']
    need(len(drivers)==1 and drivers[0][0] in instances,'CE driver missing/ambiguous')
    driver,pin=drivers[0];where=position(instances[driver])
    neighborhood={'R'+str(r)+'C'+str(c) for r in [12,13,14] for c in [15,16,17]}
    need(where is not None and where[0] in neighborhood,'Actual CE driver left reviewed bounded neighborhood; no native trial')
    need(pin in ['X','Y'],'Unexpected CE source kind')
    need(where==('R13C16',DRIVER_SITE),'Final CE driver not at exact reviewed adjacent site')
    slot='F' if pin=='X' else 'G'
    need((slot+':'+DRIVER_LOGICAL+':#LUT:') in instances[driver]
         and ('FXMUX::F' if slot=='F' else 'GYMUX::G') in instances[driver].split(),
         'Exact final CE logical LUT must directly drive actual target enable')
    need(hard=={(comp,SITE),(driver,DRIVER_SITE)} and len(locs)==114,
         'Two exact mapped COMP hard LOCs not uniquely preserved in PCF')
    return dict(targets=rows,targetComponent=comp,targetSite=SITE,bindings=expected,
        actualCeDriver=dict(component=driver,pin=pin,position=where),hardPcfLocations=[dict(component=comp,site=SITE),dict(component=driver,site=DRIVER_SITE)],
        originalIoLocCount=112,allOriginalIoLocsPreserved=True,legalMapPackingObserved=True,
        limits='Exact mapped placement/FF pin semantics and hard PCF LOC; not a routed-checkpoint or timing/hardware proof.')

def bounded(instances,nets,seeds):
    selected=set(seeds);selected_nets={n for n,raw in nets.items() if any(c in selected for _,c,_ in PIN.findall(raw))}
    for n in selected_nets:
        selected.update(c for direction,c,_ in PIN.findall(nets[n]) if direction=='outpin' and c in instances)
    raw='\n\n'.join([instances[c] for c in sorted(selected)]+[nets[n] for n in sorted(selected_nets)])+'\n'
    need(len(selected)<=400 and len(selected_nets)<=700 and len(raw.encode())<=3000000,'Fixed whole-record collection bound exceeded; no truncation')
    return raw,dict(components=sorted(selected),nets=sorted(selected_nets),bytes=len(raw.encode()),sha256=sha(raw.encode()))

def identities(root):
    root=Path(root);out=[]
    for name in PRODUCTS:
        p=root/name;need(p.is_file() and not p.is_symlink(),'Required mapped input unavailable: '+name)
        b=p.read_bytes();st=p.stat();out.append(dict(name=name,bytes=len(b),sha256=sha(b),mtimeNs=st.st_mtime_ns))
    return out

def collect(xdl,root,baseline_dir,output):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    parent=(root.parent/'sd2snes_dsp/main.ucf').read_bytes()
    ucf((root/'ucf.extra').read_bytes(),parent,(root/'main.ucf').read_bytes())
    b=Path(xdl).read_bytes();need(0<len(b)<=8000000 and b'\0' not in b,'Invalid/oversize mapped export')
    instances,nets=parse(b.decode('utf-8'))
    pcf=(root/'main.pcf').read_text();base=(Path(baseline_dir)/'constraints/main.pcf').read_text()
    occupancy=[];ffmeta=[];seeds=set()
    for comp,body in instances.items():
        pos=position(body)
        if pos and pos[1].startswith('SLICE_'):
            occupancy.append(dict(component=comp,tile=pos[0],site=pos[1],recordSha256=sha(body.encode())))
        if pos and pos[0]=='R13C16':seeds.add(comp)
        for slot,logical in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)',body):
            ffmeta.append(dict(component=comp,slot=slot,logical=logical,position=pos))
            if logical in TARGETS:seeds.add(comp)
    for direction,comp,pin in PIN.findall(nets.get('snes_dma/dma_r_4_not0001','')):
        if direction=='outpin' and comp in instances:seeds.add(comp)
    for name,rows in [('all-placed-slice-inventory.json',occupancy),('all-slice-ff-placement-inventory.json',ffmeta)]:
        need(len((json.dumps(rows,indent=2)+'\n').encode())<=3000000,'Complete inventory cap exceeded; no truncation')
        save(output/name,rows)
    raw,index=bounded(instances,nets,seeds)
    (output/'placement-raw.txt').write_text(raw)
    save(output/'placement-raw-index.json',index)
    save(output/'pre-par-input-identities.json',identities(root))
    try:
        result=physical(instances,nets,pcf,base)
        actual_clb=[c for c,body in instances.items() if position(body) and position(body)[0]=='R13C16']
        need(1<=len(actual_clb)<=4 and result['targetComponent'] in actual_clb,'Invalid actual full selected CLB occupancy')
    except ValueError as error:
        save(output/'placement-failure.json',dict(error=str(error),nativeNotAuthorizedByThisGate=True,
            mappedXdlBytes=len(b),mappedXdlSha256=sha(b),wholeRecordCollection=index))
        raise
    result.update(mappedXdlBytes=len(b),mappedXdlSha256=sha(b),totalMappedComponents=len(instances),
        totalMappedNets=len(nets),actualSelectedClbComponents=sorted(actual_clb),wholeRecordCollection=index,
        checkBeforeOriginalPar=True,sourceRtlUnchanged=True)
    save(output/'placement-result.json',result);print(json.dumps(result,indent=2),flush=True)

def native_inputs(root,physical_dir):
    before=json.loads((Path(physical_dir)/'pre-par-input-identities.json').read_text())
    after=identities(root);save(Path(physical_dir)/'post-native-input-identities.json',after)
    need(before==after,'Prechecked mapped input bytes/mtime changed during original native continuation')

def timing(text):
    par,twr=text['par'],text['twr']
    scores=re.findall(r'Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)',par)
    traces=re.findall(r'Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)',twr)
    need(len(scores)==len(traces)==1 and 'All signals are completely routed.' in par,'Incomplete/ambiguous implementation reports')
    values=[]
    for line in twr.splitlines():
        if not line.lstrip().startswith('Slack'):continue
        m=re.match(r'\s*Slack(?:\s+\(([^)]*)\))?:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))ns\b',line)
        need(m is not None,'Unknown slack record');values.append((m[1] or 'component',float(m[2])))
    need(values and any(k=='setup path' for k,v in values) and any(k=='hold path' for k,v in values),'Missing setup/hold details')
    score,setup,hold,component=map(int,scores[0]);errors,trace_score,trace_setup,trace_hold=map(int,traces[0])
    return dict(parScore=score,parSetupScore=setup,parHoldScore=hold,componentSwitchingScore=component,
        traceErrors=errors,traceScore=trace_score,traceSetupScore=trace_setup,traceHoldScore=trace_hold,
        worstDisplayedSetupSlackNs=min(v for k,v in values if k=='setup path'),
        worstDisplayedHoldSlackNs=min(v for k,v in values if k=='hold path'),
        worstDisplayedOtherSlackNs=min((v for k,v in values if k not in ('setup path','hold path')),default=0.0),
        minimumDisplayedSlackNs=min(v for k,v in values),displayedNegativePaths=sum(v<0 for k,v in values),
        displayedSlackRecords=len(values))

def progress(b,c):
    nonregression=(c['traceErrors']<=b['traceErrors'] and c['parScore']<=b['parScore']
        and c['worstDisplayedSetupSlackNs']>=b['worstDisplayedSetupSlackNs']
        and c['parHoldScore']==c['traceHoldScore']==c['componentSwitchingScore']==0
        and c['worstDisplayedHoldSlackNs']>=0 and c['worstDisplayedOtherSlackNs']>=0)
    better=(c['traceErrors']<b['traceErrors'] or c['parScore']<b['parScore']
        or c['worstDisplayedSetupSlackNs']>b['worstDisplayedSetupSlackNs'])
    return bool(nonregression and better)

def analyze(report,baseline_dir):
    report=Path(report);baseline_dir=Path(baseline_dir)
    original=timing({k:(baseline_dir/'timing'/('main.'+k)).read_text() for k in ['par','twr']})
    need(original['traceErrors']==13 and original['parScore']==1017 and original['worstDisplayedSetupSlackNs']==-0.124,
         'Best measured baseline metrics changed')
    root=report/'native-reports';text={k:(root/n).read_text() for k,n in [('par','main.par'),('twr','main.twr'),('pcf','main.pcf'),('mrp','main_map.mrp')]}
    candidate=timing(text)
    need(len(re.findall(r'^par -w -ol high -xe c -t 68 main_map\.ncd main\.ncd main\.pcf\s*$',text['par'],re.M))==1,'Original single PAR required')
    need(len(re.findall(r'/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr',text['twr']))==1,'Original single TRACE required')
    cmd=re.search(r'Command Line\s*:\s*(.*?)\s*Target Device',text['mrp'],re.S)
    need(cmd is not None and ' '.join(cmd[1].split())==MAP,'Original MAP options required')
    need(text['par'].count('Placer: Placement generated during map.')==1,'Original MAP placement not reported as used')
    need(re.findall(r'^SYSTEM_JITTER\s*=\s*([^;\r\n]+);',text['pcf'],re.M)==['480 ps'],'Original jitter required')
    periods=re.findall(r'^(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;',text['pcf'],re.M)
    need(len(periods)==4 and set(periods)==PERIODS and set(re.findall(r'^(TS_\w+)\s*=',text['pcf'],re.M))=={r[0] for r in PERIODS},'Original four timing specs required')
    need((report/'integrity-verified.txt').read_text().strip()=='Full source/index/IP immutability verified','Input integrity not accepted')
    before=json.loads((report/'physical/pre-par-input-identities.json').read_text())
    after=json.loads((report/'physical/post-native-input-identities.json').read_text())
    need(before==after,'Prechecked MAP/input metadata changed')
    build=(report/'native-build.log').read_text()
    need(not re.search(r'(?:^|\s)(?:\S*/)?map -p xc3s400',build,re.M),'Unexpected second MAP execution')
    need(not re.search(r'(?:^|\s)(?:\S*/)?xst -ifn ',build,re.M),'Unexpected second XST execution')
    finished,=json.loads((report/'native-container-finished.json').read_text());exit_code=int((report/'native-exit.txt').read_text())
    need(finished['State']['ExitCode']==exit_code and not finished['State']['OOMKilled'],'Native exit/OOM mismatch')
    if exit_code:
        need(exit_code==2 and 'make[1]: *** [../common.mk:198: main.ncd] Error 55' in build,
             'Actual native failure is not original strict timing gate')
        need(candidate['traceErrors']>0 or candidate['parScore']>0,'Failed native without timing violation')
    placement=json.loads((report/'physical/placement-result.json').read_text())
    # Direct TWR endpoint evidence is recorded when published. Hard LOC, exact
    # input identity and PAR's MAP-placement declaration remain required.
    reported=[]
    for block in re.split(r'(?=Slack(?:\s+\([^)]*\))?:)',text['twr']):
        dst=re.search(r'Destination:\s*([^\r\n]+?)\s+\(FF\)',block)
        if dst and dst[1] in TARGETS:
            fragment=block.split('Maximum Data Path:',1)[-1].split('Total ',1)[0]
            sites=re.findall(r'(?m)^\s*(SLICE_X\d+Y\d+)\.[A-Za-z0-9]+\s+',fragment)
            need(sites and sites[-1]==SITE,'Published routed target site contradicts hard LOC')
            reported.append(dict(destination=dst[1],reportedSite=sites[-1]))
    result=dict(baseline=original,candidate=candidate,nativeExit=exit_code,
        measuredImprovement=progress(original,candidate),
        strictTimingPass=candidate['traceErrors']==candidate['parScore']==0 and exit_code==0,
        mappedPlacement=placement,publishedRoutedTargetSites=reported,
        routedCheckpointInspected=False,hardwareQualified=False,ioElectricalSignoff=False,
        limits='Only exact reported constraints. Strict failures remain failures; no external I/O budgets or failed-route checkpoint invented.')
    save(report/'timing-progress-result.json',result);print(json.dumps(result,indent=2),flush=True)

def self_test(output):
    rows=[]
    def record(name,fn,expected):
        error=None
        try:fn();accepted=True
        except ValueError as exc:accepted=False;error=str(exc)
        rows.append(dict(name=name,expectedAcceptance=expected,accepted=accepted,error=error,passed=accepted==expected))
    parent=b'ORIGINAL PARENT UCF\n'
    record('exact extra and parent',lambda:ucf(EXTRA,parent,EXTRA+parent),True)
    for name,extra,generated in [
        ('extra unknown timing clause',EXTRA+b'NET "*" TIG;\n',None),
        ('different FF',EXTRA.replace(b'dma_r_4_6',b'dma_r_5_6'),None),
        ('different site',EXTRA.replace(b'X31Y39',b'X30Y39'),None),
        ('parent line omitted',EXTRA,EXTRA),
        ('parent reordered',EXTRA,parent+EXTRA),
        ('parent relaxed',EXTRA,EXTRA+b'RELAXED\n')]:
        record(name,lambda e=extra,g=generated:ucf(e,parent,g),False)
    raw=('inst "target" "SLICEL",placed R13C16 SLICE_X31Y39 , cfg " '
        'FFX:snes_dma/dma_r_4_1:#FF FFY:snes_dma/dma_r_4_6:#FF '
        'DXMUX::0 DYMUX::0 BXINV::BX BYINV::BY CEINV::CE CLKINV::CLK SRINV::SR SYNC_ATTR::SYNC '
        'FFX_INIT_ATTR::INIT0 FFY_INIT_ATTR::INIT0 FFX_SR_ATTR::SRLOW FFY_SR_ATTR::SRLOW REVUSED::#OFF ";\n'
        'inst "driver" "SLICEL",placed R13C16 SLICE_X31Y38 , cfg " F:snes_dma/dma_r_4_not00012:#LUT:D=A1 FXMUX::F ";\n'
        'net "CLK2", inpin "target" CLK;\nnet "SNES_reset_strobe", inpin "target" SR;\n'
        'net "BUS_DATA<1>", inpin "target" BX;\nnet "BUS_DATA<6>", inpin "target" BY;\n'
        'net "snes_dma/dma_r_4_not0001", outpin "driver" X, inpin "target" CE;\n'
        'net "snes_dma/dma_r_4_1", outpin "target" XQ;\nnet "snes_dma/dma_r_4_6", outpin "target" YQ;')
    base=''.join('COMP "io'+str(i)+'" LOCATE = SITE "P'+str(i)+'" LEVEL 1;\n' for i in range(112))
    pcf=base+'COMP "target" LOCATE = SITE "SLICE_X31Y39" LEVEL 1;\nCOMP "driver" LOCATE = SITE "SLICE_X31Y38" LEVEL 1;\n'
    def run(text,pcf_text=pcf):
        instances,nets=parse(text);return physical(instances,nets,pcf_text,base)
    record('exact placed FFs with hard COMP and direct pins',lambda:run(raw),True)
    for old,new,label in [
        ('FFX:snes_dma/dma_r_4_1:#FF','FFX:other:#FF','missing target alias'),
        ('FFY:snes_dma/dma_r_4_6:#FF','FFY:snes_dma/dma_r_4_1:#FF','duplicate target alias'),
        ('SLICE_X31Y39','SLICE_X30Y39','wrong target site'),
        ('placed R13C16 SLICE_X31Y39','unplaced','unplaced target'),
        ('placed R13C16 SLICE_X31Y38','placed R20C20 SLICE_X39Y26','CE driver outside reviewed region'),
        ('DXMUX::0','DXMUX::1','data through LUT instead of bypass'),
        ('SYNC_ATTR::SYNC','SYNC_ATTR::ASYNC','reset mode changed'),
        ('FFX_INIT_ATTR::INIT0','FFX_INIT_ATTR::INIT1','initial value changed'),
        ('SRINV::SR','SRINV::SR_B','reset polarity changed'),
        ('CEINV::CE','CEINV::CE_B','enable polarity changed'),
        ('CLKINV::CLK','CLKINV::CLK_B','clock edge changed'),
        ('"BUS_DATA<1>"','"BUS_DATA<0>"','wrong data bit'),
        ('"CLK2"','"OTHERCLK"','wrong clock'),
        ('"SNES_reset_strobe"','"OTHERRESET"','wrong reset'),
        ('"snes_dma/dma_r_4_not0001"','"OTHERCE"','wrong enable'),
        ('outpin "driver" X','outpin "missing" X','driver body missing'),
        ('outpin "driver" X','outpin "driver" XQ','unexpected CE source kind'),
        ('outpin "target" XQ','outpin "target" Y','wrong target Q output'),
        ('placed R13C16 SLICE_X31Y38','placed R13C16 SLICE_X30Y38','nearby but not declared CE site'),
        ('F:snes_dma/dma_r_4_not00012:#LUT:','F:wrong:#LUT:','wrong final CE logical LUT')]:
        need(raw.count(old)==1,'Unambiguous control mutation')
        record(label,lambda a=old,b=new:run(raw.replace(a,b)),False)
    for label,changed in [
        ('hard location missing',base),('final CE hard location missing',pcf.replace('COMP "driver" LOCATE = SITE "SLICE_X31Y38" LEVEL 1;\n','')),('soft location',pcf.replace('= SITE "SLICE','= SOFT SITE "SLICE')),
        ('wrong COMP name',pcf.replace('COMP "target"','COMP "wrong"')),
        ('duplicate location',pcf+pcf.splitlines()[-1]+'\n'),
        ('I/O pin changed',pcf.replace('SITE "P1"','SITE "P999"'))]:
        record(label,lambda x=changed:run(raw,x),False)
    for name,text,expected in [('empty export','',False),('incomplete net','inst "a" "SLICEL";\nnet "n"',False),
        ('duplicate instance','inst "a" "SLICEL";\ninst "a" "SLICEL";',False)]:
        record(name,lambda x=text:parse(x),expected)
    for n,expected in [(700,True),(701,False)]:
        record('whole net cap '+str(n),lambda n=n:bounded({'a':'inst "a" "SLICEL";'},
            {str(i):'net "'+str(i)+'", inpin "a" F1;' for i in range(n)},{'a'}),expected)
    metric=dict(traceErrors=13,parScore=1017,worstDisplayedSetupSlackNs=-0.124,
        parHoldScore=0,traceHoldScore=0,componentSwitchingScore=0,
        worstDisplayedHoldSlackNs=0.1,worstDisplayedOtherSlackNs=0.0)
    for label,changes,expected in [
        ('unchanged result rejected',{},False),
        ('partial real gain despite setup failure',dict(traceErrors=12),True),
        ('worse WNS rejects lower failure count',dict(traceErrors=12,worstDisplayedSetupSlackNs=-0.2),False),
        ('hold failure rejects gain',dict(traceErrors=12,worstDisplayedHoldSlackNs=-0.001),False),
        ('component failure rejects gain',dict(traceErrors=12,componentSwitchingScore=1),False),
        ('unscored negative rejects gain',dict(traceErrors=12,worstDisplayedOtherSlackNs=-0.001),False)]:
        candidate=dict(metric,**changes)
        record(label,lambda c=candidate,e=expected:need(progress(metric,c)==e,'Unexpected measured-gain classification'),True)
    save(output,dict(controls=rows,passed=all(x['passed'] for x in rows)))
    need(all(x['passed'] for x in rows),'Hosted placement/source adversarial controls failed')
    print(json.dumps(dict(controls=len(rows),passed=True)))

if __name__=='__main__':
    action=sys.argv[1]
    if action=='source' and len(sys.argv)==4:source(sys.argv[2],sys.argv[3])
    elif action=='baseline' and len(sys.argv)==3:baseline(sys.argv[2])
    elif action=='collect' and len(sys.argv)==6:collect(*sys.argv[2:])
    elif action=='inputs' and len(sys.argv)==4:native_inputs(*sys.argv[2:])
    elif action=='analyze' and len(sys.argv)==4:analyze(Path(sys.argv[2]),Path(sys.argv[3]))
    elif action=='self-test' and len(sys.argv)==3:self_test(sys.argv[2])
    else:raise SystemExit('Invalid action/argument count')
