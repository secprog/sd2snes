#!/usr/bin/env python3
"""GitHub-only injected native-exit controls using the actual menu Makefiles.

No assembler is run. Each scratch tree copies an exact reviewed Makefile and
replaces cpp/snescom/sneslink/tee with explicit status-recording text fixtures.
These controls establish failure propagation, not assembled-image correctness.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

FILE_LIMIT = 3_000_000
TOTAL_LIMIT = 96_000_000
COUNT_LIMIT = 1024
ACTIVE_REPORTS = None


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    require(len(data) <= FILE_LIMIT, 'JSON report exceeds text bound')
    with path.open('xb') as stream:
        stream.write(data)


STUB = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
name = Path(sys.argv[0]).name
mode = os.environ['SD2SNES_EXIT_CONTROL_MODE']
args = sys.argv[1:]
def event(phase, **fields):
    row = dict(tool=name, argv=args, mode=mode, phase=phase, **fields)
    record = (json.dumps(row, sort_keys=True) + '\n').encode()
    if len(record) > 4096:
        raise ValueError('Fixture event exceeds atomic bound')
    fd = os.open(os.environ['SD2SNES_EXIT_CONTROL_EVENTS'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if os.write(fd, record) != len(record):
            raise OSError('Incomplete fixture event write')
    finally:
        os.close(fd)
def child():
    if name == 'cpp':
        return 0
    if name == 'tee':
        if len(args) != 1:
            return 90
        total = 0
        with Path(args[0]).open('xb') as output:
            while True:
                data = sys.stdin.buffer.read(65536)
                if not data:
                    break
                total += len(data)
                output.write(data)
                sys.stdout.buffer.write(data)
                if total > 1000000:
                    print('Explicit fixture input bound exceeded.', file=sys.stderr)
                    return 94  # An excess is failure, never a clipped success.
        return 29 if mode == 'tee_failure' else 0
    if name not in ('snescom', 'sneslink'):
        return 91
    try:
        target = args[args.index('-o') + 1]
    except (ValueError, IndexError):
        return 92
    if target != '/dev/null':
        Path(target).write_bytes(b'Explicit text fixture; never an executable image.\n')
    if mode == 'native_failure':
        print('Fixture native tool returns nonzero without diagnostic keywords.')
        return 23
    if mode == 'diagnostic_failure':
        print('Error: fixture assembler diagnostic' if name == 'snescom' else 'ERROR: fixture linker diagnostic')
    else:
        print('Fixture native tool completed.')
    return 0
if args and args[0] == '--fixture-child':
    args = args[1:]
    raise SystemExit(child())
event('before-child')
process = subprocess.run([sys.executable, __file__, '--fixture-child'] + args, check=False)
event('child-reaped', returncode=process.returncode)
raise SystemExit(process.returncode if 0 <= process.returncode <= 125 else 1)
'''


def run_case(helper, make, family, source, fixtures, reports, action, mode):
    label = family + '-' + action + '-' + mode
    work = fixtures / label
    work.mkdir()
    (work / 'Makefile').write_bytes(source)
    (work / 'fixture.a65').write_text('; text-only control source\n', encoding='utf-8')
    (work / 'nes_equates.i65').write_text('; control dependency\n', encoding='utf-8')
    (work / 'nes_palette.i65').write_text('; control dependency\n', encoding='utf-8')
    tools = work / 'tools'
    tools.mkdir()
    for name in ('cpp', 'snescom', 'sneslink', 'tee'):
        path = tools / name
        path.write_text(STUB, encoding='utf-8')
        path.chmod(0o755)
    events = reports / (label + '.events.jsonl')
    env = {'PATH': str(tools) + os.pathsep + os.environ['PATH'],
           'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
           'GITHUB_ACTIONS': 'true',
           'GITHUB_WORKSPACE': os.environ['GITHUB_WORKSPACE'],
           'RUNNER_TEMP': os.environ['RUNNER_TEMP'],
           'SD2SNES_EXIT_CONTROL_MODE': mode, 'SD2SNES_EXIT_CONTROL_EVENTS': str(events)}
    if action == 'assembler':
        argv = [make, '--no-print-directory', '--directory', str(work), '-f', 'Makefile', 'fixture.o65']
        native = 'snescom'
        native_args = ['-J', '-Wall', '-o', 'fixture.o65', 'fixture.a65']
    else:
        # Explicit scratch prerequisites exercise the original linker recipe.
        # No production input, source option or output recipe is substituted.
        (work / 'fixture.o65').write_text('Text-only linker input fixture.\n', encoding='utf-8')
        if family == 'menu':
            argv = [make, '--no-print-directory', '--directory', str(work), '-f', 'Makefile', 'link.log', 'OBJS=fixture.o65']
            native_args = ['-fsmc', '-o', '/dev/null', 'fixture.o65']
        else:
            argv = [make, '--no-print-directory', '--directory', str(work), '-f', 'Makefile', 'nes_snes_raw.sfc', 'O65=fixture.o65', 'IPS=']
            native_args = ['-fsmc', '-o', 'nes_snes_raw.sfc', 'fixture.o65']
        native = 'sneslink'
    attempt = {'label': label, 'argv': argv, 'processCwd': str(Path.cwd()),
               'recipeDirectory': str(work), 'environment': env,
               'sourceMakefileSha256': sha(source), 'state': 'before-spawn'}
    put_json(reports / (label + '.attempt.json'), attempt)
    result = dict(attempt, state='finished', accepted=False, errors=[])
    original_env = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        # Shared reviewed primitive owns bounded, lossless capture and kill/reap.
        capture = helper.retain_capture(argv, reports / (label + '-make'), timeout=30)
        result['capture'] = capture
        require(capture['clientReaped'] and capture['textEvidenceComplete'] and not capture['errors'],
                'Incomplete actual make capture')
        stdout_path = reports / (label + '-make.stdout.txt')
        stderr_path = reports / (label + '-make.stderr.txt')
        require(events.is_file() and events.stat().st_size <= FILE_LIMIT, 'Missing/oversize complete fixture events')
        data = events.read_bytes()
        require(b'\0' not in data, 'NUL in fixture events')
        observed = [json.loads(row) for row in data.decode('utf-8', errors='strict').splitlines()]
        expected_args = {native: native_args, 'tee': ['fixture.o65.log' if action == 'assembler' else 'link.log']}
        if action == 'assembler' and family == 'menu':
            expected_args['cpp'] = ['-MM', '-MP', '-MF', '.dep/fixture.o65.d', '-MT', 'fixture.o65', '-I.', 'fixture.a65']
        require(len(observed) == 2 * len(expected_args), 'Unexpected/missing tool events')
        for tool, expected in expected_args.items():
            rows = [row for row in observed if row['tool'] == tool]
            require(len(rows) == 2 and [r['phase'] for r in rows] == ['before-child', 'child-reaped'], 'Missing/reordered actual child status')
            require(all(row['argv'] == expected and row['mode'] == mode for row in rows), 'Wrong actual tool arguments/mode')
            expected_exit = 23 if tool == native and mode == 'native_failure' else 29 if tool == 'tee' and mode == 'tee_failure' else 0
            require(rows[-1]['returncode'] == expected_exit, 'Fixture child returned unexpected native exit')
        expected_success = mode == 'success'
        require(capture['returncode'] == (0 if expected_success else 2), 'Unexpected actual GNU make exit')
        if not expected_success:
            expected_error = 23 if mode == 'native_failure' else 29 if mode == 'tee_failure' else 1
            require(('Error ' + str(expected_error) + '\n') in stderr_path.read_text(encoding='utf-8'),
                    'Make failure is not the intended original recipe error')
        if action == 'assembler' and not expected_success:
            require(not (work / 'fixture.o65').exists(), 'Failed object was retained')
        result.update(accepted=True, expectedSuccess=expected_success, observedEvents=observed,
                      representativeTargetOnly=True)
    except BaseException as caught:
        result['errors'].append(type(caught).__name__ + ': ' + str(caught))
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        put_json(reports / (label + '.result.json'), result)
    require(result['accepted'], 'Native-exit control failed: ' + label)
    return result


def main():
    global ACTIVE_REPORTS
    require(os.name == 'posix' and os.environ.get('GITHUB_ACTIONS') == 'true', 'Controls execute on GitHub only')
    require(len(sys.argv) == 3, 'Expected repository and fresh outside-checkout report directory')
    root = Path(sys.argv[1]).resolve(strict=True)
    require(Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True) == root, 'Explicit checkout differs from hosted workspace')
    reports = Path(sys.argv[2]).absolute()
    require(not reports.exists() and root not in reports.resolve().parents and reports.resolve() != root,
            'Report root must be fresh and outside checkout')
    runner_temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    require(runner_temp in reports.resolve().parents, 'Control reports must remain under RUNNER_TEMP')
    fixtures = reports.with_name(reports.name + '-fixtures')
    require(not fixtures.exists(), 'Fixture directory already exists')
    reports.mkdir(parents=True)
    ACTIVE_REPORTS = reports
    fixtures.mkdir()
    make = shutil.which('make')
    require(make is not None, 'Hosted make unavailable')
    sources = {'menu': root / 'snes/Makefile', 'nes': root / 'snes/nes/Makefile'}
    source_bytes = {family: path.read_bytes() for family, path in sources.items()}
    spec = importlib.util.spec_from_file_location('sd2snes_post_sync_evidence', root / '.github/scripts/post-sync-evidence.py')
    require(spec is not None and spec.loader is not None, 'Shared capture helper unavailable')
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)  # This entire runner is GitHub-only.
    rows = []
    for family in sources:
        for action in ('assembler', 'linker'):
            modes = ['success', 'native_failure', 'tee_failure']
            # The main menu link.log recovery recipe has no diagnostic grep;
            # its original menu/igmenu layout/diagnostic gates remain separate.
            if action == 'assembler' or family == 'nes':
                modes.append('diagnostic_failure')
            for mode in modes:
                rows.append(run_case(helper, make, family, source_bytes[family], fixtures, reports, action, mode))
    require(all(sources[family].read_bytes() == data for family, data in source_bytes.items()), 'Original Makefile mutated')
    summary = {'schema': 'sd2snes-post-sync-menu-native-exit-controls-v1', 'accepted': True,
               'positiveControls': sum(row['expectedSuccess'] for row in rows),
               'negativeControls': sum(not row['expectedSuccess'] for row in rows),
               'sourceMakefiles': {family: {'path': str(sources[family]), 'sha256': sha(data)} for family, data in source_bytes.items()},
               'cases': [row['label'] for row in rows],
               'sharedCaptureHelperSha256': sha((root / '.github/scripts/post-sync-evidence.py').read_bytes()),
               'scope': 'Representative .o65 compilation and main-menu link.log/NES raw-link failure propagation only; no .ips/log-triggered pattern, menu/onboarding/igmenu layout-gate, real assembler/linker, FPGA/MCU or hardware qualification.'}
    files = list(reports.iterdir())
    final_bytes = (json.dumps(summary, indent=2, sort_keys=True) + '\n').encode()
    require(len(files) + 1 <= COUNT_LIMIT and sum(p.stat().st_size for p in files) + len(final_bytes) <= TOTAL_LIMIT,
            'Complete control report union including final result exceeds bounds')
    put_json(reports / 'result.json', summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        diagnostic = {'accepted': False, 'error': type(error).__name__ + ': ' + str(error),
                      'finalizationScope': 'The outer reviewed capture retains complete CLI stderr/native exit even if this runner cannot write its own failure marker.'}
        if ACTIVE_REPORTS is not None:
            try:
                put_json(ACTIVE_REPORTS / 'failure.json', diagnostic)
            except BaseException as finalization:
                diagnostic['failureMarkerError'] = type(finalization).__name__ + ': ' + str(finalization)
        print(json.dumps(diagnostic, sort_keys=True), file=sys.stderr)
        raise SystemExit(1)
