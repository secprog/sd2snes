#!/usr/bin/env python3
"""GitHub-only complete DMA bank write-predecode proof and strict native timing.
All80 original register bits/init/reset, dynamic writes including unknown addresses,
and original CPU priority over ST_DONE trigger clear are retained.
"""
import copy
import io
import urllib.request
import zipfile
import difflib
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')
BASE = '4d0199bf639629284546858b2b92abcd840b48a9'
SOURCE = 'verilog/sd2snes_dsp/dma.v'
STATE = [('dma_r['+str(i)+']',8) for i in range(10)]
PIN = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')
def need(value, message):
    if not value:
        raise ValueError(message)
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')
def once(text, before, after):
    need(text.count(before) == 1, 'Ambiguous source fragment: ' + before[:80])
    return text.replace(before, after)
def run(argv, output, name, expected=0):
    engine = output / (name + '-engine.log') if argv[0] == 'yosys' else None
    if engine is not None:
        argv = [argv[0], '-l', str(engine)] + argv[1:]
    save(output / (name + '-command.json'), argv)
    result = subprocess.run(argv, cwd=output, capture_output=True, timeout=300)
    for kind, data in [('stdout', result.stdout), ('stderr', result.stderr)]:
        need(len(data) <= 3000000 and b'\0' not in data, 'Unbounded or binary tool stream')
        data.decode('utf-8')
        (output / (name + '-' + kind + '.txt')).write_bytes(data)
    save(output / (name + '-exit.json'), dict(exit=result.returncode))
    print('COMMAND ' + name + ' ' + json.dumps(argv), flush=True)
    print(result.stdout.decode(), end='', flush=True)
    print(result.stderr.decode(), end='', flush=True)
    if expected is not None:
        need(result.returncode == expected, 'Unexpected actual tool exit for ' + name)
    log = result.stdout.decode() + result.stderr.decode()
    if engine is not None:
        need(engine.is_file(), 'Actual Yosys engine log missing')
        raw = engine.read_bytes()
        need(len(raw) <= 3000000 and b'\0' not in raw, 'Unbounded or binary engine log')
        log = raw.decode('utf-8')
        print('COMPLETE ENGINE ' + name, flush=True)
        print(log, end='', flush=True)
    return result.returncode, log
