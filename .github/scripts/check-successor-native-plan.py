#!/usr/bin/env python3
"""Hosted-only, fail-closed collection of a retained-input make -n plan.

This host Python program owns the complete Docker invocation. The fixed ISE
container needs no Python. It NEVER invokes a native route command directly.
GNU make still expands its canonical Tcl option query under -n; every makefile,
project and Tcl dependency is pinned before that hosted operation. No local use.
The old post-route check-native-route-commands.py remains independently required.
"""
import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted command planning only; never execute locally')

DATA_SHA = '191c53b6d9548915dd90955a8b54f7b71ae4f39d9563b944d018ea7a94023a7b'
COMMON_SHA = 'a7d9bafa7c3e0694069045bce98446818740381ea52daa689dff6d94e354d92e'
OVERRIDES = ('MAKEFILES', 'MAKEFLAGS', 'GNUMAKEFLAGS', 'MFLAGS',
             'MAKEOVERRIDES', 'MAKELEVEL', 'MAKE_RESTARTS')
MAX_TEXT = 1_000_000
MAX_INPUT = 32_000_000


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular(path, cap):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(),
            f'Expected regular file: {path}')
    require(0 < info.st_size <= cap, f'Empty or excessive file: {path}')
    raw = path.read_bytes()
    require(len(raw) == info.st_size, f'File size changed: {path}')
    return raw


def read_text(path, cap=MAX_TEXT):
    raw = read_regular(path, cap)
    text = raw.decode('utf-8', errors='strict')
    require('\x00' not in text and '\r' not in text, f'Noncanonical text: {path}')
    return raw, text


def save_json(path, data):
    path.write_bytes((json.dumps(data, indent=2, sort_keys=True) + '\n').encode())


def data_file():
    path = Path(__file__).resolve().parent.parent / 'fixtures' / 'successor-native-plan-data.json'
    raw, text = read_text(path)
    require(sha(raw) == DATA_SHA, 'Pinned plan fixture changed')
    data = json.loads(text)
    require(data['schemaVersion'] == 1 and set(data['families']) == {'basex', 'dsp'},
            'Unexpected fixture schema/families')
    return data


def family_data(data, family):
    require(family in data['families'], 'Unknown selected family')
    return data['families'][family]


def make_argv(data, family):
    core = family_data(data, family)['core']
    return ['make', '-C', 'verilog/sd2snes_' + core, '-o', 'main_map.ncd',
            '-j2', '-n', 'main.ncd', 'HOST=LINUX', 'XILINX_ENV=', 'IGNORE_TIMING=0']


def shell_command(data, family, marker):
    require(re.fullmatch('[0-9a-f]{64}', marker) is not None, 'Invalid native-input marker')
    checks = ' '.join('test -z "${' + key + '-}";' for key in OVERRIDES)
    # All interpolated values come from the pinned fixture or a checked hex SHA.
    return ('set -euo pipefail; export LC_ALL=C LANG=C; '
            'observed_mac=$(cat /sys/class/net/eth0/address); '
            'printf "Observed preflight-container eth0 MAC: %s\\n" "$observed_mac"; '
            'test "$observed_mac" = ' + data['mac'] + '; ' + checks + ' '
            'printf "Verified retained native input manifest: %s\\n" "' + marker + '"; '
            + ' '.join(make_argv(data, family)))


def docker_argv(data, family, workspace, marker):
    # These are the original native container's image, user, bridge, MAC,
    # environment and mount/workdir/entrypoint choices. Only the task name and
    # the make -n/-o planning boundary differ from the prior route invocation.
    return ['docker', 'run', '--rm', '--network', 'bridge', '--name',
            'sd2snes-' + family + '-successor-native-preflight', '--user', '0:0',
            '--mac-address', data['mac'], '--env', 'ISE_CTABLE',
            '--volume', workspace + ':/work', '--workdir', '/work',
            '--entrypoint', '/bin/bash', 'sd2snes-ci:mk2', '-c',
            shell_command(data, family, marker)]


