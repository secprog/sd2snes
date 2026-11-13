#!/usr/bin/env python3
"""Hosted-only full address-module proof and one combinational DMA timing candidate review."""
import copy
import hashlib
import io
import itertools
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

BASE = '4d0199bf639629284546858b2b92abcd840b48a9'
ADDRESS = 'verilog/sd2snes_dsp/address.v'
GOLD_SHA = '8a329f7aac7b8a34362aff54473c45ac05332920ec8a0901e779b1b35153667d'
GATE_SHA = '8f717716358957cedff1d1341de0c01b59ae532118f92a69e5df32612ff319a9'
OLD = "assign dma_enable = (featurebits[FEAT_DMA1] | map_unlock | snescmd_unlock) & (!SNES_ADDR[22] && ((SNES_ADDR[15:0] & 16'hfff0) == 16'h2020));"
NEW = "`ifdef MK2\n`ifdef DSP_COMP\n// Two bounded LUT levels from address to DMA select. Keep all address state\n// and the live feature/unlock controls at their original capture boundaries.\nwire dma_hi_hit, dma_mid_hit, dma_lo_hit, dma_bank_permission;\ndspx_dma_cmp2 dma_hi_lut(.addr(SNES_ADDR[15:12]), .match(dma_hi_hit));\ndspx_dma_cmp0 dma_mid_lut(.addr(SNES_ADDR[11:8]), .match(dma_mid_hit));\ndspx_dma_cmp2 dma_lo_lut(.addr(SNES_ADDR[7:4]), .match(dma_lo_hit));\ndspx_dma_permission dma_permission_lut(\n  .dma_feature(featurebits[FEAT_DMA1]), .map_unlock(map_unlock),\n  .snescmd_unlock(snescmd_unlock), .bank22(SNES_ADDR[22]),\n  .allowed(dma_bank_permission)\n);\ndspx_dma_join dma_join_lut(\n  .high_match(dma_hi_hit), .middle_match(dma_mid_hit),\n  .low_match(dma_lo_hit), .allowed(dma_bank_permission), .selected(dma_enable)\n);\n`else\nassign dma_enable = (featurebits[FEAT_DMA1] | map_unlock | snescmd_unlock) & (!SNES_ADDR[22] && ((SNES_ADDR[15:0] & 16'hfff0) == 16'h2020));\n`endif\n`else\nassign dma_enable = (featurebits[FEAT_DMA1] | map_unlock | snescmd_unlock) & (!SNES_ADDR[22] && ((SNES_ADDR[15:0] & 16'hfff0) == 16'h2020));\n`endif"
HELPER = '\n`ifdef MK2\n`ifdef DSP_COMP\n// Continuous expressions retain the original four-state address semantics.\n(* LUT_MAP = "yes" *)\nmodule dspx_dma_cmp2(input [3:0] addr, output match);\nassign match = (addr == 4\'h2);\nendmodule\n\n(* LUT_MAP = "yes" *)\nmodule dspx_dma_cmp0(input [3:0] addr, output match);\nassign match = (addr == 4\'h0);\nendmodule\n\n(* LUT_MAP = "yes" *)\nmodule dspx_dma_permission(\n  input dma_feature, input map_unlock, input snescmd_unlock, input bank22,\n  output allowed\n);\nassign allowed = (dma_feature | map_unlock | snescmd_unlock) & !bank22;\nendmodule\n\n(* LUT_MAP = "yes" *)\nmodule dspx_dma_join(\n  input high_match, input middle_match, input low_match, input allowed,\n  output selected\n);\nassign selected = high_match & middle_match & low_match & allowed;\nendmodule\n`endif\n`endif\n'
PIN = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def run(argv, cwd, stem, expected=0):
    process = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    text = process.stdout.decode('utf-8')
    need('\0' not in text, 'NUL in hosted tool output')
    (cwd / (stem + '.log')).write_bytes(process.stdout)
    save(cwd / (stem + '-command.json'), dict(argv=argv, exit=process.returncode,
         stdoutBytes=len(process.stdout), stdoutSha256=sha(process.stdout)))
    print(text, end='', flush=True)
    if expected is not None:
        need(process.returncode == expected, 'Hosted command failed: ' + stem)
    return process.returncode, text


def one(text, old, new):
    need(text.count(old) == 1, 'Ambiguous exact source replacement: ' + old[:100])
    return text.replace(old, new, 1)