FRAGMENTS = {'baseline': '4d0199bf639629284546858b2b92abcd840b48a9', 'path': 'verilog/sd2snes_dsp/dma.v', 'goldSha256': '0175fe4386a97f6593f742d3302f96409ceacf8a7663e00f85111c40b050219b', 'gateSha256': '5f1572ad85495f2ed690b8613121697ffe335eb434f5630eb2cde861a4e86ae6', 'before': 'always @(posedge clkin) begin\n  if (reset) begin\n    for (i = 0; i < 10; i = i + 1) dma_r[i] <= 0;\n  end\n  else if(reg_we_rising & enable) begin\n    dma_r[reg_addr] <= reg_data_in;\n  end\n  else if (state == ST_DONE) begin\n    dma_r[9][0] <= 0;   // clear single-op trigger\n  end\nend\n', 'after': "`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_DMA_BYTE_WRITER_BEGIN\nwire dma_write_prefix, dma_write4, dma_write5, dma_write6;\ndspx_dma_write_prefix dma_write_prefix_lut(\n  .upper(reg_addr[3:2]), .strobe(reg_we_rising), .selected(dma_write_prefix)\n);\ndspx_dma_write_slot #(.WORD(2'b00)) dma_write_slot4_lut(\n  .lower(reg_addr[1:0]), .prefix(dma_write_prefix), .enabled(enable), .selected(dma_write4)\n);\ndspx_dma_write_slot #(.WORD(2'b01)) dma_write_slot5_lut(\n  .lower(reg_addr[1:0]), .prefix(dma_write_prefix), .enabled(enable), .selected(dma_write5)\n);\ndspx_dma_write_slot #(.WORD(2'b10)) dma_write_slot6_lut(\n  .lower(reg_addr[1:0]), .prefix(dma_write_prefix), .enabled(enable), .selected(dma_write6)\n);\nalways @(posedge clkin) begin\n  if (reset) begin\n    for (i = 0; i < 10; i = i + 1) dma_r[i] <= 0;\n  end else begin\n    if(dma_write4) dma_r[4] <= reg_data_in;\n    if(dma_write5) dma_r[5] <= reg_data_in;\n    if(dma_write6) dma_r[6] <= reg_data_in;\n    // Keep the original dynamic write for every other address, including X\n    // addresses. The global CPU-write guard still suppresses ST_DONE clearing\n    // even when an invalid/unknown address selects no real register.\n    if(reg_we_rising & enable) begin\n      case(reg_addr)\n        4'h4, 4'h5, 4'h6: begin end\n        default: dma_r[reg_addr] <= reg_data_in;\n      endcase\n    end else if (state == ST_DONE) begin\n      dma_r[9][0] <= 0;\n    end\n  end\nend\n// DSPX_DMA_BYTE_WRITER_END\n`else\nalways @(posedge clkin) begin\n  if (reset) begin\n    for (i = 0; i < 10; i = i + 1) dma_r[i] <= 0;\n  end\n  else if(reg_we_rising & enable) begin\n    dma_r[reg_addr] <= reg_data_in;\n  end\n  else if (state == ST_DONE) begin\n    dma_r[9][0] <= 0;   // clear single-op trigger\n  end\nend\n`endif\n`else\nalways @(posedge clkin) begin\n  if (reset) begin\n    for (i = 0; i < 10; i = i + 1) dma_r[i] <= 0;\n  end\n  else if(reg_we_rising & enable) begin\n    dma_r[reg_addr] <= reg_data_in;\n  end\n  else if (state == ST_DONE) begin\n    dma_r[9][0] <= 0;   // clear single-op trigger\n  end\nend\n`endif\n\n", 'tail': '\n`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_DMA_BYTE_HELPERS_BEGIN\n// Address and strobe decode is independent of the later global enable.\n(* LUT_MAP="yes" *)\nmodule dspx_dma_write_prefix(input [1:0] upper, input strobe, output reg selected);\nalways @* begin\n  selected = 1\'b0;\n  if(strobe & (upper == 2\'b01)) selected = 1\'b1;\nend\nendmodule\n\n// Four actual inputs: low address pair, predecode and unchanged global enable.\n(* LUT_MAP="yes" *)\nmodule dspx_dma_write_slot #(parameter [1:0] WORD = 2\'b00)(\n  input [1:0] lower, input prefix, enabled, output reg selected\n);\nalways @* begin\n  selected = 1\'b0;\n  if(enabled & prefix) begin\n    if(lower == WORD) selected = 1\'b1;\n  end\nend\nendmodule\n// DSPX_DMA_BYTE_HELPERS_END\n`endif\n`endif\n', 'originalWriter': 'always @(posedge clkin) begin\n  if (reset) begin\n    for (i = 0; i < 10; i = i + 1) dma_r[i] <= 0;\n  end\n  else if(reg_we_rising & enable) begin\n    dma_r[reg_addr] <= reg_data_in;\n  end\n  else if (state == ST_DONE) begin\n    dma_r[9][0] <= 0;   // clear single-op trigger\n  end\nend', 'writer': "// DSPX_DMA_BYTE_WRITER_BEGIN\nwire dma_write_prefix, dma_write4, dma_write5, dma_write6;\ndspx_dma_write_prefix dma_write_prefix_lut(\n  .upper(reg_addr[3:2]), .strobe(reg_we_rising), .selected(dma_write_prefix)\n);\ndspx_dma_write_slot #(.WORD(2'b00)) dma_write_slot4_lut(\n  .lower(reg_addr[1:0]), .prefix(dma_write_prefix), .enabled(enable), .selected(dma_write4)\n);\ndspx_dma_write_slot #(.WORD(2'b01)) dma_write_slot5_lut(\n  .lower(reg_addr[1:0]), .prefix(dma_write_prefix), .enabled(enable), .selected(dma_write5)\n);\ndspx_dma_write_slot #(.WORD(2'b10)) dma_write_slot6_lut(\n  .lower(reg_addr[1:0]), .prefix(dma_write_prefix), .enabled(enable), .selected(dma_write6)\n);\nalways @(posedge clkin) begin\n  if (reset) begin\n    for (i = 0; i < 10; i = i + 1) dma_r[i] <= 0;\n  end else begin\n    if(dma_write4) dma_r[4] <= reg_data_in;\n    if(dma_write5) dma_r[5] <= reg_data_in;\n    if(dma_write6) dma_r[6] <= reg_data_in;\n    // Keep the original dynamic write for every other address, including X\n    // addresses. The global CPU-write guard still suppresses ST_DONE clearing\n    // even when an invalid/unknown address selects no real register.\n    if(reg_we_rising & enable) begin\n      case(reg_addr)\n        4'h4, 4'h5, 4'h6: begin end\n        default: dma_r[reg_addr] <= reg_data_in;\n      endcase\n    end else if (state == ST_DONE) begin\n      dma_r[9][0] <= 0;\n    end\n  end\nend\n// DSPX_DMA_BYTE_WRITER_END", 'helpers': '// DSPX_DMA_BYTE_HELPERS_BEGIN\n// Address and strobe decode is independent of the later global enable.\n(* LUT_MAP="yes" *)\nmodule dspx_dma_write_prefix(input [1:0] upper, input strobe, output reg selected);\nalways @* begin\n  selected = 1\'b0;\n  if(strobe & (upper == 2\'b01)) selected = 1\'b1;\nend\nendmodule\n\n// Four actual inputs: low address pair, predecode and unchanged global enable.\n(* LUT_MAP="yes" *)\nmodule dspx_dma_write_slot #(parameter [1:0] WORD = 2\'b00)(\n  input [1:0] lower, input prefix, enabled, output reg selected\n);\nalways @* begin\n  selected = 1\'b0;\n  if(enabled & prefix) begin\n    if(lower == WORD) selected = 1\'b1;\n  end\nend\nendmodule\n// DSPX_DMA_BYTE_HELPERS_END', 'initial': "initial begin\n  dma_r[0] = 8'h00; // dst bank\n  dma_r[1] = 8'h00; // src bank\n  dma_r[2] = 8'h00; // dst[7:0]\n  dma_r[3] = 8'h00; // dst[15:8]\n  dma_r[4] = 8'h00; // src[7:0]\n  dma_r[5] = 8'h00; // src[15:0]\n  dma_r[6] = 8'h00; // len[7:0]\n  dma_r[7] = 8'h00; // len[15:8]\n  dma_r[8] = 8'h00; // len[23:16]\n  dma_r[9] = 8'h00; // opcode[7:3], loop, direction, trigger\nend", 'parameters': 'parameter ST_DONE   = 3;', 'scope': 'Only MK2+DSP_COMP DMA register4/5/6 CPU-write qualification; same full reset/init, dynamic other/unknown writes, ST_DONE clear priority and all controller/read/queue/kick code.'}

