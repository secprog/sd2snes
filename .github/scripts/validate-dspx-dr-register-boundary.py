#!/usr/bin/env python3
"""GitHub-only DR source, state, physical-text and timing-progress evidence."""
import copy
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

BASELINE = '274d52c8aa9c1970df2f04e39da1b5ddca8e6e25'
SOURCE = 'verilog/sd2snes_dsp/upd77c25.v'
ORIGINAL_SHA = 'af6ad41f629e2646763394ee0f2b5a1ef55e745fbb89b65701a3c8de54bcbf81'
CANDIDATE_SHA = '0df670a992d4d315cecca358908fcf48378346154f3baa40798ea5103fb2ccc1'
STATE = [('regs_dr', 16)]
ATTRIBUTE = '(* register_balancing = "no" *)\n'
COMMENT = '// Preserve the complete DR register boundary rather than backward retiming it.\n'
ADDITION = '`ifdef MK2\n`ifdef DSP_COMP\n// Preserve the complete DR register boundary rather than backward retiming it.\n(* register_balancing = "no" *)\n`endif\n`endif\n'
DECL = 'reg [15:0] regs_dr;\n'
ORIGINAL_BLOCK = "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(enable & reg_we_rising & (A0 == 1'b0)) begin\n      if(!regs_sr[SR_DRC]) begin\n        if(regs_sr[SR_DRS] == 1'b0) begin\n          regs_dr[7:0] <= DI;\n        end else begin\n          regs_dr[15:8] <= DI;\n        end\n      end else begin\n        regs_dr[7:0] <= DI;\n      end\n    end else if(ld_dst == 4'b0110 && insn_state == STATE_STORE) begin\n      if (op == I_OP || op == I_RT) regs_dr <= idb;\n      else if (op == I_LD) regs_dr <= ld_id;\n    end\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      if(ss_wa == 8'h0a) regs_dr[7:0]  <= ss_wd; // restore low byte\n      if(ss_wa == 8'h0b) regs_dr[15:8] <= ss_wd; // restore high byte\n    end\n  end else begin\n    regs_dr <= 16'h0000;\n  end\nend\n"