def state_audit(path, expected_bits, extra):
    module = json.loads(path.read_text())['modules']['address']
    clocks = module['ports']['CLK']['bits']
    names = module['netnames']
    expected = {'MAPPER_DEC': 8, 'SNES_ADDR': 24, 'dsp_bank4f_hit': 1, 'IS_SAVERAM_r': 1}
    qslots = {}
    for name, cell in module['cells'].items():
        if cell['type'] == '$dff':
            need(cell['connections']['CLK'] == clocks and int(cell['parameters']['CLK_POLARITY'], 2) == 1,
                 'State clock/polarity changed')
            for q, data in zip(cell['connections']['Q'], cell['connections']['D']):
                need(q not in qslots, 'Multiply driven state bit'); qslots[q] = dict(cell=name, data=data)
        else:
            need(not re.search(r'\$(?:a|s|d|f|l).*?(?:ff|latch)', cell['type'], re.I),
                 'Unsupported sequential cell ' + cell['type'])
        need(cell['type'] != '$assume', 'Unexpected proof assumption')
    observations = []
    all_q = []
    for name, width in expected.items():
        need(name in names and len(names[name]['bits']) == width, 'State carrier missing: ' + name)
        bits = names[name]['bits']; need(all(bit in qslots for bit in bits), 'State not actual FF Q')
        need('init' not in names[name].get('attributes', {}), 'Unexpected state initialization')
        all_q.extend(bits)
        observations.append(dict(name=name, bits=bits, data=[qslots[bit]['data'] for bit in bits], clock=clocks))
    need(len(set(all_q)) == len(qslots) == expected_bits, 'Unreviewed state or aliases')
    need(not any('init' in value.get('attributes', {}) and set(value['bits']) & set(all_q)
                 for value in names.values()), 'Initialized state alias not reviewed')
    return dict(stateBits=expected_bits, observations=observations, ports=module['ports'])


def compile_model(text, folder, label):
    folder.mkdir()
    (folder / 'source.v').write_text(text, encoding='utf-8')
    script = ('read_verilog -sv -formal source.v\nhierarchy -check -top address\n'
              'flatten\nproc -ifx -noopt\ndffunmap\nsetundef -undriven -undef\nopt_clean\ncheck -assert\n'
              'write_json state.json\nrename address ' + label + '\nwrite_json compiled.json\n')
    (folder / 'compile.ys').write_text(script)
    run(['yosys', '-s', 'compile.ys'], folder, 'compile')
    audit = state_audit(folder / 'state.json', 34, False)
    save(folder / 'state-audit.json', audit)
    return audit


