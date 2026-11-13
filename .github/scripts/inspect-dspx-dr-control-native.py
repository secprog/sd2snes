#!/usr/bin/env python3
"""GitHub-only bounded inspection of one retained DSPX mapping; no generation."""
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
ROLES={'F1':'SNES_WR_end','F2':'DSPX_A0','F3':'dspx_dp_enable','F4':'dspx_enable'}


def need(value,message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')


def truth(expression,values):
    need(expression.startswith('D='),'Missing LUT expression')
    text=expression[2:];tokens=re.findall(r'A[1-4]|[01()+*~]',text)
    need(''.join(tokens)==text,'Unknown LUT expression token')
    at=0
    def atom():
        nonlocal at
        need(at<len(tokens),'Incomplete LUT expression')
        token=tokens[at];at+=1
        if token=='~':
            return not atom()
        if token=='(':
            value=disjunction();need(at<len(tokens) and tokens[at]==')','Unbalanced LUT expression');at+=1;return value
        need(token in values or token in ['0','1'],'Unexpected LUT atom')
        return values[token] if token in values else token=='1'
    def conjunction():
        nonlocal at
        value=atom()
        while at<len(tokens) and tokens[at]=='*':
            at+=1;right=atom();value=value and right
        return value
    def disjunction():
        nonlocal at
        value=conjunction()
        while at<len(tokens) and tokens[at]=='+':
            at+=1;right=conjunction();value=value or right
        return value
    value=disjunction();need(at==len(tokens),'Trailing LUT expression');return value


def request_table(expression,roles):
    need(roles==ROLES,'Original four input net bindings changed')
    rows=[]
    for mask in range(16):
        values={'A'+str(i+1):bool(mask&(1<<i)) for i in range(4)}
        pins={roles['F'+str(i+1)]:values['A'+str(i+1)] for i in range(4)}
        expected=pins['SNES_WR_end'] and not pins['DSPX_A0'] and not pins['dspx_dp_enable'] and pins['dspx_enable']
        result=truth(expression,values)
        rows.append(dict(inputs=pins,expected=expected,observed=result,matched=result==expected))
    need(all(row['matched'] for row in rows),'Actual request LUT changes CPU/DP/strobe/A0 behavior')
    return rows


def self_test(output):
    equation='D=(A1*(~A2*(~A3*A4)))'
    cases=[('actual four input function',equation,ROLES,True),
           ('DP isolation removed','D=(A1*(~A2*A4))',ROLES,False),
           ('chip selection removed','D=(A1*(~A2*~A3))',ROLES,False),
           ('A0 polarity reversed','D=(A1*(A2*(~A3*A4)))',ROLES,False),
           ('unknown expression','D=eval(A1)',ROLES,False),
           ('wrong source pin binding',equation,{**ROLES,'F3':'other'},False)]
    rows=[]
    for name,text,roles,expected in cases:
        error=None
        try:
            request_table(text,roles);accepted=True
        except ValueError as failure:
            accepted=False;error=str(failure)
        rows.append(dict(name=name,expected=expected,accepted=accepted,error=error,passed=accepted==expected))
    save(output,rows);need(all(row['passed'] for row in rows),'Hosted truth/binding controls failed')


def inspect(archive_path,api,output):
    output.mkdir(parents=True,exist_ok=False)
    self_test(output/'controls.json')
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
    starts=re.findall(r'(?m)^\s*(inst|net)\s+"',text)
    statements=re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;',text)
    need(len(starts)==len(statements),'Incomplete mapped statements')
    instances={};nets={}
    for body in statements:
        match=re.match(r'\s*(inst|net)\s+"([^"\n]+)"',body);need(match is not None,'Unrecognized mapped statement')
        kind,name=match.groups();target=instances if kind=='inst' else nets
        need(name not in target,'Duplicate mapped statement');target[name]=body.strip()
    need(len(instances)==3603 and len(nets)==8657,'Mapped inventory changed')
    target='snes_dspx/dr_cpu_request';body=instances[target]
    luts=re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)',body)
    request=[(slot,name,expression) for slot,name,expression in luts if name=='snes_dspx/dr_request_lut']
    need(len(request)==1 and request[0][0]=='F' and 'FXMUX::F' in body,'Actual request LUT not observed')
    roles={}
    for name,raw_net in nets.items():
        for kind,component,pin in PIN.findall(raw_net):
            if kind=='inpin' and component==target and pin in ROLES:
                need(pin not in roles,'Multiple nets on request input');roles[pin]=name
    table=request_table(request[0][2],roles)
    request_outputs=[name for name,statement in nets.items() if ('outpin',target,'X') in PIN.findall(statement)]
    need(request_outputs==[target],'Actual request output net not observed')
    request_consumers=[dict(component=component,pin=pin) for kind,component,pin in PIN.findall(nets[target])
                       if kind=='inpin' and component in instances]
    need(request_consumers,'Request LUT has no mapped consumers')
    source_parts=[('request',{target})];mode=[]
    for bit in [10,12]:
        logical='snes_dspx/regs_sr_'+str(bit)
        sources=[(name,slot) for name,statement in instances.items()
                 for slot,signal in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)',statement) if signal==logical]
        need(len(sources)==1,'Original status FF not uniquely observed')
        component,slot=sources[0];outpin='XQ' if slot=='FFX' else 'YQ'
        need(slot+'_INIT_ATTR::INIT0' in instances[component] and 'CLKINV::CLK' in instances[component],
             'Status FF initialization/clock polarity changed')
        source_nets=[name for name,statement in nets.items() if ('outpin',component,outpin) in PIN.findall(statement)]
        need(len(source_nets)==1,'Original status source net not unique')
        uses=[]
        for kind,consumer,pin in PIN.findall(nets[source_nets[0]]):
            if kind=='inpin' and re.fullmatch(r'[FG][1-4]',pin) and consumer in instances:
                for lut_slot,signal,equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)',instances[consumer]):
                    if lut_slot==pin[0] and signal.startswith('snes_dspx/regs_dr'):
                        uses.append(dict(component=consumer,pin=pin,logical=signal,equation=equation))
        need(uses,'Status bit has no direct named DR logic consumer in mapped design')
        mode.append(dict(statusBit=bit,sourceComponent=component,sourceSlot=slot,sourceNet=source_nets[0],directDrLutUses=uses))
        source_parts.append(('mode-'+str(bit),{component}|{use['component'] for use in uses}))
    parts=[]
    for label,seeds in source_parts:
        selected=set(seeds)
        selected_nets={name for name,statement in nets.items() if any(component in selected for _,component,_ in PIN.findall(statement))}
        for name in selected_nets:
            selected.update(component for kind,component,_ in PIN.findall(nets[name]) if kind=='outpin' and component in instances)
        raw_text='\n\n'.join([instances[name] for name in sorted(selected)]+[nets[name] for name in sorted(selected_nets)])+'\n'
        need(len(selected)<=400 and len(selected_nets)<=1200 and len(raw_text.encode())<=3000000,'Fixed raw part bound exceeded; no truncation')
        (output/(label+'-raw.txt')).write_text(raw_text,encoding='utf-8')
        parts.append(dict(name=label,components=sorted(selected),nets=sorted(selected_nets),bytes=len(raw_text.encode()),sha256=sha(raw_text.encode())))
    lane_aliases=[name for name,statement in instances.items() if 'dr_lane_lut' in statement or 'dr_cpu_high' in statement]
    save(output/'inspection-result.json',dict(sourceRun=RUN,sourceHead=HEAD,sourceArtifact=ARTIFACT,sourceZipSha256=ZIP_SHA,
         mappedXdlBytes=XDL_SIZE,mappedXdlSha256=XDL_SHA,totalInstances=len(instances),totalNets=len(nets),
         requestPhysicalComponent=target,requestLogicalLut=request[0][1],requestEquation=request[0][2],requestInputBindings=roles,
         actualRequestTruthRows=table,requestOutputNet=request_outputs[0],requestConsumers=request_consumers,
         modeStatusObservations=mode,namedStandaloneLaneComponents=lane_aliases,parts=parts,
         originalRunStillFailure=True,noGenerationConversionParTraceOrSimulation=True,
         classification='Request is one actual four-input LUT under instance name without slash. Status bits10/12 remain connected to named DR combinational logic; no standalone two-input lane LUT survival claim.',
         limits='Bounded mapped inspection and actual request truth only. Source DR behavior proof remains separately accepted; no whole mapped equivalence, whole lane function, timing-pass, electrical or hardware qualification.'))
    print('Accepted retained mapped inspection:16actualrequest rows, sourceDP/chip/strobe/A0bindings, both status bits inDRlogic; original native/timing/analysis failures unchanged')


if __name__=='__main__':
    need(len(sys.argv)==4,'Usage: DESIGN_ZIP API_DIRECTORY OUTPUT')
    inspect(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