HEADER = """module dma_bank_model(input clkin,reset,enable,reg_we_rising,
input [3:0] reg_addr,input [7:0] reg_data_in,input [2:0] state,
output [79:0] bank_state,current_bytes);
reg [7:0] dma_r[9:0];
integer i;
"""
TRAILER = """
assign bank_state = {dma_r[9],dma_r[8],dma_r[7],dma_r[6],dma_r[5],dma_r[4],dma_r[3],dma_r[2],dma_r[1],dma_r[0]};
assign current_bytes = {dma_r[9],dma_r[8],dma_r[7],dma_r[6],dma_r[5],dma_r[4],dma_r[3],dma_r[2],dma_r[1],dma_r[0]};
endmodule
"""

def cut_design(design, name):
    need(set(design['modules']) == {'dma_bank_model'} and name in ('gold','gate'), 'Unexpected bank model')
    m = design['modules']['dma_bank_model']
    bits = [b for n, width in STATE for b in m['netnames'][n]['bits']]
    need(len(bits) == len(set(bits)) == 80 and all(type(b) is int for b in bits), 'Original80 unique state bits missing')
    need(all(len(m['netnames'][n]['bits']) == width for n,width in STATE), 'Register widths changed')
    observed = m['ports']['bank_state']['bits']
    need(observed == bits and m['ports']['current_bytes']['bits'] == bits, 'Bank byte ordering changed')
    initial = {}
    for net in m['netnames'].values():
        value = net.get('attributes',{}).get('init')
        if value is None:
            continue
        need(len(value) == len(net['bits']), 'Malformed initialization')
        for b,digit in zip(net['bits'],reversed(value)):
            if type(b) is int:
                need(b in bits and digit == '0','Original init0 changed or hidden initialized state')
                initial[b] = digit
        net['attributes'].pop('init',None)
    need(set(initial) == set(bits), 'All80 source initialization bits must remain zero')
    next_bits = {}; remove = []
    for key,cell in m['cells'].items():
        if cell['type'] != '$dff':
            need(cell['type'].startswith('$') and not any(t in cell['type'].lower() for t in ['ff','latch','mem']) and cell['type'] not in ['$anyseq','$anyconst'] and 'CLK' not in cell['connections'], 'Hidden state or blackbox')
            continue
        need(cell['connections']['CLK'] == m['ports']['clkin']['bits'] and int(cell['parameters']['CLK_POLARITY'],2) == 1,'Bank clock changed')
        for q,d in zip(cell['connections']['Q'],cell['connections']['D']):
            need(q not in next_bits,'Multiply driven bank state');next_bits[q] = d
        remove.append(key)
    need(set(next_bits) == set(bits),'Actual FF inventory differs from all80 bank bits')
    need(not set(bits).intersection(b for port in m['ports'].values() if port['direction']=='input' for b in port['bits']),'State aliases external input')
    for key in remove:
        del m['cells'][key]
    all_bits = bits + [b for port in m['ports'].values() for b in port['bits']]
    all_bits += [b for net in m['netnames'].values() for b in net['bits']]
    all_bits += [b for c in m['cells'].values() for v in c['connections'].values() for b in v]
    check = max(b for b in all_bits if type(b) is int) + 1
    m['cells']['$state_view_strict_eq'] = dict(hide_name=1,type='$eqx',attributes={},
        parameters=dict(A_SIGNED='0'*32,B_SIGNED='0'*32,A_WIDTH=format(80,'032b'),B_WIDTH=format(80,'032b'),Y_WIDTH=format(1,'032b')),
        port_directions=dict(A='input',B='input',Y='output'),connections=dict(A=observed,B=bits,Y=[check]))
    del m['ports']['bank_state']
    for key,direction,values in [('state_in','input',bits),('next_state','output',[next_bits[b] for b in bits]),('state_view_ok','output',[check])]:
        need(key not in m['ports'] and key not in m['netnames'],'Preexisting model boundary')
        m['ports'][key] = dict(direction=direction,bits=list(values));m['netnames'][key] = dict(hide_name=0,bits=list(values),attributes={})
    m.get('attributes',{}).pop('top',None)
    design['modules'] = {name:m}
    return design,dict(stateOrder=STATE,qBits=bits,dBits=[next_bits[b] for b in bits],initialBits=['0']*80,noHiddenState=True)