def need(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def once(text, before, after):
    need(text.count(before) == 1, 'Missing or ambiguous source boundary')
    return text.replace(before, after, 1)


def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', 'show', BASELINE + ':' + SOURCE])
    candidate = Path(SOURCE).read_bytes()
    need(sha(original) == ORIGINAL_SHA and sha(candidate) == CANDIDATE_SHA, 'DR source identity changed')
    old, new = original.decode(), candidate.decode()
    need(once(new, ADDITION, '') == old and old.count(DECL) == 1,
         'Whole source inverse changes more than one scoped register attribute')
    need(old.count(ORIGINAL_BLOCK) == new.count(ORIGINAL_BLOCK) == 1, 'Original DR writer changed')
    need(old.count("  regs_dr = 16'b0;") == 1, 'Original DR initialization changed')
    main = Path('verilog/sd2snes_dsp/main.v').read_bytes()
    need(sha(main) == 'b8603c17eed9aaaf1cc290dd278462a9443a300b1e1278af2359cf08a8054869', 'Original main/DP isolation/timer source changed')
    need(len(re.findall(r'upd77c25\s+snes_dspx\s*\(', main.decode())) == 1, 'Unexpected DSP parameter override')
    for name, text in [('original', old), ('candidate', new)]:
        (output / (name + '-upd77c25.v')).write_text(text, encoding='utf-8')
    configs = [('none', []), ('debug', ['DEBUG']), ('mk3', ['MK3']), ('mk3-debug', ['MK3', 'DEBUG']),
               ('mk2', ['MK2']), ('mk2-debug', ['MK2', 'DEBUG']), ('dsp', ['DSP_COMP']),
               ('dsp-debug', ['DSP_COMP', 'DEBUG']), ('mk3-dsp', ['MK3', 'DSP_COMP']),
               ('mk3-dsp-debug', ['MK3', 'DSP_COMP', 'DEBUG']), ('mk2-dsp', ['MK2', 'DSP_COMP']),
               ('mk2-dsp-debug', ['MK2', 'DSP_COMP', 'DEBUG']),
               ('mk2-dsp-lean', ['MK2', 'DSP_COMP', 'DSP_LEAN']),
               ('mk3-dsp-lean', ['MK3', 'DSP_COMP', 'DSP_LEAN']),
               ('mk2-lean', ['MK2', 'DSP_LEAN']), ('mk3-lean', ['MK3', 'DSP_LEAN'])]
    pp = []
    for name, flags in configs:
        target = 'MK2' in flags and 'DSP_COMP' in flags
        header = Path('verilog/sd2snes_dspx' if target else 'verilog/sd2snes_dsp')
        pair = {}
        for version in ('original', 'candidate'):
            path = output / ('pp-' + name + '-' + version + '.v')
            subprocess.run(['iverilog', '-g2012', '-E', '-I', str(header.resolve())]
                           + ['-D' + flag for flag in flags]
                           + ['-o', str(path), str(output / (version + '-upd77c25.v'))], check=True)
            pair[version] = path.read_text(encoding='utf-8')
            need(pair[version].strip(), 'Empty actual preprocessing output')
        reverted = pair['candidate']
        if target:
            reverted = once(reverted, COMMENT + ATTRIBUTE, '')
        need(re.sub(r'\s+', '', reverted) == re.sub(r'\s+', '', pair['original']), 'Preprocessing scope changed: ' + name)
        pp.append(dict(name=name, flags=flags, target=target, header=header.as_posix()))
    parameters = []
    for name in ['STATE_STORE', 'I_OP', 'I_RT', 'I_LD', 'SR_DRS', 'SR_DRC']:
        matches = re.findall(r'^parameter ' + name + r' = [^;]+;', old, re.M)
        need(len(matches) == 1, 'Source parameter missing or duplicate')
        parameters.append(matches[0])
    read = re.findall(r'^assign UPD_DO = .*?;', old, re.M)
    need(len(read) == 1, 'Missing actual CPU read expression')
    need("8'h0a: ss_reg_do = regs_dr[7:0];" in old and "8'h0b: ss_reg_do = regs_dr[15:8];" in old, 'Actual DR scan reads changed')
    prefix = ('module dr_model(input CLK, RST, ss_frozen, enable, reg_we_rising, A0, ss_wr,\n'
              ' input [7:0] DI, ss_wa, ss_wd, input [15:0] regs_sr, idb, ld_id,\n'
              ' input [3:0] ld_dst, input [7:0] insn_state, input [1:0] op,\n'
              ' output [15:0] state, output [7:0] cpu_read, scan_low, scan_high);\n'
              + '\n'.join(parameters) + "\n" + DECL + "initial regs_dr = 16'b0;\n")
    suffix = ('\nassign state = regs_dr;\n' + read[0].replace('assign UPD_DO', 'assign cpu_read')
              + '\nassign scan_low = regs_dr[7:0];\nassign scan_high = regs_dr[15:8];\nendmodule\n')
    gold = prefix + ORIGINAL_BLOCK + suffix
    gate = once(prefix, DECL, ATTRIBUTE + DECL) + ORIGINAL_BLOCK + suffix
    models = {'gold': gold, 'gate': gate}
    changes = {
        'bad-enable': ("if(enable & reg_we_rising & (A0 == 1'b0))", "if(reg_we_rising & (A0 == 1'b0))"),
        'bad-strobe': ("if(enable & reg_we_rising & (A0 == 1'b0))", "if(enable & (A0 == 1'b0))"),
        'bad-a0': ("if(enable & reg_we_rising & (A0 == 1'b0))", "if(enable & reg_we_rising & (A0 == 1'b1))"),
        'bad-word-priority': ('end else if(ld_dst', 'end\n    if(ld_dst'),
        'bad-drc-lane': ('if(!regs_sr[SR_DRC])', 'if(regs_sr[SR_DRC])'),
        'bad-drs-lane': ("if(regs_sr[SR_DRS] == 1'b0)", "if(regs_sr[SR_DRS] == 1'b1)"),
        'bad-store-phase': ("insn_state == STATE_STORE", "insn_state == 8'b00000001"),
        'bad-opcode': ('else if (op == I_LD) regs_dr <= ld_id;', "else if (op == 2'b10) regs_dr <= ld_id;"),
        'bad-restore-lane': ("if(ss_wa == 8'h0a) regs_dr[7:0]", "if(ss_wa == 8'h0b) regs_dr[7:0]"),
        'bad-final-reset': ("regs_dr <= 16'h0000;", "regs_dr <= 16'hffff;"),
        'bad-cpu-data': ("if(regs_sr[SR_DRS] == 1'b0) begin\n          regs_dr[7:0] <= DI;", "if(regs_sr[SR_DRS] == 1'b0) begin\n          regs_dr[7:0] <= ~DI;"),
        'bad-hold': ('if(RST & ~ss_frozen) begin', "if(RST & ~ss_frozen) begin\n    regs_dr <= 16'h0000;"),
        'bad-x-request': ("if(enable & reg_we_rising & (A0 == 1'b0))", "if((enable & reg_we_rising & (A0 == 1'b0)) !== 1'b0)"),
        'bad-x-drc': ('if(!regs_sr[SR_DRC])', "if((!regs_sr[SR_DRC]) !== 1'b0)"),
        'bad-x-drs': ("if(regs_sr[SR_DRS] == 1'b0)", "if((regs_sr[SR_DRS] == 1'b0) !== 1'b0)"),
    }
    for name, (before, after) in changes.items():
        models[name] = once(gate, before, after)
    for name, text in models.items():
        (output / (name + '.v')).write_text(text, encoding='utf-8')
    save(output / 'source-boundary.json', dict(baseline=BASELINE, originalSha256=ORIGINAL_SHA,
         candidateSha256=CANDIDATE_SHA, exactFullSourceInverse=True, stateBits=16, stateOrder=STATE,
         models=list(models), sourceBlock=ORIGINAL_BLOCK, addedAttribute=ADDITION, parameters=parameters,
         actualCpuRead=read[0], originalInitialization="regs_dr = 16'b0;",
         actualScanLow="8'h0a: ss_reg_do = regs_dr[7:0];",
         actualScanHigh="8'h0b: ss_reg_do = regs_dr[15:8];", noOtherBehavioralChanges=True,
         limits='Complete original DR state/init/writer and reads only; actual synthesis mapping, timing and external I/O require separate evidence.'))
    save(output / 'preprocessing.json', pp)
    (output / 'source.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), 'original', 'candidate')), encoding='utf-8')
    rows = [sha(path.read_bytes()) + '  ' + path.name for path in sorted(output.iterdir()) if path.is_file()]
    (output / 'SHA256SUMS').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    print('Bound one register attribute,16 actual preprocessing configurations and all16 unchanged DR state/init bits with original CPU/scan reads')


def cut_design(design, name):
    need(set(design['modules']) == {'dr_model'} and name in ('gold', 'gate'), 'Unexpected model')
    module = design['modules']['dr_model']
    state = [bit for signal, width in STATE for bit in module['netnames'][signal]['bits']]
    need(all(len(module['netnames'][signal]['bits']) == width for signal, width in STATE), 'State widths changed')
    need(len(state) == len(set(state)) == 16 and all(type(bit) is int for bit in state), 'State alias or missing bit')
    observed = list(module['ports']['state']['bits'])
    need(len(observed) == 16 and module['ports']['state']['direction'] == 'output', 'State view changed')
    initial = {}
    for net in module['netnames'].values():
        value = net.get('attributes', {}).get('init')
        if value is None:
            continue
        need(len(value) == len(net['bits']), 'Malformed initial state')
        for bit, digit in zip(net['bits'], reversed(value)):
            if type(bit) is int:
                need(bit in state and digit == '0', 'Unexpected initialized state or initial value')
                initial[bit] = digit
        net['attributes'].pop('init', None)
    need(set(initial) == set(state), 'Every actual state bit must retain init0')
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
    return design, dict(stateOrder=STATE, qBits=state, dBits=[next_bits[bit] for bit in state], initialBits=['0']*16, noHiddenState=True)


def cut(source, output, name):
    original = json.loads(source.read_text())
    design, audit = cut_design(copy.deepcopy(original), name)
    save(output, design)
    save(output.with_name('state-audit.json'), audit)
    # Each model must reject real JSON boundary mutations, before its proof.
    controls = []
    module = original['modules']['dr_model']
    for label in ('wrong-clock', 'duplicate-Q', 'wrong-init'):
        changed = copy.deepcopy(original); m = changed['modules']['dr_model']
        ff = next(c for c in m['cells'].values() if c['type'] == '$dff')
        if label == 'wrong-clock':
            ff['parameters']['CLK_POLARITY'] = '0'*32
        elif label == 'duplicate-Q':
            ff = next(c for c in m['cells'].values() if c['type'] == '$dff' and len(c['connections']['Q']) > 1)
            q = ff['connections']['Q']; q[1] = q[0]
        else:
            net = next(n for n in m['netnames'].values() if 'init' in n.get('attributes', {}))
            net['attributes']['init'] = '1' + net['attributes']['init'][1:]
        try:
            cut_design(changed, name)
        except ValueError as error:
            controls.append(dict(name=label,rejected=True,error=str(error)))
        else:
            raise ValueError('Accepted corrupt state boundary: ' + label)
    save(output.with_name('state-controls.json'), controls)
    if name == 'gold':
        changed = copy.deepcopy(design)
        b = changed['modules']['gold']['cells']['$state_view_strict_eq']['connections']['B']
        b[0], b[1] = b[1], b[0]
        save(output.with_name('state-view-mutant.json'), changed)
    print(name + ': all16 unique positive-edge DFF Q/D bits and init0 audited; state controls rejected')


def collect(source, output):
    text = source.read_text(encoding='utf-8')
    starts = re.findall(r'(?m)^\s*(inst|net)\s+"', text)
    statements = re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;', text)
    need(starts and len(starts) == len(statements), 'Missing or incomplete physical statements')
    instances, nets = {}, {}
    for statement in statements:
        match = re.match(r'\s*(inst|net)\s+"([^"\n]+)"', statement)
        need(match is not None, 'Unrecognized physical statement')
        kind, name = match.groups(); target = instances if kind == 'inst' else nets
        need(name not in target, 'Duplicate physical statement')
        target[name] = statement.strip()
    need(len(instances) > 1000 and len(nets) > 1000, 'Unexpectedly small mapped design')
    pin = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')
    bindings, unrecognized = [], []
    named_components = {comp for comp, statement in instances.items() if ('regs_dr' in statement)}
    for comp, statement in instances.items():
        for slot, logical in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)', statement):
            match = re.fullmatch(r'snes_dspx/regs_dr(?:_(\d+)|<(\d+)>)(?:_.*)?', logical)
            if match:
                bit = int(match.group(1) or match.group(2))
                bindings.append(dict(bit=bit, logical=logical, slot=slot, component=comp))
            elif 'regs_dr' in logical:
                unrecognized.append(dict(logical=logical, slot=slot, component=comp))
    selected = named_components | {b['component'] for b in bindings}
    selected_nets = {name for name, raw in nets.items() if any(comp in selected for _, comp, _ in pin.findall(raw))}
    for name in selected_nets:
        selected.update(comp for kind, comp, _ in pin.findall(nets[name]) if kind == 'outpin' and comp in instances)
    need(len(selected) <= 400 and len(selected_nets) <= 1200, 'Physical excerpt exceeds declared bound')
    records = [instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]
    raw = '\n\n'.join(records) + '\n'
    need(len(raw.encode()) <= 3000000, 'Physical excerpt exceeds text limit')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'dr-raw-statements.txt').write_text(raw, encoding='utf-8')
    save(output / 'dr-physical-index.json', dict(sourceBytes=source.stat().st_size,
         sourceSha256=sha(source.read_bytes()), totalInstances=len(instances), totalNets=len(nets),
         bindings=bindings, unrecognizedDrFFs=unrecognized, observedBitNumbers=sorted({b['bit'] for b in bindings}),
         selectedInstances=len(selected), selectedNets=len(selected_nets),
         rawSha256=sha(raw.encode()), limits='Raw mapped component, co-packed attributes and immediate adjacent nets/drivers only; no whole mapped equivalence claim.'))
    need({b['bit'] for b in bindings} == set(range(16)), 'Not all sixteen named DR bits were observed')
    need(len({(b['component'], b['slot']) for b in bindings}) == len(bindings), 'Duplicate physical FF slot')
    print('Retained all observed DR FF bindings and complete bounded physical records')


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
                minimumDisplayedSlackNs=min(value for _, value in values),
                displayedNegativePaths=sum(value < 0 for _, value in values), displayedSlackRecords=len(values))