def expected_recipe(common, data, family):
    """Literal, finite expansion of the pinned native recipe, never execution."""
    require(sha(common) == COMMON_SHA, 'Canonical common.mk differs')
    source = common.decode('utf-8', errors='strict')
    require(source.count('main.ncd: main_map.ncd\n') == 1, 'Ambiguous native recipe')
    section = source.split('main.ncd: main_map.ncd\n', 1)[1].split('\nmain.bit:', 1)[0]
    lines = section.splitlines()
    require(lines[0] == '\t$(call T,[mk2] fpga_$(CORE) - Place and Route)', 'Title source changed')
    require(lines[1] == '\t$(eval XILINX_PAR_OPTS := $(shell $(XILINX_ENV) $(XILINX_BIN)/xtclsh $(XILINX_SCRIPTS)/xgenparcmd.tcl sd2snes_$(CORE).xise $(ISE_CTABLE)))',
            'Option query source changed')
    cfg = family_data(data, family)
    replacements = {'$(XILINX_ENV)': '', '$(XILINX_BIN)': '/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64',
                    '$(XILINX_PAR_OPTS)': '-ol high -xe c -t ' + str(cfg['seed']),
                    '$(CORE)': cfg['core'], '$(IGNORE_TIMING)': '0',
                    '$^': 'main_map.ncd', '$@': 'main.ncd', '$$': '$'}
    body = []
    for line in lines[2:]:
        require(line.startswith('\t'), 'Unexpected native recipe line')
        line = line[1:]
        if line.startswith('@'):
            line = line[1:]
        for before, after in replacements.items():
            line = line.replace(before, after)
        require('$(' not in line, 'Unexpanded make expression in canonical plan')
        body.append(line)
    title_source = 'T = @echo -e "\\e]0;$(1)\\a"'
    require(source.splitlines().count(title_source) == 1, 'Canonical T macro changed')
    title = 'echo -e "\\e]0;[mk2] fpga_' + cfg['core'] + ' - Place and Route\\a"'
    return '\n'.join(body) + '\n', title


def check_plan(stdout, stderr, invocation, common, data, family):
    require(isinstance(stdout, bytes) and isinstance(stderr, bytes), 'Raw plan bytes required')
    require(len(stdout) <= MAX_TEXT and len(stderr) <= MAX_TEXT, 'Plan output exceeds declared bound')
    require(not stderr, 'Unexpected stderr from hosted make planning; inspect complete retained bytes')
    text = stdout.decode('utf-8', errors='strict')
    require('\x00' not in text and '\r' not in text and text.endswith('\n'), 'Noncanonical plan text')
    cfg = family_data(data, family)
    require(invocation.get('schemaVersion') == 1 and invocation.get('family') == family,
            'Invocation schema/family differs')
    marker = invocation.get('nativeInputMarker', {})
    digest = marker.get('manifestSha256', '')
    require(re.fullmatch('[0-9a-f]{64}', digest) is not None, 'Missing verified native-input marker')
    require(marker.get('checkedPaths') == sorted(row['path'] for row in cfg['inputs']),
            'Incomplete or foreign native-input marker inventory')
    workspace = invocation.get('workspace', '')
    require(workspace.startswith('/') and ':' not in workspace and '\n' not in workspace,
            'Invalid mounted checkout path')
    require(invocation.get('makeArgv') == make_argv(data, family), 'Full make invocation differs')
    require(invocation.get('dockerArgv') == docker_argv(data, family, workspace, digest),
            'Full owned Docker invocation differs')
    require(invocation.get('environment') == {'ISE_CTABLE': str(cfg['seed'])}, 'Seed environment differs')
    require(invocation.get('hostMakeOverrides') == {}, 'Inherited host make override')
    require(invocation.get('imageBefore') == data['image'] == invocation.get('imageAfter'),
            'Fixed ISE image identity differs')
    require(invocation.get('returncode') == 0, 'Actual Docker/make planning exit failed')
    require(invocation.get('inputsUnchanged') is True, 'Complete input immutability not established')
    require(invocation.get('commandPlanOnly') is True, 'Wrong operation marker')
    lines = text.splitlines(keepends=True)
    prefix = ['Observed preflight-container eth0 MAC: ' + data['mac'] + '\n',
              'Verified retained native input manifest: ' + digest + '\n']
    require(lines[:2] == prefix, 'Missing or changed observed MAC/native-input stdout marker')
    lines = lines[2:]
    directory = '/work/verilog/sd2snes_' + cfg['core']
    directory_form = None
    for quote in ("'", '`'):
        enter = 'make: Entering directory ' + quote + directory + "'\n"
        leave = 'make: Leaving directory ' + quote + directory + "'\n"
        if lines and lines[0] == enter:
            require(lines[-1] == leave, 'Missing or foreign matching make directory footer')
            lines = lines[1:-1]
            directory_form = quote
            break
    expected, title = expected_recipe(common, data, family)
    title_present = bool(lines and lines[0] == title + '\n')
    if title_present:
        lines = lines[1:]
    observed = ''.join(lines)
    require(observed == expected,
            'Complete native plan differs: reject missing/extra/foreign commands, options, handlers or timing guards')
    require(observed.count(cfg['par'] + ' || par_status=$?; \\') == 1 and
            observed.count(cfg['trace'] + ' || trce_status=$?; \\') == 1,
            'Expected exactly one original PAR and TRACE recipe')
    return dict(family=family, seed=cfg['seed'], originalParRecipes=1, originalTraceRecipes=1,
                heldMappedInput='main_map.ncd', makeDryRun=True, completeRecipeByteMatch=True,
                optionalCanonicalTitlePresent=title_present, directoryQuote=directory_form,
                nativeInputManifestSha256=digest, planBytes=len(stdout), planSha256=sha(stdout),
                nativeExecuted=False, timingPass=False, wholeMappedEquivalenceProved=False,
                actualPostRouteCommandGateStillRequired=True)