def compile_model(text, output, name):
    output.mkdir()
    (output/'model.v').write_text(text)
    script = ('read_verilog -sv -formal -mem2reg model.v\nhierarchy -check -top dma_bank_model\nflatten\n'
              'proc -ifx -noopt\ndffunmap\nsetundef -undriven -undef\nopt_clean\ncheck -assert\nwrite_json state.json\n')
    (output/'prepare.ys').write_text(script);run(['yosys','-s','prepare.ys'],output,'preparation')
    original = json.loads((output/'state.json').read_text())
    design,audit = cut_design(copy.deepcopy(original),name)
    save(output/'transition.json',design);save(output/'state-audit.json',audit)
    controls = []
    for label in ['wrong-clock','duplicate-Q','wrong-init']:
        changed = copy.deepcopy(original);m=changed['modules']['dma_bank_model']
        ff=next(c for c in m['cells'].values() if c['type']=='$dff')
        if label=='wrong-clock':
            ff['parameters']['CLK_POLARITY']='0'*32
        elif label=='duplicate-Q':
            ff=next(c for c in m['cells'].values() if c['type']=='$dff' and len(c['connections']['Q'])>1)
            ff['connections']['Q'][1]=ff['connections']['Q'][0]
        else:
            net=next(n for n in m['netnames'].values() if 'init' in n.get('attributes',{}))
            net['attributes']['init']='1'+net['attributes']['init'][1:]
        try:
            cut_design(changed,name)
        except ValueError as error:
            controls.append(dict(name=label,rejected=True,error=str(error)))
        else:
            raise ValueError('Accepted actual corrupt state: '+label)
    save(output/'state-controls.json',controls)
    script='read_json transition.json\nhierarchy -check -top '+name+'\nsat -verify -enable_undef -prove state_view_ok 1 -show-inputs -show state_view_ok -timeout 180\n'
    (output/'state-view.ys').write_text(script);_,log=run(['yosys','-s','state-view.ys'],output,'state-view')
    need('SAT proof finished - no model found: SUCCESS!' in log,'Actual bank ordering proof missing')
    if name=='gold':
        mutant=copy.deepcopy(design);b=mutant['modules']['gold']['cells']['$state_view_strict_eq']['connections']['B'];b[0],b[1]=b[1],b[0]
        save(output/'state-view-mutant.json',mutant)
        script=script.replace('read_json transition.json','read_json state-view-mutant.json').replace('-show-inputs','-set-def-inputs -dump_json observation-counterexample.json -show-inputs')
        (output/'state-view-mutant.ys').write_text(script);code,log=run(['yosys','-s','state-view-mutant.ys'],output,'state-view-mutant',expected=None)
        need(code!=0 and 'SAT proof finished - model found: FAIL!' in log and (output/'observation-counterexample.json').is_file(),'Real bank-order corruption counterexample missing')

def prove_pair(gold,gate,output,mode,expected):
    output.mkdir()
    flags='-set-def-inputs ' if mode=='binary' else ''
    script=('read_json '+str(gold/'transition.json')+'\nread_json '+str(gate/'transition.json')+'\n'
            'miter -equiv -make_assert -make_outputs -make_outcmp gold gate miter\n'
            'hierarchy -check -top miter\nflatten -wb\nopt_clean\ncheck -assert\nwrite_json miter.json\n'
            'sat -verify -enable_undef '+flags+'-prove-asserts -show-inputs -show-outputs -dump_json counterexample.json -timeout 180\n')
    (output/'prove.ys').write_text(script);code,log=run(['yosys','-s','prove.ys'],output,'proof',expected=None)
    source=json.loads((gold/'transition.json').read_text())['modules']['gold'];m=json.loads((output/'miter.json').read_text())['modules']['miter']
    inputs={k:v for k,v in source['ports'].items() if v['direction']=='input'}
    actual={k[3:]:v for k,v in m['ports'].items() if v['direction']=='input' and k.startswith('in_')}
    need(set(actual)==set(inputs) and all(len(actual[k]['bits'])==len(v['bits']) for k,v in inputs.items()),'Original inputs/arbitrary80bit state missing')
    outputs=[k for k,v in source['ports'].items() if v['direction']=='output']
    for k in outputs:
        need(any(c['type']=='$eqx' and c['connections']['Y']==m['ports']['cmp_'+k]['bits'] for c in m['cells'].values()),'Missing strict X comparison '+k)
    need(any(c['type']=='$assert' for c in m['cells'].values()) and not any(c['type']=='$assume' for c in m['cells'].values()),'Assertions/assumptions changed')
    need(not any(any(t in c['type'].lower() for t in ['ff','latch','mem']) for c in m['cells'].values()),'Transition miter contains hidden state')
    if expected:
        need(code==0 and 'SAT proof finished - no model found: SUCCESS!' in log,'Complete bank transition not equivalent')
    else:
        need(code!=0 and 'SAT proof finished - model found: FAIL!' in log and (output/'counterexample.json').is_file(),'Bad-source control lacks actual counterexample')
    result=dict(mode=mode,expectedPass=expected,actualExit=code,inputPorts=len(inputs),inputBits=sum(len(v['bits']) for v in inputs.values()),
                outputPorts=outputs,strictX=True,currentStateBits=80,sourceInitialization='all80 bits init0',arbitraryCurrentState=True,noCycleSkips=True,noAssumptions=True)
    save(output/'proof-review.json',result);return result

