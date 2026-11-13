#!/usr/bin/env python3
"""GitHub-only ALU_P control proof, retained mapping and strict timing analysis.
Every original ALU_P write, reset hold, freeze and scan restore is retained.
The transition proof covers arbitrary current state and X inputs without cycle skips.
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
STATE = [('alu_p', 16)]
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
    return result.returncode, result.stdout.decode() + result.stderr.decode()
FRAGMENTS = {'baseline': '4d0199bf639629284546858b2b92abcd840b48a9', 'path': 'verilog/sd2snes_dsp/upd77c25.v', 'goldSha256': '8e82c280d3b69fd273ffd468b5de4b06fd82fbf3a352b9948d70ef214b9253ff', 'gateSha256': '70839c426a0cc2c5449fb329289c195196b8ee5af807b77eb01e61b121e0e34e', 'edits': [{'before': "            if(op_alu[3:1] == 3'b100) begin\n              alu_p <= 16'h0001;\n            end else begin\n              case(op_pselect)\n                2'b00:\n                  alu_p <= ram_douta;\n                2'b01:\n                  alu_p <= idb;\n                2'b10:\n                  alu_p <= regs_m;\n                2'b11:\n                  alu_p <= regs_n;\n              endcase\n            end", 'after': "`ifdef MK2\n`ifdef DSP_COMP\n            // ALU_P has its own equivalent writer below the bounded decode.\n`else\n            if(op_alu[3:1] == 3'b100) begin\n              alu_p <= 16'h0001;\n            end else begin\n              case(op_pselect)\n                2'b00:\n                  alu_p <= ram_douta;\n                2'b01:\n                  alu_p <= idb;\n                2'b10:\n                  alu_p <= regs_m;\n                2'b11:\n                  alu_p <= regs_n;\n              endcase\n            end\n`endif\n`else\n            if(op_alu[3:1] == 3'b100) begin\n              alu_p <= 16'h0001;\n            end else begin\n              case(op_pselect)\n                2'b00:\n                  alu_p <= ram_douta;\n                2'b01:\n                  alu_p <= idb;\n                2'b10:\n                  alu_p <= regs_m;\n                2'b11:\n                  alu_p <= regs_n;\n              endcase\n            end\n`endif"}, {'before': "        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;", 'after': "`ifdef MK2\n`ifdef DSP_COMP\n        // ALU_P restore remains in its separate complete writer.\n`else\n        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;\n`endif\n`else\n        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;\n`endif"}, {'before': "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n`ifdef MK2\n    push_now <= 1'b0;", 'after': "`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_ALUP_WRITER_BEGIN\nwire alu_p_state_low, alu_p_state_high, alu_p_op_allowed, alu_p_run, alu_p_normal_write;\ndspx_alup_nibble #(.VALUE(4'h4)) alu_p_state_low_lut(\n  .value(insn_state[3:0]), .selected(alu_p_state_low)\n);\ndspx_alup_nibble #(.VALUE(4'h0)) alu_p_state_high_lut(\n  .value(insn_state[7:4]), .selected(alu_p_state_high)\n);\ndspx_alup_opcode alu_p_opcode_lut(.op(op), .selected(alu_p_op_allowed));\ndspx_alup_run alu_p_run_lut(.reset_n(RST), .frozen(ss_frozen), .selected(alu_p_run));\ndspx_alup_join alu_p_join_lut(\n  .lo(alu_p_state_low), .hi(alu_p_state_high),\n  .arithmetic(alu_p_op_allowed), .running(alu_p_run), .selected(alu_p_normal_write)\n);\nalways @(posedge CLK) begin\n  if(alu_p_normal_write) begin\n    if(op_alu[3:1] == 3'b100) begin\n      alu_p <= 16'h0001;\n    end else begin\n      case(op_pselect)\n        2'b00:\n          alu_p <= ram_douta;\n        2'b01:\n          alu_p <= idb;\n        2'b10:\n          alu_p <= regs_m;\n        2'b11:\n          alu_p <= regs_n;\n      endcase\n    end\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n      end else case(ss_wa)\n        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;\n      endcase\n    end\n  end\nend\n// DSPX_ALUP_WRITER_END\n`endif\n`endif\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n`ifdef MK2\n    push_now <= 1'b0;"}], 'tail': '\n`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_ALUP_HELPERS_BEGIN\n// Procedural qualification keeps the original unknown-condition behavior.\n(* LUT_MAP="yes" *)\nmodule dspx_alup_nibble #(parameter [3:0] VALUE = 4\'h0)(\n  input [3:0] value, output reg selected\n);\nalways @* begin\n  selected = 1\'b0;\n  if(value == VALUE) selected = 1\'b1;\nend\nendmodule\n\n(* LUT_MAP="yes" *)\nmodule dspx_alup_opcode(input [1:0] op, output reg selected);\nalways @* begin\n  selected = 1\'b0;\n  case(op)\n    2\'b00, 2\'b01: selected = 1\'b1;\n  endcase\nend\nendmodule\n\n(* LUT_MAP="yes" *)\nmodule dspx_alup_run(input reset_n, frozen, output reg selected);\nalways @* begin\n  selected = 1\'b0;\n  if(reset_n & ~frozen) selected = 1\'b1;\nend\nendmodule\n\n(* LUT_MAP="yes" *)\nmodule dspx_alup_join(input lo, hi, arithmetic, running, output selected);\nassign selected = lo & hi & arithmetic & running;\nendmodule\n// DSPX_ALUP_HELPERS_END\n`endif\n`endif\n', 'normal': "            if(op_alu[3:1] == 3'b100) begin\n              alu_p <= 16'h0001;\n            end else begin\n              case(op_pselect)\n                2'b00:\n                  alu_p <= ram_douta;\n                2'b01:\n                  alu_p <= idb;\n                2'b10:\n                  alu_p <= regs_m;\n                2'b11:\n                  alu_p <= regs_n;\n              endcase\n            end", 'restore': "        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;", 'writer': "// DSPX_ALUP_WRITER_BEGIN\nwire alu_p_state_low, alu_p_state_high, alu_p_op_allowed, alu_p_run, alu_p_normal_write;\ndspx_alup_nibble #(.VALUE(4'h4)) alu_p_state_low_lut(\n  .value(insn_state[3:0]), .selected(alu_p_state_low)\n);\ndspx_alup_nibble #(.VALUE(4'h0)) alu_p_state_high_lut(\n  .value(insn_state[7:4]), .selected(alu_p_state_high)\n);\ndspx_alup_opcode alu_p_opcode_lut(.op(op), .selected(alu_p_op_allowed));\ndspx_alup_run alu_p_run_lut(.reset_n(RST), .frozen(ss_frozen), .selected(alu_p_run));\ndspx_alup_join alu_p_join_lut(\n  .lo(alu_p_state_low), .hi(alu_p_state_high),\n  .arithmetic(alu_p_op_allowed), .running(alu_p_run), .selected(alu_p_normal_write)\n);\nalways @(posedge CLK) begin\n  if(alu_p_normal_write) begin\n    if(op_alu[3:1] == 3'b100) begin\n      alu_p <= 16'h0001;\n    end else begin\n      case(op_pselect)\n        2'b00:\n          alu_p <= ram_douta;\n        2'b01:\n          alu_p <= idb;\n        2'b10:\n          alu_p <= regs_m;\n        2'b11:\n          alu_p <= regs_n;\n      endcase\n    end\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n      end else case(ss_wa)\n        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;\n      endcase\n    end\n  end\nend\n// DSPX_ALUP_WRITER_END", 'helpers': '// DSPX_ALUP_HELPERS_BEGIN\n// Procedural qualification keeps the original unknown-condition behavior.\n(* LUT_MAP="yes" *)\nmodule dspx_alup_nibble #(parameter [3:0] VALUE = 4\'h0)(\n  input [3:0] value, output reg selected\n);\nalways @* begin\n  selected = 1\'b0;\n  if(value == VALUE) selected = 1\'b1;\nend\nendmodule\n\n(* LUT_MAP="yes" *)\nmodule dspx_alup_opcode(input [1:0] op, output reg selected);\nalways @* begin\n  selected = 1\'b0;\n  case(op)\n    2\'b00, 2\'b01: selected = 1\'b1;\n  endcase\nend\nendmodule\n\n(* LUT_MAP="yes" *)\nmodule dspx_alup_run(input reset_n, frozen, output reg selected);\nalways @* begin\n  selected = 1\'b0;\n  if(reset_n & ~frozen) selected = 1\'b1;\nend\nendmodule\n\n(* LUT_MAP="yes" *)\nmodule dspx_alup_join(input lo, hi, arithmetic, running, output selected);\nassign selected = lo & hi & arithmetic & running;\nendmodule\n// DSPX_ALUP_HELPERS_END', 'parameters': "parameter STATE_ALU1  = 8'b00000100;\nparameter I_OP = 2'b00;\nparameter I_RT = 2'b01;", 'goldBody': "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    case(insn_state)\n      STATE_ALU1: begin\n        case(op)\n          I_OP, I_RT: begin\n            if(op_alu[3:1] == 3'b100) begin\n              alu_p <= 16'h0001;\n            end else begin\n              case(op_pselect)\n                2'b00:\n                  alu_p <= ram_douta;\n                2'b01:\n                  alu_p <= idb;\n                2'b10:\n                  alu_p <= regs_m;\n                2'b11:\n                  alu_p <= regs_n;\n              endcase\n            end\n          end\n        endcase\n      end\n    endcase\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n      end else case(ss_wa)\n        8'h20: alu_p[7:0]  <= ss_wd;\n        8'h21: alu_p[15:8] <= ss_wd;\n      endcase\n    end\n  end\nend"}

HEADER = """module alup_model(input CLK,RST,ss_frozen,ss_wr,
input [7:0] ss_wa,ss_wd,insn_state,input [1:0] op,op_pselect,
input [3:0] op_alu,input [15:0] ram_douta,idb,regs_m,regs_n,
output [15:0] state,output [7:0] scan_low,scan_high);
reg [15:0] alu_p;
"""
TRAILER = """
assign state = alu_p;
assign scan_low = alu_p[7:0];
assign scan_high = alu_p[15:8];
endmodule
"""
def cut_design(design, name):
    need(set(design['modules']) == {'alup_model'} and name in ('gold', 'gate'), 'Unexpected model')
    module = design['modules']['alup_model']
    state = [bit for signal, width in STATE for bit in module['netnames'][signal]['bits']]
    need(all(len(module['netnames'][signal]['bits']) == width for signal, width in STATE), 'State widths changed')
    need(len(state) == len(set(state)) == 16 and all(type(bit) is int for bit in state), 'State alias or missing bit')
    observed = list(module['ports']['state']['bits'])
    need(len(observed) == 16 and module['ports']['state']['direction'] == 'output', 'State view changed')
    for net in module['netnames'].values():
        need('init' not in net.get('attributes', {}), 'Original ALU_P must remain uninitialized')
    clock = module['ports']['CLK']['bits']
    next_bits, registers = {}, []
    for key, cell in module['cells'].items():
        kind = cell['type']
        if kind != '$dff':
            need(kind.startswith('$') and not any(s in kind.lower() for s in ('ff', 'latch', 'mem'))
                 and 'CLK' not in cell['connections'] and kind not in ('$anyseq', '$anyconst'), 'Hidden state or blackbox')
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
        parameters=dict(A_SIGNED='0'*32, B_SIGNED='0'*32, A_WIDTH=format(16,'032b'), B_WIDTH=format(16,'032b'), Y_WIDTH=format(1,'032b')),
        port_directions=dict(A='input',B='input',Y='output'), connections=dict(A=observed,B=list(state),Y=[check]))
    del module['ports']['state']
    for key, direction, bits in [('state_in','input',state), ('next_state','output',[next_bits[bit] for bit in state]), ('state_view_ok','output',[check])]:
        need(key not in module['ports'] and key not in module['netnames'], 'Preexisting state boundary')
        module['ports'][key] = dict(direction=direction,bits=list(bits))
        module['netnames'][key] = dict(hide_name=0,bits=list(bits),attributes={})
    module.get('attributes', {}).pop('top', None)
    design['modules'] = {name: module}
    return design, dict(stateOrder=STATE, qBits=state, dBits=[next_bits[bit] for bit in state], initialBits=['x']*16, noHiddenState=True)


def compile_model(text, output, name):
    output.mkdir()
    (output / 'model.v').write_text(text)
    script = ('read_verilog -sv -formal model.v\nhierarchy -check -top alup_model\nflatten\n'
              'proc -ifx -noopt\ndffunmap\nsetundef -undriven -undef\nopt_clean\ncheck -assert\nwrite_json state.json\n')
    (output / 'prepare.ys').write_text(script)
    run(['yosys', '-s', 'prepare.ys'], output, 'preparation')
    original = json.loads((output / 'state.json').read_text())
    design, audit = cut_design(copy.deepcopy(original), name)
    save(output / 'transition.json', design); save(output / 'state-audit.json', audit)
    controls = []
    for label in ['wrong-clock', 'duplicate-Q', 'wrong-init']:
        changed = copy.deepcopy(original); m = changed['modules']['alup_model']
        ff = next(cell for cell in m['cells'].values() if cell['type'] == '$dff')
        if label == 'wrong-clock':
            ff['parameters']['CLK_POLARITY'] = '0' * 32
        elif label == 'duplicate-Q':
            ff = next(cell for cell in m['cells'].values() if cell['type'] == '$dff' and len(cell['connections']['Q']) > 1)
            ff['connections']['Q'][1] = ff['connections']['Q'][0]
        else:
            m['netnames']['alu_p'].setdefault('attributes', {})['init'] = '0' * 16
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
                   outputPorts=outputs, strictX=True, currentStateBits=16, sourceInitialization='undefined, no initialization added',
                   noCycleSkips=True, arbitraryCurrentState=True, noAssumptions=True)
    save(output / 'proof-review.json', receipt)
    return receipt

def proof(output):
    output.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', BASE + ':' + SOURCE]).decode()
    gate = Path(SOURCE).read_text()
    need(sha(original.encode()) == FRAGMENTS['goldSha256'] and sha(gate.encode()) == FRAGMENTS['gateSha256'], 'Original or candidate full source identity changed')
    reconstructed = original
    for edit in FRAGMENTS['edits']:
        reconstructed = once(reconstructed, edit['before'], edit['after'])
    need(reconstructed + FRAGMENTS['tail'] == gate, 'Change not limited to full reviewed ALU_P writer')
    need(len(re.findall(r'\balu_p(?:\[[^\]]+\])?\s*<=', original)) == 7, 'Original ALU_P writer inventory changed')
    need(not re.search(r'\binitial\b[^;\n]*\balu_p\b', original), 'Original ALU_P startup initialization changed')
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, 'HEAD', '--', 'verilog']).decode().splitlines()
    need(changed == [SOURCE], 'Unreviewed production edit')
    main = Path('verilog/sd2snes_dsp/main.v').read_text()
    need(re.search(r'\bupd77c25\s+snes_dspx\s*\(', main), 'Actual instance overrides default state/opcode parameters')
    for fragment in [FRAGMENTS['normal'], FRAGMENTS['restore'], '  if(RST & ~ss_frozen) begin',
                     "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin"]:
        need(fragment in original, 'Original procedural ancestor missing')
    need('      STATE_ALU1: begin\n        insn_state <= STATE_ALU2;\n        case(op)\n          I_OP, I_RT: begin\n            alu_q <= regs_ab[op_asl];\n' + FRAGMENTS['normal'] in original, 'Original normal ALU_P ancestors differ')
    (output / 'gold-source.v').write_text(original); (output / 'gate-source.v').write_text(gate)
    save(output / 'source-boundary.json', FRAGMENTS)
    rows = []; results = []; first = None
    for index, (board, comp, debug, lean) in enumerate(itertools.product(['MK2','MK3'], [False,True], [False,True], [False,True])):
        defines = [board] + (['DSP_COMP'] if comp else []) + (['DEBUG'] if debug else []) + (['DSP_LEAN'] if lean else [])
        paths = []
        for label in ['gold','gate']:
            path = output / (label + '-preprocessed-' + str(index) + '.v')
            run(['iverilog','-g2005-sv','-E'] + ['-D' + d for d in defines] + ['-o',str(path),str(output / (label + '-source.v'))], output, label + '-preprocess-' + str(index))
            paths.append(path)
        target = board == 'MK2' and comp
        rows.append(dict(index=index, defines=defines, target=target, goldSha256=sha(paths[0].read_bytes()), gateSha256=sha(paths[1].read_bytes())))
        if not target:
            need([s for s in paths[0].read_text().splitlines() if s.strip()] == [s for s in paths[1].read_text().splitlines() if s.strip()], 'Non-target source changed')
            continue
        need(FRAGMENTS['writer'] in paths[1].read_text() and FRAGMENTS['helpers'] in paths[1].read_text(), 'Actual preprocessed target writer missing')
        need(len(re.findall(r'\balu_p(?:\[[^\]]+\])?\s*<=', paths[0].read_text())) == len(re.findall(r'\balu_p(?:\[[^\]]+\])?\s*<=', paths[1].read_text())) == 7, 'Preprocessed complete writer inventory changed')
        prefix = HEADER + FRAGMENTS['parameters'] + '\n'
        golden = prefix + FRAGMENTS['goldBody'] + TRAILER
        candidate = prefix + FRAGMENTS['writer'] + TRAILER + FRAGMENTS['helpers'] + '\n'
        folder = output / ('config-' + str(index)); folder.mkdir()
        compile_model(golden, folder / 'gold', 'gold'); compile_model(candidate, folder / 'gate', 'gate')
        for mode in ['binary','xstate']:
            results.append(prove_pair(folder / 'gold', folder / 'gate', folder / mode, mode, True))
        if first is None:
            first = (folder / 'gold', candidate)
    gold, candidate = first
    mutations = [
        ('missing-freeze', 'if(reset_n & ~frozen)', 'if(reset_n)'),
        ('wrong-state', ".VALUE(4'h4)", ".VALUE(4'h5)"),
        ('wrong-opcode', "2'b00, 2'b01: selected", "2'b00: selected"),
        ('wrong-data', 'alu_p <= regs_m;', 'alu_p <= regs_n;'),
        ('wrong-constant', "alu_p <= 16'h0001;", "alu_p <= 16'h0000;"),
        ('wrong-restore', "8'h20: alu_p[7:0]", "8'h22: alu_p[7:0]"),
        ('wrong-reset-hold', '  if(alu_p_normal_write) begin', "  if(!RST) alu_p <= 16'h0000;\n  else if(alu_p_normal_write) begin"),
        ('x-run-qualification', 'if(reset_n & ~frozen)', "if((reset_n & ~frozen) !== 1'b0)"),
        ('x-opcode-qualification', "case(op)\n    2'b00, 2'b01: selected = 1'b1;\n  endcase", "if(op[1] !== 1'b1) selected = 1'b1;"),
        ('x-constant-qualification', "if(op_alu[3:1] == 3'b100)", "if((op_alu[3:1] == 3'b100) !== 1'b0)")]
    for label, before, after in mutations:
        folder = output / label
        compile_model(once(candidate, before, after), folder, 'gate')
        results.append(prove_pair(gold, folder, output / (label + '-binary'), 'binary', label.startswith('x-')))
        if label.startswith('x-'):
            results.append(prove_pair(gold, folder, output / (label + '-xstate'), 'xstate', False))
    save(output / 'preprocessor-configurations.json', rows); save(output / 'full-transition-results.json', results)
    (output / 'production-change.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True), gate.splitlines(True), 'original', 'candidate')))
    sums = [sha(p.read_bytes()) + '  ' + p.relative_to(output).as_posix() for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'SHA256SUMS']
    (output / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    (output / 'verified.txt').write_text('Actual complete16-bit ALU_P arbitrary-state transitions and scan observations proved strictly for binary and unrestricted-X inputs in four target configurations; no temporal startup skips, no init/reset change, no hidden state, no assumptions. Other configurations unchanged. Ten actual bad-source counterexamples and three binary-only X-control passes required. Component proof only; native mapping/timing separate.\n')

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
    families = ['alu_p_state_low_lut','alu_p_state_high_lut','alu_p_opcode_lut','alu_p_run_lut','alu_p_join_lut']
    bindings = {family: [] for family in families}
    for component, body in instances.items():
        for slot, logical, equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)', body):
            for family in families:
                prefix = 'snes_dspx/' + family
                if logical == prefix or logical.startswith(prefix + '/'):
                    bindings[family].append(dict(component=component, slot=slot, logical=logical, equation=equation))
    save(output / 'alup-lut-observed-bindings.json', bindings)
    selected = {row['component'] for rows in bindings.values() for row in rows}
    selected_nets = {name for name, body in nets.items() if any(comp in selected for _, comp, _ in PIN.findall(body))}
    for name in selected_nets:
        selected.update(comp for direction, comp, _ in PIN.findall(nets[name]) if direction == 'outpin' and comp in instances)
    body = '\n\n'.join([instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]) + '\n'
    need(len(selected) <= 400 and len(selected_nets) <= 700 and len(body.encode()) <= 3000000, 'Bounded neighborhood exceeded; no truncation')
    (output / 'alup-luts-raw.txt').write_text(body)
    save(output / 'alup-physical-index.json', dict(sourceBytes=len(raw), sourceSha256=sha(raw), totalInstances=len(instances),
         totalNets=len(nets), bindings=bindings, selectedInstances=sorted(selected), selectedNets=sorted(selected_nets), rawSha256=sha(body.encode()),
         limits='Five bounded combinational helper LUTs, incident nets and immediate input drivers only; no whole mapped equivalence'))
    need(all(len(rows) == 1 for rows in bindings.values()), 'Five separate actual helper LUTs not observed; raw/index retained')

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
    for unit in ['dspx_alup_nibble', 'dspx_alup_opcode', 'dspx_alup_run', 'dspx_alup_join']:
        need(re.search(r'Set property "LUT_MAP = yes" for unit <' + unit + r'(?:_[^>]*)?>\.', syr), 'Combinational LUT_MAP not recognized: ' + unit)
    physical = json.loads((report / 'physical/alup-physical-index.json').read_text())
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
    families = ['alu_p_state_low_lut','alu_p_state_high_lut','alu_p_opcode_lut','alu_p_run_lut','alu_p_join_lut']
    fixture = '\n'.join('inst "part' + str(i) + '" "SLICEL", cfg " F:snes_dspx/' + family + ':#LUT:D=A1 ";' for i, family in enumerate(families)) + '\n'
    cases = [('five actual helper LUTs', fixture, True),
             ('missing helper', fixture.replace('alu_p_state_low_lut', 'other'), False),
             ('FF is not LUT', fixture.replace('F:snes_dspx/alu_p_state_low_lut:#LUT:D=A1', 'FFX:snes_dspx/alu_p_state_low_lut:#FF'), False),
             ('duplicate instance', fixture + 'inst "part0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture + 'net "n";\nnet "n";\n', False),
             ('incomplete record', fixture + 'net "incomplete"', False),
             ('two physical aliases', fixture + 'inst "extra" "SLICEL", cfg " F:snes_dspx/alu_p_state_low_lut/x:#LUT:D=A1 ";\n', False),
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