def relative_path(name):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and '\\' not in name and ':' not in name and
            '\x00' not in name and '\n' not in name and all(p not in ('', '.', '..') for p in path.parts)
            and str(path) == name, 'Unsafe manifest path')
    return path


def parse_manifest(raw):
    text = raw.decode('utf-8', errors='strict')
    require(text.endswith('\n') and '\r' not in text and '\x00' not in text, 'Invalid SHA manifest text')
    rows = {}
    for line in text.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        require(match is not None, 'Unexpected SHA manifest row')
        digest, name = match.groups()
        relative_path(name)
        require(name not in rows, 'Duplicate manifest path')
        rows[name] = digest
    require(rows, 'Empty manifest')
    return rows


def git_bytes(workspace, *args):
    return subprocess.check_output(['git', '-C', str(workspace), *args])


def inspect_inputs(workspace, evidence, data, family):
    cfg = family_data(data, family)
    raw, text = read_text(evidence / 'preparation-result.json')
    prepared = json.loads(text)
    require(prepared.get('preparationComplete') is True and prepared.get('family') == family,
            'Preparation did not verify this family')
    head = git_bytes(workspace, 'rev-parse', 'HEAD').decode().strip()
    tree = git_bytes(workspace, 'rev-parse', 'HEAD:verilog').decode().strip()
    require(prepared.get('checkoutHead') == head and
            prepared.get('productionVerilogTree') == tree == data['productionVerilogTree'],
            'Preparation checkout/production tree differs')
    require(prepared.get('nativeExecution') is False and prepared.get('timingAccepted') is False,
            'Unexpected preparation operation/result')
    manifest = read_regular(evidence / 'restored-inputs.sha256', MAX_TEXT)
    require(sha(manifest) == prepared.get('restoredInputsManifestSha256'), 'Restored input manifest binding differs')
    expected = {row['path']: row['sha256'] for row in cfg['inputs']}
    require(parse_manifest(manifest) == expected, 'Restored input paths/hashes differ from exact accepted candidate/NCD/PCF/IP')
    require(prepared.get('sourcePath') == cfg['candidatePath'] and
            prepared.get('candidateSha256') == expected[cfg['candidatePath']], 'Candidate preparation binding differs')
    core_dir = 'verilog/sd2snes_' + cfg['core']
    for key, filename in [('ncdSha256', 'main_map.ncd'), ('pcfSha256', 'main.pcf')]:
        require(prepared.get(key) == expected[core_dir + '/' + filename], 'Native input preparation binding differs')
    provenance = read_regular(evidence / 'provenance.json', 8_000_000)
    require(sha(provenance) == prepared.get('provenanceSha256'), 'Preparation provenance changed')
    source_manifest = read_regular(evidence / 'checkout-after-candidate.sha256', MAX_TEXT)
    source_index = read_regular(evidence / 'checkout-after-candidate-index.txt', MAX_TEXT)
    require(sha(source_manifest) == prepared.get('checkoutAfterCandidateSha256') and
            sha(source_index) == prepared.get('checkoutAfterCandidateIndexSha256'), 'Full checkout receipt binding differs')
    require(git_bytes(workspace, 'ls-files', '-s') == source_index, 'Complete index changed')
    require(git_bytes(workspace, 'diff', '--name-only').decode() == cfg['candidatePath'] + '\n',
            'Candidate is not the sole tracked working-tree override')
    subprocess.run(['git', '-C', str(workspace), 'diff', '--cached', '--exit-code'], check=True)
    source_rows = parse_manifest(source_manifest)
    tracked = git_bytes(workspace, 'ls-files', '-z').decode('utf-8', errors='strict').split('\x00')
    require(tracked[-1] == '' and set(tracked[:-1]) == set(source_rows), 'Incomplete tracked source inventory')
    for name, digest in source_rows.items():
        path = workspace / relative_path(name)
        require(path.is_file() and sha(path.read_bytes()) == digest, 'Tracked source SHA changed: ' + name)
    for pin in data['sourcePins']:
        raw = read_regular(workspace / relative_path(pin['path']), MAX_TEXT)
        require((len(raw), sha(raw)) == (pin['bytes'], pin['sha256']), 'Canonical planning source changed: ' + pin['path'])
    for name in ('verilog/settings.local.mk', core_dir + '/GNUmakefile', core_dir + '/makefile'):
        path = workspace / name
        require(not path.exists() and not path.is_symlink(), 'Unapproved makefile/override exists: ' + name)
    for name in ('main.ncd', 'main.par', 'main.twr', 'main.ngd', 'main.ngc', 'main.bit'):
        path = workspace / core_dir / name
        require(not path.exists() and not path.is_symlink(), 'Unexpected native/upstream product: ' + name)
    native = []
    for pin in cfg['inputs']:
        path = workspace / relative_path(pin['path'])
        require(all(not parent.is_symlink() for parent in path.parents if parent != workspace.parent),
                'Symlink in native-input ancestry')
        raw = read_regular(path, MAX_INPUT)
        require(sha(raw) == pin['sha256'] and ('bytes' not in pin or len(raw) == pin['bytes']),
                'Actual retained native input differs: ' + pin['path'])
        native.append(dict(path=pin['path'], bytes=len(raw), sha256=sha(raw)))
    return dict(checkoutHead=head, productionVerilogTree=tree,
                preparationResultSha256=sha(read_regular(evidence / 'preparation-result.json', MAX_TEXT)),
                provenanceSha256=sha(provenance), nativeInputManifestSha256=sha(manifest),
                checkoutManifestSha256=sha(source_manifest), checkoutIndexSha256=sha(source_index),
                trackedSourceCount=len(source_rows), nativeInputs=native)