def proof(output):
    output.mkdir(parents=True,exist_ok=True)
    old=subprocess.check_output(['git','show',BASE+':'+SOURCE]).decode();gate=Path(SOURCE).read_text()
    need(sha(old.encode())==FRAGMENTS['goldSha256'] and sha(gate.encode())==FRAGMENTS['gateSha256'],'Full DMA source identity changed')
    need(once(old,FRAGMENTS['before'],FRAGMENTS['after'])+FRAGMENTS['tail']==gate,'DMA controller/read/queue/kick or init changed outside exact writer replacement')
    need(subprocess.check_output(['git','diff','--name-only',BASE,'HEAD','--','verilog']).decode().splitlines()==[SOURCE],'Unreviewed production edit')
    need(re.search(r'\bdma\s+snes_dma\s*\(',Path('verilog/sd2snes_dsp/main.v').read_text()),'Main overrides original DMA parameters')
    need(old.count(FRAGMENTS['initial'])==gate.count(FRAGMENTS['initial'])==1,'Bank initialization changed')
    need(old.count('reg [7:0] dma_r[9:0];')==gate.count('reg [7:0] dma_r[9:0];')==1,'Original bank storage shape changed')
    (output/'gold-source.v').write_text(old);(output/'gate-source.v').write_text(gate);save(output/'source-boundary.json',FRAGMENTS)
    configs=[];results=[];first=None
    for index,(board,comp,debug,lean) in enumerate(itertools.product(['MK2','MK3'],[False,True],[False,True],[False,True])):
        defines=[board]+(['DSP_COMP'] if comp else [])+(['DEBUG'] if debug else [])+(['DSP_LEAN'] if lean else [])
        paths=[]
        for label in ['gold','gate']:
            source=output/(label+'-source.v');destination=output/(label+'-preprocessed-'+str(index)+'.v')
            flags=['-D'+d for d in defines]
            run(['iverilog','-g2012','-E']+flags+['-o',str(destination),str(source)],output,label+'-preprocess-'+str(index))
            run(['iverilog','-g2012','-tnull','-s','dma']+flags+[str(source)],output,label+'-syntax-'+str(index))
            paths.append(destination)
        target=board=='MK2' and comp
        configs.append(dict(index=index,defines=defines,target=target,goldSha256=sha(paths[0].read_bytes()),gateSha256=sha(paths[1].read_bytes())))
        if not target:
            need([s for s in paths[0].read_text().splitlines() if s.strip()]==[s for s in paths[1].read_text().splitlines() if s.strip()],'Non-target source changed')
            continue
        need(FRAGMENTS['writer'] in paths[1].read_text() and FRAGMENTS['helpers'] in paths[1].read_text(),'Actual preprocessed writer/helpers missing')
        prefix=HEADER+FRAGMENTS['parameters']+'\n'+FRAGMENTS['initial']+'\n'
        golden=prefix+FRAGMENTS['originalWriter']+TRAILER
        candidate=prefix+FRAGMENTS['writer']+TRAILER+FRAGMENTS['helpers']+'\n'
        folder=output/('config-'+str(index));folder.mkdir()
        compile_model(golden,folder/'gold','gold');compile_model(candidate,folder/'gate','gate')
        for mode in ['binary','xstate']:
            results.append(prove_pair(folder/'gold',folder/'gate',folder/mode,mode,True))
        if first is None:first=(folder/'gold',candidate)
    gold,candidate=first
    mutations=[
        ('missing-strobe',"if(strobe & (upper == 2'b01))","if(upper == 2'b01)"),
        ('wrong-upper-address',"upper == 2'b01","upper == 2'b10"),
        ('wrong-lower-address',".WORD(2'b00)",".WORD(2'b11)"),
        ('wrong-enable-polarity','if(enabled & prefix)','if(~enabled & prefix)'),
        ('wrong-bank-target','if(dma_write4) dma_r[4]','if(dma_write4) dma_r[5]'),
        ('wrong-data-byte','if(dma_write5) dma_r[5] <= reg_data_in;',"if(dma_write5) dma_r[5] <= reg_data_in ^ 8'h01;"),
        ('lost-cpu-clear-priority','end else if (state == ST_DONE)','end if (state == ST_DONE)'),
        ('wrong-reset-priority','if (reset) begin','if (reset & ~enable) begin'),
        ('x-prefix-guard',"if(strobe & (upper == 2'b01))","if((strobe & (upper == 2'b01)) !== 1'b0)"),
        ('x-enable-guard','if(enabled & prefix)',"if((enabled & prefix) !== 1'b0)"),
        ('x-cpu-clear-priority','if(reg_we_rising & enable)',"if((reg_we_rising & enable) !== 1'b0)")]
    for label,before,after in mutations:
        folder=output/label;compile_model(once(candidate,before,after),folder,'gate')
        results.append(prove_pair(gold,folder,output/(label+'-binary'),'binary',label.startswith('x-')))
        if label.startswith('x-'):
            results.append(prove_pair(gold,folder,output/(label+'-xstate'),'xstate',False))
    save(output/'preprocessor-configurations.json',configs);save(output/'full-transition-results.json',results)
    sums=[sha(p.read_bytes())+'  '+p.relative_to(output).as_posix() for p in sorted(output.rglob('*')) if p.is_file() and p.name!='SHA256SUMS']
    (output/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
    (output/'verified.txt').write_text('Complete actual80-bit DMA register-bank arbitrary-state binary/X transition proof; original init0/reset, other and unknown dynamic writes and CPU/ST_DONE trigger-clear priority retained. Four target configurations,32 fullsource syntax compiles,11 actual bad-source counterexamples and4 observation counterexamples. No temporal cycle skips. Component only; native timing separately required.\n')

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


def collect(path, output):
    output.mkdir(parents=True, exist_ok=True)
    raw = path.read_bytes(); need(len(raw) < 32000000 and b'\0' not in raw, 'Unbounded/invalid mapped text')
    text = raw.decode('utf-8'); starts = re.findall(r'(?m)^\s*(inst|net)\s+"', text)
    statements = re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;', text)
    need(len(starts) == len(statements), 'Incomplete mapped statement')
    instances = {}; nets = {}
    for body in statements:
        match = re.match(r'\s*(inst|net)\s+"([^"\n]+)"', body); need(match is not None, 'Unknown mapped record')
        kind, name = match.groups(); target = instances if kind == 'inst' else nets
        need(name not in target, 'Duplicate mapped record'); target[name] = body.strip()
    families = ['dma_write_prefix_lut','dma_write_slot4_lut','dma_write_slot5_lut','dma_write_slot6_lut']
    bindings = {family: [] for family in families}
    for component, body in instances.items():
        for slot, logical, equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)', body):
            for family in families:
                prefix = 'snes_dma/' + family
                if logical == prefix or logical.startswith(prefix + '/'):
                    bindings[family].append(dict(component=component, slot=slot, logical=logical, equation=equation))
    save(output / 'dma-write-lut-observed-bindings.json', bindings)
    selected = {row['component'] for rows in bindings.values() for row in rows}
    selected_nets = {name for name, body in nets.items() if any(comp in selected for _, comp, _ in PIN.findall(body))}
    for name in selected_nets:
        selected.update(comp for direction, comp, _ in PIN.findall(nets[name]) if direction == 'outpin' and comp in instances)
    body = '\n\n'.join([instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]) + '\n'
    need(len(selected) <= 400 and len(selected_nets) <= 700 and len(body.encode()) <= 3000000, 'Bounded neighborhood exceeded; no truncation')
    (output / 'dma-write-luts-raw.txt').write_text(body)
    save(output / 'dma-write-physical-index.json', dict(sourceBytes=len(raw), sourceSha256=sha(raw), totalInstances=len(instances),
         totalNets=len(nets), bindings=bindings, selectedInstances=sorted(selected), selectedNets=sorted(selected_nets), rawSha256=sha(body.encode()),
         limits='Four bounded combinational helper LUTs, incident nets and immediate input drivers only; no whole mapped equivalence'))
    need(all(len(rows) == 1 for rows in bindings.values()), 'Four separate actual helper LUTs not observed; raw/index retained')