def collect_controls(output):
    output.mkdir(parents=True, exist_ok=True)
    fixture = '\n'.join('inst "dummy' + str(i) + '" "SLICEL", cfg " F::#OFF ";' for i in range(1001)) + '\n'
    fixture += '\n'.join('net "dummy' + str(i) + '";' for i in range(1001)) + '\n'
    fixture += '\n'.join('inst "sec' + str(i) + '" "SLICEL", cfg " FFX:snes_dspx/regs_dr_' + str(i) + ':#FF FFX_INIT_ATTR::INIT0 SRINV::#OFF ";' for i in range(16)) + '\n'
    cases = [('sixteen named physical FFs', fixture, True),
             ('two FF slots in one component', fixture.replace('FFX:snes_dspx/regs_dr_0:#FF', 'FFX:snes_dspx/regs_dr_0:#FF FFY:snes_dspx/regs_dr_1:#FF').replace('FFX:snes_dspx/regs_dr_1:#FF', 'FFX:other_1:#FF'), True),
             ('missing bit', fixture.replace('FFX:snes_dspx/regs_dr_5:#FF', 'FFX:other_5:#FF'), False),
             ('LUT is not FF', fixture.replace('FFX:snes_dspx/regs_dr_5:#FF', 'F:snes_dspx/regs_dr_5:#LUT:D=A1'), False),
             ('duplicate instance', fixture + 'inst "sec0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture + 'net "dummy0";\n', False),
             ('incomplete statement', fixture + 'net "incomplete"', False),
             ('duplicate physical slot', fixture.replace('FFX:snes_dspx/regs_dr_0:#FF', 'FFX:snes_dspx/regs_dr_0:#FF FFX:snes_dspx/regs_dr_1:#FF'), False)]
    rows = []
    for i, (name, text, expected) in enumerate(cases):
        path = output / (str(i) + '.xdl.txt'); path.write_text(text, encoding='utf-8')
        error = None
        try:
            collect(path, output / str(i)); accepted = True
        except ValueError as failure:
            accepted, error = False, str(failure)
        rows.append(dict(name=name, expected=expected, accepted=accepted, error=error, passed=accepted == expected))
    save(output / 'results.json', dict(controls=rows, passed=all(row['passed'] for row in rows)))
    need(all(row['passed'] for row in rows), 'Physical text collector controls failed')


def progress(baseline, candidate):
    # Keep a better result only when the scored setup measures agree and no
    # hold/component regression is introduced. Remaining failures stay failures.
    nonregression = (candidate['traceErrors'] <= baseline['traceErrors']
                     and candidate['parScore'] <= baseline['parScore']
                     and candidate['worstDisplayedSetupSlackNs'] >= baseline['worstDisplayedSetupSlackNs']
                     and candidate['parHoldScore'] == candidate['traceHoldScore'] == candidate['componentSwitchingScore'] == 0
                     and candidate['worstDisplayedHoldSlackNs'] >= 0)
    better = (candidate['traceErrors'] < baseline['traceErrors']
              or candidate['parScore'] < baseline['parScore']
              or candidate['worstDisplayedSetupSlackNs'] > baseline['worstDisplayedSetupSlackNs'])
    return bool(nonregression and better)


def analysis_controls(output):
    base = dict(traceErrors=13, parScore=1503, worstDisplayedSetupSlackNs=-0.206,
                parHoldScore=0, traceHoldScore=0, componentSwitchingScore=0, worstDisplayedHoldSlackNs=0.798)
    cases = [('unchanged is not improvement', {}, False),
             ('fewer failures while still failing', dict(traceErrors=12), True),
             ('less negative slack while still failing', dict(worstDisplayedSetupSlackNs=-0.205), True),
             ('lower total score while still failing', dict(parScore=1502), True),
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
    print('Passed thirteen incremental-adoption controls, including remaining-failure positives')


def analyze(report, baseline_dir):
    baseline_paths = {}
    for name, expected in [('main.twr', 'cbdfa669beca53cd215d6e81f9759d5053fc8c2746f94fdc43a8f469605973cf'),
                           ('main.par', '4e44e96e979c704cdf205f552be45cdf6e4fe9f0008b51ab351bb9d731494012')]:
        paths = list(baseline_dir.rglob(name)); need(len(paths) == 1, 'Missing/duplicate original production report')
        need(sha(paths[0].read_bytes()) == expected, 'Original production report identity changed')
        baseline_paths[name] = paths[0]
    baseline = timing({key: baseline_paths['main.' + key].read_text() for key in ('par', 'twr')})
    native = report / 'native-reports'
    text = {key: (native / name).read_text(encoding='utf-8') for key, name in
            [('par', 'main.par'), ('twr', 'main.twr'), ('pcf', 'main.pcf'), ('mrp', 'main_map.mrp')]}
    candidate = timing(text)
    need(len(re.findall(r'^par -w -ol high -xe c -t 68 main_map\.ncd main\.ncd main\.pcf\s*$', text['par'], re.M)) == 1, 'Original PAR invocation changed')
    need(len(re.findall(r'/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr', text['twr'])) == 1, 'Original TRACE invocation changed')
    expected_map = 'map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 68 -register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy -pr b -bp -power off -o main_map.ncd main.ngd main.pcf'
    command = re.search(r'Command Line\s*:\s*(.*?)\s*Target Device', text['mrp'], re.S)
    need(command is not None and ' '.join(command.group(1).split()) == expected_map, 'Original MAP invocation changed')
    need(re.findall(r'^SYSTEM_JITTER\s*=\s*([^;\r\n]+);', text['pcf'], re.M) == ['480 ps'], 'Original jitter changed')
    periods = re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;', text['pcf'])
    expected_periods = {('TS_CLKIN','CLKIN','24.01'),('TS_SPI_SCK','SPI_SCK','48.1'),('TS_SNES_SYSCLK','SNES_SYSCLK','21.5'),('TS_CLK21','CLK21','96.04')}
    need(len(periods) == 4 and set(periods) == expected_periods, 'Original periods changed')
    need(set(re.findall(r'^(TS_\w+)\s*=', text['pcf'], re.M)) == {x[0] for x in expected_periods}, 'Extra timing specification')
    need((report / 'integrity-verified.txt').read_text().strip() == 'Full source/index/IP immutability verified', 'Input integrity not established')
    finished, = json.loads((report / 'native-container-finished.json').read_text())
    native_exit = int((report / 'native-exit.txt').read_text())
    need(finished['State']['ExitCode'] == native_exit and not finished['State']['OOMKilled'], 'Native exit or OOM mismatch')
    log = (report / 'native-build.log').read_text()
    if native_exit != 0:
        need(native_exit == 2 and 'make[1]: *** [../common.mk:198: main.ncd] Error 55' in log,
             'Actual compilation/native error is not the original strict timing gate')
        need(candidate['traceErrors'] > 0 or candidate['parScore'] > 0, 'Timing-gate failure without reported timing violations')
    physical = json.loads((report / 'physical' / 'dr-physical-index.json').read_text())
    need(physical['observedBitNumbers'] == list(range(16)), 'Incomplete mapped DR state')
    syr = (native / 'main.syr').read_text(encoding='utf-8')
    need('Set property "register_balancing = no" for signal <regs_dr>.' in syr, 'Retiming directive not recognized by XST')
    need(not re.search(r'Register\(s\) snes_dspx/regs_dr[^\n]*balanced into', syr), 'DR registers still retimed')
    need(len(physical['bindings']) == 16 and not physical['unrecognizedDrFFs'], 'Expected exactly16 original DR state FF bindings')
    need(all(not re.search(r'_(?:BRB|FRB)\d+', b['logical']) for b in physical['bindings']), 'Retimed mapped DR alias')
    passed = (native_exit == 0 and candidate['parScore'] == candidate['traceErrors'] == 0
              and candidate['minimumDisplayedSlackNs'] >= 0)
    result = dict(baselineRun=42507318034, baseline=baseline, candidate=candidate,
                  reportedTimingPassed=passed, measuredImprovement=progress(baseline, candidate),
                  nativeBuildExit=native_exit, nativeBuildSucceeded=native_exit == 0,
                  originalTimingGateFailure=native_exit == 2, constraintsAndOptionsUnchanged=True,
                  originalDrRegisterBoundaryOnly=True, mappedDrBindings=physical['bindings'],
                  unconstrainedIoSignoff=False, hardwareQualified=False,
                  limits='Remaining violations are not passes. Improvement permits source adoption only after evidence review; no whole mapped/electrical qualification.')
    save(report / 'timing-progress-result.json', result)
    print(json.dumps(result, indent=2))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == 'prepare':
        prepare(Path(sys.argv[2]))
    elif len(sys.argv) == 5 and sys.argv[1] == 'cut':
        cut(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4])
    elif len(sys.argv) == 4 and sys.argv[1] == 'collect':
        collect(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'analysis-controls':
        analysis_controls(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'collect-controls':
        collect_controls(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == 'analyze':
        analyze(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit('Usage: prepare OUT | cut SOURCE OUT gold|gate | collect XDL OUT | analysis-controls OUT | analyze REPORT BASELINE')


if __name__ == '__main__':
    main()
