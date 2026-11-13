#!/usr/bin/env python3
"""GitHub-only bounded inspection of adopted baseline DMA register CE logic; no generation or Boolean evaluation."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
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

def part(instances,nets,seeds):
    selected=set(seeds);frontier=set(seeds)
    for depth in range(3):
        incoming={name for name,body in nets.items() if any(kind=='inpin' and comp in frontier and (pin=='CE' or re.fullmatch(r'[FG][1-4]',pin)) for kind,comp,pin in PIN.findall(body))}
        following=set()
        for name in incoming:
            for kind,comp,pin in PIN.findall(nets[name]):
                if kind=='outpin' and comp in instances:
                    selected.add(comp)
                    if pin in ['X','Y']:
                        following.add(comp)
        frontier=following
    selected_nets={name for name,body in nets.items() if any(comp in selected for _,comp,_ in PIN.findall(body))}
    # Preserve immediate source bodies for every selected whole net.
    for name in selected_nets:
        selected.update(comp for kind,comp,_ in PIN.findall(nets[name]) if kind=='outpin' and comp in instances)
    text='\n\n'.join([instances[name] for name in sorted(selected)]+[nets[name] for name in sorted(selected_nets)])+'\n'
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
    return text,dict(components=sorted(selected),nets=sorted(selected_nets),bytes=len(text.encode()),sha256=sha(text.encode()),luts=nodes,scope='Seed register components, three upstream CE/LUT input layers, whole incident nets and immediate source bodies; no downstream closure or truth evaluation')

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
    save(output,rows);need(all(x['passed'] for x in rows),'Hosted parser/bound controls failed')

def inspect(archive_path,api,output):
    output.mkdir(parents=True,exist_ok=False)
    self_test(output/'controls.json')
    instances,nets=load_original(archive_path,api)
    inventory=[]
    for comp,body in instances.items():
        for slot,logical in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)',body):
            if not logical.startswith('snes_dma/dma_r'):
                continue
            match=re.fullmatch(r'snes_dma/dma_r_(\d+)_(\d+)(?:_.*)?',logical)
            if match is None:
                match=re.fullmatch(r'snes_dma/dma_r<(\d+)><(\d+)>(?:_.*)?',logical)
            inventory.append(dict(component=comp,slot=slot,logical=logical,bank=int(match[1]) if match else None,bit=int(match[2]) if match else None))
    save(output/'all-dma-register-ff-inventory.json',inventory)
    reports=[];observed=[]
    for bank in [4,5,6]:
        rows=[x for x in inventory if x['bank']==bank]
        seeds={x['component'] for x in rows}
        body,index=part(instances,nets,seeds)
        (output/('dma-bank-'+str(bank)+'-raw.txt')).write_text(body)
        index['bank']=bank;index['registers']=rows
        bindings=[]
        for row in rows:
            comp=row['component'];pins={}
            for name,net in nets.items():
                for kind,target,pin in PIN.findall(net):
                    if kind=='inpin' and target==comp and pin in ['CLK','CE','SR','BX','BY']:
                        need(pin not in pins,'Multiple nets on register control pin');pins[pin]=name
            bindings.append(dict(**row,controlPins=pins,config=instances[comp]))
        index['actualRegisterControlPins']=bindings
        save(output/('dma-bank-'+str(bank)+'-index.json'),index)
        reports.append(index);observed.extend(rows)
    save(output/'inspection-result.json',dict(sourceRun=RUN,sourceHead=HEAD,sourceArtifact=ARTIFACT,sourceZipBytes=ZIP_SIZE,
         sourceZipSha256=ZIP_SHA,mappedXdlBytes=XDL_SIZE,mappedXdlSha256=XDL_SHA,totalInstances=len(instances),totalNets=len(nets),
         sourceProductionVerilogTree='893e807029df25af8263fd63fa71dadabf02b0d0',banks=[dict(bank=x['bank'],components=len(x['components']),nets=len(x['nets']),rawBytes=x['bytes'],rawSha256=x['sha256'],registerBits=[r['bit'] for r in x['registers']]) for x in reports],
         actualRegisterBits=observed,collectionOnly=True,originalNativeStillFailure=True,noGenerationConversionParTraceProofOrSimulation=True,
         limits='Read-only bounded actual baseline mapping to plan a write-enable repair. No source behavior proof, Boolean evaluation, timing improvement, whole mapped equivalence or I/O/hardware qualification.'))
    need(all({x['bit'] for x in observed if x['bank']==bank}==set(range(8)) for bank in [4,5,6]),'Exact eight original bits not observed in every selected bank; complete raw/index already retained')
    need(all(x['controlPins'].get('CLK')=='CLK2' and 'CLKINV::CLK' in x['config'] for report in reports for x in report['actualRegisterControlPins']),'Original register clock not observed; complete raw retained')
    print('Collected original baseline DMA banks4/5/6: all24 source bits, actual clock/CE pins and bounded upstream LUT input bindings. Original native/timing failures unchanged.')

if __name__=='__main__':
    need(len(sys.argv)==4,'Usage: ORIGINAL_DESIGN_ZIP API_DIRECTORY OUTPUT')
    inspect(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