def property_seen(syr, unit):
    return bool(re.search(r'Set property "LUT_MAP = yes" for unit <' + re.escape(unit) + r'(?:[._][^>]*)?>\.', syr))


def analyze(report, baseline_dir):
    original = timing({key: (baseline_dir / ('main.' + key)).read_text() for key in ['par', 'twr']})
    need(original['traceErrors'] == 13 and original['parScore'] == 1017 and original['worstDisplayedSetupSlackNs'] == -0.124,
         'Best measured baseline metrics changed')
    native = report / 'native-reports'
    text = {key: (native / file).read_text() for key, file in [('par', 'main.par'), ('twr', 'main.twr'), ('pcf', 'main.pcf'), ('mrp', 'main_map.mrp')]}
    candidate = timing(text)
    need(len(re.findall(r'^par -w -ol high -xe c -t 68 main_map\.ncd main\.ncd main\.pcf\s*$', text['par'], re.M)) == 1,
         'Original PAR invocation changed')
    need(len(re.findall(r'/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr', text['twr'])) == 1,
         'Original TRACE invocation changed')
    command = re.search(r'Command Line\s*:\s*(.*?)\s*Target Device', text['mrp'], re.S)
    need(command is not None and ' '.join(command[1].split()) == 'map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 68 -register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy -pr b -bp -power off -o main_map.ncd main.ngd main.pcf', 'Original MAP changed')
    need(re.findall(r'^SYSTEM_JITTER\s*=\s*([^;\r\n]+);', text['pcf'], re.M) == ['480 ps'], 'Original jitter changed')
    periods = re.findall(r'^(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;', text['pcf'], re.M)
    expected = {('TS_CLKIN', 'CLKIN', '24.01'), ('TS_SPI_SCK', 'SPI_SCK', '48.1'), ('TS_SNES_SYSCLK', 'SNES_SYSCLK', '21.5'), ('TS_CLK21', 'CLK21', '96.04')}
    need(len(periods) == 4 and set(periods) == expected and set(re.findall(r'^(TS_\w+)\s*=', text['pcf'], re.M)) == {row[0] for row in expected}, 'Original timing specifications changed')
    need((report / 'integrity-verified.txt').read_text().strip() == 'Full source/index/IP immutability verified', 'Inputs not verified')
    finished, = json.loads((report / 'native-container-finished.json').read_text())
    native_exit = int((report / 'native-exit.txt').read_text())
    need(finished['State']['ExitCode'] == native_exit and not finished['State']['OOMKilled'], 'Native exit/OOM mismatch')
    if native_exit:
        need(native_exit == 2 and 'make[1]: *** [../common.mk:198: main.ncd] Error 55' in (report / 'native-build.log').read_text(),
             'Actual failure is not the original strict timing gate')
        need(candidate['traceErrors'] > 0 or candidate['parScore'] > 0, 'Timing failure without violations')
    syr = (native / 'main.syr').read_text()
    for unit in ['dspx_dma_write_prefix', 'dspx_dma_write_slot']:
        need(property_seen(syr, unit), 'Combinational LUT_MAP not recognized: ' + unit)
    physical = json.loads((report / 'physical/dma-write-physical-index.json').read_text())
    result = dict(baseline=original, candidate=candidate, nativeExit=native_exit, measuredImprovement=progress(original, candidate),
                  strictTimingPass=candidate['traceErrors'] == candidate['parScore'] == 0 and native_exit == 0,
                  mappedLuts=physical['bindings'], hardwareQualified=False, ioElectricalSignoff=False,
                  limits='Incremental improvement does not relabel original failed native/timing gate. No external I/O budget inferred.')
    save(report / 'timing-progress-result.json', result); print(json.dumps(result, indent=2), flush=True)


