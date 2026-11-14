#!/usr/bin/env python3
"""GitHub-only structural/conversion diagnostic; no synthesis, PAR or TRACE."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import zipfile

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

IMAGE='sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8'
SRC='snes_dma/dma_r_4_1'
DST='snes_mcu_cmd/N185'
MOVES={
    'BUS_DATA<1>':('inpin','BX'),
    'BUS_DATA<6>':('inpin','BY'),
    'CLK2':('inpin','CLK'),
    'SNES_reset_strobe':('inpin','SR'),
    'snes_dma/dma_r_4_not0001':('inpin','CE'),
    'snes_dma/dma_r_4_1':('outpin','XQ'),
    'snes_dma/dma_r_4_6':('outpin','YQ'),
}
STATE_KEYS=['BXINV','BYINV','CEINV','CLKINV','DXMUX','DYMUX','FFX','FFX_INIT_ATTR',
            'FFX_SR_ATTR','FFY','FFY_INIT_ATTR','FFY_SR_ATTR','SRINV','SYNC_ATTR']
PIN=re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')

def need(value,message):
    if not value:
        raise ValueError(message)

def sha(b):
    return hashlib.sha256(b).hexdigest()

def save(path,value):
    raw=(json.dumps(value,indent=2)+'\n').encode()
    need(len(raw)<=3000000,'Derived JSON file cap exceeded; no truncation')
    Path(path).write_bytes(raw)

def canonical_body(text):
    # Independently locate/validate all leading comment lines.
    lines=text.splitlines(keepends=True);first=None
    for index,line in enumerate(lines):
        if line.startswith('design '):
            first=index;break
        need(not line.strip() or line.lstrip().startswith('#'),'Unknown pre-design text')
    need(first is not None,'No design statement')
    return ''.join(lines[first:]).strip()

def configuration_tokens(value):
    # Preserve escaped spaces, quotes and backslashes as opaque token bytes.
    # No unescaping, expression interpretation or Boolean evaluation.
    matches=list(re.finditer(r'(?:\\.|[^\s\\])+',value,re.S));cursor=0;tokens=[]
    for match in matches:
        need(not value[cursor:match.start()].strip(),'Unparsed configuration escape')
        tokens.append(match[0]);cursor=match.end()
    need(not value[cursor:].strip(),'Incomplete configuration escape')
    need(all(re.match(r'^[A-Za-z0-9_]+:',x) for x in tokens),'Unknown config token grammar')
    return tokens

def lexical_tokens(value):
    # Quoted CFG values are single lexer tokens, so apparent "inpin" words
    # inside quoted properties cannot become electrical net-pin entries.
    matches=list(re.finditer(r'"(?:\\.|[^"\\])*"|(?:\\.|[^\s"\\,;])+|[,;]',value,re.S))
    cursor=0;tokens=[]
    for match in matches:
        need(not value[cursor:match.start()].strip(),'Unparsed quoted-token grammar')
        tokens.append(match[0]);cursor=match.end()
    need(not value[cursor:].strip(),'Incomplete quoted-token escape')
    return tokens

def parse(text,full=True,rejected=None):
    need('\0' not in text and text.isascii(),'Only actual ASCII XDL grammar accepted')
    # A semicolon inside a quoted property is not a record terminator.
    records=list(re.finditer(r'(?ms)^(design|inst|net)\s+"([^"\n]+)"(?:"(?:\\.|[^"\\])*"|[^";])*;',text))
    need(records,'Empty design')
    need(len(records)==len(re.findall(r'(?m)^(?:design|inst|net)\s+"',text)),
         'Incomplete or unparsed design-record boundary')
    cursor=0;raw={};instances={};nets={};design=[]
    for m in records:
        gap=text[cursor:m.start()]
        need(all(not line.strip() or line.lstrip().startswith('#') for line in gap.splitlines()),
             'Unparsed inter-record content')
        cursor=m.end();kind,name=m[1],m[2];body=m[0]
        need((kind,name) not in raw,'Duplicate complete design record');raw[kind,name]=body
        need(not re.search(r'\s',name),'Whitespace-bearing identifier outside reviewed grammar')
        try:
            if kind=='design':
                design.append(lexical_tokens(body));continue
            if kind=='inst':
                g=re.fullmatch(r'inst\s+"([^"]+)"\s+"([^"]+)"\s*,\s*(.*?)\s*,\s*cfg\s+"((?:\\.|[^"\\])*)"\s*;',body,re.S)
                need(g is not None,'Unknown complete instance grammar')
                where=' '.join(g[3].split());tokens=configuration_tokens(g[4])
                instances[name]=dict(type=g[2],placement=where,cfg=sorted(tokens))
            else:
                tokens=lexical_tokens(body);pins=[];residue=[];index=0
                while index<len(tokens):
                    token=tokens[index]
                    if token in ('outpin','inpin'):
                        need(index+2<len(tokens),'Incomplete actual net pin')
                        comp=tokens[index+1];pin=tokens[index+2]
                        need(re.fullmatch(r'"[^"\s\\]+"',comp) and re.fullmatch(r'[A-Za-z0-9_]+',pin),
                             'Unknown actual net-pin identifier grammar')
                        pins.append((token,comp[1:-1],pin));index+=3
                    elif token=='cfg':
                        need(index+1<len(tokens),'Incomplete net configuration')
                        config=tokens[index+1]
                        need(config.startswith('"') and config.endswith('"'),'Unquoted net configuration')
                        residue.extend(['cfg',configuration_tokens(config[1:-1])]);index+=2
                    else:
                        residue.append(token);index+=1
                need(len(pins)==len(set(pins)),'Duplicate actual net pin')
                nets[name]=dict(pins=sorted(pins),residue=json.dumps(residue,separators=(',',':')))
        except ValueError as problem:
            if rejected is not None:
                b=body.encode()
                save(str(rejected)+'-identity.json',dict(kind=kind,name=name,bytes=len(b),sha256=sha(b),
                     error=str(problem),wholeRecordRetained=len(b)<=3000000))
                if len(b)<=3000000:Path(str(rejected)+'-raw.txt').write_bytes(b)
            raise
    need(all(not line.strip() or line.lstrip().startswith('#') for line in text[cursor:].splitlines()),
         'Unknown trailing design data')
    need(len(design)==1,'Design header count changed')
    if full:
        need(len(instances)==3603 and len(nets)==8657,'Original full inventory changed')
    return dict(design=design,instances=instances,nets=nets),raw

def parser_controls(output):
    # Actual bounded original record, independently retained before this parser.
    actual_escaped='inst "snes_spi/Result<0>1_FRB" "SLICEL",placed R17C19 SLICE_X36Y30  ,\n  cfg " BXINV::BX BYINV::#OFF CEINV::CE CLKINV::CLK COUTUSED::0 CY0F::1\n       CY0G::0 CYINIT::BX CYSELF::F CYSELG::G DXMUX::1 DYMUX::1 F:snes_spi/Mcount_byte_cnt_r_lut<0>_INV_0:#LUT:D=~A1\n       F5USED::#OFF FFX:snes_spi/Result<0>1_FRB:#FF FFX_INIT_ATTR::INIT1\n       FFX_SR_ATTR::SRHIGH FFY:snes_spi/Result<1>1_FRB:#FF FFY_INIT_ATTR::INIT0\n       FFY_SR_ATTR::SRLOW FXMUX::FXOR FXUSED::#OFF G:snes_spi/Result<1>1_FRB_rt:#LUT:D=A1\n       _BEL_PROP::G:PK_PACKTHRU: GYMUX::GXOR REVUSED::#OFF SRINV::SR SYNC_ATTR::SYNC\n       XBUSED::#OFF XUSED::#OFF YBUSED::#OFF YUSED::#OFF C1VDD:ProtoComp532.C1VDD:\n       CYMUXF:snes_spi/Mcount_byte_cnt_r_cy<0>: CYMUXG:snes_spi/Mcount_byte_cnt_r_cy<1>:\n       GNDG:ProtoComp532.GNDG: XORF:snes_spi/Mcount_byte_cnt_r_xor<0>: XORG:snes_spi/Mcount_byte_cnt_r_xor<1>:\n       _INST_PROP::XDL_SHAPE_DESC:Shape_20:CARRY,A\\ carry\\ chain\\ starting\\ with\\ carry\\ mux\\ \\"snes_spi/Mcount_byte_cnt_r_cy<0>\\"\n       _INST_PROP::XDL_SHAPE_MEMBER:Shape_20:0,0 "\n  ;'
    base='design "main" xc3s400pq208-4 v3.2;\n'
    inst='inst "a" "SLICEL",placed R1C1 SLICE_X0Y0, cfg " F:f:#LUT:D=A1 ";\n'
    net='net "n", outpin "a" X, inpin "b" F1;\n'
    cases=[
        ('plain complete grammar',base+inst+net,True),
        ('actual escaped original carry-shape metadata',base+actual_escaped+'\n'+net,True),
        ('quoted pin text remains opaque',base+inst+'net "n", cfg " _PROP::inpin\\ \\"ignored\\"\\ BX ", outpin "a" X;\n',True),
        ('semicolon inside quoted CFG',base+inst.replace('F:f:#LUT:D=A1','_PROP::opaque;value')+net,True),
        ('empty export','',False),
        ('missing design',inst+net,False),
        ('incomplete instance',base+inst[:-3]+'\n'+net,False),
        ('duplicate instance',base+inst+inst+net,False),
        ('duplicate net',base+inst+net+net,False),
        ('duplicate actual pin',base+inst+'net "n", outpin "a" X, outpin "a" X;\n',False),
        ('unknown inter-record data',base+'CORRUPT\n'+inst+net,False),
        ('broken escaped string',base+inst.replace('D=A1 "',r'D=A1 \"')+net,False),
        ('unparsed trailing data',base+inst+net+'CORRUPT',False)]
    rows=[]
    for name,text,expected in cases:
        error=None;model=None
        try:model,_=parse(text,full=False);accepted=True
        except ValueError as problem:accepted=False;error=str(problem)
        passed=accepted==expected
        if name=='quoted pin text remains opaque' and accepted:
            passed=passed and model['nets']['n']['pins']==[('outpin','a','X')]
        if name=='actual escaped original carry-shape metadata' and accepted:
            tokens=model['instances']['snes_spi/Result<0>1_FRB']['cfg']
            passed=passed and len([x for x in tokens if x.startswith('_INST_PROP::XDL_SHAPE_DESC:')])==1
        rows.append(dict(name=name,expectedAcceptance=expected,accepted=accepted,passed=passed,error=error))
    save(output/'parser-controls.json',dict(controls=rows,passed=all(x['passed'] for x in rows),
         actualEscapedRecordBytes=len(actual_escaped.encode()),actualEscapedRecordSha256=sha(actual_escaped.encode())))
    need(all(x['passed'] for x in rows),'Hosted complete-record lexer controls failed')

def cfg_map(row):
    out={}
    for token in row['cfg']:
        key=token.split(':',1)[0]
        need(key not in out,'Ambiguous selected configuration key');out[key]=token
    return out

def expected_move(before):
    need(before['instances'][SRC]['type']==before['instances'][DST]['type']=='SLICEL','Original slice types changed')
    need(before['instances'][SRC]['placement']=='placed R11C15 SLICE_X29Y42','Original FF source site changed')
    need(before['instances'][DST]['placement']=='placed R13C16 SLICE_X31Y39','Reviewed destination site changed')
    source=cfg_map(before['instances'][SRC]);destination=cfg_map(before['instances'][DST])
    active={'BXINV':'BXINV::BX','BYINV':'BYINV::BY','CEINV':'CEINV::CE','CLKINV':'CLKINV::CLK',
            'DXMUX':'DXMUX::0','DYMUX':'DYMUX::0','FFX':'FFX:snes_dma/dma_r_4_1:#FF',
            'FFX_INIT_ATTR':'FFX_INIT_ATTR::INIT0','FFX_SR_ATTR':'FFX_SR_ATTR::SRLOW',
            'FFY':'FFY:snes_dma/dma_r_4_6:#FF','FFY_INIT_ATTR':'FFY_INIT_ATTR::INIT0',
            'FFY_SR_ATTR':'FFY_SR_ATTR::SRLOW','SRINV':'SRINV::SR','SYNC_ATTR':'SYNC_ATTR::SYNC'}
    need(set(active)==set(STATE_KEYS),'Incomplete declared state field specification')
    for key in STATE_KEYS:
        need(source[key]==active[key] and destination[key]==key+'::#OFF','Original field or spare capacity changed: '+key)
    for row in [source,destination]:
        need(all(row[key]==key+'::#OFF' for key in ['F5USED','FXUSED','CYINIT','CYSELF','CYSELG','COUTUSED','REVUSED','XBUSED','YBUSED']),
             'Carry/wide-mux/bypass side use not reviewed')
        need(row['F'].split(':',3)[2]=='#LUT' and row['G'].split(':',3)[2]=='#LUT','Co-packed logic is not ordinary LUT')
    for name,net in before['nets'].items():
        for direction,component,pin in net['pins']:
            if component==DST:
                need(pin not in ['BX','BY','CLK','CE','SR','XQ','YQ'],'Destination state pin already in use')
    result=copy.deepcopy(before)
    source_new=dict(source);destination_new=dict(destination)
    for key in STATE_KEYS:
        source_new[key]=key+'::#OFF';destination_new[key]=source[key]
    result['instances'][SRC]['cfg']=sorted(source_new.values())
    result['instances'][DST]['cfg']=sorted(destination_new.values())
    for name,(direction,pin) in MOVES.items():
        old=(direction,SRC,pin);new=(direction,DST,pin)
        pins=before['nets'][name]['pins']
        need(pins.count(old)==1 and new not in pins,'Original state pin binding changed: '+name)
        result['nets'][name]['pins']=sorted(new if x==old else x for x in pins)
    return result

def require_equal(actual,expected,label):
    need(actual['design']==expected['design'],label+': design header changed')
    need(set(actual['instances'])==set(expected['instances']),label+': instance inventory changed')
    need(set(actual['nets'])==set(expected['nets']),label+': net inventory changed')
    for key in ['instances','nets']:
        changed=[name for name,row in expected[key].items() if actual[key][name]!=row]
        need(not changed,label+': unexpected '+key+' records '+repr(changed[:8]))

def ff_contract(model,logical):
    hits=[]
    for name,row in model['instances'].items():
        for token in row['cfg']:
            m=re.fullmatch(r'(FFX|FFY):([^:]+):#FF',token)
            if m and m[2]==logical:hits.append((name,m[1],row))
    need(len(hits)==1,'Logical FF count/identity not preserved')
    name,slot,row=hits[0];cfg=cfg_map(row);data='BX' if slot=='FFX' else 'BY';out='XQ' if slot=='FFX' else 'YQ'
    bindings={}
    for pin,direction in [(data,'inpin'),(out,'outpin'),('CLK','inpin'),('CE','inpin'),('SR','inpin')]:
        names=[net for net,netrow in model['nets'].items() if (direction,name,pin) in netrow['pins']]
        need(len(names)==1,'Ambiguous moved state pin');bindings['D' if pin==data else 'Q' if pin==out else pin]=names[0]
    return dict(logical=logical,bindings=bindings,clock=cfg['CLKINV'],enable=cfg['CEINV'],
        reset=cfg['SRINV'],sync=cfg['SYNC_ATTR'],init=cfg[slot+'_INIT_ATTR'].split(':',1)[1],
        resetValue=cfg[slot+'_SR_ATTR'].split(':',1)[1],dataMode=cfg['DXMUX' if slot=='FFX' else 'DYMUX'])

def validate_move(before,after,label):
    require_equal(after,expected_move(before),label)
    a=[ff_contract(before,x) for x in ['snes_dma/dma_r_4_1','snes_dma/dma_r_4_6']]
    b=[ff_contract(after,x) for x in ['snes_dma/dma_r_4_1','snes_dma/dma_r_4_6']]
    need(a==b,'Moved FF logical D/Q/clock/reset/enable/init contract changed')
    return a

def indexes(raw,output,label):
    for kind in ['design','inst','net']:
        rows=[dict(name=name,bytes=len(body.encode()),sha256=sha(body.encode()))
              for (k,name),body in raw.items() if k==kind]
        save(output/(label+'-'+kind+'-record-index.json'),rows)

def bounded(raw,model,output,label):
    names={SRC,DST}
    for net in MOVES:
        for direction,component,pin in model['nets'][net]['pins']:
            if direction=='outpin':names.add(component)
    need(all(('inst',name) in raw for name in names),'Immediate driver body missing')
    text='\n\n'.join([raw['inst',x] for x in sorted(names)]+[raw['net',n] for n in sorted(MOVES)])+'\n'
    need(len(names)<=400 and len(MOVES)<=700 and len(text.encode())<=3000000,'Whole raw bound exceeded; no truncation')
    (output/(label+'-raw.txt')).write_text(text)
    save(output/(label+'-raw-index.json'),dict(components=sorted(names),nets=sorted(MOVES),bytes=len(text.encode()),sha256=sha(text.encode())))

def controls(before,output):
    expected=expected_move(before);rows=[]
    def case(name,mutate):
        changed=copy.deepcopy(expected);mutate(changed);error=None
        try:validate_move(before,changed,'negative '+name);accepted=True
        except ValueError as problem:accepted=False;error=str(problem)
        rows.append(dict(name=name,expectedAcceptance=False,accepted=accepted,error=error,passed=not accepted))
    for key,new in [('BXINV','BXINV::BX_B'),('BYINV','BYINV::BY_B'),
                    ('CLKINV','CLKINV::CLK_B'),('CEINV','CEINV::CE_B'),('SRINV','SRINV::SR_B'),
                    ('SYNC_ATTR','SYNC_ATTR::ASYNC'),('FFX_INIT_ATTR','FFX_INIT_ATTR::INIT1'),
                    ('FFX_SR_ATTR','FFX_SR_ATTR::SRHIGH'),('DXMUX','DXMUX::1'),('FFX','FFX::#OFF'),
                    ('FFY_INIT_ATTR','FFY_INIT_ATTR::INIT1'),('FFY_SR_ATTR','FFY_SR_ATTR::SRHIGH'),
                    ('DYMUX','DYMUX::1'),('FFY','FFY::#OFF')]:
        def mutate(model,key=key,new=new):
            row=cfg_map(model['instances'][DST]);row[key]=new;model['instances'][DST]['cfg']=sorted(row.values())
        case('changed '+key,mutate)
    for comp,key in [(SRC,'F'),(DST,'G')]:
        def mutate(model,comp=comp,key=key):
            row=cfg_map(model['instances'][comp]);row[key]+='CORRUPT';model['instances'][comp]['cfg']=sorted(row.values())
        case('co-packed LUT '+comp,mutate)
    other=next(name for name in before['instances'] if name not in [SRC,DST])
    case('unrelated placement',lambda x:x['instances'][other].update(placement='unplaced'))
    case('unrelated instance omitted',lambda x:x['instances'].pop(other))
    othernet=next(name for name in before['nets'] if name not in MOVES)
    case('unrelated net omitted',lambda x:x['nets'].pop(othernet))
    case('extra state copy',lambda x:x['instances'].update(extra=copy.deepcopy(x['instances'][DST])))
    case('data pin omitted',lambda x:x['nets']['BUS_DATA<1>']['pins'].remove(('inpin',DST,'BX')))
    case('duplicate pin',lambda x:x['nets']['BUS_DATA<1>']['pins'].append(('inpin',DST,'BX')))
    case('Q pin omitted',lambda x:x['nets']['snes_dma/dma_r_4_1']['pins'].remove(('outpin',DST,'XQ')))
    case('routing residue changed',lambda x:x['nets']['CLK2'].update(residue=x['nets']['CLK2']['residue']+' pip CORRUPT'))
    case('clock driver removed',lambda x:x['nets']['CLK2'].update(pins=[t for t in x['nets']['CLK2']['pins'] if t[0]!='outpin']))
    case('wrong logical data source',lambda x:x['nets']['BUS_DATA<6>']['pins'].append(('inpin',DST,'BX')))
    case('wrong Q output direction',lambda x:x['nets']['snes_dma/dma_r_4_6'].update(pins=[
        ('inpin',DST,'YQ') if t==('outpin',DST,'YQ') else t for t in x['nets']['snes_dma/dma_r_4_6']['pins']]))
    case('unrelated design header',lambda x:x.update(design=x['design']+['CORRUPT']))
    positive=validate_move(before,expected,'positive model')
    rows.insert(0,dict(name='complete expected relocation model',expectedAcceptance=True,accepted=True,passed=True))
    save(output/'structural-controls.json',dict(controls=rows,passed=all(x['passed'] for x in rows),ffContract=positive))
    need(all(x['passed'] for x in rows),'Structural negative control failed')

def load_original(archive,api,original):
    meta=json.loads((api/'artifact.json').read_text());jobs=json.loads((api/'jobs.json').read_text())['jobs']
    need(meta['id']==14062690690 and meta['workflow_run']['id']==43467561223
        and meta['workflow_run']['head_sha']=='f4bcfe872f4c10f067fd1d6eca72882fa23b5b26'
        and meta['size_in_bytes']==2520006 and meta['digest']=='sha256:fae12362d987524ba0f7713e563f82bd27940b3f8010e7e43d589a17fe3ae93c'
        and not meta['expired'],'Original design API identity changed')
    proof=next(x for x in jobs if x['id']==132030641690)
    native=next(x for x in jobs if x['id']==132030910778)
    need(all(x['head_sha']=='f4bcfe872f4c10f067fd1d6eca72882fa23b5b26'
             and x['run_attempt']==1 and x['status']=='completed' for x in [proof,native])
         and proof['conclusion']=='success' and native['conclusion']=='failure'
         and [x['number'] for x in native['steps'] if x['conclusion']=='failure']==[9,12],
         'Original proof/native provenance or outcome changed')
    raw=archive.read_bytes();need(len(raw)==2520006 and sha(raw)=='fae12362d987524ba0f7713e563f82bd27940b3f8010e7e43d589a17fe3ae93c','Original ZIP changed')
    wanted={'map.xdl':(4631153,'c3f1214ed604a032b9c045bbb5bd0f2ca32c6d53f6bc7ab46915d31a826af22e'),
            'main_map.ncd':(1178950,'494ce2a5f15a9c3ad4a3e65d1f6d71d326059684e783c23edc83d0559eb7fb37'),
            'main.pcf':(147838,'16985854878afc6eaa628da2d46bbf9102b73f12e38d6c7b14f36a308ccbf060')}
    found=set();seen=set()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        need(len(z.infolist())<=512,'Unexpected native ZIP inventory')
        for entry in z.infolist():
            path=PurePosixPath(entry.filename);mode=(entry.external_attr>>16)&0xffff
            need(not path.is_absolute() and '\\' not in entry.filename and ':' not in entry.filename
                and '..' not in path.parts and path.as_posix()==entry.filename.rstrip('/')
                and stat.S_IFMT(mode) in [0,stat.S_IFREG,stat.S_IFDIR],'Unsafe original ZIP path')
            need(entry.filename.casefold() not in seen,'Duplicate original ZIP path');seen.add(entry.filename.casefold())
            name=path.name
            if entry.is_dir() or name not in wanted:continue
            need(name not in found,'Duplicate retained input');found.add(name);b=z.read(entry)
            need((len(b),sha(b))==wanted[name],'Retained input bytes/hash changed')
            (original/name).write_bytes(b)
    need(found==set(wanted),'Retained original input missing')
    return {name:dict(bytes=n,sha256=h) for name,(n,h) in wanted.items()}

def captured(report,label,argv):
    result=subprocess.run(argv,capture_output=True)
    streams={}
    for name,b in [('stdout',result.stdout),('stderr',result.stderr)]:
        need(len(b)<=3000000 and b'\0' not in b,'Complete control/tool stream cap or text failed')
        b.decode('utf-8')
        for suffix in ['.raw','.txt']:(report/(label+'-'+name+suffix)).write_bytes(b)
        streams[name]=dict(bytes=len(b),sha256=sha(b),raw=label+'-'+name+'.raw',text=label+'-'+name+'.txt')
    save(report/(label+'-command.json'),dict(argv=argv,returncode=result.returncode,streams=streams,complete=True))
    need(result.returncode==0,'Owned Docker client command failed: '+label)
    return result

def tool(scratch,report,label,argv,help_only=False,expected_exit=0):
    name='dspx-relocation-'+os.environ['GITHUB_RUN_ID']+'-'+label
    gate='/scratch/go-'+label
    command=['docker','create','--name',name,'--user','0:0','--network','bridge','--mac-address','08:00:27:68:c9:35',
        '--volume',str(Path(os.environ['GITHUB_WORKSPACE']).resolve())+':/work:ro',
        '--volume',str(scratch.resolve())+':/scratch','--workdir','/scratch','--entrypoint','/bin/bash',IMAGE,
        '-c','set -euo pipefail; gate=$1; shift; while [[ ! -f "$gate" ]]; do sleep 0.05; done; exec "$@"','bash',gate,*argv]
    save(report/(label+'-intent.json'),dict(argv=command,toolArgv=argv,helpOnly=help_only))
    created=False;released=False
    try:
        identifier=captured(report,label+'-create',command).stdout.decode().strip();created=True
        created_json=json.loads(captured(report,label+'-inspect-created',['docker','inspect',name]).stdout)
        save(report/(label+'-created.json'),created_json)
        captured(report,label+'-start',['docker','start',name])
        live_json=json.loads(captured(report,label+'-inspect-live',['docker','inspect',name]).stdout);save(report/(label+'-live.json'),live_json)
        live,=live_json
        need(live['Id']==identifier and live['Image']==IMAGE and live['State']['Running'],'Owned converter not live')
        need(live['Config']['User']=='0:0' and live['Config']['WorkingDir']=='/scratch'
             and live['HostConfig']['NetworkMode']=='bridge'
             and live['NetworkSettings']['Networks']['bridge']['MacAddress']=='08:00:27:68:c9:35','Converter image/MAC/interface changed')
        need(live['Config']['Entrypoint']==['/bin/bash'] and live['Config']['Cmd']==command[command.index(IMAGE)+1:],
             'Unexpected actual converter command')
        expected_mounts={'/work':(str(Path(os.environ['GITHUB_WORKSPACE']).resolve()),False),
                         '/scratch':(str(scratch.resolve()),True)}
        need(len(live['Mounts'])==2 and all(m['Type']=='bind' and m['Destination'] in expected_mounts
             and (m['Source'],m['RW'])==expected_mounts[m['Destination']] for m in live['Mounts']),
             'Owned tool mount/source/read-only contract changed')
        need(not live['HostConfig']['Privileged'] and not live['HostConfig'].get('AutoRemove',False),
             'Owned tool privilege/lifecycle changed')
        env=dict(v.split('=',1) for v in live['Config']['Env'])
        need(not any(k.startswith('MAKE') for k in env),'Inherited make controls in tool image')
        (scratch/('go-'+label)).write_bytes(b'go\n');released=True
        native=int(captured(report,label+'-wait',['docker','wait',name]).stdout.decode().strip())
        logs=captured(report,label+'-logs',['docker','logs',name])
        need(logs.returncode==0,'Could not collect complete owned tool logs')
        streams={}
        for stream,b in [('stdout',logs.stdout),('stderr',logs.stderr)]:
            need(len(b)<=3000000 and b'\0' not in b,'Tool stream cap/text failed; no truncation')
            b.decode('utf-8');(report/(label+'-'+stream+'.txt')).write_bytes(b)
            streams[stream]=dict(bytes=len(b),sha256=sha(b))
        finished_json=json.loads(captured(report,label+'-inspect-finished',['docker','inspect',name]).stdout);save(report/(label+'-finished.json'),finished_json)
        finished,=finished_json
        need(not finished['State']['Running'] and finished['State']['ExitCode']==native and not finished['State']['OOMKilled'],
             'Owned converter exit/OOM mismatch')
        save(report/(label+'-result.json'),dict(nativeExit=native,streams=streams,helpCollectionOnly=help_only,toolArgv=argv))
        if not help_only:need(native==expected_exit,'Direct converter/patch tool exit mismatch: '+label)
        return native
    finally:
        if created:
            data=json.loads(captured(report,label+'-cleanup-inspect',['docker','inspect',name]).stdout);save(report/(label+'-cleanup-before.json'),data)
            if data[0]['State']['Running']:
                need(not released,'Refuse to cancel a released owned tool')
                captured(report,label+'-cleanup-stop-unreleased',['docker','stop','--time','1',name])
            captured(report,label+'-cleanup-remove',['docker','rm',name])

def collect(archive,api,scratch,output,tcl_path):
    output.mkdir(parents=True,exist_ok=False);scratch.mkdir(parents=True,exist_ok=False)
    original=scratch/'original';original.mkdir();control=scratch/'control';control.mkdir();changed=scratch/'changed';changed.mkdir()
    parser_controls(output)
    identities=load_original(archive,api,original);save(output/'original-input-identities.json',identities)
    original_text=(original/'map.xdl').read_text();before,before_raw=parse(original_text,rejected=output/"original-rejected")
    body=canonical_body(original_text);fingerprint=sha(body.encode())
    (scratch/'source-body.sha256').write_text(fingerprint+'\n')
    save(output/'source-body-fingerprint.json',dict(sha256=fingerprint,bytes=len(body.encode()),
        algorithm='Exact bytes from first line-start design through final non-whitespace byte; only pre-design comment lines and trailing whitespace excluded.',
        originalWholeXdlSha256=identities['map.xdl']['sha256'],oldWholeHashGateUnchanged=True))
    indexes(before_raw,output,'original');bounded(before_raw,before,output,'original')
    controls(before,output)
    image_before=json.loads(captured(output,'image-before',['docker','image','inspect',IMAGE]).stdout)
    need(len(image_before)==1 and image_before[0]['Id']==IMAGE,'Exact tool image unavailable')
    save(output/'image-before.json',image_before)
    tool(scratch,output,'help',['xdl'],help_only=True)
    help_text=(output/'help-stdout.txt').read_text()+(output/'help-stderr.txt').read_text()
    need('-xdl2ncd' in help_text and '-ncd2xdl' in help_text,'Actual installed XDL conversion help not confirmed')
    tool(scratch,output,'fresh-export',['xdl','-ncd2xdl','/scratch/original/main_map.ncd','/scratch/fresh-original.xdl'])
    fresh_text=(scratch/'fresh-original.xdl').read_text();fresh,fresh_raw=parse(fresh_text,rejected=output/"fresh-rejected")
    indexes(fresh_raw,output,'fresh')
    require_equal(fresh,before,'fresh original NCD export')
    need(sha(canonical_body(fresh_text).encode())==fingerprint,'Fresh exact original design-body bytes differ')
    # Actual production-script failure controls, before any conversion.
    (scratch/'bad-input.xdl').write_text(original_text+'\nnet "unexpected", inpin "unexpected" X;\n')
    tool(scratch,output,'bad-source',['xtclsh',tcl_path,'/scratch/bad-input.xdl','/scratch/bad-output.xdl','/scratch/source-body.sha256'],expected_exit=1)
    need(not (scratch/'bad-output.xdl').exists(),'Bad-source script created an output')
    (scratch/'existing-output.xdl').write_bytes(b'EXISTING_SENTINEL\n')
    tool(scratch,output,'existing-output',['xtclsh',tcl_path,'/scratch/original/map.xdl','/scratch/existing-output.xdl','/scratch/source-body.sha256'],expected_exit=1)
    need((scratch/'existing-output.xdl').read_bytes()==b'EXISTING_SENTINEL\n','Existing output was modified')
    need(b'fingerprint mismatch' in (output/'bad-source-stderr.txt').read_bytes(),'Bad-source control failed for another reason')
    need(b'Output already exists' in (output/'existing-output-stderr.txt').read_bytes(),'Existing-output control failed for another reason')
    tool(scratch,output,'tcl',['xtclsh',tcl_path,'/scratch/original/map.xdl','/scratch/changed/moved.xdl','/scratch/source-body.sha256'])
    tcl_stdout=(output/'tcl-stdout.txt').read_text()
    need('TCL_VERSION=8.4.14\n' in tcl_stdout and 'SOURCE_BODY_SHA256='+fingerprint+'\n' in tcl_stdout
         and 'DECLARED_COMPONENTS=2 DECLARED_NETS=7 MOVED_FF_BITS=2\n' in tcl_stdout,
         'Actual runtime Tcl/version/fingerprint report missing')
    changed_text=(changed/'moved.xdl').read_text();planned,planned_raw=parse(changed_text,rejected=output/"planned-rejected")
    contract=validate_move(before,planned,'actual Tcl output')
    changed_records=[dict(kind=k,name=n) for (k,n),raw in before_raw.items() if raw!=planned_raw[k,n]]
    need(set((x['kind'],x['name']) for x in changed_records)=={('inst',SRC),('inst',DST)}|{('net',n) for n in MOVES},
         'Actual Tcl changed raw records outside exact2COMP/7NET scope')
    save(output/'pre-conversion-conservation.json',dict(changedRecords=changed_records,ffContract=contract,accepted=True))
    tool(scratch,output,'control-import',['xdl','-xdl2ncd','/scratch/original/map.xdl','/scratch/control/main_map.ncd'])
    tool(scratch,output,'control-export',['xdl','-ncd2xdl','/scratch/control/main_map.ncd','/scratch/control/control.xdl'])
    control_model,control_raw=parse((control/'control.xdl').read_text(),rejected=output/'control-rejected')
    require_equal(control_model,before,'actual unmodified conversion control')
    indexes(control_raw,output,'control')
    tool(scratch,output,'move-import',['xdl','-xdl2ncd','/scratch/changed/moved.xdl','/scratch/changed/main_map.ncd'])
    tool(scratch,output,'move-export',['xdl','-ncd2xdl','/scratch/changed/main_map.ncd','/scratch/changed/reexport.xdl'])
    final_text=(changed/'reexport.xdl').read_text();after,after_raw=parse(final_text,rejected=output/"converted-rejected")
    contract=validate_move(before,after,'actual converted relocation')
    indexes(after_raw,output,'converted');bounded(after_raw,after,output,'converted')
    for name,identity in identities.items():
        data=(original/name).read_bytes();need(len(data)==identity['bytes'] and sha(data)==identity['sha256'],'Original retained input mutated')
    save(output/'image-after.json',json.loads(captured(output,'image-after',['docker','image','inspect',IMAGE]).stdout))
    need((output/'image-before.json').read_bytes()==(output/'image-after.json').read_bytes(),'Tool image metadata changed')
    save(output/'conversion-result.json',dict(sourceRun=43467561223,sourceArtifact=14062690690,sourceHead='f4bcfe872f4c10f067fd1d6eca72882fa23b5b26',
        freshOriginalBodyMatched=True,sourceBodySha256=fingerprint,convertedBodySha256=sha(canonical_body(final_text).encode()),unmodifiedControlPassed=True,
        actualTclPatchPassedIndependentValidator=True,actualNoForceNcdConversionPassed=True,totalInstances=3603,totalNets=8657,
        changedRawRecordsBeforeConversion=changed_records,ffContract=contract,allOtherCanonicalInstancesNetsAndPlacementsEqual=True,
        originalInputsImmutable=True,noSynthesisMapParTraceProofSimulationOrBooleanEvaluation=True,
        noTimingResult=True,nativeEligible=False,productionHookWired=False,hardwareQualified=False,ioElectricalSignoff=False,
        limits='Complete declared mapped-record/state-pin structural conservation and actual converter acceptance only. No whole-circuit formal/hardware/timing proof. Production reproducibility and workflow integration remain unproved.'))
    print((output/'conversion-result.json').read_text(),end='')

if __name__=='__main__':
    need(len(sys.argv)==6,'Usage: ORIGINAL_ZIP API_DIRECTORY SCRATCH OUTPUT TCL_PATH_IN_CONTAINER')
    collect(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),sys.argv[5])