def common_transition_fingerprints(module, audit):
    """Structural congruence only: hash exact typed operators, pins and parameters."""
    labels = {}
    for name, port in module['ports'].items():
        if port['direction'] == 'input':
            for index, bit in enumerate(port['bits']):
                labels[bit] = ['input', name, index]
    for observation in audit['observations']:
        for index, bit in enumerate(observation['bits']):
            need(bit not in labels, 'Source state aliases a primary input')
            labels[bit] = ['state', observation['name'], index]
    drivers = {}
    for name, cell in module['cells'].items():
        need(cell['type'].startswith('$'), 'Unknown primitive in structural congruence')
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] == 'output':
                for index, bit in enumerate(bits):
                    need(bit not in drivers, 'Multiple drivers in source netlist')
                    drivers[bit] = (name, port, index)
    memo = {}; visiting = set()
    def fingerprint(bit):
        if isinstance(bit, str):
            return sha(json.dumps(['constant', bit]).encode())
        if bit in labels:
            return sha(json.dumps(labels[bit]).encode())
        if bit in memo:
            return memo[bit]
        need(bit not in visiting and bit in drivers, 'Cycle/undriven bit in state transition cone')
        visiting.add(bit)
        name, outport, index = drivers[bit]; cell = module['cells'][name]
        need(cell['type'] != '$dff', 'Unreviewed state in transition cone')
        inputs = {port: [fingerprint(item) for item in bits] for port, bits in sorted(cell['connections'].items())
                  if cell['port_directions'][port] == 'input'}
        value = [cell['type'], cell['parameters'], inputs, outport, index]
        memo[bit] = sha(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        visiting.remove(bit)
        return memo[bit]
    rows = []
    for observation in audit['observations']:
        for index, data in enumerate(observation['data']):
            rows.append(dict(name=observation['name'], bit=index, fingerprint=fingerprint(data)))
    need(len(rows) == 34, 'Complete common transition fingerprints missing')
    return rows


def fold_identical_common_state(gold, gate, output):
    """Share only proven identical source state; preserve all outputs and new state.

    Both models' 34 common bits have identical undefined source startup,
    positive common clocks and structurally identical next-state functions over
    the same primary inputs and named state. This establishes their equality
    inductively without an assumption. Keep both actual D vectors in the final
    miter and assert strict equality again. Neither model has additional state.
    """
    ga = state_audit(gold / 'state.json', 34, False)
    ca = state_audit(gate / 'state.json', 34, False)
    gm = json.loads((gold / 'state.json').read_text())['modules']['address']
    cm = json.loads((gate / 'state.json').read_text())['modules']['address']
    gr = common_transition_fingerprints(gm, ga)
    cr = common_transition_fingerprints(cm, ca)
    need(gr == cr, 'Common source transition is not structurally identical')
    # A real corruption of an actual source D pin must reject this sharing.
    corrupt = copy.deepcopy(cm)
    bit = cm['netnames']['SNES_ADDR']['bits'][0]
    cell = next(cell for cell in corrupt['cells'].values() if cell['type'] == '$dff' and bit in cell['connections']['Q'])
    cell['connections']['D'][cell['connections']['Q'].index(bit)] = '0'
    corrupt_audit = copy.deepcopy(ca)
    next(row for row in corrupt_audit['observations'] if row['name'] == 'SNES_ADDR')['data'][0] = '0'
    corrupted = common_transition_fingerprints(corrupt, corrupt_audit)
    need(gr != corrupted, 'Common state D corruption was not detected')
    save(output / 'common-state-d-corruption.json', dict(original=gr, corrupted=corrupted, rejected=True))
    design = json.loads((output / 'miter-unfolded.json').read_text())
    module = design['modules']['miter']; q_to_d = {}
    for name, cell in module['cells'].items():
        if cell['type'] == '$dff':
            for q, data in zip(cell['connections']['Q'], cell['connections']['D']):
                need(q not in q_to_d, 'Multiply driven unfolded state'); q_to_d[q] = data
    replacements = {}; gold_d = []; gate_d = []; bindings = []
    for row in ga['observations']:
        name = row['name']; old = module['netnames']['gold.' + name]['bits']; new = module['netnames']['gate.' + name]['bits']
        need(len(old) == len(new) == len(row['bits']), 'Unfolded common state width changed')
        for index, (a, b) in enumerate(zip(old, new)):
            need(a in q_to_d and b in q_to_d and b not in replacements and a != b, 'Common state carrier not distinct FF Q')
            replacements[b] = a; gold_d.append(q_to_d[a]); gate_d.append(q_to_d[b])
            bindings.append(dict(name=name,bit=index,goldQ=a,gateQ=b,goldD=q_to_d[a],gateD=q_to_d[b]))
    need(len(replacements) == 34, 'Common state sharing incomplete')
    removed = []
    for name, cell in list(module['cells'].items()):
        outputs = [bit for port, bits in cell['connections'].items() if cell['port_directions'][port] == 'output' for bit in bits]
        if any(bit in replacements for bit in outputs):
            need(cell['type'] == '$dff' and set(cell['connections']['Q']) <= set(replacements), 'Sharing would change another driver')
            removed.append(name); del module['cells'][name]
    need(sum(len(cell['connections']['Q']) for cell in module['cells'].values() if cell['type'] == '$dff') == 34,
         'Original common source state lost')
    def rewrite(bits):
        return [replacements.get(bit, bit) for bit in bits]
    for cell in module['cells'].values():
        cell['connections'] = {port: rewrite(bits) for port, bits in cell['connections'].items()}
    for collection in [module['ports'], module['netnames']]:
        for value in collection.values():
            value['bits'] = rewrite(value['bits'])
    gold_d = rewrite(gold_d); gate_d = rewrite(gate_d)
    used = [bit for value in module['netnames'].values() for bit in value['bits'] if isinstance(bit, int)]
    used += [bit for cell in module['cells'].values() for bits in cell['connections'].values() for bit in bits if isinstance(bit, int)]
    comparison = max(used) + 1
    module['ports']['gold_common_next'] = dict(direction='output', bits=gold_d)
    module['ports']['gate_common_next'] = dict(direction='output', bits=gate_d)
    module['ports']['cmp_common_next'] = dict(direction='output', bits=[comparison])
    for name in ['gold_common_next', 'gate_common_next', 'cmp_common_next']:
        module['netnames'][name] = dict(hide_name=0, bits=module['ports'][name]['bits'], attributes={})
    module['netnames']['common_state_transition_ok'] = dict(hide_name=0, bits=[comparison], attributes={})
    module['cells']['common_state_transition_eqx'] = dict(hide_name=0, type='$eqx',
        parameters=dict(A_SIGNED='0'*32, B_SIGNED='0'*32, A_WIDTH=format(34,'032b'), B_WIDTH=format(34,'032b'), Y_WIDTH=format(1,'032b')),
        attributes={}, port_directions=dict(A='input', B='input', Y='output'), connections=dict(A=gold_d, B=gate_d, Y=[comparison]))
    module['cells']['common_state_transition_assert'] = dict(hide_name=0, type='$assert', parameters={}, attributes={},
        port_directions=dict(A='input', EN='input'), connections=dict(A=[comparison], EN=['1']))
    save(output / 'miter-shared-state.json', design)
    save(output / 'common-state-congruence.json', dict(commonBits=34, fingerprints=gr, actualBindings=bindings,
         removedDuplicateStateCells=removed, retainedStateBits=34, actualCommonNextStateBitsCompared=34,
         noStateAssumption=True, noAdditionalSourceState=True, commonStartup='All source state bits uninitialized; both source simulations begin undefined',
         dPinCorruptionRejected=True, scope='Identical typed next-state graphs and clock/startup establish common state equality inductively. Full original outputs and both common D vectors are still compared by SAT; no new state relation assumed.'))


def prove_pair(gold, gate, output, mode, expected, induction):
    output.mkdir()
    flags = '-set-def-inputs ' if mode == 'binary' else ''
    proof_flags = '-seq 2 -tempinduct -maxsteps 4 ' if induction else '-seq 3 '
    preparation = ('read_json ' + str(gold / 'compiled.json') + '\nread_json ' + str(gate / 'compiled.json') + '\n'
              'miter -equiv -make_assert -make_outputs -make_outcmp gold gate miter\n'
              'hierarchy -check -top miter\nflatten -wb\nopt_clean\ncheck -assert\nwrite_json miter-unfolded.json\n')
    (output / 'prepare.ys').write_text(preparation)
    run(['yosys', '-s', 'prepare.ys'], output, 'miter-preparation')
    fold_identical_common_state(gold, gate, output)
    script = ('read_json miter-shared-state.json\nhierarchy -check -top miter\n'
              'opt_merge -keepdc\nopt_clean\ncheck -assert\nwrite_json miter.json\n'
              'sat -verify -enable_undef -set-init-undef ' + flags + proof_flags +
              '-prove-asserts -show-inputs -show-outputs -dump_json counterexample.json -timeout 180\n')
    (output / 'prove.ys').write_text(script)
    code, text = run(['yosys', '-s', 'prove.ys'], output, 'proof', expected=None)
    module = json.loads((output / 'miter.json').read_text())['modules']['miter']
    source = json.loads((gold / 'state.json').read_text())['modules']['address']
    inputs = {name: port for name, port in source['ports'].items() if port['direction'] == 'input'}
    actual = {name[3:]: port for name, port in module['ports'].items() if port['direction'] == 'input' and name.startswith('in_')}
    need(set(actual) == set(inputs) and all(len(actual[name]['bits']) == len(inputs[name]['bits']) for name in inputs),
         'Full common source inputs not present in actual miter')
    outputs = [name for name, port in source['ports'].items() if port['direction'] == 'output']
    need(all('cmp_' + name in module['ports'] for name in outputs), 'Full source outputs not compared')
    cells = list(module['cells'].values())
    need(any(cell['type'] == '$assert' for cell in cells) and not any(cell['type'] == '$assume' for cell in cells),
         'Actual miter assertions/assumptions changed')
    for name in outputs + ['common_next']:
        bits = module['ports']['cmp_' + name]['bits']
        need(len(bits) == 1 and any(cell['type'] == '$eqx' and cell['connections']['Y'] == bits for cell in cells),
             'Strict X comparison missing for ' + name)
    if expected:
        marker = 'Induction step proven: SUCCESS!' if induction else 'SAT proof finished - no model found: SUCCESS!'
        need(code == 0 and marker in text, 'Positive full-module proof not established')
    else:
        need(code != 0 and 'SAT proof finished - model found: FAIL!' in text and (output / 'counterexample.json').is_file(),
             'Negative control lacks actual counterexample')
    receipt = dict(mode=mode, expectedPass=expected, induction=induction, exit=code, inputs=len(inputs),
                   inputBits=sum(len(port['bits']) for port in inputs.values()), outputs=outputs,
                   outputBits=sum(len(source['ports'][name]['bits']) for name in outputs), strictX=True, assumptions=0,
                   identicalCommonStateBitsShared=34, actualCommonNextStateBitsCompared=34, noAdditionalSourceState=True)
    save(output / 'proof-review.json', receipt)
    return receipt


def proof(output):
    output.mkdir(parents=True, exist_ok=True)
    gold = subprocess.check_output(['git', 'show', BASE + ':' + ADDRESS]).decode()
    gate = Path(ADDRESS).read_text()
    need(sha(gold.encode()) == GOLD_SHA and sha(gate.encode()) == GATE_SHA, 'Original/candidate combinational source identity changed')
    need(one(gold, OLD, NEW) + HELPER == gate, 'Change is not exact combinational DMA decode')
    changed = subprocess.check_output(['git', 'diff', '--name-only', BASE, 'HEAD', '--', 'verilog']).decode().splitlines()
    need(changed == [ADDRESS], 'Unreviewed production edit')
    main = Path('verilog/sd2snes_dsp/main.v').read_text()
    need('reg  [23:0] SNES_ADDR_early; always @(posedge CLK2) SNES_ADDR_early <= (SNES_ADDRr[3] & SNES_ADDRr[2]);' in main
         and '.SNES_ADDR_early(SNES_ADDR_early)' in main and '.CLK(CLK2)' in main,
         'Registered upstream address/clock binding changed')
    (output / 'gold-source.v').write_text(gold); (output / 'gate-source.v').write_text(gate)
    configurations = []; results = []; target_models = []
    for index, (board, comp, debug, lean) in enumerate(itertools.product(['MK2', 'MK3'], [False, True], [False, True], [False, True])):
        defines = [board] + (['DSP_COMP'] if comp else []) + (['DEBUG'] if debug else []) + (['DSP_LEAN'] if lean else [])
        paths = []
        for label in ['gold', 'gate']:
            path = output / (label + '-preprocessed-' + str(index) + '.v')
            argv = ['iverilog', '-g2005-sv', '-E'] + ['-D' + define for define in defines] + ['-o', str(path), str(output / (label + '-source.v'))]
            run(argv, output, label + '-preprocess-' + str(index)); paths.append(path)
        target = board == 'MK2' and comp
        if not target:
            need([line for line in paths[0].read_text().splitlines() if line.strip()] == [line for line in paths[1].read_text().splitlines() if line.strip()], 'Non-target preprocessed source tokens changed')
        configurations.append(dict(defines=defines, target=target, goldSha256=sha(paths[0].read_bytes()), gateSha256=sha(paths[1].read_bytes())))
        if target:
            base = output / ('config-' + str(index)); base.mkdir()
            compile_model(paths[0].read_text(), base / 'gold', 'gold')
            compile_model(paths[1].read_text(), base / 'gate', 'gate')
            for mode in ['binary', 'xstate']:
                results.append(prove_pair(base / 'gold', base / 'gate', base / mode, mode, True, True))
            target_models.append((base, paths[1].read_text()))
    base, original = target_models[0]
    mutations = [
        ('wrong-high-address', '.addr(SNES_ADDR[15:12])', '.addr(SNES_ADDR[14:11])'),
        ('wrong-two-nibble-pattern', "assign match = (addr == 4'h2);", "assign match = (addr == 4'h3);"),
        ('wrong-middle-pattern', "assign match = (addr == 4'h0);", "assign match = (addr == 4'h1);"),
        ('missing-command-unlock', 'dma_feature | map_unlock | snescmd_unlock', 'dma_feature | map_unlock'),
        ('missing-map-unlock', 'dma_feature | map_unlock | snescmd_unlock', 'dma_feature | snescmd_unlock'),
        ('wrong-bank-polarity', ' & !bank22;', ' & bank22;'),
        ('wrong-low-address-slice', '.addr(SNES_ADDR[7:4])', '.addr(SNES_ADDR[3:0])'),
        ('x-decode-startup-mismatch', "assign match = (addr == 4'h2);", "assign match = (addr === 4'h2);")]
    for name, before, after in mutations:
        folder = output / name
        compile_model(one(original, before, after), folder, 'gate')
        if name == 'x-decode-startup-mismatch':
            results.append(prove_pair(base / 'gold', folder, output / (name + '-binary'), 'binary', False, False))
            results.append(prove_pair(base / 'gold', folder, output / (name + '-xstate'), 'xstate', False, False))
        else:
            results.append(prove_pair(base / 'gold', folder, output / (name + '-binary'), 'binary', False, False))
    save(output / 'preprocessor-configurations.json', configurations)
    save(output / 'full-module-proof-results.json', results)
    rows = []
    for path in sorted(output.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS':
            rows.append(sha(path.read_bytes()) + '  ' + path.relative_to(output).as_posix())
    (output / 'SHA256SUMS').write_text('\n'.join(rows) + '\n')
    (output / 'verified.txt').write_text('Complete actual address module:34 common source state bits shared only after typed transition/clock/undefined-startup congruence checks and a real D-pin corruption control; both common D vectors still strictly compared. Four target configurations pass binary and unrestricted-X induction without new state; other preprocessed configurations unchanged except blank lines; nine actual bad-source counterexamples required. No whole FPGA or timing claim.\n')


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
    families = ['dma_hi_lut','dma_mid_lut','dma_lo_lut','dma_permission_lut','dma_join_lut']
    bindings = {family: [] for family in families}
    for component, body in instances.items():
        for slot, logical, equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)', body):
            for family in families:
                prefix = 'snes_addr/' + family
                if logical == prefix or logical.startswith(prefix + '/'):
                    bindings[family].append(dict(component=component, slot=slot, logical=logical, equation=equation))
    save(output / 'dma-lut-observed-bindings.json', bindings)
    selected = {row['component'] for rows in bindings.values() for row in rows}
    selected_nets = {name for name, body in nets.items() if any(comp in selected for _, comp, _ in PIN.findall(body))}
    for name in selected_nets:
        selected.update(comp for direction, comp, _ in PIN.findall(nets[name]) if direction == 'outpin' and comp in instances)
    body = '\n\n'.join([instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]) + '\n'
    need(len(selected) <= 400 and len(selected_nets) <= 700 and len(body.encode()) <= 3000000, 'Bounded neighborhood exceeded; no truncation')
    (output / 'dma-luts-raw.txt').write_text(body)
    save(output / 'dma-physical-index.json', dict(sourceBytes=len(raw), sourceSha256=sha(raw), totalInstances=len(instances),
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
    for unit in ['dspx_dma_cmp2', 'dspx_dma_cmp0', 'dspx_dma_permission', 'dspx_dma_join']:
        need(re.search(r'Set property "LUT_MAP = yes" for unit <' + unit + r'(?:_[^>]*)?>\.', syr), 'Combinational LUT_MAP not recognized: ' + unit)
    physical = json.loads((report / 'physical/dma-physical-index.json').read_text())
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
    families = ['dma_hi_lut','dma_mid_lut','dma_lo_lut','dma_permission_lut','dma_join_lut']
    fixture = '\n'.join('inst "part' + str(i) + '" "SLICEL", cfg " F:snes_addr/' + family + ':#LUT:D=A1 ";' for i, family in enumerate(families)) + '\n'
    cases = [('five actual helper LUTs', fixture, True),
             ('missing helper', fixture.replace('dma_hi_lut', 'other'), False),
             ('FF is not LUT', fixture.replace('F:snes_addr/dma_hi_lut:#LUT:D=A1', 'FFX:snes_addr/dma_hi_lut:#FF'), False),
             ('duplicate instance', fixture + 'inst "part0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture + 'net "n";\nnet "n";\n', False),
             ('incomplete record', fixture + 'net "incomplete"', False),
             ('two physical aliases', fixture + 'inst "extra" "SLICEL", cfg " F:snes_addr/dma_hi_lut/x:#LUT:D=A1 ";\n', False),
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