def timing(text):
    par, twr = text['par'], text['twr']
    scores = re.findall(r'Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)', par)
    traces = re.findall(r'Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)', twr)
    need(len(scores) == len(traces) == 1 and 'All signals are completely routed.' in par, 'Incomplete or ambiguous implementation report')
    values = []
    for line in twr.splitlines():
        if not line.lstrip().startswith('Slack'):
            continue
        match = re.match(r'\s*Slack(?:\s+\(([^)]*)\))?:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))ns\b', line)
        need(match is not None, 'Unknown actual slack record')
        values.append((match.group(1) or 'component', float(match.group(2))))
    need(values and any(kind == 'setup path' for kind, _ in values) and any(kind == 'hold path' for kind, _ in values), 'Missing setup/hold detail')
    score, setup, hold, component = map(int, scores[0])
    errors, trace_score, trace_setup, trace_hold = map(int, traces[0])
    return dict(parScore=score, parSetupScore=setup, parHoldScore=hold, componentSwitchingScore=component,
                traceErrors=errors, traceScore=trace_score, traceSetupScore=trace_setup, traceHoldScore=trace_hold,
                worstDisplayedSetupSlackNs=min(value for kind, value in values if kind == 'setup path'),
                worstDisplayedHoldSlackNs=min(value for kind, value in values if kind == 'hold path'),
                worstDisplayedOtherSlackNs=min((value for kind, value in values if kind not in ('setup path','hold path')), default=0.0),
                minimumDisplayedSlackNs=min(value for _, value in values),
                displayedNegativePaths=sum(value < 0 for _, value in values), displayedSlackRecords=len(values))


def progress(baseline, candidate):
    # Keep a better result only when the scored setup measures agree and no
    # hold/component regression is introduced. Remaining failures stay failures.
    nonregression = (candidate['traceErrors'] <= baseline['traceErrors']
                     and candidate['parScore'] <= baseline['parScore']
                     and candidate['worstDisplayedSetupSlackNs'] >= baseline['worstDisplayedSetupSlackNs']
                     and candidate['parHoldScore'] == candidate['traceHoldScore'] == candidate['componentSwitchingScore'] == 0
                     and candidate['worstDisplayedHoldSlackNs'] >= 0
                     and candidate['worstDisplayedOtherSlackNs'] >= 0)
    better = (candidate['traceErrors'] < baseline['traceErrors']
              or candidate['parScore'] < baseline['parScore']
              or candidate['worstDisplayedSetupSlackNs'] > baseline['worstDisplayedSetupSlackNs'])
    return bool(nonregression and better)

