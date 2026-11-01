#!/usr/bin/env python3
"""Hosted-only bounded raw XDL collection for the proved parallel-stack change.

This never generates an FPGA design or evaluates a LUT equation. Complete raw
records precede binding errors. A successful collector is not a mapping proof.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted inspection only; never execute locally')
parser_path = Path(__file__).with_name('inspect-dsp-retained-map.py')
parser_raw = parser_path.read_bytes()
parser_blob = hashlib.sha1(b'blob ' + str(len(parser_raw)).encode() + b'\0' + parser_raw).hexdigest()
if parser_blob != '2b3b867372717b5729e26cb4880cb1af0b01a965':
    raise SystemExit('Reviewed XDL parser changed')
spec = importlib.util.spec_from_file_location('parallel_xdl', parser_path)
xdl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xdl)

SCOPES = ('address-high', 'address-low', 'stack-pointer', 'cpu-permits',
          'joins-low-0', 'joins-low-8', 'joins-high-0', 'joins-high-8', 'sources')


def constant(statement):
    return bool(re.match(r'^net\s+"[^"\n]+"\s+(?:vcc|gnd)\s*,', statement))


def describe(scope):
    required, optional, targets, fragments = [], [], [], []
    if scope in ('address-high', 'address-low', 'stack-pointer', 'cpu-permits'):
        signal, helper, count = {
            'address-high': ('stack_addr_high', 'restore_high', 3),
            'address-low': ('stack_addr_low', 'restore_low', 16),
            'stack-pointer': ('stack_sp_match', 'stack_pointer', 16),
            'cpu-permits': ('stack_cpu_word', 'cpu_word', 16),
        }[scope]
        required = [f'snes_dspx/{signal}<{i}>' for i in range(count)]
        fragments = [rf'{signal}<\d+>', rf'{helper}_\d+(?:/|\b)']
    elif scope.startswith('joins-'):
        _, lane, start = scope.split('-')
        first = int(start)
        words = range(first, first + 8)
        bits = range(8) if lane == 'low' else range(8, 11)
        optional = [f'snes_dspx/stack_late_{lane}<{w}>' for w in words]
        targets = [f'snes_dspx/stack<{w}>_{b}' for w in words for b in bits]
        fragments = [rf'stack_late_{lane}<{w}>|late_{lane}_{w}(?:/|\b)' for w in words]
    elif scope == 'sources':
        required = [f'snes_dspx/ss_wa<{i}>' for i in range(8)]
        required += [f'snes_dspx/regs_sp<{i}>' for i in range(4)]
        required += ['snes_dspx/ss_wr', 'snes_dspx/push_now', 'snes_dspx/ss_frozen',
                     'snes_mcu_cmd/dspx_reset_out', 'snes_dspx/stack_late_run',
                     'snes_dspx/stack_restore_write']
        fragments = [r'stack_late_run\b', r'stack_restore_write\b',
                     r'run_permit/', r'restore_write_permit/']
    else:
        raise ValueError('Unknown declared scope')
    return required, optional, targets, re.compile('|'.join(fragments))


def collect(scope, instances, nets):
    required, optional, targets, pattern = describe(scope)
    selected = {name for name, statement in instances.items() if pattern.search(statement)}
    errors, bindings, target_bindings = [], [], []
    pin_nets = {}
    for name, statement in nets.items():
        for kind, comp, pin in xdl.net_pins(statement):
            key = (comp, pin)
            if key in pin_nets:
                errors.append(f'Duplicate physical pin {key}: {pin_nets[key]}, {name}')
            else:
                pin_nets[key] = name

    def driver(name):
        if name not in nets:
            errors.append(f'Required source name absent: {name}; no missing-logic inference')
            return
        pins = [(comp, pin) for kind, comp, pin in xdl.net_pins(nets[name]) if kind == 'outpin']
        if constant(nets[name]):
            if pins:
                errors.append(f'Constant net also has an output pin: {name}')
            bindings.append(dict(net=name,constant=True))
        elif len(pins) != 1 or pins[0][0] not in instances:
            errors.append(f'Expected one physical driver: {name}: {pins}')
        else:
            selected.add(pins[0][0])
            bindings.append(dict(net=name,driver=list(pins[0])))

    observed = set(required) | {name for name in optional if name in nets}
    observed |= {name for name in nets if pattern.search(name)}
    for name in sorted(observed):
        driver(name)
    # Each final lane is anchored to all its actual FFs and their CE input pins.
    # Unkept logical join wire names are optional; no physical alias is guessed.
    for target in targets:
        try:
            comp = xdl.bind(instances, target)
            selected.add(comp)
            slot = re.findall(r'(?<!\S)FF([XY]):' + re.escape(target) + r':#FF(?=\s|$)',
                              ' '.join(instances[comp].split()))
            if len(slot) != 1:
                raise ValueError('Missing or ambiguous exact FF slot')
            ce_name, _ = xdl.ce_for(nets, comp)
            observed.add(ce_name)
            driver(ce_name)
            target_bindings.append(dict(target=target,comp=comp,slot=slot[0],ce=ce_name))
        except ValueError as error:
            errors.append(f'Target {target}: {error}; no missing-state inference')
    seeds = sorted(selected)
    # One complete physical predecessor layer for every selected COMP. Packed
    # unrelated LUTs are retained without claiming that they are logically used.
    for comp in seeds:
        for pin in sorted(xdl.INPUT_PINS):
            name = pin_nets.get((comp, pin))
            if name:
                observed.add(name)
                driver(name)
    selected_nets = {name for name, statement in nets.items() if name in observed or any(
        comp in selected for kind, comp, pin in xdl.net_pins(statement))}
    records = [instances[name] for name in sorted(selected)]
    records += [nets[name] for name in sorted(selected_nets)]
    raw = '\n'.join(records)
    summary = dict(scope=scope,fullInstances=len(instances),fullNets=len(nets),
                   selectedInstances=len(selected),selectedNets=len(selected_nets),
                   rawBytes=len(raw.encode()),rawSha256=hashlib.sha256(raw.encode()).hexdigest(),
                   requiredSources=required,optionalJoinSources=optional,
                   absentOptionalJoinAliases=[n for n in optional if n not in nets],
                   targets=len(targets),boundTargets=len(target_bindings),
                   predecessorSeedComps=seeds,bindings=bindings,targetBindings=target_bindings,
                   errors=errors,mappedOnly=True,timingPass=False)
    return raw, summary


def emit(raw, summary):
    if (summary['selectedInstances'] > 400
            or summary['selectedNets'] > 700 or summary['rawBytes'] > 3_000_000):
        raise ValueError('Complete raw scope exceeds declared bounds; no truncation accepted: '
                         + json.dumps({k: summary[k] for k in ('scope','selectedInstances','selectedNets','rawBytes')}))
    print('Complete bounded raw XDL records precede all binding outcomes. Independent physical review remains required.')
    print(raw, flush=True)
    print(json.dumps(summary, sort_keys=True, indent=2), flush=True)
    if summary['errors']:
        raise ValueError('\n'.join(summary['errors']))
    print('Raw mapped scope retained. No LUT-equation evaluation, timing closure, sequential or hardware proof.')


def controls():
    xdl.fixture_checks()
    for kind in ('vcc','gnd'):
        assert constant(f'net "GLOBAL" {kind}, inpin "slice" F1;')
    for statement in ('net "vcc", inpin "slice" F1;', 'net "GLOBAL" vccx, inpin "slice" F1;', ''):
        assert not constant(statement)
    for scope in SCOPES:
        required, optional, targets, pattern = describe(scope)
        assert len(set(required)) == len(required) and len(set(targets)) == len(targets)
        assert all(pattern.search(name) for name in optional)
    assert sum(len(describe(s)[2]) for s in SCOPES)==176
    assert describe('joins-low-0')[3].search('snes_dspx/late_low_7/write')
    for name in ('snes_dspx/late_low_10/write', 'snes_dspx/late_high_7/write',
                 'snes_dspx/stack_late_low<10>'):
        assert not describe('joins-low-0')[3].search(name)
    # A partial fixture must retain its authentic available records while
    # reporting missing required logical bindings, not silently fill aliases.
    fixture = '''inst "drive" "SLICEL", cfg " F:snes_dspx/stack_addr_high<0>:#LUT:D=A1 ";
net "snes_dspx/stack_addr_high<0>", outpin "drive" X;
'''
    inst, nets = xdl.parse(fixture)
    raw, summary = collect('address-high', inst, nets)
    assert inst['drive'] in raw and nets['snes_dspx/stack_addr_high<0>'] in raw
    assert len(summary['errors'])==2 and summary['bindings']==[dict(net='snes_dspx/stack_addr_high<0>',driver=['drive','X'])]
    import contextlib
    import io
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        try:
            emit(raw,summary)
        except ValueError:
            pass
        else:
            raise AssertionError('Missing required source fixture accepted')
    output=stream.getvalue()
    assert output.index(inst['drive']) < output.index('Required source name absent:')
    complete='\n'.join(
        f'inst "drive{i}" "SLICEL", cfg " F:snes_dspx/stack_addr_high<{i}>:#LUT:D=A1 ";\n'
        f'net "snes_dspx/stack_addr_high<{i}>", outpin "drive{i}" X;'
        for i in range(3))
    inst,nets=xdl.parse(complete)
    raw,summary=collect('address-high',inst,nets)
    assert not summary['errors'] and len(summary['bindings'])==3
    for changed in (complete.replace('outpin "drive0" X;', 'outpin "drive0" X, outpin "drive1" Y;'),
                    complete.replace('outpin "drive0" X;', 'outpin "missing" X;')):
        bad_inst,bad_nets=xdl.parse(changed)
        bad_raw,bad_summary=collect('address-high',bad_inst,bad_nets)
        assert any('Expected one physical driver:' in error for error in bad_summary['errors'])
        assert bad_nets['snes_dspx/stack_addr_high<0>'] in bad_raw
    print('Hosted parser, source-binding and raw-before-error fixtures passed; synthetic controls only.')


def main():
    if sys.argv[1:] == ['--self-test']:
        controls()
        return
    scope, filename = sys.argv[1:]
    if scope not in SCOPES:
        raise SystemExit('Unknown declared scope')
    controls()
    path=Path(filename)
    if path.stat().st_size > 32_000_000:
        raise SystemExit('Full XDL exceeds declared limit')
    instances,nets=xdl.parse(path.read_text(encoding='utf-8',errors='strict'))
    if len(instances)<100 or len(nets)<100:
        raise SystemExit('Unexpectedly small full design')
    emit(*collect(scope,instances,nets))


if __name__ == '__main__':
    main()
