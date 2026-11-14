#!/usr/bin/env python3
"""GitHub-only production-hook controls, complete fresh mapping check and timing comparison."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import zipfile

if os.environ.get('GITHUB_ACTIONS')!='true':
    raise SystemExit('GitHub-hosted execution only')
ROOT=Path(os.environ['GITHUB_WORKSPACE']).resolve()
DIAG=Path(__file__).with_name('inspect-dspx-retained-ff-relocation.py')
if hashlib.sha256(DIAG.read_bytes()).hexdigest()!='3dbc5a668a3ba027ce3fda252caa8bf932a78eb9882f112dfeb66b201d738889':
    raise SystemExit('Frozen independently reviewed conversion helper changed')
spec=importlib.util.spec_from_file_location('dspx_ff_record_inspector',DIAG)
diag=importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
need=diag.need
save=diag.save
sha=diag.sha
BIN='/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64'
ORIGINAL='202a5f708880fc4d659760aabd7b236cae2fddc5b0c13c3cf1460a8d0ce2fe44'
CONVERTED='62367acd5c11d9ad891a1076bb716465d8126e6025346660227df41e275e35c7'
PCF='16985854878afc6eaa628da2d46bbf9102b73f12e38d6c7b14f36a308ccbf060'
PATCH='d64c47a0468c0d16bdbd87d3251a0d434a6ce89b704cce93acc139a62bff1ba4'
MAP='map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 68 -register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy -pr b -bp -power off -o main_map.ncd main.ngd main.pcf'
PERIODS={('TS_CLKIN','CLKIN','24.01'),('TS_SPI_SCK','SPI_SCK','48.1'),('TS_SNES_SYSCLK','SNES_SYSCLK','21.5'),('TS_CLK21','CLK21','96.04')}

def compact_capture(report,label,argv):
    # Full UTF-8 stdout/stderr bytes are kept losslessly inside this typed JSON.
    # One command file avoids duplicate raw/text copies of every Docker response.
    result=subprocess.run(argv,capture_output=True)
    streams={}
    for name,b in [('stdout',result.stdout),('stderr',result.stderr)]:
        need(len(b)<=3000000 and b'\0' not in b,'Complete command stream cap/text failed')
        streams[name]=dict(bytes=len(b),sha256=sha(b),text=b.decode('utf-8'))
    save(report/(label+'-command.json'),dict(argv=argv,returncode=result.returncode,streams=streams,complete=True))
    need(result.returncode==0,'Owned Docker client command failed: '+label)
    return result

# Reuse the accepted owned-tool/image/MAC/read-only mount/lifecycle validation,
# changing only the lossless host capture representation documented above.
diag.captured=compact_capture

def copy_generation_text(project,output):
    generations=sorted((project/'.dma4-ff-relocation').glob('generation-*'))
    output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for generation in generations:
        need(generation.is_dir() and not generation.is_symlink(),'Unsafe generation directory')
        for path in sorted(generation.iterdir()):
            need(not path.is_symlink(),'Unexpected generation symlink')
            if not path.is_file() or path.suffix not in ['.txt','.log','.sha256']:continue
            b=path.read_bytes()
            need(len(b)<=3000000 and b'\0' not in b,'Complete production stream cap/text failed')
            b.decode('utf-8')
            target=output/generation.name/path.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
            rows.append(dict(path=target.relative_to(output).as_posix(),bytes=len(b),sha256=sha(b)))
    save(output/'generation-text-index.json',rows)
    return generations

def original_inputs(archive,api,directory):
    directory.mkdir(parents=True,exist_ok=False)
    identities=diag.load_original(archive,api,directory)
    text=(directory/'map.xdl').read_text()
    model,raw=diag.parse(text)
    need(sha(diag.canonical_body(text).encode())==ORIGINAL,'Accepted original design-body pin changed')
    return identities,model,raw

def controls(archive,api,scratch,output):
    scratch.mkdir(parents=True,exist_ok=False);output.mkdir(parents=True,exist_ok=False)
    identities,before,raw=original_inputs(archive,api,scratch/'original')
    save(output/'original-input-identities.json',identities)
    diag.parser_controls(output);diag.controls(before,output)
    image_before=json.loads(compact_capture(output,'image-before',['docker','image','inspect',diag.IMAGE]).stdout)
    save(output/'image-before.json',image_before);need(image_before[0]['Id']==diag.IMAGE,'Tool image changed')
    source=ROOT/'verilog/sd2snes_dspx'
    original_pin=(source/'dma4_ff_relocation.sha256').read_bytes()
    expected=('ORIGINAL_BODY_SHA256 '+ORIGINAL+'\nRELOCATED_BODY_SHA256 '+CONVERTED+
              '\nORIGINAL_PCF_SHA256 '+PCF+'\nPATCH_SCRIPT_SHA256 '+PATCH+'\n').encode()
    need(original_pin==expected and sha((source/'dma4_ff_relocation.tcl').read_bytes())==PATCH,'Production patch/manifest pins changed')
    cases=[
      ('good',None,None,0,None),
      ('malformed-manifest','malformed',None,1,'Malformed physical manifest'),
      ('duplicate-manifest','duplicate',None,1,'Duplicate physical manifest key'),
      ('bad-pcf','ORIGINAL_PCF_SHA256','0'*64,1,'Complete original PCF fingerprint mismatch'),
      ('bad-source-body','ORIGINAL_BODY_SHA256','0'*64,1,'Fresh MAP complete design-body fingerprint mismatch'),
      ('bad-converted-body','RELOCATED_BODY_SHA256','0'*64,1,'Converted complete relocated design-body fingerprint mismatch'),
      ('bad-patch','PATCH_SCRIPT_SHA256','0'*64,1,'Complete patch script fingerprint mismatch')]
    rows=[]
    for name,key,value,exit_code,message in cases:
        project=scratch/('case-'+name);project.mkdir()
        shutil.copyfile(scratch/'original/main_map.ncd',project/'main_map.ncd')
        shutil.copyfile(scratch/'original/main.pcf',project/'main.pcf')
        shutil.copyfile(source/'dma4_ff_relocation.tcl',project/'dma4_ff_relocation.tcl')
        content=original_pin
        if key=='malformed':content=b'INVALID\n'
        elif key=='duplicate':content+=content.splitlines(keepends=True)[0]
        elif key:
            lines=content.decode().splitlines()
            content=('\n'.join(key+' '+value if line.startswith(key+' ') else line for line in lines)+'\n').encode()
        (project/'dma4_ff_relocation.sha256').write_bytes(content)
        prefix='/scratch/'+project.name
        argv=['/bin/bash','-c','cd -- "$1"; shift; exec "$@"','bash',prefix,
              BIN+'/xtclsh','/work/verilog/sd2snes_dspx/dma4_ff_physical.tcl',BIN,
              prefix+'/main_map.ncd',prefix+'/main.pcf',prefix+'/dma4_ff_relocation.sha256']
        diag.tool(scratch,output,'production-'+name,argv,expected_exit=exit_code)
        need(sha((project/'main.pcf').read_bytes())==PCF,'Production control changed PCF')
        generations=copy_generation_text(project,output/('generation-'+name))
        if exit_code:
            need(sha((project/'main_map.ncd').read_bytes())==identities['main_map.ncd']['sha256'],
                 'Rejected production case changed original mapped NCD')
            need(message.encode() in (output/('production-'+name+'-stderr.txt')).read_bytes(),
                 'Actual production failure arose for another reason')
        else:
            need(len(generations)==1,'Positive control did not create one owned generation')
            generation=generations[0]
            final_text=(generation/'converted.xdl').read_text();after,after_raw=diag.parse(final_text)
            diag.validate_move(before,after,'actual production wrapper positive control')
            need(sha(diag.canonical_body(final_text).encode())==CONVERTED,'Positive conversion body changed')
            need(sha((generation/'original.ncd').read_bytes())==identities['main_map.ncd']['sha256'],'Positive original backup changed')
            need((generation/'result.txt').is_file(),'Positive wrapper lacks success receipt')
            installed_sha=sha((project/'main_map.ncd').read_bytes())
            need(installed_sha!=identities['main_map.ncd']['sha256']
                 and 'relocatedNcdSha256='+installed_sha+'\n' in (generation/'result.txt').read_text(),
                 'Positive mapped NCD was not the checked installed conversion')
            need(sha((generation/'import.stderr.log').read_bytes())=='9e71e89bd7801df8854203d65d74116454669b7eb99a37e03cd910755765a3cc',
                 'Production positive-control import warning body differs from reviewed conversion')
            diag.indexes(raw,output,'control-original');diag.indexes(after_raw,output,'control-converted')
            diag.bounded(raw,before,output,'control-original');diag.bounded(after_raw,after,output,'control-converted')
        rows.append(dict(name=name,expectedDirectExit=exit_code,pcfUnchanged=True,
                         rejectedInputNcdUnchanged=bool(exit_code),expectedSpecificError=message,passed=True))
    for name,identity in identities.items():
        data=(scratch/'original'/name).read_bytes()
        need((len(data),sha(data))==(identity['bytes'],identity['sha256']),'Original retained input changed during controls')
    save(output/'image-after.json',json.loads(compact_capture(output,'image-after',['docker','image','inspect',diag.IMAGE]).stdout))
    need((output/'image-before.json').read_bytes()==(output/'image-after.json').read_bytes(),'Tool image metadata changed')
    save(output/'production-controls.json',dict(controls=rows,passed=True,actualWrapperCalls=7,
         actualPositiveInstalledAndGraphVerified=True,noSynthesisMapParTrace=True,noTimingResult=True))
    print((output/'production-controls.json').read_text(),end='')

def input_rows(project):
    rows=[]
    for name in ['main.ngc','main.ngd','main_map.ncd','main.pcf','../sd2snes_dsp/main.ucf','main.xst','main.prj']:
        path=project/name;need(path.is_file() and not path.is_symlink(),'Prechecked input missing/unsafe: '+name)
        b=path.read_bytes();rows.append(dict(path=name,bytes=len(b),sha256=sha(b),mtimeNs=path.stat().st_mtime_ns))
    return rows

def inputs(project,output):
    before=json.loads((output/'pre-par-input-identities.json').read_text())
    after=input_rows(project);save(output/'post-native-input-identities.json',after)
    need(before==after,'Prechecked inputs changed after production mapping')
    print('Prechecked mapped NCD, PCF and source products unchanged')

def fresh(archive,api,project,output,comparison):
    output.mkdir(parents=True,exist_ok=False)
    identities,before,original_raw=original_inputs(archive,api,comparison)
    # Complete comparison XDL/NCD remains in the separate GitHub-only directory.
    generations=copy_generation_text(project,output/'generation')
    need(len(generations)==1,'Fresh build must have exactly one production physical generation')
    g=generations[0];need((g/'result.txt').is_file(),'Production hook did not commit a checked mapping')
    need(sha((g/'import.stderr.log').read_bytes())=='9e71e89bd7801df8854203d65d74116454669b7eb99a37e03cd910755765a3cc',
         'Fresh production import warning body differs from reviewed conversion')
    old_text=(g/'original.xdl').read_text();original_model,fresh_raw=diag.parse(old_text)
    diag.require_equal(original_model,before,'fresh original production MAP')
    need(sha(diag.canonical_body(old_text).encode())==ORIGINAL,'Fresh MAP original-body pin mismatch')
    new_text=(g/'converted.xdl').read_text();after,after_raw=diag.parse(new_text)
    contract=diag.validate_move(before,after,'fresh actual production hook')
    need(sha(diag.canonical_body(new_text).encode())==CONVERTED,'Fresh converted body pin mismatch')
    need(sha((project/'main.pcf').read_bytes())==PCF,'Original PCF changed in production')
    installed=sha((project/'main_map.ncd').read_bytes())
    installed_record=(g/'result.txt').read_text()
    need('relocatedNcdSha256='+installed+'\n' in installed_record,'Installed mapping differs from checked production conversion')
    for label,records in [('original',original_raw),('fresh',fresh_raw),('converted',after_raw)]:diag.indexes(records,output,label)
    diag.bounded(fresh_raw,original_model,output,'fresh');diag.bounded(after_raw,after,output,'converted')
    save(output/'pre-par-input-identities.json',input_rows(project))
    save(output/'fresh-structural-result.json',dict(freshOriginalMapExactlyReproducedAcceptedBody=True,
      actualProductionConvertedBodyMatched=True,sourceBodySha256=ORIGINAL,convertedBodySha256=CONVERTED,
      originalWholeRetainedInputGatesUnchanged=True,freshOriginalNcdSha256=sha((g/'original.ncd').read_bytes()),
      freshOriginalNcdByteEqualHistorical=sha((g/'original.ncd').read_bytes())==identities['main_map.ncd']['sha256'],
      exactPcfUnchanged=True,allOtherMappedConfigAndPlacementsPreserved=True,ffContract=contract,
      originalNativeNotYetRun=True,noTimingResult=True,hardwareQualified=False,ioElectricalSignoff=False))
    print((output/'fresh-structural-result.json').read_text(),end='')

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
    placement=json.loads((report/'physical/fresh-structural-result.json').read_text())
    need(placement['freshOriginalMapExactlyReproducedAcceptedBody'] and placement['actualProductionConvertedBodyMatched']
         and placement['exactPcfUnchanged'] and placement['allOtherMappedConfigAndPlacementsPreserved'],'Fresh structural production mapping gate not accepted')
    # Published endpoint sites, full pre-PAR placement conservation, exact
    # input identity and PAR route-only declaration remain required.
    reported=[]
    for block in re.split(r'(?=Slack(?:\s+\([^)]*\))?:)',text['twr']):
        dst=re.search(r'Destination:\s*([^\r\n]+?)\s+\(FF\)',block)
        if dst and dst[1] in ['snes_dma/dma_r_4_1','snes_dma/dma_r_4_6']:
            fragment=block.split('Maximum Data Path:',1)[-1].split('Total ',1)[0]
            sites=re.findall(r'(?m)^\s*(SLICE_X\d+Y\d+)\.[A-Za-z0-9]+\s+',fragment)
            need(sites and sites[-1]=='SLICE_X31Y39','Published routed target site contradicts verified MAP placement')
            reported.append(dict(destination=dst[1],reportedSite=sites[-1]))
    result=dict(baseline=original,candidate=candidate,nativeExit=exit_code,
        measuredImprovement=progress(original,candidate),
        strictTimingPass=candidate['traceErrors']==candidate['parScore']==candidate['parHoldScore']==candidate['traceHoldScore']==candidate['componentSwitchingScore']==0 and candidate['minimumDisplayedSlackNs']>=0 and exit_code==0,
        mappedStructuralRelocation=placement,publishedRoutedTargetSites=reported,
        routedCheckpointInspected=False,hardwareQualified=False,ioElectricalSignoff=False,
        limits='Only exact reported constraints. Strict failures remain failures; no external I/O budgets or failed-route checkpoint invented.')
    save(report/'timing-progress-result.json',result);print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    modes={'controls':(4,controls),'fresh':(5,fresh),'inputs':(2,inputs),'baseline':(1,baseline),'analyze':(2,analyze)}
    need(len(sys.argv)>=2 and sys.argv[1] in modes,'Unknown hosted production-check mode')
    count,function=modes[sys.argv[1]]
    need(len(sys.argv)==count+2,'Wrong mode argument count')
    function(*(Path(value) for value in sys.argv[2:]))