def analysis_controls(output):
    base = dict(traceErrors=13, parScore=1017, worstDisplayedSetupSlackNs=-0.124,
                parHoldScore=0, traceHoldScore=0, componentSwitchingScore=0, worstDisplayedHoldSlackNs=0.798, worstDisplayedOtherSlackNs=5.651)
    cases = [('unchanged is not improvement', {}, False),
             ('unscored plain negative slack rejects', dict(worstDisplayedOtherSlackNs=-0.001), False),
             ('fewer failures while still failing', dict(traceErrors=12), True),
             ('less negative slack while still failing', dict(worstDisplayedSetupSlackNs=-0.123), True),
             ('lower total score while still failing', dict(parScore=1016), True),
             ('worse slack rejects lower count', dict(traceErrors=9, worstDisplayedSetupSlackNs=-0.680), False),
             ('worse score rejects lower count', dict(traceErrors=9, parScore=1740), False),
             ('more failures reject better slack', dict(traceErrors=14, worstDisplayedSetupSlackNs=-0.100), False),
             ('hold errors reject', dict(traceErrors=12, traceHoldScore=1), False),
             ('unscored negative hold rejects', dict(traceErrors=12, worstDisplayedHoldSlackNs=-0.001), False),
             ('component errors reject', dict(traceErrors=12, componentSwitchingScore=1), False),
             ('current failed rewrite rejects', dict(traceErrors=173, parScore=50505, worstDisplayedSetupSlackNs=-1.324), False),
             ('seconds reset mapping regression rejects', dict(traceErrors=43, parScore=9812, worstDisplayedSetupSlackNs=-0.650), False),
             ('DR late selection regression rejects', dict(traceErrors=193, parScore=147633, worstDisplayedSetupSlackNs=-2.527), False)]
    rows = []
    for name, change, expected in cases:
        candidate = {**base, **change}; result = progress(base, candidate)
        rows.append(dict(name=name, expected=expected, result=result, passed=result == expected))
    save(output, dict(controls=rows, passed=all(row['passed'] for row in rows)))
    need(all(row['passed'] for row in rows), 'Timing-progress controls failed')
    print('Passed fourteen incremental-adoption controls, including remaining-failure positives')




def controls(output):
    output.mkdir(parents=True, exist_ok=False)
    analysis_controls(output / 'progress-controls.json')
    property_cases=[('bare unit','Set property "LUT_MAP = yes" for unit <dspx_dma_write_slot>.',True),
                    ('dot parameter','Set property "LUT_MAP = yes" for unit <dspx_dma_write_slot.1>.',True),
                    ('underscore parameter','Set property "LUT_MAP = yes" for unit <dspx_dma_write_slot_2>.',True),
                    ('property disabled','Set property "LUT_MAP = no" for unit <dspx_dma_write_slot.1>.',False),
                    ('unrelated unit','Set property "LUT_MAP = yes" for unit <other.1>.',False)]
    property_rows=[dict(name=name,expected=expected,observed=property_seen(text,'dspx_dma_write_slot'),passed=property_seen(text,'dspx_dma_write_slot')==expected) for name,text,expected in property_cases]
    save(output/'property-controls.json',property_rows)
    need(all(x['passed'] for x in property_rows),'Actual parameterized property controls failed')

    families = ['dma_write_prefix_lut','dma_write_slot4_lut','dma_write_slot5_lut','dma_write_slot6_lut']
    fixture = '\n'.join('inst "part' + str(i) + '" "SLICEL", cfg " F:snes_dma/' + family + ':#LUT:D=A1 ";' for i, family in enumerate(families)) + '\n'
    cases = [('four actual helper LUTs', fixture, True),
             ('missing helper', fixture.replace('dma_write_prefix_lut', 'other'), False),
             ('FF is not LUT', fixture.replace('F:snes_dma/dma_write_prefix_lut:#LUT:D=A1', 'FFX:snes_dma/dma_write_prefix_lut:#FF'), False),
             ('duplicate instance', fixture + 'inst "part0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture + 'net "n";\nnet "n";\n', False),
             ('incomplete record', fixture + 'net "incomplete"', False),
             ('two physical aliases', fixture + 'inst "extra" "SLICEL", cfg " F:snes_dma/dma_write_prefix_lut/x:#LUT:D=A1 ";\n', False),
             ('net bound exceeded', fixture + ''.join('net "extra' + str(i) + '", inpin "part0" F1;\n' for i in range(701)), False)]
    rows = []
    for index, (name, text, expected) in enumerate(cases):
        path = output / ('fixture-' + str(index) + '.txt'); path.write_text(text)
        error = None
        try:
            collect(path, output / ('physical-' + str(index))); accepted = True
        except ValueError as failure:
            accepted = False; error = str(failure)
        rows.append(dict(name=name, expected=expected, accepted=accepted, error=error, passed=accepted == expected))
    save(output / 'physical-controls.json', rows)
    need(all(row['passed'] for row in rows), 'Physical LUT/bound controls failed')



if __name__ == '__main__':
    need(len(sys.argv) >= 3, 'Usage: proof|baseline|collect|analyze|controls OUTPUT [SECOND]')
    action = sys.argv[1]
    if action == 'proof':
        proof(Path(sys.argv[2]).resolve())
    elif action == 'baseline':
        baseline(Path(sys.argv[2]))
    elif action == 'collect':
        collect(Path(sys.argv[2]), Path(sys.argv[3]))
    elif action == 'analyze':
        analyze(Path(sys.argv[2]), Path(sys.argv[3]))
    elif action == 'controls':
        controls(Path(sys.argv[2]))
    else:
        raise ValueError('Unknown action')
