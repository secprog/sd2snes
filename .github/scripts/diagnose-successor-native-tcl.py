#!/usr/bin/env python3
"""Hosted-only, single original Tcl option query with complete diagnostic tracing.
No make recipes, PAR, TRACE, synthesis, map, IP generation, or property setters execute.
The original preflight stderr gate remains unchanged and is not called here.
Collection completion is evidence collection only, never native eligibility.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted Tcl diagnosis only; never execute locally')
sys.dont_write_bytecode = True
CHECKER_SHA = 'd531e2702b9ca199562e4661613df25f979531e5f8da5e6cd0b224c6a8227193'
PREPARER_SHA = 'ed3e6b2d949558cf00094d5c250e02ef32aac2adf03884ef66562cd39592fabb'
WRAPPER_SHA = '313d243ca9f416174e6e920319db8b3ea208bb877dc1b43f1d5cb8bfaeb1bf8d'
FAILURE_SHA = '030c3c71d255361536458a9c7938672ac333632936c4936bb87db5a7ca65e690'
HISTORICAL_STDERR_SHA = '6a7ae06c40870a728c0e75980f592670d39bc098932e53ddcd0e82b1fa9f3a77'
MAX_TEXT = 3_000_000
MAX_REPORTS = 1024
MAX_AGGREGATE = 96_000_000
MAX_INVENTORY = 10000
MAX_FILE = 32_000_000
ENV_KEYS = 'ISE_CTABLE LC_ALL LANG JAVA_OPTS _JAVA_OPTIONS XILINX XILINX_EDK XILINX_DSP XILINX_PLANAHEAD XILINX_PATH XILINXD_LICENSE_FILE LD_LIBRARY_PATH PATH MAKEFILES MAKEFLAGS GNUMAKEFLAGS MFLAGS MAKEOVERRIDES MAKELEVEL MAKE_RESTARTS HOST XILINX_ENV IGNORE_TIMING'.split()
CORE = 'verilog/sd2snes_dspx'
ORIGINAL = '/work/verilog/xilinx_scripts/xgenparcmd.tcl'
WRAPPER = '.github/scripts/trace-successor-native-query.tcl'
EXPECTED_STDOUT = b'-ol high -xe c -t 68\n'
MEMBERS = ['Placer Effort Level', 'Placer Effort Level (Overrides Overall Level)',
           'Router Effort Level', 'Router Effort Level (Overrides Overall Level)',
           'Place & Route Effort Level (Overall)']
PROBES = [['properties', '-process', 'Place & Route'], ['properties'],
          ['get', MEMBERS[0]], ['get', MEMBERS[1], '-process', 'Place & Route'],
          ['get', MEMBERS[2]], ['get', MEMBERS[3], '-process', 'Place & Route'],
          ['get', MEMBERS[4], '-process', 'Place & Route'],
          ['get', 'Extra Effort (Highest PAR level only)', '-process', 'Place & Route'],
          ['get', 'Starting Placer Cost Table (1-100)', '-process', 'Place & Route'],
          ['get', 'Ignore User Timing Constraints', '-process', 'Place & Route'],
          ['get', 'Other Place & Route Command Line Options']]
ORIGINAL_GETS = set(MEMBERS + ['Extra Effort (Highest PAR level only)',
    'Starting Placer Cost Table (1-100)', 'Use SmartGuide', 'SmartGuide Filename',
    'Ignore User Timing Constraints', 'Timing Mode', 'Power Reduction',
    'Power Activity File', 'Power Activity File PAR', 'Enable Multi-Threading',
    'Other Place & Route Command Line Options'])


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def text_bytes(raw, label, cap=MAX_TEXT):
    require(isinstance(raw, bytes) and len(raw) <= cap, label + ': complete text bound')
    text = raw.decode('utf-8', errors='strict')
    require('\x00' not in text, label + ': NUL in text')
    return text


def read(path, cap=MAX_TEXT):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), 'Nonregular file: ' + str(path))
    require(info.st_size <= cap, 'File bound: ' + str(path))
    raw = path.read_bytes()
    require(len(raw) == info.st_size, 'Changed size while reading: ' + str(path))
    return raw


def save(root, name, raw):
    require('/' not in name and '\\' not in name and name not in ('', '.', '..'), 'Unsafe output name')
    text_bytes(raw, name)
    path = root / name
    require(not path.exists() and not path.is_symlink(), 'Output already exists: ' + name)
    path.write_bytes(raw)


def save_json(root, name, value):
    save(root, name, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())


def pin(raw):
    return dict(bytes=len(raw), sha256=sha(raw))


def imported(workspace, name, digest):
    path = workspace / '.github/scripts' / (name + '.py')
    require(sha(read(path)) == digest, 'Unchanged shared helper pin differs: ' + name)
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def failure_data(workspace):
    raw = read(workspace / '.github/fixtures/dsp-native-query-failure-data.json', 1_000_000)
    require(sha(raw) == FAILURE_SHA, 'Failure context fixture changed')
    data = json.loads(text_bytes(raw, 'failure fixture'))
    require(data['schemaVersion'] == 1 and data['family'] == 'dsp' and data['core'] == 'dspx', 'Failure schema')
    for stream in ('stdout', 'stderr'):
        record = data['failedPlan'][stream]
        value = record['text'].encode('utf-8')
        require(pin(value) == {k: record[k] for k in ('bytes', 'sha256')}, 'Failed stream literal pin')
    require(data['failedPlan']['stderr']['sha256'] == HISTORICAL_STDERR_SHA and
            data['failedPlan']['stderr']['bytes'] == 5386, 'Historical exact stderr pin')
    require(data['failedPlan']['collectionResult']['collectionComplete'] is False and
            data['acceptance']['oldEmptyStderrGateUnchanged'] is True and
            data['acceptance']['stderrAllowlist'] is False, 'Old failure/gate must stay rejected')
    return data


def retrieve_failure(preparer, data, output):
    contract = dict(run=data['failureRunFields'], jobs=data['failureJobs'], artifacts=data['failureArtifacts'])
    observed, artifacts = preparer.bind_runs([contract])
    require(len(artifacts) == 1, 'Exact failed artifact inventory')
    artifact = next(iter(artifacts.values()))
    bounds = data['limits']
    limits = dict(zipBytes=bounds['failureZipBytes'], members=bounds['failureMembers'],
                  textAggregateBytes=bounds['failureTextAggregateBytes'], textFileBytes=bounds['failureFileBytes'])
    archive_raw, files = preparer.verified_zip(artifact, data['failureReportMembers'], 'text', 'dsp', limits)
    for stream in ('stdout', 'stderr'):
        item = data['failedPlan'][stream]
        require(files[item['name']] == item['text'].encode(), 'Actual failed stream differs')
        save(output, 'failed-make-plan.' + stream + '.txt', files[item['name']])
    save_json(output, 'failed-run-bound-evidence.json', dict(metadata=observed,
              allReportMembers=data['failureReportMembers'], fullArchiveVerified=True,
              context=data, normalized=False, oldFailurePreserved=True))


def decode_trace(raw):
    source = text_bytes(raw, 'complete query trace')
    require(source.endswith('\n') and '\r' not in source, 'Trace line framing')
    rows = []
    for line in source.splitlines():
        fields = line.split('\t')
        require(fields[0] in {'VERSION', 'START', 'CALL', 'ARG', 'RETURN', 'LIST', 'ITEM',
                             'SOURCE', 'MEMBERSHIP', 'PROBE', 'END', 'ENV'}, 'Unknown trace event')
        decoded = [fields[0]]
        for value in fields[1:]:
            require(re.fullmatch(r'(?:[0-9a-f]{2})*', value) is not None, 'Noncanonical trace hex')
            decoded.append(text_bytes(bytes.fromhex(value), 'trace field'))
        rows.append(decoded)
    require(4 <= len(rows) <= 12000, 'Trace record count')
    require(len(rows[0]) == 4 and rows[0][0] == 'VERSION' and
            re.fullmatch(r'8\.[456](?:\.[0-9]+)?', rows[0][1]) is not None and
            rows[0][2] == '.'.join(rows[0][1].split('.')[:2]) and
            rows[0][3] == '/work/' + CORE, 'Runtime Tcl version or cwd not established')
    require(rows[1] == ['START', ORIGINAL, 'sd2snes_dspx.xise', '68'], 'Original source/arguments differ')
    calls, stack, markers, memberships, probes, environment = [], [], [], [], [], []
    source_result = None
    i = 2
    while i < len(rows) - 1:
        row = rows[i]
        kind = row[0]
        if kind == 'ENV':
            require(len(row) == 4 and not calls and len(environment) < len(ENV_KEYS) and
                    row[1] == ENV_KEYS[len(environment)] and row[2] in ('0', '1') and
                    (row[2] == '1' or row[3] == ''), 'Complete observed environment')
            environment.append(dict(name=row[1], exists=row[2] == '1', value=row[3]))
        elif kind == 'CALL':
            require(len(row) == 4 and row[1] == str(len(calls) + 1) and len(calls) < 128 and
                    row[2] in ('original', 'probe') and row[3].isdigit(), 'CALL shape/order')
            count = int(row[3])
            require(1 <= count <= 4, 'Project argument count')
            args = []
            for n in range(count):
                i += 1
                require(i < len(rows) - 1 and len(rows[i]) == 4 and
                        rows[i][:3] == ['ARG', row[1], str(n)], 'Complete ARG sequence')
                args.append(rows[i][3])
            require((source_result is None) == (row[2] == 'original'), 'Query phase order')
            require(args[0] in ('open', 'properties', 'get'), 'Forbidden project operation')
            call = dict(id=int(row[1]), phase=row[2], argv=args)
            calls.append(call)
            stack.append(call)
            markers.append('SD2SNES_QUERY_V1|BEGIN|' + row[1] + '|' + row[2])
        elif kind == 'RETURN':
            require(len(row) == 6 and stack and row[1] == str(stack[-1]['id']), 'RETURN scope/order')
            call = stack.pop()
            require(row[2] == '0' and row[4:] == ['', ''], 'Project operation returned nonzero/error metadata')
            call.update(returnCode=int(row[2]), result=row[3], errorCode=row[4], errorInfo=row[5])
            if call['argv'][0] == 'properties':
                i += 1
                require(i < len(rows) - 1 and len(rows[i]) == 3 and
                        rows[i][:2] == ['LIST', row[1]] and rows[i][2].isdigit(), 'Complete property list header')
                count = int(rows[i][2])
                require(0 < count <= 2048, 'Complete property list bound')
                items = []
                for n in range(count):
                    i += 1
                    require(i < len(rows) - 1 and len(rows[i]) == 4 and
                            rows[i][:3] == ['ITEM', row[1], str(n)], 'Complete property item sequence')
                    items.append(rows[i][3])
                call['propertyItems'] = items
            markers.append('SD2SNES_QUERY_V1|END|' + row[1] + '|' + call['phase'])
        elif kind == 'SOURCE':
            require(len(row) == 5 and row[1:] == ['0', '', '', ''] and source_result is None and
                    not stack and calls and all(c['phase'] == 'original' for c in calls), 'Original source catch status')
            source_result = dict(catchCode=0, result=row[2], errorCode=row[3], errorInfo=row[4])
        elif kind == 'MEMBERSHIP':
            require(len(row) == 3 and source_result is not None and not stack and not probes and
                    len(memberships) < len(MEMBERS) and row[1] == MEMBERS[len(memberships)] and
                    row[2] in ('0', '1'), 'Membership record order/value')
            memberships.append(dict(name=row[1], exists=bool(int(row[2]))))
        elif kind == 'PROBE':
            require(len(row) == 4 and len(probes) < len(PROBES) and row[1] == str(len(probes)) and
                    row[2] == '0' and not stack and calls[-1]['phase'] == 'probe' and
                    calls[-1]['argv'] == PROBES[len(probes)] and calls[-1]['result'] == row[3], 'Probe result/order')
            probes.append(dict(index=int(row[1]), callId=calls[-1]['id'], catchCode=0, result=row[3]))
        else:
            raise ValueError('Unexpected or residual trace event: ' + kind)
        i += 1
    require(not stack and source_result is not None and rows[-1] == ['END', 'complete', str(len(calls))],
            'Missing final complete trace / unresolved command')
    require(len(environment) == len(ENV_KEYS), 'Incomplete observed environment')
    for name, expected in [('ISE_CTABLE', '68'), ('LC_ALL', 'C'), ('LANG', 'C')]:
        require(environment[ENV_KEYS.index(name)] == dict(name=name, exists=True, value=expected), 'Observed environment differs: ' + name)
    original = [c for c in calls if c['phase'] == 'original']
    diagnostic = [c for c in calls if c['phase'] == 'probe']
    require(original and original[0]['argv'] == ['open', 'sd2snes_dspx.xise'] and
            sum(c['argv'][0] == 'open' for c in calls) == 1, 'Exactly one original project open required')
    for call in original[1:]:
        args = call['argv']
        require(args in (['properties'], ['properties', '-process', 'Place & Route']) or
                (args[0] == 'get' and len(args) in (2, 4) and args[1] in ORIGINAL_GETS and
                 (len(args) == 2 or args[2:] == ['-process', 'Place & Route'])), 'Original query command differs')
    par_lists = [c for c in original if c['argv'] == ['properties', '-process', 'Place & Route']]
    require(len(par_lists) == 1 and sum(c['argv'] == ['properties'] for c in original) == 1,
            'Both original complete property inventories required')
    require([c['argv'] for c in diagnostic] == PROBES and len(probes) == len(PROBES) and
            len(memberships) == len(MEMBERS), 'Missing/extra diagnostic probe or membership')
    for item in memberships:
        require(item['exists'] == (item['name'] in par_lists[0]['propertyItems']), 'Membership/list disagreement')
    return dict(runtimeTcl=rows[0][1], observedEnvironment=environment, priorShellEnvironmentEqualityProved=False, originalSource=source_result, commands=calls,
                memberships=memberships, probes=probes, expectedStderrMarkers=markers,
                originalQueries=1, projectOpens=1)


def validate_query(streams, expected_pins, direct_exit, docker_exit):
    require(set(streams) == {'stdout', 'stderr', 'trace'}, 'Complete stream inventory')
    require(set(expected_pins) == set(streams), 'Complete stream pin inventory')
    for name, raw in streams.items():
        text_bytes(raw, name)
        require(pin(raw) == expected_pins[name], 'Stream integrity differs: ' + name)
    require(docker_exit == 0 and direct_exit == b'0\n', 'Direct xtclsh or container exit failed')
    require(streams['stdout'] == EXPECTED_STDOUT, 'Complete original query stdout differs')
    decoded = decode_trace(streams['trace'])
    markers, offsets, cursor = [], [], 0
    for line in streams['stderr'].splitlines(keepends=True):
        if b'SD2SNES_QUERY_V1' in line:
            require(re.fullmatch(rb'SD2SNES_QUERY_V1\|(BEGIN|END)\|[1-9][0-9]*\|(original|probe)\n', line),
                    'Malformed diagnostic stderr marker')
            markers.append(line[:-1].decode('ascii'))
            offsets.append(dict(byteOffset=cursor, bytes=len(line), marker=markers[-1]))
        cursor += len(line)
    require(markers == decoded.pop('expectedStderrMarkers'), 'Missing/extra/changed diagnostic stderr markers')
    decoded['stderrMarkerOffsets'] = offsets
    decoded['streams'] = expected_pins
    decoded['directXtclshExit'] = 0
    decoded['stderrApproval'] = False
    decoded['warningInternalFilenamesAttributed'] = False
    return decoded


def file_metadata(workspace, path):
    require(workspace in path.parents and all(not p.is_symlink() for p in [path] + list(path.parents)
                if p != workspace.parent), 'Unsafe referenced path ancestry')
    name = path.relative_to(workspace).as_posix()
    if not path.exists():
        return dict(path=name, exists=False, fileType='missing')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), 'Nonregular referenced filesystem object')
    result = dict(path=name, exists=True, fileType='regular' if stat.S_ISREG(info.st_mode) else 'directory',
                  mode=oct(stat.S_IMODE(info.st_mode)))
    if stat.S_ISREG(info.st_mode):
        result.update(pin(read(path, MAX_FILE)))
    return result


def referenced_files(workspace, native_inputs):
    namespace = '{http://www.xilinx.com/XMLSchema}'
    pending = [workspace / CORE / 'sd2snes_dspx.xise']
    seen, projects, rows = set(), [], []
    while pending:
        path = pending.pop(0)
        require(path not in seen and len(seen) < 16, 'Repeated/cyclic or excessive nested project')
        seen.add(path)
        metadata = file_metadata(workspace, path)
        require(metadata['fileType'] == 'regular', 'Referenced project missing')
        raw = read(path)
        text_bytes(raw, 'project XML')
        require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'Unsupported project XML declarations')
        document = ET.fromstring(raw)
        projects.append(metadata)
        for node in document.iter(namespace + 'file'):
            literal = node.attrib.get(namespace + 'name', '')
            file_type = node.attrib.get(namespace + 'type', '')
            relative = PurePosixPath(literal)
            require(literal and '\\' not in literal and ':' not in literal and not relative.is_absolute()
                    and '\x00' not in literal and '\n' not in literal, 'Unsafe XISE reference')
            target = Path(os.path.abspath(path.parent / literal))
            row = dict(project=metadata['path'], literalName=literal, declaredType=file_type,
                       associations=[dict(child.attrib) for child in node if child.tag == namespace + 'association'],
                       observed=file_metadata(workspace, target))
            rows.append(row)
            require(len(rows) <= 512, 'Complete referenced-file count bound')
            if file_type == 'FILE_COREGENISE':
                pending.append(target)
    require(len(projects) == 4 and len(rows) == 33, 'Pinned complete original project-reference inventory differs')
    return dict(projects=projects, references=rows,
                retainedNativeInputs=[file_metadata(workspace, workspace / item['path']) for item in native_inputs],
                scope='Every file element in the pinned top-level and three nested XISE projects, plus all nine retained native inputs. Missing references are diagnostic observations, not approvals.')


def tree_inventory(workspace):
    rows = []
    total = 0
    for path in sorted((workspace / 'verilog').rglob('*')):
        require(len(rows) < MAX_INVENTORY, 'Complete Verilog filesystem inventory count bound')
        entry = file_metadata(workspace, path)
        total += entry.get('bytes', 0)
        require(total <= 256_000_000, 'Complete Verilog file hash byte bound')
        rows.append(entry)
    return rows


def require_existing_unchanged(before, after):
    old = {row['path']: row for row in before}
    new = {row['path']: row for row in after}
    for name, row in old.items():
        require(new.get(name) == row, 'Existing input/auxiliary path changed: ' + name)
    additions = [row for row in after if row['path'] not in old]
    forbidden = {'.ncd', '.ngc', '.ngd', '.ngm', '.bit', '.par', '.twr', '.pcf', '.xdl'}
    require(all(PurePosixPath(row['path']).suffix.lower() not in forbidden for row in additions),
            'Unexpected generated FPGA product in query-only operation')
    return additions


def docker_argv(data, workspace, output):
    owner = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    require(re.fullmatch(r'[0-9]+-[0-9]+', owner), 'Hosted run ownership identity')
    checks = ' '.join('test -z "${' + key + '-}";' for key in
                      ('MAKEFILES', 'MAKEFLAGS', 'GNUMAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES', 'MAKELEVEL', 'MAKE_RESTARTS'))
    script = ('set -euo pipefail; export LC_ALL=C LANG=C; '
              'observed_mac=$(cat /sys/class/net/eth0/address); '
              'printf "%s\\n" "$observed_mac" > /diagnostic/observed-mac.txt; '
              'test "$observed_mac" = ' + data['mac'] + '; test "$ISE_CTABLE" = 68; ' + checks + ' '
              'make --version > /diagnostic/make-version.txt; '
              'cd /work/' + CORE + '; set +e; '
              '/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64/xtclsh /work/' + WRAPPER +
              ' > /diagnostic/query.stdout.txt 2> /diagnostic/query.stderr.txt; '
              'query_status=$?; set -e; printf "%s\\n" "$query_status" > /diagnostic/query-exit.txt; '
              'exit "$query_status"')
    return ['docker', 'run', '--rm', '--network', 'bridge', '--name', 'sd2snes-dsp-successor-native-tcl-query-' + owner,
            '--label', 'sd2snes.query.owner=' + owner,
            '--user', '0:0', '--mac-address', data['mac'], '--env', 'ISE_CTABLE',
            '--ulimit', 'fsize=3000000:3000000', '--cidfile', str(output / 'container-id.txt'),
            '--volume', str(workspace) + ':/work', '--volume', str(output) + ':/diagnostic',
            '--workdir', '/work', '--entrypoint', '/bin/bash', 'sd2snes-ci:mk2', '-c', script]



def wrapper_controls(raw, markers):
    rows = []
    for line in text_bytes(raw, 'complete wrapper controls trace').splitlines():
        fields = line.split('\t')
        require(fields[0] in {'CALL', 'ARG', 'RETURN', 'LIST', 'ITEM', 'CONTROL', 'CONTROLS_COMPLETE'}, 'Wrapper control event')
        require(all(re.fullmatch(r'(?:[0-9a-f]{2})*', f) is not None for f in fields[1:]), 'Wrapper control trace hex')
        rows.append([fields[0]] + [text_bytes(bytes.fromhex(f), 'control field') for f in fields[1:]])
    labels = ['normal-result', 'list-result', 'caller-scope', 'error-preservation'] + ['unsupported-' + str(n) for n in (2, 3, 4, 5)]
    require([r for r in rows if r[0] == 'CONTROL'] == [['CONTROL', label, 'pass'] for label in labels],
            'Hosted real-wrapper control results incomplete')
    require(rows[-1:] == [['CONTROLS_COMPLETE', '8']], 'Missing complete wrapper controls marker')
    calls = [r for r in rows if r[0] == 'CALL']
    returns = [r for r in rows if r[0] == 'RETURN']
    require(calls == [['CALL', str(n), 'control', '1'] for n in range(1, 9)], 'Exactly eight synthetic delegate calls')
    require([r[:3] for r in returns] == [['RETURN', str(n), str(code)] for n, code in enumerate((0, 0, 0, 1, 2, 3, 4, 5), 1)],
            'Actual wrapper return-code controls differ')
    expected = ''.join('SD2SNES_QUERY_V1|' + kind + '|' + str(n) + '|control\n' for n in range(1, 9) for kind in ('BEGIN', 'END')).encode()
    require(markers == expected, 'Complete hosted wrapper-control markers differ')
    return dict(passed=8, labels=labels, controlsTrace=pin(raw), controlsMarkers=pin(markers),
                vendorProjectOperations=0, unsupportedCompletionCodesRejected=[2, 3, 4, 5])


def evidence_hashes(root):
    rows, total = [], 0
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Symlink in preparation evidence')
        if path.is_dir():
            continue
        raw = read(path, MAX_FILE)
        total += len(raw)
        require(len(rows) < MAX_INVENTORY and total <= 300_000_000, 'Complete preparation evidence bound')
        rows.append(dict(path=path.relative_to(root).as_posix(), **pin(raw)))
    require(rows, 'Empty preparation evidence')
    return rows


def run_owned_container(argv, env, output):
    owner = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    name = 'sd2snes-dsp-successor-native-tcl-query-' + owner
    actions = []
    def command(args):
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        actions.append(dict(argv=args, returncode=result.returncode,
                            stdout=text_bytes(result.stdout, 'container control stdout'),
                            stderr=text_bytes(result.stderr, 'container control stderr')))
        require(result.returncode == 0 and not result.stderr, 'Owned container control failed')
        return result.stdout
    require(command(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'name=^/' + name + '$']) == b'',
            'Refuse existing diagnostic container name')
    status, operation_error = None, None
    def file_limit():
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEXT, MAX_TEXT))
    try:
        with (output / 'container.stdout.txt').open('xb') as stdout, (output / 'container.stderr.txt').open('xb') as stderr:
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, env=env, preexec_fn=file_limit)
            try:
                status = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                operation_error = 'Owned Tcl diagnostic exceeded 600 seconds; incomplete query evidence'
                process.kill()
                status = process.wait(timeout=30)
    finally:
        stopped = False
        cleanup_error = None
        try:
            # A dead/timed-out Docker client is not proof that its container stopped.
            remaining = command(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=sd2snes.query.owner=' + owner])
            ids = remaining.decode('ascii').splitlines()
            require(len(ids) <= 1 and all(re.fullmatch('[0-9a-f]{64}', x) for x in ids), 'Ambiguous owned container inventory')
            if (output / 'container-id.txt').exists():
                cid = read(output / 'container-id.txt').decode('ascii').strip()
                require(re.fullmatch('[0-9a-f]{64}', cid) and all(x == cid for x in ids), 'Owned container ID differs')
            for cid in ids:
                command(['docker', 'rm', '-f', cid])
                operation_error = operation_error or 'Docker client exited while its owned container remained; query incomplete'
            require(command(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=sd2snes.query.owner=' + owner]) == b'',
                    'Owned container termination not established')
            stopped = True
        except Exception as exc:
            cleanup_error = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            save_json(output, 'container-lifecycle.json', dict(actions=actions, dockerExit=status,
                      operationError=operation_error, cleanupError=cleanup_error,
                      ownedContainerStopped=stopped, fileSizeLimitBytes=MAX_TEXT))
    return status, operation_error


def report_manifest(output):
    rows, total = [], 0
    for path in sorted(output.iterdir()):
        require(path.name != 'reports.sha256', 'Report manifest already exists')
        raw = read(path)
        text_bytes(raw, path.name)
        rows.append((path.name, sha(raw)))
        total += len(raw)
    manifest = ''.join(digest + '  ' + name + '\n' for name, digest in rows).encode()
    require(0 < len(rows) < MAX_REPORTS and total + len(manifest) <= MAX_AGGREGATE,
            'Complete report aggregate/count bound including manifest')
    save(output, 'reports.sha256', manifest)


def collect(family, evidence, output):
    require(family == 'dsp', 'First query diagnosis is DSP only')
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    evidence = evidence.resolve(strict=True)
    output = output.absolute()
    require(str(workspace).startswith('/') and all(':' not in str(p) and '\n' not in str(p)
            for p in (workspace, evidence, output)), 'Expected hosted Linux paths')
    require(evidence.is_dir() and workspace not in evidence.parents and evidence != workspace,
            'Preparation evidence must be outside checkout')
    require(not output.exists() and not output.is_symlink() and output.parent.is_dir() and
            workspace not in output.parents and output != workspace and evidence not in output.parents and
            output != evidence, 'Fresh independent outside-checkout output required')
    output.mkdir()
    outcome = dict(collectionComplete=False, family=family, nativeExecuted=False, timingPass=False,
                   oldPreflightFailurePreserved=True, oldCheckerPassed=False, stderrApproval=False,
                   wholeMappedEquivalenceProved=False, hardwareQualified=False)
    try:
        checker = imported(workspace, 'check-successor-native-plan', CHECKER_SHA)
        preparer = imported(workspace, 'prepare-successor-native-inputs', PREPARER_SHA)
        data = checker.data_file()
        failure = failure_data(workspace)
        wrapper = read(workspace / WRAPPER)
        require(sha(wrapper) == WRAPPER_SHA, 'Reviewed Tcl wrapper changed')
        require(all(not os.environ.get(key) for key in checker.OVERRIDES), 'Inherited make override environment')
        require(os.environ.get('ISE_CTABLE') in (None, '68'), 'Unexpected host seed environment')
        before = checker.inspect_inputs(workspace, evidence, data, 'dsp')
        require(before['nativeInputs'] == failure['context']['nativeInputs'] and
                before['nativeInputManifestSha256'] == failure['context']['nativeInputManifestSha256'],
                'Query inputs differ from failed preflight')
        image_before = checker.image_id()
        require(image_before == data['image'] == failure['context']['fixedImage'], 'Fixed image changed')
        retrieve_failure(preparer, failure, output)
        evidence_before = evidence_hashes(evidence)
        save_json(output, 'preparation-evidence-before.json', evidence_before)
        save_json(output, 'inputs-before.json', before)
        references_before = referenced_files(workspace, before['nativeInputs'])
        inventory_before = tree_inventory(workspace)
        save_json(output, 'referenced-files-before.json', references_before)
        save_json(output, 'verilog-inventory-before.json', inventory_before)
        argv = docker_argv(data, workspace, output)
        invocation = dict(schemaVersion=1, family=family, dockerArgv=argv,
                          environment={'ISE_CTABLE': '68'}, imageBefore=image_before,
                          nativeInputManifestSha256=before['nativeInputManifestSha256'],
                          checkerSha256=CHECKER_SHA, preparerSha256=PREPARER_SHA,
                          wrapperSha256=WRAPPER_SHA, failureFixtureSha256=FAILURE_SHA,
                          originalQueryCount=1, makeRecipeInvocations=0, makeVersionQueries=1, nativeExecuted=False)
        save_json(output, 'invocation-before.json', invocation)
        env = dict(os.environ)
        env['ISE_CTABLE'] = '68'
        # GH_TOKEN is host-only; no token environment is forwarded into Docker.
        operation_error = None
        status = None
        snapshots, snapshot_errors = {}, {}
        try:
            status, operation_error = run_owned_container(argv, env, output)
        except Exception as exc:
            operation_error = type(exc).__name__ + ': ' + str(exc)
        finally:
            # Every independent after-check is attempted even after timeout or a failed query.
            lifecycle = output / 'container-lifecycle.json'
            termination_established = lifecycle.exists() and json.loads(read(lifecycle))['ownedContainerStopped'] is True
            operations = [('inputs-after.json', lambda: checker.inspect_inputs(workspace, evidence, data, 'dsp')),
                          ('referenced-files-after.json', lambda: referenced_files(workspace, before['nativeInputs'])),
                          ('verilog-inventory-after.json', lambda: tree_inventory(workspace)),
                          ('preparation-evidence-after.json', lambda: evidence_hashes(evidence)),
                          ('image-after.json', lambda: dict(image=checker.image_id()))]
            if not termination_established:
                snapshot_errors['container-termination'] = 'Termination not established; after snapshots are not authoritative'
            for name, operation in operations:
                try:
                    snapshots[name] = operation()
                    save_json(output, name, snapshots[name])
                except Exception as exc:
                    snapshot_errors[name] = type(exc).__name__ + ': ' + str(exc)
            invocation['dockerExit'] = status
            invocation['operationError'] = operation_error
            save_json(output, 'invocation-exited.json', invocation)
            save_json(output, 'after-checks.json', dict(errors=snapshot_errors, completed=list(snapshots),
                      ownedContainerStopped=termination_established, snapshotsAuthoritative=termination_established))
        require(not snapshot_errors, 'One or more immutable after-checks failed; see all retained results')
        after = snapshots['inputs-after.json']
        references_after = snapshots['referenced-files-after.json']
        inventory_after = snapshots['verilog-inventory-after.json']
        image_after = snapshots['image-after.json']['image']
        require(evidence_before == snapshots['preparation-evidence-after.json'], 'Preparation evidence changed')
        require(before == after and image_before == image_after, 'Input/index/source/image immutability failed')
        require(references_before == references_after, 'Referenced file identity/type/existence changed')
        additions = require_existing_unchanged(inventory_before, inventory_after)
        save_json(output, 'auxiliary-additions.json', additions)
        require(operation_error is None, operation_error or 'Owned process lifecycle incomplete')
        controls_result = wrapper_controls(read(output / 'wrapper-controls.trace.tsv'), read(output / 'wrapper-controls.markers.txt'))
        save_json(output, 'wrapper-controls-result.json', controls_result)
        require(read(output / 'container.stdout.txt') == b'' and read(output / 'container.stderr.txt') == b'',
                'Unexpected Docker/bash output; inspect retained full streams')
        require(read(output / 'observed-mac.txt') == (data['mac'] + '\n').encode(), 'Observed MAC differs')
        streams = {key: read(output / ('query.' + key + ('.tsv' if key == 'trace' else '.txt')))
                   for key in ('stdout', 'stderr', 'trace')}
        stream_pins = {key: pin(value) for key, value in streams.items()}
        save_json(output, 'raw-query-streams.json', stream_pins)
        decoded = validate_query(streams, stream_pins, read(output / 'query-exit.txt'), status)
        require(read(output / 'runtime-version.txt') == (decoded['runtimeTcl'] + '\n' + '.'.join(decoded['runtimeTcl'].split('.')[:2]) + '\n').encode(), 'Early/late runtime version differs')
        require(text_bytes(read(output / 'make-version.txt'), 'make version').startswith('GNU Make '), 'GNU make version evidence missing')
        save_json(output, 'decoded-trace.json', decoded)
        invocation.update(imageAfter=image_after, inputsUnchanged=True, directXtclshExit=0,
                          stdout=stream_pins['stdout'], stderr=stream_pins['stderr'], trace=stream_pins['trace'])
        save_json(output, 'invocation-completed.json', invocation)
        outcome.update(collectionComplete=True, originalQueries=1, projectOpens=1, directXtclshExit=0,
                       originalSourceCatchCode=0, allOriginalInputsUnchanged=True,
                       auxiliaryAdditions=len(additions), diagnosticOnly=True,
                       warningCauseDetermined=False, nativeEligibilityEstablished=False)
    except Exception as exc:
        outcome['error'] = type(exc).__name__ + ': ' + str(exc)
        save_json(output, 'collection-result.json', outcome)
        report_manifest(output)
        raise
    save_json(output, 'collection-result.json', outcome)
    report_manifest(output)
    print(json.dumps(outcome, sort_keys=True))


def encode_rows(rows):
    return ''.join(row[0] + '\t' + '\t'.join(str(x).encode().hex() for x in row[1:]) + '\n' for row in rows).encode()


def control_streams():
    rows = [['VERSION', '8.4.19', '8.4', '/work/' + CORE], ['START', ORIGINAL, 'sd2snes_dspx.xise', '68']]
    rows.extend(['ENV', name, int(name in ('ISE_CTABLE', 'LC_ALL', 'LANG')),
                 '68' if name == 'ISE_CTABLE' else 'C' if name in ('LC_ALL', 'LANG') else ''] for name in ENV_KEYS)
    markers, counter = [], 0
    values = MEMBERS[1::2] + [MEMBERS[4], 'Extra Effort (Highest PAR level only)']
    def command(args, phase, result='', items=None):
        nonlocal counter
        counter += 1
        rows.append(['CALL', counter, phase, len(args)])
        rows.extend(['ARG', counter, n, value] for n, value in enumerate(args))
        rows.append(['RETURN', counter, 0, result, '', ''])
        if items is not None:
            rows.append(['LIST', counter, len(items)])
            rows.extend(['ITEM', counter, n, value] for n, value in enumerate(items))
        markers.extend(['SD2SNES_QUERY_V1|BEGIN|' + str(counter) + '|' + phase,
                        'SD2SNES_QUERY_V1|END|' + str(counter) + '|' + phase])
    command(['open', 'sd2snes_dspx.xise'], 'original')
    command(['properties', '-process', 'Place & Route'], 'original', 'complete synthetic list', values)
    command(['properties'], 'original', 'synthetic global list', ['Use SmartGuide'])
    rows.append(['SOURCE', 0, '', '', ''])
    rows.extend(['MEMBERSHIP', name, int(name in values)] for name in MEMBERS)
    for index, args in enumerate(PROBES):
        command(args, 'probe', 'complete synthetic list' if args[0] == 'properties' else 'High',
                values if args[0] == 'properties' else None)
        rows.append(['PROBE', index, 0, 'complete synthetic list' if args[0] == 'properties' else 'High'])
    rows.append(['END', 'complete', counter])
    return dict(stdout=EXPECTED_STDOUT, stderr=('\n'.join(markers) + '\n').encode(), trace=encode_rows(rows)), rows


def controls():
    streams, rows = control_streams()
    fixed = {key: pin(raw) for key, raw in streams.items()}
    validate_query(streams, fixed, b'0\n', 0)
    outcomes = [{'name': 'complete synthetic query', 'accepted': True}]
    cases = []
    for name, field, value in [('nonzero xtclsh', 'exit', b'71\n'), ('nonzero container', 'docker', 1),
                              ('wrong options', 'stdout', b'-ol high -xe c -t 46\n'),
                              ('extra stdout', 'stdout', EXPECTED_STDOUT + b'foreign\n'),
                              ('missing stderr markers', 'stderr', b''),
                              ('extra stderr marker', 'stderr', streams['stderr'] + b'SD2SNES_QUERY_V1|END|99|probe\n'),
                              ('malformed stderr marker', 'stderr', streams['stderr'].replace(b'|BEGIN|1|', b'|MODIFIED|1|', 1)),
                              ('NUL stream', 'stderr', streams['stderr'] + b'\0'),
                              ('stream bound', 'stderr', b'x' * (MAX_TEXT + 1))]:
        cases.append((name, field, value))
    for name, mutate in [
        ('source catch failed', lambda r: next(x for x in r if x[0] == 'SOURCE').__setitem__(1, 1)),
        ('project returned error', lambda r: next(x for x in r if x[0] == 'RETURN').__setitem__(2, 1)),
        ('missing final trace marker', lambda r: r.pop()),
        ('extra trace marker', lambda r: r.insert(-1, ['END', 'complete', 1])),
        ('modified original source', lambda r: r[1].__setitem__(1, '/foreign.tcl')),
        ('modified seed', lambda r: r[1].__setitem__(3, 46)),
        ('missing environment observation', lambda r: r.remove(next(x for x in r if x[0] == 'ENV'))),
        ('missing property item', lambda r: r.remove(next(x for x in r if x[0] == 'ITEM'))),
        ('missing probe', lambda r: r.remove(next(x for x in r if x[0] == 'PROBE'))),
        ('modified membership', lambda r: next(x for x in r if x[0] == 'MEMBERSHIP').__setitem__(2, 1)),
        ('forbidden project command', lambda r: next(x for x in r if x[0] == 'ARG').__setitem__(3, 'set'))]:
        changed = copy.deepcopy(rows)
        mutate(changed)
        cases.append((name, 'trace', encode_rows(changed)))
    for name, field, value in cases:
        changed = dict(streams)
        direct, docker = b'0\n', 0
        if field == 'exit':
            direct = value
        elif field == 'docker':
            docker = value
        else:
            changed[field] = value
        pins = {key: pin(raw) for key, raw in changed.items()}
        try:
            validate_query(changed, pins, direct, docker)
        except (ValueError, UnicodeError):
            outcomes.append(dict(name=name, rejected=True))
        else:
            raise ValueError('Negative query control accepted: ' + name)
    changed = dict(streams)
    changed['stderr'] += b'changed after pin\n'
    try:
        validate_query(changed, fixed, b'0\n', 0)
    except ValueError:
        outcomes.append(dict(name='stream bytes changed after identity capture', rejected=True))
    else:
        raise ValueError('Stream integrity negative accepted')
    # Arbitrary vendor stderr is collected, never accepted as native/preflight evidence.
    diagnostic = dict(streams)
    diagnostic['stderr'] += b'WARNING:synthetic diagnostic observation\n'
    result = validate_query(diagnostic, {k: pin(v) for k, v in diagnostic.items()}, b'0\n', 0)
    require(result['stderrApproval'] is False, 'Collection must never approve stderr')
    outcomes.append(dict(name='vendor stderr retained without acceptance', collected=True, stderrApproval=False))
    print(json.dumps(dict(hostedOnly=True, controls=outcomes, localExecution=False,
                         oldCheckerChanged=False, oldFailurePreserved=True, nativeExecuted=False), indent=2))


if __name__ == '__main__':
    if sys.argv[1:] == ['--self-test']:
        controls()
    elif len(sys.argv) == 5 and sys.argv[1] == '--collect':
        collect(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        raise SystemExit('Usage: diagnose-successor-native-tcl.py --self-test | --collect dsp EVIDENCE_ROOT OUTPUT_ROOT')