def image_id():
    result = subprocess.run(['docker', 'image', 'inspect', 'sd2snes-ci:mk2', '--format', '{{.Id}}'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    require(not result.stderr and result.stdout.endswith(b'\n'), 'Unexpected image identity output')
    return result.stdout.decode('ascii', errors='strict').strip()


def collect(data, family, evidence, output):
    workspace = Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
    require(workspace.is_dir() and str(workspace).startswith('/') and ':' not in str(workspace), 'Expected hosted Linux checkout')
    evidence = evidence.resolve(strict=True)
    require(evidence.is_dir() and evidence != workspace and workspace not in evidence.parents,
            'Preparation evidence must be outside checkout')
    require(not output.exists() and not output.is_symlink(), 'Output directory must be new')
    output = output.resolve()
    require(workspace not in output.parents and output != workspace and evidence not in output.parents and output != evidence,
            'Output must be outside checkout and imported evidence')
    output.mkdir(parents=True, exist_ok=False)
    result = dict(family=family, collectionComplete=False, nativeExecuted=False, timingPass=False)
    invocation = None
    try:
        overrides = {key: os.environ[key] for key in OVERRIDES if os.environ.get(key)}
        require(not overrides, 'Inherited host make override')
        before = inspect_inputs(workspace, evidence, data, family)
        save_json(output / 'inputs-before.json', before)
        require(image_id() == data['image'], 'Unexpected fixed ISE image before planning')
        cfg = family_data(data, family)
        marker = before['nativeInputManifestSha256']
        invocation = dict(schemaVersion=1, family=family, workspace=str(workspace),
                          makeArgv=make_argv(data, family), dockerArgv=docker_argv(data, family, str(workspace), marker),
                          environment={'ISE_CTABLE': str(cfg['seed'])}, hostMakeOverrides={},
                          nativeInputMarker=dict(manifestSha256=marker, checkedPaths=sorted(x['path'] for x in cfg['inputs'])),
                          imageBefore=data['image'], commandPlanOnly=True, inputsUnchanged=False,
                          returncode=None)
        save_json(output / 'invocation-before.json', invocation)
        env = dict(os.environ, ISE_CTABLE=str(cfg['seed']))
        with (output / 'make-plan.stdout.txt').open('wb') as stdout, (output / 'make-plan.stderr.txt').open('wb') as stderr:
            process = subprocess.run(invocation['dockerArgv'], env=env, stdout=stdout, stderr=stderr, check=False)
        invocation['returncode'] = process.returncode
        invocation['imageAfter'] = image_id()
        after = inspect_inputs(workspace, evidence, data, family)
        save_json(output / 'inputs-after.json', after)
        invocation['inputsUnchanged'] = before == after
        save_json(output / 'invocation-completed.json', invocation)
        stdout = (output / 'make-plan.stdout.txt').read_bytes()
        stderr = (output / 'make-plan.stderr.txt').read_bytes()
        common = read_regular(workspace / 'verilog/common.mk', MAX_TEXT)
        checked = check_plan(stdout, stderr, invocation, common, data, family)
        save_json(output / 'checked-plan.json', checked)
        result.update(collectionComplete=True, checkedPlanSha256=sha((output / 'checked-plan.json').read_bytes()),
                      exactOriginalRecipe=True, inputsUnchanged=True)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        if invocation is not None:
            save_json(output / 'invocation-at-failure.json', invocation)
        raise
    finally:
        save_json(output / 'collection-result.json', result)
        print(json.dumps(result, sort_keys=True))


def controls(data):
    """Hosted synthetic text/invocation controls; these never start Docker/make."""
    root = Path(__file__).resolve().parent.parent.parent
    common = read_regular(root / 'verilog/common.mk', MAX_TEXT)
    cases = []
    for family in ('basex', 'dsp'):
        cfg = family_data(data, family)
        marker = 'a' * 64
        invocation = dict(schemaVersion=1, family=family, workspace='/work-fixture',
                          makeArgv=make_argv(data, family), dockerArgv=docker_argv(data, family, '/work-fixture', marker),
                          environment={'ISE_CTABLE': str(cfg['seed'])}, hostMakeOverrides={},
                          nativeInputMarker=dict(manifestSha256=marker, checkedPaths=sorted(x['path'] for x in cfg['inputs'])),
                          imageBefore=data['image'], imageAfter=data['image'], returncode=0,
                          inputsUnchanged=True, commandPlanOnly=True)
        body, title = expected_recipe(common, data, family)
        prefix = 'Observed preflight-container eth0 MAC: ' + data['mac'] + '\nVerified retained native input manifest: ' + marker + '\n'
        plain = prefix + body
        for quote in (None, "'", '`'):
            for with_title in (False, True):
                directory = '/work/verilog/sd2snes_' + cfg['core']
                plan = (prefix + ('make: Entering directory ' + quote + directory + "'\n" if quote else '')
                        + (title + '\n' if with_title else '') + body
                        + ('make: Leaving directory ' + quote + directory + "'\n" if quote else ''))
                check_plan(plan.encode(), b'', invocation, common, data, family)
                cases.append(dict(family=family, control='positive', quote=quote, title=with_title, passed=True))
        mutations = {
            'missing-par': plain.replace(cfg['par'], '', 1),
            'extra-par': plain + cfg['par'] + '\n',
            'missing-trace': plain.replace(cfg['trace'], '', 1),
            'extra-trace': plain + cfg['trace'] + '\n',
            'foreign-par': plain.replace('/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64/par', '/tmp/par', 1),
            'unwrapped-trace': plain.replace('/lin64/trce', '/lin64/unwrapped/trce', 1),
            'wrong-seed': plain.replace('-t ' + str(cfg['seed']), '-t 1', 1),
            'changed-flags': plain.replace('-ol high', '-ol std', 1),
            'missing-par-status-init': plain.replace('par_status=0; \\\n', '', 1),
            'wrong-par-handler': plain.replace('|| par_status=$?', '|| par_status=0', 1),
            'wrong-trace-handler': plain.replace('|| trce_status=$?', '|| true', 1),
            'removed-native-exit': plain.replace('exit $par_status', 'true', 1),
            'ignored-native-exit': plain.replace('exit $trce_status', 'true', 1),
            'timing-waiver': plain.replace('[ "0"a = 1a ]', '[ "1"a = 1a ]', 1),
            'omitted-timing-guard': prefix + body.split('{ grep -Eq', 1)[0],
            'altered-timing-expression': plain.replace('Timing Score: 0', 'Timing Score:', 1),
            'unknown-shell-command': plain + 'touch main_map.ncd\n',
            'missing-native-input-marker': plain.replace(prefix.splitlines(True)[1], '', 1),
            'wrong-native-input-marker': plain.replace(marker, 'b' * 64, 1),
            'wrong-mac': plain.replace(data['mac'], '00:00:00:00:00:00', 1),
        }
        for tool in ('coregen', 'xst', 'ngdbuild', 'map', 'bitgen', 'xtclsh'):
            mutations['extra-' + tool] = plain + '/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64/' + tool + ' unexpected\n'
        for name, bad in mutations.items():
            try:
                check_plan(bad.encode(), b'', invocation, common, data, family)
            except (ValueError, UnicodeError):
                cases.append(dict(family=family, control=name, rejected=True))
            else:
                raise ValueError('Accepted negative plan control: ' + name)
        negative_invocations = {}
        for name, edit in (
            ('missing-held-option', lambda x: x['makeArgv'].remove('-o')),
            ('missing-dry-run', lambda x: x['makeArgv'].remove('-n')),
            ('wrong-held-file', lambda x: x['makeArgv'].__setitem__(4, 'foreign.ncd')),
            ('foreign-core', lambda x: x['makeArgv'].__setitem__(2, 'verilog/sd2snes_cx4')),
            ('timing-option-override', lambda x: x['makeArgv'].append('IGNORE_TIMING=1')),
            ('changed-jobs', lambda x: x['makeArgv'].__setitem__(5, '-j8')),
            ('foreign-docker-command', lambda x: x['dockerArgv'].__setitem__(-1, 'true')),
            ('seed-env-override', lambda x: x['environment'].__setitem__('ISE_CTABLE', '1')),
            ('inherited-makeflags', lambda x: x.__setitem__('hostMakeOverrides', {'MAKEFLAGS': '-i'})),
            ('missing-input-proof', lambda x: x.__setitem__('nativeInputMarker', {})),
            ('partial-input-proof', lambda x: x['nativeInputMarker']['checkedPaths'].pop()),
            ('failed-native-plan-exit', lambda x: x.__setitem__('returncode', 2)),
            ('changed-input', lambda x: x.__setitem__('inputsUnchanged', False)),
            ('wrong-image', lambda x: x.__setitem__('imageAfter', 'sha256:' + '0' * 64)),
        ):
            bad = copy.deepcopy(invocation)
            edit(bad)
            negative_invocations[name] = bad
        for name, bad in negative_invocations.items():
            try:
                check_plan(plain.encode(), b'', bad, common, data, family)
            except (ValueError, UnicodeError):
                cases.append(dict(family=family, control=name, rejected=True))
            else:
                raise ValueError('Accepted negative invocation control: ' + name)
        try:
            check_plan(plain.encode(), b'unexpected tool stderr\n', invocation, common, data, family)
        except ValueError:
            cases.append(dict(family=family, control='unexpected-stderr', rejected=True))
        else:
            raise ValueError('Accepted unexpected stderr')
    print(json.dumps(dict(hostedSyntheticControls=True, controls=cases,
                          nativeExecuted=False, timingPass=False), indent=2, sort_keys=True))


def main():
    data = data_file()
    if sys.argv[1:] == ['--self-test']:
        controls(data)
    elif len(sys.argv) == 5 and sys.argv[1] == '--collect':
        collect(data, sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    else:
        raise SystemExit('usage: check-successor-native-plan.py --self-test | --collect FAMILY EVIDENCE_ROOT OUTPUT_ROOT')


if __name__ == '__main__':
    main()
