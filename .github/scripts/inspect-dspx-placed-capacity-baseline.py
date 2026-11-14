#!/usr/bin/env python3
"""GitHub-only bounded inspection of adopted baseline placed resources and reported critical endpoint capacity; no generation or Boolean evaluation."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import subprocess
import zipfile

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

RUN=43467561223
HEAD='f4bcfe872f4c10f067fd1d6eca72882fa23b5b26'
ARTIFACT=14062690690
ZIP_SIZE=2520006
ZIP_SHA='fae12362d987524ba0f7713e563f82bd27940b3f8010e7e43d589a17fe3ae93c'
XDL_SIZE=4631153
XDL_SHA='c3f1214ed604a032b9c045bbb5bd0f2ca32c6d53f6bc7ab46915d31a826af22e'
PIN=re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')


def need(value,message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def load_original(archive_path,api):
    metadata=json.loads((api/'artifact.json').read_text())
    jobs=json.loads((api/'jobs.json').read_text())['jobs']
    need(metadata['id']==ARTIFACT and metadata['workflow_run']['id']==RUN
         and metadata['workflow_run']['head_sha']==HEAD and metadata['digest']=='sha256:'+ZIP_SHA
         and metadata['size_in_bytes']==ZIP_SIZE and not metadata['expired'],'Original design API identity changed')
    proof=next(job for job in jobs if job['id']==132030641690)
    native=next(job for job in jobs if job['id']==132030910778)
    need(proof['head_sha']==HEAD and native['head_sha']==HEAD and proof['run_attempt']==1 and native['run_attempt']==1
         and proof['conclusion']=='success' and native['status']=='completed' and native['conclusion']=='failure'
         and [step['number'] for step in native['steps'] if step['conclusion']=='failure']==[9,12],
         'Original proof/native outcome changed')
    raw=archive_path.read_bytes();need(len(raw)==ZIP_SIZE and sha(raw)==ZIP_SHA,'Original design ZIP changed')
    found=[];seen=set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        need(len(archive.infolist())<=512,'Unexpected native ZIP entry count')
        for info in archive.infolist():
            name=info.filename;path=PurePosixPath(name);mode=(info.external_attr>>16)&0xffff
            need(not path.is_absolute() and chr(92) not in name and ':' not in name
                 and '..' not in path.parts and path.as_posix()==name.rstrip('/')
                 and stat.S_IFMT(mode) in (0,stat.S_IFREG,stat.S_IFDIR),'Unsafe original design ZIP path')
            need(name.casefold() not in seen,'Duplicate original design ZIP path');seen.add(name.casefold())
            if path.name=='map.xdl' and not info.is_dir():
                need(info.file_size==XDL_SIZE,'Original mapped export size changed');found.append(archive.read(info))
    need(len(found)==1 and len(found[0])==XDL_SIZE and sha(found[0])==XDL_SHA,'Original mapped XDL identity changed')
    need(b'\0' not in found[0],'Invalid mapped text');text=found[0].decode('utf-8')
    return parse_xdl(text, full=True)

def parse_xdl(text, full=False):
    starts=re.findall(r'(?m)^\s*(inst|net)\s+"',text)
    statements=re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;',text)
    need(starts and len(starts)==len(statements),'Incomplete or empty mapped statements')
    instances={};nets={}
    for body in statements:
        match=re.match(r'\s*(inst|net)\s+"([^"\n]+)"',body);need(match is not None,'Unrecognized mapped statement')
        kind,name=match.groups();target=instances if kind=='inst' else nets
        need(name not in target,'Duplicate mapped statement');target[name]=body.strip()
    if full:
        need(len(instances)==3603 and len(nets)==8657,'Original mapped inventory changed')
    return instances,nets

def part(instances,nets,seeds,stats_path=None):
    selected=set(seeds)
    frontier={(comp,'CE') for comp in seeds}
    for depth in range(3):
        incoming={name for name,body in nets.items() if any(kind=='inpin' and (comp,pin) in frontier for kind,comp,pin in PIN.findall(body))}
        following=set()
        for name in incoming:
            for kind,comp,pin in PIN.findall(nets[name]):
                if kind!='outpin' or comp not in instances:
                    continue
                selected.add(comp)
                if pin not in ['X','Y']:
                    continue
                direct='F' if pin=='X' else 'G'
                mux='FXMUX::F' if pin=='X' else 'GYMUX::G'
                # Follow only the LUT slot driving this output. A physical F5/FX
                # mux conservatively retains both LUTs and BX/BY select inputs.
                pins=[direct+str(i) for i in range(1,5)] if mux in instances[comp].split() else ['F'+str(i) for i in range(1,5)]+['G'+str(i) for i in range(1,5)]+['BX','BY']
                following.update((comp,p) for p in pins)
        frontier=following
    selected_nets={name for name,body in nets.items() if any(comp in selected for _,comp,_ in PIN.findall(body))}
    # Preserve immediate source bodies for every selected whole net.
    for name in selected_nets:
        selected.update(comp for kind,comp,_ in PIN.findall(nets[name]) if kind=='outpin' and comp in instances)
    text='\n\n'.join([instances[name] for name in sorted(selected)]+[nets[name] for name in sorted(selected_nets)])+'\n'
    if stats_path is not None:
        save(stats_path,dict(components=len(selected),nets=len(selected_nets),bytes=len(text.encode()),seedComponents=sorted(seeds),scope='CE first, then actual driving LUT-slot input edges only; no unrelated seed data-LUT traversal'))
    need(len(selected)<=400 and len(selected_nets)<=700 and len(text.encode())<=3000000,'Fixed component/net/text part bound exceeded; no truncation')
    nodes=[]
    for comp in sorted(selected):
        for slot,logical,equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)',instances[comp]):
            bindings={}
            for name in selected_nets:
                for kind,target,pin in PIN.findall(nets[name]):
                    if kind=='inpin' and target==comp and re.fullmatch(slot+r'[1-4]',pin):
                        need(pin not in bindings,'Multiply bound LUT pin');bindings[pin]=name
            nodes.append(dict(component=comp,slot=slot,logical=logical,equation=equation,inputNetBindings=bindings))
    return text,dict(components=sorted(selected),nets=sorted(selected_nets),bytes=len(text.encode()),sha256=sha(text.encode()),luts=nodes,scope='Seed register components, three upstream CE and driving-LUT-slot input layers, whole incident nets and immediate source bodies; no downstream closure or truth evaluation')

def self_test(output):
    rows=[]
    fixtures=[('complete records','inst "a" "SLICEL", cfg " F:logic:#LUT:D=A1 ";\nnet "n", inpin "a" F1;',True),
              ('empty export','',False),('incomplete net','inst "a" "SLICEL";\nnet "n"',False),
              ('duplicate instance','inst "a" "SLICEL";\ninst "a" "SLICEL";',False),
              ('duplicate net','inst "a" "SLICEL";\nnet "n";\nnet "n";',False)]
    for name,text,expected in fixtures:
        error=None
        try:
            parse_xdl(text);accepted=True
        except ValueError as exc:
            accepted=False;error=str(exc)
        rows.append(dict(name=name,expected=expected,accepted=accepted,error=error,passed=accepted==expected))
    for name,count,expected in [('within net bound',700,True),('net cap not silently raised',701,False)]:
        instances={'a':'inst "a" "SLICEL";'}
        nets={str(i):'net "'+str(i)+'", inpin "a" F1;' for i in range(count)}
        error=None
        try:
            part(instances,nets,{'a'});accepted=True
        except ValueError as exc:
            accepted=False;error=str(exc)
        rows.append(dict(name=name,expected=expected,accepted=accepted,error=error,passed=accepted==expected))
    for mux,expect_far in [('F',False),('FX',True)]:
        instances={'seed':'inst "seed" "SLICEL";',
                   'driver':'inst "driver" "SLICEL", cfg " FXMUX::'+mux+' F:lo:#LUT:D=A1 G:hi:#LUT:D=A1 ";',
                   'branch':'inst "branch" "SLICEL", cfg " FXMUX::F F:branch:#LUT:D=A1 ";',
                   'near':'inst "near" "SLICEL";', 'far':'inst "far" "SLICEL";'}
        nets={'ce':'net "ce", outpin "driver" X, inpin "seed" CE;',
              'lo':'net "lo", outpin "near" XQ, inpin "driver" F1;',
              'hi':'net "hi", outpin "branch" X, inpin "driver" G1;',
              'far':'net "far", outpin "far" XQ, inpin "branch" F1;'}
        _,index=part(instances,nets,{'seed'})
        actual='far' in index['components']
        rows.append(dict(name='Exact output mux token '+mux,expectedFarBranch=expect_far,observedFarBranch=actual,passed=actual==expect_far))
    save(output,rows);need(all(x['passed'] for x in rows),'Hosted parser/bound controls failed')

def baseline(output):
    output.mkdir(parents=True, exist_ok=False)
    artifact = 14062675697
    metadata = json.loads(subprocess.check_output(['gh', 'api', 'repos/secprog/sd2snes/actions/artifacts/' + str(artifact)]))
    expected = 'c49567c870dce5e5d162849f2df9907d08eab5c7c50a11b88426673dd1ad7cc6'
    need(metadata['id'] == artifact and metadata['workflow_run']['id'] == 43467561223
         and metadata['workflow_run']['head_sha'] == 'f4bcfe872f4c10f067fd1d6eca72882fa23b5b26'
         and metadata['size_in_bytes'] == 1320091 and metadata['digest'] == 'sha256:' + expected and not metadata['expired'],
         'Best measured baseline API identity changed')
    raw = subprocess.check_output(['gh', 'api', 'repos/secprog/sd2snes/actions/artifacts/' + str(artifact) + '/zip'])
    need(len(raw) == 1320091 and sha(raw) == expected, 'Best baseline ZIP changed')
    wanted = {'native-reports/main.par': '2c98994def19078e17b2e1fda065d2863aa953a14d8cf0c3d2cdbcef56c45893',
              'native-reports/main.twr': '4c925afed46c3f520950a9b0711e89f2e6795dbbda696dc8e0e7bab09900b5a8'}
    found = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            if info.filename in wanted:
                need(info.filename not in found and info.file_size <= 3000000, 'Duplicate/oversize baseline report'); found.add(info.filename)
                data = archive.read(info); need(sha(data) == wanted[info.filename] and b'\0' not in data, 'Baseline report hash/text changed')
                data.decode('utf-8'); (output / PurePosixPath(info.filename).name).write_bytes(data)
    need(found == set(wanted), 'Best baseline reports missing')
    save(output / 'artifact.json', metadata)



def placed(body):
    match=re.search(r',\s*placed\s+([^\s,]+)\s+([^\s,]+)\s*,',body)
    return dict(tile=match[1],site=match[2]) if match else None

SPARE_FIELDS=['FFX::#OFF','FFY::#OFF','DXMUX::#OFF','DYMUX::#OFF','BXINV::#OFF','BYINV::#OFF',
              'F5USED::#OFF','FXUSED::#OFF','CYINIT::#OFF','CYSELF::#OFF','CYSELG::#OFF','COUTUSED::#OFF']

def observed_spare_fields(config):
    tokens=set(config.split())
    return all(x in tokens for x in SPARE_FIELDS) and not any(x in config for x in ['#RAM','#SRL','#ROM'])

def placement_controls(path):
    rows=[]
    for name,text,expected in [
        ('actual placement form','inst "a" "SLICEL",placed R13C16 SLICE_X31Y38 , cfg " ";',dict(tile='R13C16',site='SLICE_X31Y38')),
        ('spaced placement','inst "a" "SLICEL", placed   R13C16  SLICE_X31Y38 , cfg " ";',dict(tile='R13C16',site='SLICE_X31Y38')),
        ('unplaced is not placed','inst "a" "SLICEL", unplaced , cfg " ";',None),
        ('missing site not parsed','inst "a" "SLICEL",placed R13C16 , cfg " ";',None)]:
        actual=placed(text);rows.append(dict(name=name,expected=expected,actual=actual,passed=actual==expected))
    fixture=' '.join(SPARE_FIELDS)
    cases=[('all explicit fields',fixture,True),
        ('occupied FFX',fixture.replace('FFX::#OFF','FFX:actual:#FF'),False),
        ('occupied FFY',fixture.replace('FFY::#OFF','FFY:actual:#FF'),False),
        ('BX already used',fixture.replace('BXINV::#OFF','BXINV::BX'),False),
        ('carry already used',fixture.replace('CYINIT::#OFF','CYINIT::BX'),False),
        ('F5 already used',fixture.replace('F5USED::#OFF','F5USED::0'),False),
        ('RAM resource',fixture+' F:ram:#RAM:16',False),
        ('SRL resource',fixture+' F:srl:#SRL16E',False),
        ('token prefix cannot qualify',fixture.replace('FFY::#OFF','FFY::#OFF_MORE'),False)]
    for name,text,expected in cases:
        actual=observed_spare_fields(text);rows.append(dict(name=name,expected=expected,actual=actual,passed=actual==expected))
    save(path,rows);need(all(x['passed'] for x in rows),'Hosted placement/field controls failed')
    
def inspect(archive_path,api,output):
    output.mkdir(parents=True,exist_ok=False)
    self_test(output/'controls.json')
    placement_controls(output/'placement-controls.json')
    instances,nets=load_original(archive_path,api)
    baseline_dir=output/'original-reports';baseline(baseline_dir)
    with zipfile.ZipFile(io.BytesIO(archive_path.read_bytes())) as archive:
        entries=[x for x in archive.infolist() if PurePosixPath(x.filename).name=='main.pcf' and not x.is_dir()]
        need(len(entries)==1 and entries[0].file_size==147838,'Original PCF entry changed')
        pcf=archive.read(entries[0])
        need(sha(pcf)=='16985854878afc6eaa628da2d46bbf9102b73f12e38d6c7b14f36a308ccbf060' and b'\0' not in pcf,'Original retained PCF identity changed')
        pcf.decode('utf-8');(output/'retained-main.pcf').write_bytes(pcf)
    occupancy=[];ffs=[];site_owners={}
    for comp,raw in instances.items():
        position=placed(raw)
        if position and position['site'].startswith('SLICE_'):
            need(position['site'] not in site_owners,'Ambiguous occupied slice');site_owners[position['site']]=comp
            occupancy.append(dict(component=comp,**position,recordSha256=sha(raw.encode())))
        for slot,logical in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)',raw):
            ffs.append(dict(component=comp,slot=slot,logical=logical,placement=position))
    inv=json.dumps(occupancy,indent=2)+'\n';need(len(inv.encode())<=3000000,'Complete placed inventory exceeds text cap; no truncation')
    (output/'all-placed-slice-inventory.json').write_text(inv)
    inv=json.dumps(ffs,indent=2)+'\n';need(len(inv.encode())<=3000000,'Complete FF metadata inventory exceeds cap; no truncation')
    (output/'all-slice-ff-placement-inventory.json').write_text(inv)
    def exact_ff(logical):
        rows=[x for x in ffs if x['logical']==logical]
        need(len(rows)==1,'Exact timing FF alias unavailable: '+logical)
        return rows[0]
    def retain(label,seeds):
        raw,index=part(instances,nets,seeds,output/(label+'-collection-stats.json'))
        (output/(label+'-raw.txt')).write_text(raw);save(output/(label+'-index.json'),index)
        return dict(name=label,components=len(index['components']),nets=len(index['nets']),bytes=index['bytes'],sha256=index['sha256'])
    twr=(baseline_dir/'main.twr').read_text();endpoint_rows=[];reports=[];unresolved=[]
    blocks=re.split(r'(?=Slack(?:\s+\([^)]*\))?:)',twr)
    for block in blocks:
        slack=re.match(r'Slack(?:\s+\(([^)]*)\))?:\s*([+-]?\d+(?:\.\d+)?)ns',block)
        if not slack or float(slack[2])>=0:
            continue
        src=re.search(r'Source:\s*([^\r\n]+?)\s+\(FF\)',block)
        dst=re.search(r'Destination:\s*([^\r\n]+?)\s+\(FF\)',block)
        if not src or not dst:
            unresolved.append(dict(source=src[1] if src else None,destination=dst[1] if dst else None,error='Not a complete FF endpoint record'));continue
        try:
            source=exact_ff(src[1]);destination=exact_ff(dst[1])
        except ValueError as error:
            unresolved.append(dict(source=src[1],destination=dst[1],error=str(error)));continue
        fragment=block.split('Maximum Data Path:',1)[-1].split('Total ',1)[0]
        sites=re.findall(r'(?m)^\s*(SLICE_X\d+Y\d+)\.[A-Za-z0-9]+\s+',fragment)
        label='critical-'+str(len(endpoint_rows))
        reports.append(retain(label,{source['component'],destination['component']}))
        endpoint_rows.append(dict(label=label,slackNs=float(slack[2]),source=source,destination=destination,
            reportedSourceSite=sites[0] if sites else None,reportedDestinationSite=sites[-1] if sites else None,
            sourceMapSiteMatchesReported=bool(sites and source['placement'] and sites[0]==source['placement']['site']),
            destinationMapSiteMatchesReported=bool(sites and destination['placement'] and sites[-1]==destination['placement']['site'])))
    save(output/'critical-endpoint-placement.json',endpoint_rows);save(output/'unresolved-critical-endpoints.json',unresolved)
    targets=[exact_ff('snes_dma/dma_r_4_1'),exact_ff('snes_dma/dma_r_4_6')]
    target_comps={x['component'] for x in targets}
    ce_nets=[(name,raw) for name,raw in nets.items() if any(direction=='inpin' and comp in target_comps and pin=='CE' for direction,comp,pin in PIN.findall(raw))]
    need(len(ce_nets)==1,'Two target FFs do not have one actual shared CE net')
    drivers=[(comp,pin) for direction,comp,pin in PIN.findall(ce_nets[0][1]) if direction=='outpin' and comp in instances]
    need(len(drivers)==1,'Target CE driver not unique')
    driver,driver_pin=drivers[0];where=placed(instances[driver]);need(where is not None,'CE driver placement absent')
    tile=re.fullmatch(r'R(\d+)C(\d+)',where['tile']);need(tile is not None,'Unknown original CLB tile notation')
    row,col=map(int,tile.groups());neighbors=[];spare=[]
    for delta_row in [-1,0,1]:
        for delta_col in [-1,0,1]:
            name='R'+str(row+delta_row)+'C'+str(col+delta_col)
            seeds={x['component'] for x in occupancy if x['tile']==name}
            label='neighbor-'+name
            reports.append(retain(label,seeds));neighbors.append(dict(tile=name,seedComponents=sorted(seeds)))
            for comp in sorted(seeds):
                config=instances[comp]
                if observed_spare_fields(config):
                    spare.append(dict(component=comp,placement=placed(config),recordSha256=sha(config.encode()),
                        observedEmptyFields=SPARE_FIELDS,limits='Configuration fields only; not a legal-packing/capacity/safe-placement proof. Other CLB/global requirements and all critical-path impact still require review and hosted validation.'))
    save(output/'observed-spare-ff-fields.json',spare)
    result=dict(sourceRun=RUN,sourceHead=HEAD,sourceArtifact=ARTIFACT,sourceZipBytes=ZIP_SIZE,sourceZipSha256=ZIP_SHA,
        mappedXdlBytes=XDL_SIZE,mappedXdlSha256=XDL_SHA,totalInstances=len(instances),totalNets=len(nets),
        sourceProductionVerilogTree='893e807029df25af8263fd63fa71dadabf02b0d0',placedSliceRecords=len(occupancy),
        sliceFfMetadataRecords=len(ffs),allPublishedNegativeEndpointParts=len(endpoint_rows),unresolvedEndpoints=unresolved,
        allPublishedEndpointSitesMatch=all(x['sourceMapSiteMatchesReported'] and x['destinationMapSiteMatchesReported'] for x in endpoint_rows),
        targets=targets,actualTargetCeNet=ce_nets[0][0],actualCeDriver=dict(component=driver,pin=driver_pin,placement=where),
        neighborClbs=neighbors,observedSpareFieldRecords=spare,parts=reports,collectionOnly=True,
        noGenerationConversionParTraceProofSimulationOrBooleanEvaluation=True,originalNativeStillFailure=True,
        limits='Only complete placed metadata and declared bounded raw parts from original MAP export. All published negative endpoints, not all timing paths. Spare fields are not legal-capacity proof; no source/constraint/native candidate selected or timing/whole-mapped/I/O/hardware qualification.')
    save(output/'inspection-result.json',result)
    need(not unresolved and len(endpoint_rows)==15,'All original published negative endpoints not resolved; raw/metadata retained')
    need(all(any(x['destination']['logical']==target['logical'] and x['destinationMapSiteMatchesReported'] for x in endpoint_rows) for target in targets),'Selected DMA target MAP/reported positions not reconciled')
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    need(len(sys.argv)==4,'Usage: ORIGINAL_DESIGN_ZIP API_DIRECTORY OUTPUT')
    inspect(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
