#!/usr/bin/env python3
"""GitHub-only complete32bit M/N transition proof andstrictnative timing.
Preserves multiplier packing, all32 uninitialized statebits, reset/restore andeveryother source byte.
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
SOURCE = 'verilog/sd2snes_dsp/upd77c25.v'
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
FRAGMENTS = {'baseline': '4d0199bf639629284546858b2b92abcd840b48a9', 'path': 'verilog/sd2snes_dsp/upd77c25.v', 'goldSha256': '8e82c280d3b69fd273ffd468b5de4b06fd82fbf3a352b9948d70ef214b9253ff', 'gateSha256': '7a620d45030ee0824bf4494e1b62245566099d8e0bf01e46b5c235d0147c1449', 'normal': "        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};", 'restore': "        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;", 'reset': "    regs_m <= 16'b0;\n    regs_n <= 16'b0;", 'anchor': "assign DO = ss_ctrl ? {7'b0, ss_halted}\n          : ss_regwin ? ss_reg_do\n          : (DP_enable ? DP_DO : UPD_DO);\n\n", 'body': "// DSPX_MN_CONTROL_BEGIN\nwire mn_fetch_low, mn_fetch_high, mn_running;\ndspx_mn_case4 #(.VALUE(STATE_FETCH[3:0])) mn_fetch_low_lut(.key(insn_state[3:0]), .match(mn_fetch_low));\ndspx_mn_case4 #(.VALUE(STATE_FETCH[7:4])) mn_fetch_high_lut(.key(insn_state[7:4]), .match(mn_fetch_high));\ndspx_mn_run4 mn_fetch_run_lut(.rst(RST), .frozen(ss_frozen), .lo_match(mn_fetch_low), .hi_match(mn_fetch_high), .running(mn_running));\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(mn_running) begin\n        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};\n    end\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      case(ss_wa)\n        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;\n      endcase\n    end\n  end else begin\n    regs_m <= 16'b0;\n    regs_n <= 16'b0;\n  end\nend\n// DSPX_MN_CONTROL_END\n", 'guard': "`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_MN_CONTROL_BEGIN\nwire mn_fetch_low, mn_fetch_high, mn_running;\ndspx_mn_case4 #(.VALUE(STATE_FETCH[3:0])) mn_fetch_low_lut(.key(insn_state[3:0]), .match(mn_fetch_low));\ndspx_mn_case4 #(.VALUE(STATE_FETCH[7:4])) mn_fetch_high_lut(.key(insn_state[7:4]), .match(mn_fetch_high));\ndspx_mn_run4 mn_fetch_run_lut(.rst(RST), .frozen(ss_frozen), .lo_match(mn_fetch_low), .hi_match(mn_fetch_high), .running(mn_running));\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(mn_running) begin\n        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};\n    end\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      case(ss_wa)\n        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;\n      endcase\n    end\n  end else begin\n    regs_m <= 16'b0;\n    regs_n <= 16'b0;\n  end\nend\n// DSPX_MN_CONTROL_END\n`endif\n`endif\n\n", 'helpers': '// DSPX_MN_HELPERS_BEGIN\n// Procedural case retains the original full-state case behavior for unknowns.\n(* LUT_MAP="yes" *)\nmodule dspx_mn_case4 #(parameter [3:0] VALUE=4\'b0000)(input [3:0] key, output reg match);\nalways @* begin\n  match = 1\'b0;\n  case(key)\n    VALUE: match = 1\'b1;\n  endcase\nend\nendmodule\n(* LUT_MAP="yes" *)\nmodule dspx_mn_run4(input rst,frozen,lo_match,hi_match,output running);\nassign running = rst & ~frozen & lo_match & hi_match;\nendmodule\n// DSPX_MN_HELPERS_END', 'tail': '\n`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_MN_HELPERS_BEGIN\n// Procedural case retains the original full-state case behavior for unknowns.\n(* LUT_MAP="yes" *)\nmodule dspx_mn_case4 #(parameter [3:0] VALUE=4\'b0000)(input [3:0] key, output reg match);\nalways @* begin\n  match = 1\'b0;\n  case(key)\n    VALUE: match = 1\'b1;\n  endcase\nend\nendmodule\n(* LUT_MAP="yes" *)\nmodule dspx_mn_run4(input rst,frozen,lo_match,hi_match,output running);\nassign running = rst & ~frozen & lo_match & hi_match;\nendmodule\n// DSPX_MN_HELPERS_END\n`endif\n`endif\n', 'nontargetReplacements': [{'before': "        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};", 'after': "`ifdef MK2\n`ifndef DSP_COMP\n        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};\n`endif\n`else\n        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};\n`endif"}, {'before': "        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;", 'after': "`ifdef MK2\n`ifndef DSP_COMP\n        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;\n`endif\n`else\n        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;\n`endif"}, {'before': "    regs_m <= 16'b0;\n    regs_n <= 16'b0;", 'after': "`ifdef MK2\n`ifndef DSP_COMP\n    regs_m <= 16'b0;\n    regs_n <= 16'b0;\n`endif\n`else\n    regs_m <= 16'b0;\n    regs_n <= 16'b0;\n`endif"}], 'stateFetchDeclaration': "parameter STATE_FETCH = 8'b00000001;", 'sourceScope': 'Only MK2+DSP_COMP 32-bit M/N writer controls; exact multiplier packing, full reset andallfourrestorebytes preserved; no state/latency/clock/interface added orremoved.'}
STATE = [('regs_n', 16), ('regs_m', 16)]
HEADER = 'module mn_model(input CLK,RST,ss_frozen,ss_wr,\ninput [7:0] ss_wa,ss_wd,insn_state,input [31:0] mul_result,\noutput [31:0] state,output [7:0] scan_m_low,scan_m_high,scan_n_low,scan_n_high);\nreg [15:0] regs_m,regs_n;\n'
TRAILER = '\nassign state = {regs_m,regs_n};\nassign scan_m_low=regs_m[7:0];\nassign scan_m_high=regs_m[15:8];\nassign scan_n_low=regs_n[7:0];\nassign scan_n_high=regs_n[15:8];\nendmodule\n'
GOLD_BODY = "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    case(insn_state)\n      STATE_FETCH: begin\n        regs_m <= {mul_result[31], mul_result[29:15]};\n        regs_n <= {mul_result[14:0], 1'b0};\n      end\n    endcase\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      case(ss_wa)\n        8'h14: regs_m[7:0]      <= ss_wd;\n        8'h15: regs_m[15:8]     <= ss_wd;\n        8'h16: regs_n[7:0]      <= ss_wd;\n        8'h17: regs_n[15:8]     <= ss_wd;\n      endcase\n    end\n  end else begin\n    regs_m <= 16'b0;\n    regs_n <= 16'b0;\n  end\nend\n"

def cut_design(design, name):
    need(set(design['modules']) == {'mn_model'} and name in ('gold', 'gate'), 'Unexpected model')
    module = design['modules']['mn_model']
    state = [bit for signal, width in STATE for bit in module['netnames'][signal]['bits']]
    need(all(len(module['netnames'][signal]['bits']) == width for signal, width in STATE), 'State widths changed')
    need(len(state) == len(set(state)) == 32 and all(type(bit) is int for bit in state), 'State alias or missing bit')
    observed = list(module['ports']['state']['bits'])
    need(len(observed) == 32 and module['ports']['state']['direction'] == 'output', 'State view changed')
    for net in module['netnames'].values():
        need('init' not in net.get('attributes', {}), 'Original M/N must remain uninitialized')
    clock = module['ports']['CLK']['bits']
    next_bits, registers = {}, []
    for key, cell in module['cells'].items():
        kind = cell['type']
        if kind != '$dff':
            need(kind.startswith('$') and not any(s in kind.lower() for s in ('ff', 'latch', 'mem'))
                 and 'CLK' not in cell['connections'] and kind not in ('$anyseq', '$anyconst', '$assume', '$assert'), 'Hidden state or blackbox')
            continue
        need(cell['connections']['CLK'] == clock and int(cell['parameters']['CLK_POLARITY'], 2) == 1, 'Clock changed')
        q, d = cell['connections']['Q'], cell['connections']['D']
        need(len(q) == len(d), 'D/Q width mismatch')
        for qb, db in zip(q, d):
            need(qb not in next_bits, 'Multiply driven state')
            next_bits[qb] = db
        registers.append(key)
    need(set(next_bits) == set(state), 'All DFF bits must exactly match named state')
    inputs = {bit for port in module['ports'].values() if port['direction'] == 'input' for bit in port['bits']}
    need(not inputs.intersection(state), 'State aliases source input')
    for key in registers:
        del module['cells'][key]
    all_bits = state + [bit for port in module['ports'].values() for bit in port['bits']]
    all_bits += [bit for net in module['netnames'].values() for bit in net['bits']]
    all_bits += [bit for cell in module['cells'].values() for bits in cell['connections'].values() for bit in bits]
    check = max(bit for bit in all_bits if type(bit) is int) + 1
    module['cells']['$state_view_strict_eq'] = dict(hide_name=1, type='$eqx', attributes={},
        parameters=dict(A_SIGNED='0'*32, B_SIGNED='0'*32, A_WIDTH=format(32,'032b'), B_WIDTH=format(32,'032b'), Y_WIDTH=format(1,'032b')),
        port_directions=dict(A='input',B='input',Y='output'), connections=dict(A=observed,B=list(state),Y=[check]))
    del module['ports']['state']
    for key, direction, bits in [('state_in','input',state), ('next_state','output',[next_bits[bit] for bit in state]), ('state_view_ok','output',[check])]:
        need(key not in module['ports'] and key not in module['netnames'], 'Preexisting state boundary')
        module['ports'][key] = dict(direction=direction,bits=list(bits))
        module['netnames'][key] = dict(hide_name=0,bits=list(bits),attributes={})
    module.get('attributes', {}).pop('top', None)
    design['modules'] = {name: module}
    return design, dict(stateOrder=STATE, qBits=state, dBits=[next_bits[bit] for bit in state], initialBits=['x']*32, noHiddenState=True)


def compile_model(text, output, name):
    output.mkdir()
    (output / 'model.v').write_text(text)
    run(['iverilog','-g2012','-tnull','-s','mn_model','model.v'],output,'syntax')
    script = ('read_verilog -sv -formal model.v\nhierarchy -check -top mn_model\nflatten\n'
              'proc -ifx -noopt\ndffunmap\nsetundef -undriven -undef\nopt_clean\ncheck -assert\nwrite_json state.json\n')
    (output / 'prepare.ys').write_text(script)
    run(['yosys', '-s', 'prepare.ys'], output, 'preparation')
    original = json.loads((output / 'state.json').read_text())
    design, audit = cut_design(copy.deepcopy(original), name)
    save(output / 'transition.json', design); save(output / 'state-audit.json', audit)
    controls = []
    for label in ['wrong-clock', 'duplicate-Q', 'wrong-init']:
        changed = copy.deepcopy(original); m = changed['modules']['mn_model']
        ff = next(cell for cell in m['cells'].values() if cell['type'] == '$dff')
        if label == 'wrong-clock':
            ff['parameters']['CLK_POLARITY'] = '0' * 32
        elif label == 'duplicate-Q':
            ff = next(cell for cell in m['cells'].values() if cell['type'] == '$dff' and len(cell['connections']['Q']) > 1)
            ff['connections']['Q'][1] = ff['connections']['Q'][0]
        else:
            m['netnames']['regs_m'].setdefault('attributes', {})['init'] = '0' * 16
        try:
            cut_design(changed, name)
        except ValueError as error:
            controls.append(dict(name=label, rejected=True, error=str(error)))
        else:
            raise ValueError('Accepted actual corrupt state: ' + label)
    save(output / 'state-controls.json', controls)
    state_script = ('read_json transition.json\nhierarchy -check -top ' + name +
                    '\nsat -verify -enable_undef -prove state_view_ok 1 -show-inputs -show state_view_ok -timeout 180\n')
    (output / 'state-view.ys').write_text(state_script)
    _, log = run(['yosys', '-s', 'state-view.ys'], output, 'state-view')
    need('SAT proof finished - no model found: SUCCESS!' in log, 'Actual current-state observation proof missing')
    if name == 'gold':
        mutant = copy.deepcopy(design)
        bits = mutant['modules']['gold']['cells']['$state_view_strict_eq']['connections']['B']
        bits[0], bits[1] = bits[1], bits[0]
        save(output / 'state-view-mutant.json', mutant)
        state_script = state_script.replace('read_json transition.json', 'read_json state-view-mutant.json').replace('-show-inputs', '-set-def-inputs -dump_json observation-counterexample.json -show-inputs')
        (output / 'state-view-mutant.ys').write_text(state_script)
        code, log = run(['yosys', '-s', 'state-view-mutant.ys'], output, 'state-view-mutant', expected=None)
        need(code != 0 and 'SAT proof finished - model found: FAIL!' in log and (output / 'observation-counterexample.json').is_file(), 'Real observation corruption counterexample missing')

def prove_pair(gold, gate, output, mode, expected):
    output.mkdir()
    flags = '-set-def-inputs ' if mode == 'binary' else ''
    script = ('read_json ' + str(gold / 'transition.json') + '\nread_json ' + str(gate / 'transition.json') + '\n'
              'miter -equiv -make_assert -make_outputs -make_outcmp gold gate miter\n'
              'hierarchy -check -top miter\nflatten -wb\nopt_clean\ncheck -assert\nwrite_json miter.json\n'
              'sat -verify -enable_undef ' + flags + '-prove-asserts -show-inputs -show-outputs -dump_json counterexample.json -timeout 180\n')
    (output / 'prove.ys').write_text(script)
    code, log = run(['yosys', '-s', 'prove.ys'], output, 'proof', expected=None)
    m = json.loads((output / 'miter.json').read_text())['modules']['miter']
    source = json.loads((gold / 'transition.json').read_text())['modules']['gold']
    inputs = {k: v for k, v in source['ports'].items() if v['direction'] == 'input'}
    actual = {k[3:]: v for k, v in m['ports'].items() if v['direction'] == 'input' and k.startswith('in_')}
    need(set(actual) == set(inputs) and all(len(actual[k]['bits']) == len(v['bits']) for k, v in inputs.items()), 'Complete input and arbitrary current-state boundary missing')
    outputs = [k for k, v in source['ports'].items() if v['direction'] == 'output']
    for k in outputs:
        bits = m['ports']['cmp_' + k]['bits']
        need(any(cell['type'] == '$eqx' and cell['connections']['Y'] == bits for cell in m['cells'].values()), 'Output not strictly X-compared: ' + k)
    need(any(c['type'] == '$assert' for c in m['cells'].values()) and not any(c['type'] == '$assume' for c in m['cells'].values()), 'Assertions or assumptions changed')
    need(not any(any(s in c['type'].lower() for s in ['ff','latch','mem']) for c in m['cells'].values()), 'Transition miter has hidden state')
    if expected:
        need(code == 0 and 'SAT proof finished - no model found: SUCCESS!' in log, 'Complete arbitrary-state transition not equivalent')
    else:
        need(code != 0 and 'SAT proof finished - model found: FAIL!' in log and (output / 'counterexample.json').is_file(), 'Bad-source control lacks actual counterexample')
    receipt = dict(mode=mode, expectedPass=expected, actualExit=code, inputPorts=len(inputs), inputBits=sum(len(v['bits']) for v in inputs.values()),
                   outputPorts=outputs, strictX=True, currentStateBits=32, sourceInitialization='undefined, no initialization added',
                   noCycleSkips=True, arbitraryCurrentState=True, noAssumptions=True)
    save(output / 'proof-review.json', receipt)
    return receipt

def proof(output):
    output.mkdir(parents=True,exist_ok=True)
    original=subprocess.check_output(['git','show',BASE+':'+SOURCE]).decode();gate=Path(SOURCE).read_text()
    need(sha(original.encode())==FRAGMENTS['goldSha256'] and sha(gate.encode())==FRAGMENTS['gateSha256'],'Full UPD source identity changed')
    inverse=original
    for row in FRAGMENTS['nontargetReplacements']:
        inverse=once(inverse,row['before'],row['after'])
    inverse=once(inverse,FRAGMENTS['anchor'],FRAGMENTS['anchor']+FRAGMENTS['guard'])+FRAGMENTS['tail']
    need(inverse==gate,'Change exceeds exact M/N control writer')
    need(subprocess.check_output(['git','diff','--name-only',BASE,'HEAD','--','verilog']).decode().splitlines()==[SOURCE],'Unreviewed production edit')
    need(original.count(FRAGMENTS['stateFetchDeclaration'])==1,'Actual FETCH parameter changed')
    for fragment in ['normal','restore','reset']:
        need(original.count(FRAGMENTS[fragment])==1,'Actual M/N writer fragment ambiguous')
    remaining=original
    for fragment in ['normal','restore','reset']:
        remaining=once(remaining,FRAGMENTS[fragment],'')
    need(not re.search(r'\bregs_[mn](?:\[[^]]+\])?\s*<=',remaining),'Unmodeled M/N state writer')
    # The exact inverse retains every other FSM writer and every read/interface.
    (output/'gold-source.v').write_text(original);(output/'gate-source.v').write_text(gate);save(output/'source-boundary.json',FRAGMENTS)
    results=[];configs=[];first=None
    for index,(board,comp,debug,lean) in enumerate(itertools.product(['MK2','MK3'],[False,True],[False,True],[False,True])):
        defines=[board]+(['DSP_COMP'] if comp else [])+(['DEBUG'] if debug else [])+(['DSP_LEAN'] if lean else [])
        target=board=='MK2' and comp;header=Path('verilog/sd2snes_dspx' if target else 'verilog/sd2snes_dsp').resolve()
        (output/('config-header-'+str(index)+'.vh')).write_bytes((header/'config.vh').read_bytes())
        paths=[]
        for label in ['gold','gate']:
            destination=output/(label+'-preprocessed-'+str(index)+'.v')
            run(['iverilog','-g2012','-E','-I',str(header)]+['-D'+d for d in defines]+['-o',str(destination),str(output/(label+'-source.v'))],output,label+'-preprocess-'+str(index))
            paths.append(destination)
        configs.append(dict(index=index,defines=defines,target=target,header=header.as_posix(),headerSha256=sha((header/'config.vh').read_bytes()),goldSha256=sha(paths[0].read_bytes()),gateSha256=sha(paths[1].read_bytes())))
        if not target:
            need([s for s in paths[0].read_text().splitlines() if s.strip()]==[s for s in paths[1].read_text().splitlines() if s.strip()],'Non-target source changed')
            continue
        need(FRAGMENTS['body'] in paths[1].read_text() and FRAGMENTS['helpers'] in paths[1].read_text(),'Actual preprocessed M/N writer missing')
        need(len(re.findall(r'\bregs_[mn](?:\[[^]]+\])?\s*<=',paths[1].read_text()))==8,'Target M/N writes omitted or duplicated')
        golden=HEADER+FRAGMENTS['stateFetchDeclaration']+'\n'+GOLD_BODY+TRAILER
        candidate=HEADER+FRAGMENTS['stateFetchDeclaration']+'\n'+FRAGMENTS['body']+TRAILER+FRAGMENTS['helpers']+'\n'
        folder=output/('config-'+str(index));folder.mkdir()
        compile_model(golden,folder/'gold','gold');compile_model(candidate,folder/'gate','gate')
        for mode in ['binary','xstate']:
            results.append(prove_pair(folder/'gold',folder/'gate',folder/mode,mode,True))
        if first is None:first=(folder/'gold',candidate)
    gold,candidate=first
    normal=FRAGMENTS['normal'];restore=FRAGMENTS['restore'];reset=FRAGMENTS['reset']
    mutations=[
      ('missing-reset',reset,"    regs_m <= regs_m;\n    regs_n <= regs_n;"),
      ('freeze-not-preserved','if(RST & ~ss_frozen) begin','if(RST) begin'),
      ('missing-m-low-restore',"        8'h14: regs_m[7:0]      <= ss_wd;",""),
      ('wrong-n-high-restore',"8'h17: regs_n[15:8]     <= ss_wd;","8'h17: regs_m[15:8]     <= ss_wd;"),
      ('wrong-fetch-low','.VALUE(STATE_FETCH[3:0])',".VALUE(4'b0010)"),
      ('wrong-fetch-high','.VALUE(STATE_FETCH[7:4])',".VALUE(4'b0001)"),
      ('wrong-product-sign','{mul_result[31], mul_result[29:15]}','{mul_result[30], mul_result[29:15]}'),
      ('missing-n-shift',"{mul_result[14:0], 1'b0}",'mul_result[15:0]'),
      ('x-state-casex','case(key)','casex(key)'),
      ('x-run-guard','if(RST & ~ss_frozen) begin',"if((RST !== 1'b0) & (ss_frozen !== 1'b1)) begin"),
      ('x-unused-product-bit','regs_m <= {mul_result[31], mul_result[29:15]};','regs_m <= {mul_result[31], mul_result[29:15]} ^ {16{mul_result[30] & ~mul_result[30]}};')]
    for label,before,after in mutations:
        folder=output/label;compile_model(once(candidate,before,after),folder,'gate')
        results.append(prove_pair(gold,folder,output/(label+'-binary'),'binary',label.startswith('x-')))
        if label.startswith('x-'):results.append(prove_pair(gold,folder,output/(label+'-xstate'),'xstate',False))
    save(output/'preprocessor-configurations.json',configs);save(output/'full-state-results.json',results)
    sums=[sha(p.read_bytes())+'  '+p.relative_to(output).as_posix() for p in sorted(output.rglob('*')) if p.is_file() and p.name!='SHA256SUMS']
    (output/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
    (output/'verified.txt').write_text('Complete32bitactualM/Nwriter transitions/observations proved forbinary andunrestrictedX in4targetconfigs witharbitrarycurrentstate; noinitializationadded;fullreset/productpacking/restorepreserved;11badsource and4observation counterexamples. No temporal skips/assumptions/wholemapped/timing/hardwareclaim.\n')

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
    families = ['mn_fetch_low_lut','mn_fetch_high_lut','mn_fetch_run_lut']
    bindings = {family: [] for family in families}
    for component, body in instances.items():
        for slot, logical, equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)', body):
            for family in families:
                prefix = 'snes_dspx/' + family
                if logical == prefix or logical.startswith(prefix + '/'):
                    bindings[family].append(dict(component=component, slot=slot, logical=logical, equation=equation))
    save(output / 'mn-control-lut-observed-bindings.json', bindings)
    selected = {row['component'] for rows in bindings.values() for row in rows}
    selected_nets = {name for name, body in nets.items() if any(comp in selected for _, comp, _ in PIN.findall(body))}
    for name in selected_nets:
        selected.update(comp for direction, comp, _ in PIN.findall(nets[name]) if direction == 'outpin' and comp in instances)
    body = '\n\n'.join([instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]) + '\n'
    need(len(selected) <= 400 and len(selected_nets) <= 700 and len(body.encode()) <= 3000000, 'Bounded neighborhood exceeded; no truncation')
    (output / 'mn-control-luts-raw.txt').write_text(body)
    save(output / 'mn-control-physical-index.json', dict(sourceBytes=len(raw), sourceSha256=sha(raw), totalInstances=len(instances),
         totalNets=len(nets), bindings=bindings, selectedInstances=sorted(selected), selectedNets=sorted(selected_nets), rawSha256=sha(body.encode()),
         limits='One bounded combinational helper LUTs, incident nets and immediate input drivers only; no whole mapped equivalence'))
    need(all(len(rows) == 1 for rows in bindings.values()), 'One separate actual helper LUTs not observed; raw/index retained')

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
    for unit in ['dspx_mn_case4','dspx_mn_run4']:
        need(property_seen(syr, unit), 'Combinational LUT_MAP not recognized: ' + unit)
    physical = json.loads((report / 'physical/mn-control-physical-index.json').read_text())
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
    property_cases=[('bare unit','Set property "LUT_MAP = yes" for unit <dspx_mn_run4>.',True),
                    ('dot parameter','Set property "LUT_MAP = yes" for unit <dspx_mn_run4.1>.',True),
                    ('underscore parameter','Set property "LUT_MAP = yes" for unit <dspx_mn_run4_2>.',True),
                    ('property disabled','Set property "LUT_MAP = no" for unit <dspx_mn_run4.1>.',False),
                    ('unrelated unit','Set property "LUT_MAP = yes" for unit <other.1>.',False)]
    property_rows=[dict(name=name,expected=expected,observed=property_seen(text,'dspx_mn_run4'),passed=property_seen(text,'dspx_mn_run4')==expected) for name,text,expected in property_cases]
    save(output/'property-controls.json',property_rows)
    need(all(x['passed'] for x in property_rows),'Actual parameterized property controls failed')

    families = ['mn_fetch_low_lut','mn_fetch_high_lut','mn_fetch_run_lut']
    fixture = '\n'.join('inst "part' + str(i) + '" "SLICEL", cfg " F:snes_dspx/' + family + ':#LUT:D=A1 ";' for i, family in enumerate(families)) + '\n'
    cases = [('three actual helper LUTs', fixture, True),
             ('missing helper', fixture.replace('mn_fetch_run_lut', 'other'), False),
             ('FF is not LUT', fixture.replace('F:snes_dspx/mn_fetch_run_lut:#LUT:D=A1', 'FFX:snes_dspx/mn_fetch_run_lut:#FF'), False),
             ('duplicate instance', fixture + 'inst "part0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture + 'net "n";\nnet "n";\n', False),
             ('incomplete record', fixture + 'net "incomplete"', False),
             ('two physical aliases', fixture + 'inst "extra" "SLICEL", cfg " F:snes_dspx/mn_fetch_run_lut/x:#LUT:D=A1 ";\n', False),
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
