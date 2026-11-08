#!/usr/bin/env python3
"""GitHub-only post-sync text evidence. This helper does not qualify timing or hardware."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid

MAX_FILE = 3_000_000
MAX_TOTAL = 96_000_000
MAX_FILES = 1024
ISE_IMAGE = 'sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8'
MAC = '08:00:27:68:c9:35'
OWNER_KEY = 'sd2snes.post-sync.owner'
TEXT_SUFFIXES = {'.txt', '.log', '.map', '.json', '.sha256', '.a65', '.i65', '.s',
                 '.asm', '.inc', '.h', '.c', '.mk', '.py', '.xml', '.yml', '.yaml',
                 '.d', '.sym', '.lst', '.list', '.cfg', '.hex', '.csv', '.tsv'}
SOFTWARE_BINARY_SUFFIXES = {'.bin', '.fnt', '.o65', '.o', '.ips', '.smc', '.rom',
                            '.sfc', '.png', '.bmp', '.gz', '.zx0', '.rle', '.a'}
FPGA_SUFFIXES = {'.bit', '.bi3', '.ncd', '.ngc', '.ngd', '.xdl', '.edn', '.edf',
                 '.jed', '.sof', '.pof', '.rbf', '.par', '.twr'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def describe(error):
    return type(error).__name__ + ': ' + str(error)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + '\n').encode('ascii')


def text_bytes(raw):
    require(b'\0' not in raw, 'NUL byte in text evidence')
    raw.decode('utf-8', errors='strict')
    return raw


def relative_name(name):
    require(isinstance(name, str) and name and not any(ord(c) < 32 for c in name), 'Invalid path characters')
    path = PurePosixPath(name)
    require(not path.is_absolute() and str(path) == name and
            all(p not in ('', '.', '..') for p in path.parts) and '\\' not in name and ':' not in name,
            'Unsafe relative path: ' + name)
    return name


def safe_path(path, must_exist=True):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'Symlink in path ancestry: ' + str(part))
    if must_exist:
        require(path.exists(), 'Missing path: ' + str(path))
    return path


def regular(path, unique=True):
    path = safe_path(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and (not unique or info.st_nlink == 1),
            'Not an allowed regular file: ' + str(path))
    return info


def digest_file(path, unique=True):
    before = regular(path, unique)
    sha = hashlib.sha256()
    blob = hashlib.sha1(('blob ' + str(before.st_size) + '\0').encode('ascii'))
    size = 0
    with Path(path).open('rb') as stream:
        while True:
            data = stream.read(1024 * 1024)
            if not data:
                break
            sha.update(data)
            blob.update(data)
            size += len(data)
    after = regular(path, unique)
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and size == after.st_size,
            'File changed while hashing: ' + str(path))
    return {'bytes': size, 'sha256': sha.hexdigest(), 'gitBlob': blob.hexdigest()}


def read_text(path):
    info = regular(path)
    require(info.st_size <= MAX_FILE, 'Per-file text bound exceeded: ' + str(path))
    raw = Path(path).read_bytes()
    require(len(raw) == info.st_size, 'Text size changed: ' + str(path))
    return text_bytes(raw)


def write_new(path, raw):
    path = safe_path(path, False)
    require(not path.exists(), 'Refusing to overwrite evidence: ' + str(path))
    require(len(raw) <= MAX_FILE, 'Per-file evidence bound: ' + str(path))
    text_bytes(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(path.parent)
    with path.open('xb') as stream:
        stream.write(raw)


def write_json(path, value):
    write_new(path, encoded(value))


def outside(path, root=None):
    path = safe_path(path, False)
    temp = safe_path(os.environ['RUNNER_TEMP'])
    require(temp == path.parent or temp in path.parents, 'Evidence must remain under RUNNER_TEMP')
    if root is None and os.environ.get('GITHUB_WORKSPACE'):
        root = Path(os.environ['GITHUB_WORKSPACE'])
    if root is not None:
        root = safe_path(root)
        require(path != root and root not in path.parents, 'Evidence must remain outside checkout')
    return path


def git(root, *args):
    result = subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(root), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)
    require(result.returncode == 0 and not result.stderr,
            'Read-only Git request failed: ' + repr(args) + ': ' + result.stderr.decode('utf-8', 'replace'))
    return result.stdout


def source_rows(root):
    root = safe_path(root)
    require(root.is_dir(), 'Checkout directory required')
    head = git(root, 'rev-parse', 'HEAD').decode('ascii').strip()
    require(re.fullmatch('[0-9a-f]{40}', head) is not None, 'Expected SHA1 Git repository')
    tree = git(root, 'ls-tree', '-rz', '--full-tree', 'HEAD')
    indexed = git(root, 'ls-files', '--stage', '-z')
    trees, indexes, index_lines, differences = {}, {}, [], []
    for record in tree.split(b'\0'):
        if not record:
            continue
        meta, raw_name = record.split(b'\t', 1)
        mode, kind, blob = meta.decode('ascii').split()
        name = relative_name(raw_name.decode('utf-8'))
        require(mode in ('100644', '100755') and kind == 'blob' and
                re.fullmatch('[0-9a-f]{40}', blob) is not None and name not in trees,
                'Unsupported or duplicate canonical source entry: ' + name)
        trees[name] = (mode, blob)
    for record in indexed.split(b'\0'):
        if not record:
            continue
        meta, raw_name = record.split(b'\t', 1)
        mode, blob, stage = meta.decode('ascii').split()
        name = relative_name(raw_name.decode('utf-8'))
        require(re.fullmatch('[0-9a-f]{40}', blob) is not None and stage in ('0', '1', '2', '3'), 'Malformed index record')
        index_lines.append(mode + ' ' + blob + ' ' + stage + '\t' + name + '\n')
        if stage != '0' or name in indexes:
            differences.append(dict(path=name, kind='unmerged-or-duplicate-index', mode=mode, gitBlob=blob, stage=stage))
        indexes[name] = (mode, blob)
    require(trees, 'Empty canonical source tree')
    for name in sorted(set(trees) | set(indexes)):
        if trees.get(name) != indexes.get(name):
            differences.append(dict(path=name, kind='index-differs-from-HEAD',
                                    canonical=trees.get(name), index=indexes.get(name)))
    rows = []
    for name in sorted(set(trees) | set(indexes)):
        mode, blob = trees.get(name, indexes.get(name))
        path = root / name
        try:
            record = digest_file(path)
            row = dict(path=name, mode=mode, **record)
            if record['gitBlob'] != blob:
                differences.append(dict(path=name, kind='worktree-bytes-differ', canonicalGitBlob=blob,
                                        actualGitBlob=record['gitBlob']))
                row['canonicalGitBlob'] = blob
            if bool(path.stat().st_mode & stat.S_IXUSR) != (mode == '100755'):
                differences.append(dict(path=name, kind='worktree-executable-mode-differs', canonicalMode=mode))
            rows.append(row)
        except BaseException as error:
            differences.append(dict(path=name, kind='worktree-read-failure', error=describe(error)))
            rows.append(dict(path=name, mode=mode, canonicalGitBlob=blob, readError=describe(error)))
    index_text = ''.join(sorted(index_lines)).encode('utf-8')
    return head, rows, index_text, differences


def snapshot(root, prefix):
    root, prefix = safe_path(root), outside(prefix, root)
    head, rows, index, differences = source_rows(root)
    data = {'schema': 'post-sync-source-snapshot-v1', 'head': head,
            'rootTree': git(root, 'rev-parse', 'HEAD^{tree}').decode('ascii').strip(),
            'productionVerilogTree': git(root, 'rev-parse', 'HEAD:verilog').decode('ascii').strip(),
            'logicalIndexSha256': hashlib.sha256(index).hexdigest(), 'files': rows,
            'differences': differences, 'unchangedCanonicalSourceAndIndex': not differences,
            'claim': 'Full tracked/index file inventory; only zero differences establishes canonical source and stage-zero index equality.'}
    write_json(str(prefix) + '.json', data)
    write_new(str(prefix) + '-index.txt', index)
    require(not differences, 'Source/index differences retained in the complete snapshot')
    return data

def validate_pins(data, root, fixture_path):
    require(isinstance(data, dict) and set(data) == {'schema', 'reviewedParent', 'productionVerilogTree',
            'fixturePath', 'changedPaths', 'files'}, 'Exact source-pin fixture fields required')
    require(data['schema'] == 'post-sync-source-pins-v1', 'Source-pin schema')
    fixture_name = fixture_path.relative_to(root).as_posix()
    require(relative_name(data['fixturePath']) == fixture_name, 'Fixture self-path mismatch')
    parent_line = git(root, 'rev-list', '--parents', '-n', '1', 'HEAD').decode('ascii').split()
    require(len(parent_line) == 2 and parent_line[1] == data['reviewedParent'], 'Exact single reviewed parent required')
    require(git(root, 'rev-parse', 'HEAD:verilog').decode('ascii').strip() == data['productionVerilogTree'],
            'Reviewed production Verilog tree differs')
    changed = [relative_name(x.decode('utf-8')) for x in
               git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', '-z', 'HEAD').split(b'\0') if x]
    require(isinstance(data['changedPaths'], list) and data['changedPaths'] == sorted(set(changed)),
            'Complete changed-path list differs from review')
    require(fixture_name in changed, 'The immutable source-pin fixture must be part of this commit')
    head, rows, index, differences = source_rows(root)
    require(not differences, 'Source/index differences prevent pin acceptance')
    actual = {row['path']: row for row in rows}
    expected = {}
    require(isinstance(data['files'], list), 'Source-pin file list')
    for row in data['files']:
        require(isinstance(row, dict) and set(row) == {'path', 'mode', 'bytes', 'sha256', 'gitBlob'}, 'Exact file pin fields')
        require(row['mode'] in ('100644','100755') and type(row['bytes']) is int and row['bytes'] >= 0 and
                isinstance(row['sha256'],str) and re.fullmatch('[0-9a-f]{64}',row['sha256']) is not None and
                isinstance(row['gitBlob'],str) and re.fullmatch('[0-9a-f]{40}',row['gitBlob']) is not None, 'Malformed source file pin')
        name = relative_name(row['path'])
        require(name != fixture_name and name not in expected and actual.get(name) == row,
                'Missing, duplicate or changed source pin: ' + name)
        expected[name] = row
    require(set(changed) - {fixture_name} <= set(expected), 'Every changed file except this self-referential fixture needs a reviewed pin')
    return {'schema': data['schema'], 'head': head, 'reviewedParent': data['reviewedParent'],
            'filesVerified': len(expected), 'fullTrackedFilesVerified': len(rows),
            'fixture': digest_file(fixture_path), 'fixtureSelfPinExcludedExplicitly': True}


def verify_pins(fixture):
    root = safe_path(git(Path.cwd(), 'rev-parse', '--show-toplevel').decode('utf-8').strip())
    fixture = safe_path(fixture)
    require(root in fixture.parents, 'Pin fixture must be tracked inside checkout')
    result = validate_pins(json.loads(read_text(fixture)), root, fixture)
    print(json.dumps(result, sort_keys=True))
    return result


def retain_capture(argv, prefix, timeout=7200, waiter=None, popen=None, after_spawn=None):
    """Own one client, never truncate streams, and retain process failure before raising.
    waiter/popen are hosted control seams; production uses Popen and wait directly.
    Container lifetime is separately proved by the typed Docker driver below.
    """
    prefix = outside(prefix, Path(os.environ['GITHUB_WORKSPACE']))
    require(isinstance(argv, list) and argv and all(isinstance(x, str) and '\0' not in x for x in argv), 'Argument vector')
    require(type(timeout) is int and 1 <= timeout <= 14400, 'Capture timeout bound')
    prefix.parent.mkdir(parents=True, exist_ok=True)
    state = {'schema': 'post-sync-command-capture-v1', 'argv': argv, 'cwd': str(Path.cwd()),
             'startedAt': now(), 'pid': None, 'spawnAttempted': False, 'clientReaped': False,
             'returncode': None, 'killAttempted': False, 'errors': [], 'streams': {},
             'rawStreamsTruncated': False, 'textEvidenceComplete': False,
             'descendantClosureClaim': False}
    write_json(str(prefix) + '.attempt.json', state)
    process, failure = None, None
    raw_paths = {kind: Path(str(prefix) + '.' + kind + '.raw') for kind in ('stdout', 'stderr')}
    try:
        with raw_paths['stdout'].open('xb') as stdout, raw_paths['stderr'].open('xb') as stderr:
            state['spawnAttempted'] = True
            factory = subprocess.Popen if popen is None else popen
            process = factory(argv, stdout=stdout, stderr=stderr, start_new_session=True)
            state['pid'] = process.pid
            if after_spawn is not None:
                after_spawn(process)
            state['returncode'] = process.wait(timeout=timeout) if waiter is None else waiter(process, timeout)
    except BaseException as error:
        failure = error
        state['errors'].append(describe(error))
    finally:
        if process is None:
            state['clientReaped'] = True  # No successfully returned owned client.
        else:
            try:
                still_running = process.poll() is None
            except BaseException as error:
                state['errors'].append('poll: ' + describe(error))
                failure = failure or error
                still_running = True
            if still_running:
                state['killAttempted'] = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except BaseException as error:
                    state['errors'].append('kill: ' + describe(error))
                    failure = failure or error
            try:
                state['returncode'] = process.wait(timeout=30)
                state['clientReaped'] = True
            except BaseException as error:
                state['errors'].append('reap: ' + describe(error))
                failure = failure or error
        for kind, raw_path in raw_paths.items():
            try:
                info = digest_file(raw_path)
                state['streams'][kind] = dict(info, raw=raw_path.name, text=None)
                raw = read_text(raw_path)  # Reject oversized/non-UTF8/NUL; original raw remains complete.
                text_path = Path(str(prefix) + '.' + kind + '.txt')
                write_new(text_path, raw)
                state['streams'][kind]['text'] = text_path.name
            except BaseException as error:
                state['errors'].append(kind + ': ' + describe(error))
                failure = failure or error
        state['finishedAt'] = now()
        state['textEvidenceComplete'] = (not state['errors'] and state['clientReaped'] and
                                         all(state['streams'].get(k, {}).get('text') for k in raw_paths))
        state['commandSucceeded'] = bool(state['textEvidenceComplete'] and state['returncode'] == 0)
        try:
            write_json(str(prefix) + '.status.json', state)
        except BaseException as error:
            failure = failure or error
    if failure is not None:
        raise failure
    return state


def capture(argv, prefix, timeout=7200):
    result = retain_capture(argv, prefix, timeout)
    print(json.dumps({'capture': str(prefix), 'returncode': result['returncode'],
                      'textEvidenceComplete': result['textEvidenceComplete']}, sort_keys=True))
    return result

def image_probe(reports):
    """Fixed software-image observation, executed only by the typed probe container.
    Reuses the same owned capture implementation for every version subprocess.
    """
    reports = outside(reports, Path(os.environ['GITHUB_WORKSPACE']))
    require(not reports.exists(), 'Fresh image-provenance directory required')
    reports.mkdir()
    native = ['xst','ngdbuild','map','par','trce','xdl','bitgen','coregen',
              'quartus_sh','quartus_map','quartus_fit','quartus_asm','quartus_sta']
    known = ['/opt/Xilinx','/opt/Xilinx14.7','/opt/ise14','/opt/quartus','/opt/quartus_lite','/home/ise']
    observation = dict(PATH=os.environ.get('PATH'), nativeToolLookups={name:shutil.which(name) for name in native},
        knownNativeDirectories={name:os.path.lexists(name) for name in known},
        claim='PATH/known-directory observation supporting the source-audited software image only; not an execution-absence proof')
    write_json(reports/'software-tool-observation.json', observation)
    require(not any(observation['nativeToolLookups'].values()) and not any(observation['knownNativeDirectories'].values()),
            'Native FPGA tools unexpectedly present in software image observation')
    copied = []
    def copy(source, name):
        raw = read_text(source)
        write_new(reports/relative_name(name), raw)
        copied.append(dict(source=str(source), path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    for label in ('cc65','asar'):
        base = Path('/opt')/label/'share/provenance'
        paths = walk_files(base)
        require(paths, 'Missing '+label+' provenance')
        for path in paths:
            copy(path, label+'/'+path.relative_to(base).as_posix())
    for name in ('source-version.txt','newlib-full-before-nano.sha256','newlib-full-preserved.txt','newlib-nano.sha256'):
        copy(Path('/opt/gcc-13.5/share')/name, 'gcc/'+name)
    for label in ('gcc-13.5','cc65','asar'):
        base = Path('/opt')/label/'share/licenses'
        for path in walk_files(base):
            copy(path, 'licenses/'+label+'/'+path.relative_to(base).as_posix())
    checks, errors = [], []
    manifests = ['/opt/cc65/share/provenance/tools.sha256','/opt/asar/share/provenance/tools.sha256',
                 '/opt/gcc-13.5/share/newlib-full-before-nano.sha256','/opt/gcc-13.5/share/newlib-nano.sha256']
    for manifest in manifests:
        names = set()
        for line in read_text(manifest).decode('utf-8').splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  (/[^\0]+)', line)
            require(match is not None and match[2] not in names, 'Unexpected image integrity manifest line')
            names.add(match[2])
            path = safe_path(match[2])
            require(str(path).startswith('/opt/'), 'Image manifest path outside /opt')
            # Installed native library hardlinks are hashed in place, never copied
            # into the safe text union. Evidence/source files still require nlink1.
            actual = digest_file(path, unique=False)
            row = dict(manifest=manifest,path=str(path),expectedSha256=match[1],**actual)
            row['matches'] = actual['sha256'] == match[1]
            checks.append(row)
            if not row['matches']:
                errors.append(str(path))
    write_json(reports/'integrity-checks.json',dict(files=checks,mismatches=errors))
    require(not errors, 'Installed tool/full-newlib/nano bytes differ from their image manifests')
    versions = {}
    for name, argv in [('gcc',['/opt/gcc-13.5/bin/arm-none-eabi-gcc','--version']),
                       ('ca65',['/opt/cc65/bin/ca65','--version']),
                       ('ld65',['/opt/cc65/bin/ld65','--version']),('asar',['/opt/asar/bin/asar','--version'])]:
        result = retain_capture(argv, reports/('version-'+name), 30)
        versions[name] = result['returncode']
        require(result['returncode'] == 0, 'Installed tool version command failed: '+name)
    write_json(reports/'probe-result.json',dict(copied=copied,versions=versions,
        integrityFilesVerified=len(checks),complete=True,qualification='Installed image provenance collection only'))

def container_spec(root, report_root, name, image, kind, family=None):
    require(re.fullmatch('[a-z][a-z0-9-]{0,62}', name) is not None, 'Bounded owned container name')
    require(re.fullmatch('sha256:[0-9a-f]{64}', image) is not None, 'Immutable image ID required')
    require(kind in ('menus', 'probe', 'coregen'), 'Fixed typed container operation')
    owner = uuid.uuid4().hex
    binds = [str(root) + ':/work']
    command = ['.github/scripts/build.sh', 'menus']
    entrypoint = '/bin/bash'
    if kind == 'probe':
        binds = [str(root) + ':/work:ro', str(report_root) + ':/reports']
        command = ['.github/scripts/post-sync-evidence.py', 'image-probe', '/reports/image-provenance']
        entrypoint = 'python3'
    elif kind == 'coregen':
        require(family in ('base', 'dsp') and image == ISE_IMAGE, 'Exact CoreGen family and image')
        binds.append(str(report_root) + ':/report')
        command = ['.github/scripts/validate-coregen-build-directory.sh']
    else:
        require(family is None, 'Menus does not accept a family')
    argv = ['docker', 'create', '--name', name, '--label', OWNER_KEY + '=' + owner,
            '--network', 'bridge' if kind == 'coregen' else 'none', '--user', '0:0',
            '--workdir', '/work', '--entrypoint', entrypoint]
    for bind in binds:
        argv += ['--volume', bind]
    if kind == 'coregen':
        argv += ['--mac-address', MAC, '--env', 'FAMILY=' + family]
    else:
        argv += ['--env', 'PYTHONDONTWRITEBYTECODE=1']
        if kind == 'probe':
            argv += ['--env', 'RUNNER_TEMP=/reports', '--env', 'GITHUB_WORKSPACE=/work']
    required_env = {'FAMILY':family} if kind == 'coregen' else {'PYTHONDONTWRITEBYTECODE':'1'}
    if kind == 'probe':
        required_env.update(RUNNER_TEMP='/reports', GITHUB_WORKSPACE='/work')
    argv += [image, *command]
    return dict(requiredEnv=required_env, name=name, owner=owner, image=image, kind=kind, family=family, binds=binds,
                entrypoint=entrypoint, command=command, createArgv=argv)


def validate_container(info, spec):
    require(isinstance(info, dict), 'Container inspect object')
    cid = info.get('Id')
    require(isinstance(cid, str) and re.fullmatch('[0-9a-f]{64}', cid) is not None, 'Complete owned container ID')
    config, host = info.get('Config', {}), info.get('HostConfig', {})
    require(info.get('Name') == '/' + spec['name'] and info.get('Image') == spec['image'] and
            config.get('Labels', {}).get(OWNER_KEY) == spec['owner'], 'Container identity/ownership mismatch')
    require(config.get('Entrypoint') == [spec['entrypoint']] and config.get('Cmd') == spec['command'] and
            config.get('WorkingDir') == '/work' and config.get('User') == '0:0' and not config.get('Tty') and
            not config.get('OpenStdin'), 'Owned container command/context differs')
    require(host.get('NetworkMode') == ('bridge' if spec['kind'] == 'coregen' else 'none') and
            sorted(host.get('Binds') or []) == sorted(spec['binds']) and
            host.get('Privileged') is False and not host.get('PidMode') and not host.get('IpcMode') == 'host',
            'Owned container isolation differs')
    for key, value in spec['requiredEnv'].items():
        require([item for item in config.get('Env',[]) if item.startswith(key+'=')] == [key+'='+value],
                'Exact declared container environment differs: '+key)
    if spec['kind'] == 'coregen':
        require(config.get('MacAddress') in (None, '', MAC), 'Conflicting requested ISE MAC')
        values = [value for value in config.get('Env', []) if value.startswith('FAMILY=')]
        require(values == ['FAMILY=' + spec['family']], 'Exact isolated IP family environment required')
    return cid


def validate_live_interface(info, spec):
    require(spec['kind'] == 'coregen', 'Live license interface only applies to CoreGen')
    validate_container(info, spec)
    require(info.get('State', {}).get('Running') is True, 'Live container state required for interface observation')
    endpoint = info.get('NetworkSettings', {}).get('Networks', {}).get('bridge', {})
    require(endpoint.get('MacAddress') == MAC, 'Actual live bridge endpoint MAC differs')
    return True

def list_owned(raw):
    lines = raw.decode('ascii').splitlines()
    require(len(lines) <= 1 and len(set(lines)) == len(lines) and
            all(re.fullmatch('[0-9a-f]{64}', line) is not None for line in lines), 'Unexpected owned container inventory')
    return lines


def inspect_one(raw):
    data = json.loads(raw)
    require(isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict), 'Exactly one Docker inspect record required')
    return data[0]


def cleanup_container(spec, command, saved_verified=None, writer=None):
    """Removal proceeds despite evidence-write failure; unknown ownership is never removed.
    command/writer are shared production/control seams, not a generic CLI executor.
    """
    result = dict(owner=spec['owner'], name=spec['name'], verified=[], removalAttempts=[],
                  removed=[], errors=[], stateWriteErrors=[], finalInventory=None, stoppedAndRemoved=False)
    known = {} if saved_verified is None else dict(saved_verified)
    query = ['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=' + OWNER_KEY + '=' + spec['owner']]
    try:
        ids = list_owned(command('cleanup-inventory', query))
    except BaseException as error:
        result['errors'].append('inventory: ' + describe(error))
        ids = list(known)
    for cid in ids:
        try:
            info = inspect_one(command('cleanup-inspect', ['docker', 'inspect', cid]))
            require(validate_container(info, spec) == cid, 'Cleanup ID differs')
            known[cid] = info
            result['verified'].append(cid)
            if writer is not None:
                try:
                    writer(cid, info)
                except BaseException as error:
                    result['stateWriteErrors'].append(describe(error))
        except BaseException as error:
            result['errors'].append('inspect: ' + describe(error))
        if cid not in known:
            continue
        # Docker IDs are immutable; an earlier complete inspection still proves
        # this exact ID belongs to this call if a later report/inspect fails.
        try:
            validate_container(known[cid], spec)
            result['removalAttempts'].append(cid)
            command('cleanup-remove', ['docker', 'rm', '--force', cid])
            result['removed'].append(cid)
        except BaseException as error:
            result['errors'].append('remove: ' + describe(error))
    try:
        result['finalInventory'] = list_owned(command('cleanup-final-inventory', query))
        result['stoppedAndRemoved'] = result['finalInventory'] == [] and set(known) <= set(result['removed'])
    except BaseException as error:
        result['errors'].append('final-inventory: ' + describe(error))
    return result


def run_container(root, report_root, spec, prefix, command_prefix):
    record = dict(spec=spec, startedAt=now(), createdId=None, nativeExit=None, clientExit=None,
                  operationErrors=[], nativeState=None, cleanup=None, success=False)
    write_json(report_root / (prefix + '-intent.json'), record)
    counter = 0
    known, failure = {}, None
    def command(label, argv):
        nonlocal counter
        counter += 1
        point = report_root / (prefix + '-control-%02d-' % counter + label)
        result = retain_capture(argv, point, timeout=180)
        require(result['returncode'] == 0, 'Docker control nonzero: ' + label)
        return read_text(str(point) + '.stdout.txt')
    try:
        initial = command('initial-inventory', ['docker', 'ps', '-aq', '--no-trunc', '--filter',
                                               'label=' + OWNER_KEY + '=' + spec['owner']])
        require(list_owned(initial) == [], 'New owner label already exists')
        created = command('create', spec['createArgv']).decode('ascii').strip()
        require(re.fullmatch('[0-9a-f]{64}', created) is not None, 'Create must return exactly one immutable ID')
        record['createdId'] = created
        info = inspect_one(command('before-inspect', ['docker', 'inspect', created]))
        require(validate_container(info, spec) == created, 'Created ID differs')
        known[created] = info
        require(info.get('State', {}).get('Status') == 'created' and not info['State'].get('Running'), 'Fresh unstarted container required')
        def live_ise(process):
            for attempt in range(20):
                live = inspect_one(command('live-inspect-%02d' % attempt, ['docker', 'inspect', created]))
                validate_container(live, spec)
                state = live.get('State', {})
                if state.get('Running'):
                    validate_live_interface(live, spec)
                    write_json(report_root / (prefix + '-live-interface.json'), live)
                    return
                require(state.get('Status') == 'created' and process.poll() is None,
                        'ISE exited before its actual interface could be observed')
                time.sleep(1)
            raise ValueError('Live ISE interface observation timed out')
        started = retain_capture(['docker', 'start', '--attach', created], report_root / command_prefix,
                                 timeout=7200, after_spawn=live_ise if spec['kind'] == 'coregen' else None)
        record['clientExit'] = started['returncode']
        info = inspect_one(command('after-inspect', ['docker', 'inspect', created]))
        validate_container(info, spec)
        record['nativeState'] = info['State']
        record['nativeExit'] = info['State'].get('ExitCode')
        require(info['State'].get('Status') == 'exited' and not info['State'].get('Running') and
                not info['State'].get('OOMKilled') and not info['State'].get('Error'), 'Owned container did not exit normally')
        require(type(record['nativeExit']) is int and record['clientExit'] == record['nativeExit'] == 0,
                'Client and native container must both exit zero')
    except BaseException as error:
        failure = error
        record['operationErrors'].append(describe(error))
    finally:
        try:
            record['cleanup'] = cleanup_container(spec, command, known,
                lambda cid, info: write_json(report_root / (prefix + '-cleanup-state.json'), info))
            clean = record['cleanup']
            require(clean['stoppedAndRemoved'] and not clean['errors'] and not clean['stateWriteErrors'],
                    'Owned container cleanup or retention failed')
        except BaseException as error:
            failure = failure or error
            record['operationErrors'].append('cleanup: ' + describe(error))
        record['finishedAt'] = now()
        record['success'] = failure is None
        try:
            write_json(report_root / (prefix + '-result.json'), record)
        except BaseException as error:
            failure = failure or error
    if failure is not None:
        raise failure
    return record


def typed_container(root, reports, name, kind, family=None):
    root, reports = safe_path(root), outside(reports, root)
    reports.mkdir(parents=True, exist_ok=True)
    require(Path.cwd().resolve() == root, 'Run typed driver from checkout root')
    image_name = 'sd2snes-ci:software' if kind == 'menus' else ISE_IMAGE
    initial = retain_capture(['docker', 'image', 'inspect', image_name], reports / (kind + '-image-before'), 180)
    require(initial['returncode'] == 0, 'Image inspect failed')
    image_info = inspect_one(read_text(reports / (kind + '-image-before.stdout.txt')))
    image = image_info.get('Id')
    require(isinstance(image, str) and re.fullmatch('sha256:[0-9a-f]{64}', image) is not None, 'Complete immutable image ID')
    if kind == 'coregen':
        require(image == ISE_IMAGE, 'Original pinned ISE image changed')
    error, results = None, []
    try:
        if kind == 'menus':
            probe_spec = container_spec(root, reports, name + '-probe', image, 'probe')
            results.append(run_container(root, reports, probe_spec, 'software-probe', 'software-probe-command'))
        spec = container_spec(root, reports, name, image, kind, family)
        results.append(run_container(root, reports, spec, kind + '-container', kind + '-command'))
    except BaseException as failure:
        error = failure
    finally:
        final_image = None
        try:
            after = retain_capture(['docker', 'image', 'inspect', image], reports / (kind + '-image-after'), 180)
            require(after['returncode'] == 0, 'Final image inspect failed')
            final_image = inspect_one(read_text(reports / (kind + '-image-after.stdout.txt')))
            require(final_image == image_info, 'Immutable inspected image metadata changed')
        except BaseException as failure:
            error = error or failure
        write_json(reports / (kind + '-result.json'), dict(image=image, kind=kind, family=family,
            operationResults=results, imageBeforeAfterEqual=final_image == image_info,
            accepted=error is None, error=None if error is None else describe(error),
            limits='Collection and owned lifecycle only; no native timing, IP-count, functionality or hardware acceptance'))
    if error is not None:
        raise error


def walk_files(root, checkout=False):
    root = safe_path(root)
    require(root.is_dir(), 'Evidence directory required')
    result = []
    def scan_error(error):
        # os.walk otherwise silently omits inaccessible directories.
        raise error
    for current, dirs, files in os.walk(root, followlinks=False, onerror=scan_error):
        current = Path(current)
        if checkout and current == root:
            dirs[:] = [name for name in dirs if name != '.git']
            files = [name for name in files if name != '.git']
        for name in dirs:
            path = current / name
            relative_name(path.relative_to(root).as_posix())
            safe_path(path)
            require(path.is_dir(), 'Special directory in tree: ' + str(path))
        for name in files:
            path = current / name
            relative_name(path.relative_to(root).as_posix())
            regular(path)
            result.append(path)
    return sorted(result)


def tracked_names(root):
    return {relative_name(x.decode('utf-8')) for x in
            git(root, 'ls-tree', '-rz', '--name-only', '--full-tree', 'HEAD').split(b'\0') if x}


def no_fpga_products(root, destination):
    root, destination = safe_path(root), outside(destination, root)
    tracked = tracked_names(root)
    products = []
    for path in walk_files(root, checkout=True):
        name = path.relative_to(root).as_posix()
        if path.suffix.lower() in FPGA_SUFFIXES and name not in tracked:
            products.append(dict(path=name, **digest_file(path)))
    result = dict(schema='post-sync-no-generated-fpga-products-v1', generatedProducts=products,
                  accepted=not products,
                  claim='No untracked known FPGA product suffixes in checkout; tracked source/input identity is separately snapshotted. This is not proof of absence of hidden execution.')
    write_json(destination, result)
    require(not products, 'Unexpected generated FPGA products; full identities retained')
    return result


def checked_raw_binding(path):
    name = path.name
    match = re.fullmatch(r'(.+)\.(stdout|stderr)\.raw', name)
    require(match is not None, 'Unknown raw evidence file: ' + str(path))
    prefix, stream = match.groups()
    status_path = path.parent / (prefix + '.status.json')
    state = json.loads(read_text(status_path))
    require(state.get('schema') == 'post-sync-command-capture-v1', 'Raw capture status schema')
    record = state.get('streams', {}).get(stream)
    require(isinstance(record, dict) and record.get('raw') == name and
            record.get('text') == prefix + '.' + stream + '.txt', 'Missing exact full text representation for raw stream')
    actual = digest_file(path)
    require(all(record.get(key) == actual[key] for key in ('bytes', 'sha256', 'gitBlob')), 'Raw stream differs from captured status')
    text_path = path.parent / record['text']
    text = read_text(text_path)
    require(len(text) == actual['bytes'] and hashlib.sha256(text).hexdigest() == actual['sha256'], 'Text stream is not a complete exact raw copy')
    require(state.get('rawStreamsTruncated') is False and state.get('clientReaped') is True,
            'Unproved raw capture completion or owned-client reap')
    return dict(raw=name, text=record['text'], status=status_path.name, **actual)


def bounded_union(entries):
    """All metadata, result and both manifest files count toward final exact bounds."""
    require(isinstance(entries, dict) and entries, 'Nonempty complete text union required')
    checked = {}
    for name, raw in sorted(entries.items()):
        relative_name(name)
        require(isinstance(raw, bytes) and len(raw) <= MAX_FILE, 'Per-file text union bound: ' + name)
        text_bytes(raw)
        checked[name] = raw
    require('reports.sha256' not in checked and 'report-manifest.json' not in checked, 'Reserved manifest destination')
    rows = [dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) for name, raw in checked.items()]
    manifest = encoded({'schema': 'post-sync-text-manifest-v1', 'files': rows,
                        'manifestSelfReferenceExcluded': True,
                        'boundsIncludeBothManifestFiles': True})
    checked['report-manifest.json'] = manifest
    hashes = ''.join(hashlib.sha256(raw).hexdigest() + '  ' + name + '\n'
                     for name, raw in sorted(checked.items())).encode('utf-8')
    checked['reports.sha256'] = hashes
    require(all(len(raw) <= MAX_FILE for raw in checked.values()), 'Generated manifest exceeds per-file bound')
    require(len(checked) <= MAX_FILES, 'Complete union file count exceeds inclusive bound')
    require(sum(len(raw) for raw in checked.values()) <= MAX_TOTAL, 'Complete union bytes exceed inclusive bound')
    return checked


def known_source_archive(name, pin):
    if name == '.github/docker/snescom.tar.xz':
        require(pin.get('sha256') == '7caade189572d4463c281b48d1bc68b5f9f7070c40b02e220565a6b48b18ae2a' and
                type(pin.get('bytes')) is int and pin['bytes'] > 0,
                'Prepared snescom source archive differs from the action fixed digest')
        return True
    return False

def bound_generated_text(path, pin):
    raw = read_text(path)
    blob = hashlib.sha1(('blob ' + str(len(raw)) + '\0').encode('ascii') + raw).hexdigest()
    require(len(raw) == pin['bytes'] and hashlib.sha256(raw).hexdigest() == pin['sha256'] and
            blob == pin['gitBlob'], 'Generated text changed between inventory and retention: ' + str(path))
    return raw


def collect(root, reports, output):
    root = None if root is None else safe_path(root)
    reports, output = outside(reports, root), outside(output, root)
    require(reports != output and reports not in output.parents and output not in reports.parents, 'Collection roots must be disjoint')
    require(not output.exists(), 'Collection output must be fresh')
    failure_path = output.parent / (output.name + '-collection-failure.json')
    entries, raw_bindings, inputs, binaries = {}, [], [], []
    accumulated = 0
    def add_entry(name, raw):
        nonlocal accumulated
        require(name not in entries, 'Duplicate complete-union destination')
        require(len(raw) <= MAX_FILE, 'Per-file union bound')
        accumulated += len(raw)
        require(accumulated <= MAX_TOTAL and len(entries) < MAX_FILES, 'Incomplete union already exceeds final bounds')
        entries[name] = raw
    try:
        for path in walk_files(reports):
            name = path.relative_to(reports).as_posix()
            if name.endswith('.raw'):
                raw_bindings.append(dict(directory=path.parent.relative_to(reports).as_posix(), **checked_raw_binding(path)))
                continue
            raw = read_text(path)
            key = 'reports/' + name
            require(key not in entries, 'Duplicate report union destination')
            add_entry(key, raw)
            inputs.append(dict(origin='reports', path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        if root is not None:
            tracked = tracked_names(root)
            for path in walk_files(root, checkout=True):
                name = path.relative_to(root).as_posix()
                if name in tracked:
                    continue
                pin = digest_file(path)
                suffix = path.suffix.lower()
                require(suffix not in FPGA_SUFFIXES, 'Unexpected FPGA product in software collection: ' + name)
                if known_source_archive(name, pin):
                    binaries.append(dict(path=name, role='pinned-snescom-source-archive', **pin))
                elif suffix in TEXT_SUFFIXES or path.name in ('Makefile', 'LICENSE', 'COPYING', 'COPYING3', 'COPYING.RUNTIME'):
                    key = 'generated/' + name
                    require(key not in entries, 'Duplicate generated union destination')
                    add_entry(key, bound_generated_text(path, pin))
                    inputs.append(dict(origin='generated', path=name, **pin))
                elif suffix in SOFTWARE_BINARY_SUFFIXES:
                    binaries.append(dict(path=name, **pin))
                else:
                    raise ValueError('Unknown generated output requires explicit review: ' + name)
        entries['collection-inputs.json'] = encoded(dict(inputs=inputs, rawBindings=raw_bindings,
                                                        softwareBinaryInventory=binaries,
                                                        binaryContentsIncluded=False))
        entries['collection-result.json'] = encoded(dict(schema='post-sync-text-collection-v1', complete=True,
            sourceGeneratedTextIncluded=root is not None, rawStreamsHaveExactTextRepresentations=True,
            bounds=dict(maxFileBytes=MAX_FILE, maxUnionBytes=MAX_TOTAL, maxFiles=MAX_FILES),
            qualification='Complete bounded text collection only; underlying native statuses remain separate.'))
        complete = bounded_union(entries)
        # No partial output directory is created until the entire union, including
        # metadata and manifests, has passed. Source/report inputs remain preserved.
        output.mkdir()
        for name, raw in complete.items():
            write_new(output / name, raw)
        for name, raw in complete.items():
            require(read_text(output / name) == raw, 'Published evidence bytes changed: ' + name)
        return dict(files=len(complete), bytes=sum(len(raw) for raw in complete.values()), output=str(output))
    except BaseException as error:
        rejection = dict(schema='post-sync-text-collection-failure-v1', complete=False, error=describe(error),
            reportRoot=str(reports), outputRoot=str(output), partialOutputDirectoryExists=output.exists(),
            originalReportRootPreserved=True, rawStreamsClipped=False,
            bounds=dict(maxFileBytes=MAX_FILE, maxUnionBytes=MAX_TOTAL, maxFiles=MAX_FILES),
            instruction='Retain original reports including raw streams on GitHub; never treat an incomplete or rejected union as accepted text evidence.')
        write_json(failure_path, rejection)
        raise


def self_test(destination=None):
    """Hosted only. Exercise the shared implementation, including real tiny clients.
    Deliberately invalid raw controls stay in a separate GitHub-only directory;
    they are never classified as accepted production text evidence.
    """
    chosen = Path(destination) if destination is not None else Path(os.environ['RUNNER_TEMP']) / ('post-sync-evidence-controls-' + uuid.uuid4().hex)
    temp = outside(chosen, Path(os.environ['GITHUB_WORKSPACE']))
    require(not temp.exists(), 'Hosted control evidence directory must be fresh')
    temp.mkdir(parents=True)
    rows, complete = [], False
    def control(label, operation, reject=False, expected=Exception):
        result = None
        try:
            result = operation()
        except BaseException as error:
            if not reject or not isinstance(error, expected):
                rows.append(dict(label=label, expectedRejection=reject, passed=False, error=describe(error)))
                raise
            rows.append(dict(label=label, expectedRejection=True, passed=True, error=describe(error)))
            return
        require(not reject, 'Negative control accepted: ' + label)
        rows.append(dict(label=label, expectedRejection=False, passed=True))
        return result
    def same(actual, expected, message):
        require(actual == expected, message)
    try:
        control('UTF8 complete', lambda: text_bytes('complete café\n'.encode()))
        control('NUL rejected', lambda: text_bytes(b'a\0b'), True, ValueError)
        control('invalid UTF8 rejected', lambda: text_bytes(b'\xff'), True, UnicodeError)
        for name in ('../escape', '/absolute', 'a\\b', 'a//b', 'a/./b', 'C:drive', 'a\nb'):
            control('unsafe path ' + repr(name), lambda n=name: relative_name(n), True, ValueError)
        control('nested ordinary path', lambda: relative_name('full/source-index.txt'))
        control('file boundary inclusive', lambda: bounded_union({'at-limit.txt': b'x' * MAX_FILE}))
        control('file overflow', lambda: bounded_union({'over.txt': b'x' * (MAX_FILE + 1)}), True, ValueError)
        control('final count inclusive', lambda: bounded_union({str(i)+'.txt': b'x' for i in range(MAX_FILES-2)}))
        control('generated manifests count too', lambda: bounded_union({str(i)+'.txt': b'x' for i in range(MAX_FILES-1)}), True, ValueError)
        control('reserved manifest path', lambda: bounded_union({'reports.sha256': b'a'}), True, ValueError)
        control('union invalid UTF8', lambda: bounded_union({'bad.txt': b'\xff'}), True, UnicodeError)
        control('union NUL', lambda: bounded_union({'bad.txt': b'\0'}), True, ValueError)
        control('large complete union', lambda: bounded_union({str(i)+'.txt': b'x' * MAX_FILE for i in range(31)}))
        control('manifests push raw96M over bound', lambda: bounded_union({str(i)+'.txt': b'x' * MAX_FILE for i in range(32)}), True, ValueError)
        link_target = temp / 'link-target.txt'
        write_new(link_target, b'original')
        linked = temp / 'linked.txt'
        linked.symlink_to(link_target)
        control('symlink file rejected', lambda: read_text(linked), True, ValueError)
        hard = temp / 'hard.txt'
        os.link(link_target, hard)
        control('hardlink file rejected', lambda: read_text(hard), True, ValueError)
        control('read-only installed hardlink hash supported', lambda: digest_file(hard, unique=False))
        prefix = temp / 'positive-command'
        result = control('actual tiny client stdout and stderr', lambda: retain_capture(
            [sys.executable, '-c', "import os;os.write(1,b'complete stdout\\n');os.write(2,b'complete stderr\\n')"], prefix, 30))
        same(result['returncode'], 0, 'Actual positive client native status')
        same(read_text(str(prefix)+'.stdout.txt'), b'complete stdout\n', 'Complete stdout')
        same(read_text(str(prefix)+'.stderr.txt'), b'complete stderr\n', 'Complete stderr')
        control('raw and text complete binding', lambda: checked_raw_binding(Path(str(prefix)+'.stdout.raw')))
        nonzero = temp / 'nonzero-command'
        result = control('actual nonzero exit retained without success', lambda: retain_capture(
            [sys.executable, '-c', "import os;os.write(2,b'failure details\\n');raise SystemExit(7)"], nonzero, 30))
        require(result['returncode'] == 7 and result['commandSucceeded'] is False and result['textEvidenceComplete'],
                'Nonzero must preserve full streams while remaining a failed command')
        spawn = temp / 'spawn-failure'
        control('actual missing executable spawn failure', lambda: retain_capture(
            [str(temp / 'does-not-exist')], spawn, 30), True, OSError)
        require(json.loads(read_text(str(spawn)+'.status.json'))['clientReaped'], 'No spawned client on spawn failure')
        def interrupted(process, timeout):
            raise KeyboardInterrupt('hosted injected interruption after Popen')
        interrupted_prefix = temp / 'interruption'
        control('BaseException kills and reaps actual client', lambda: retain_capture(
            [sys.executable, '-c', 'import time;time.sleep(60)'], interrupted_prefix, 30, waiter=interrupted), True, KeyboardInterrupt)
        state = json.loads(read_text(str(interrupted_prefix)+'.status.json'))
        require(state['killAttempted'] and state['clientReaped'] and state['returncode'] is not None,
                'Interrupted actual process not proved reaped')
        def timed_out(process, timeout):
            raise subprocess.TimeoutExpired('hosted owned-client control', timeout)
        timeout_prefix = temp / 'timeout'
        control('TimeoutExpired kills and reaps actual client', lambda: retain_capture(
            [sys.executable, '-c', 'import time;time.sleep(60)'], timeout_prefix, 1, waiter=timed_out), True, subprocess.TimeoutExpired)
        state = json.loads(read_text(str(timeout_prefix)+'.status.json'))
        require(state['killAttempted'] and state['clientReaped'], 'Timed-out actual process not reaped')
        def observer_failure(process):
            raise RuntimeError('hosted live-observer failure')
        observer_prefix = temp / 'observer-failure'
        control('live observer failure reaps actual client', lambda: retain_capture(
            [sys.executable, '-c', 'import time;time.sleep(60)'], observer_prefix, 30, after_spawn=observer_failure), True, RuntimeError)
        require(json.loads(read_text(str(observer_prefix)+'.status.json'))['clientReaped'], 'Observer failure left client unreaped')
        for label, expression, error_type, expected_bytes in (
                ('binary-output', "b'\\xff'", UnicodeError, 1),
                ('nul-output', "b'\\0'", ValueError, 1),
                ('oversized-output', "b'x' * 3000001", ValueError, MAX_FILE+1)):
            point = temp / label
            control('actual ' + label + ' rejected losslessly', lambda p=point, e=expression: retain_capture(
                [sys.executable, '-c', 'import os;os.write(1,'+e+')'], p, 30), True, error_type)
            require(digest_file(str(point)+'.stdout.raw')['bytes'] == expected_bytes,
                    'Rejected raw stream must remain complete')
            control(label + ' cannot enter safe union', lambda p=point: checked_raw_binding(Path(str(p)+'.stdout.raw')), True, ValueError)
        # Synthetic Docker controls call the exact shared ownership/removal code.
        spec = container_spec(Path(os.environ['GITHUB_WORKSPACE']), temp, 'hosted-control', 'sha256:'+'1'*64, 'menus')
        cid = '2'*64
        info = dict(Id=cid, Name='/'+spec['name'], Image=spec['image'],
            Config=dict(Labels={OWNER_KEY:spec['owner']}, Entrypoint=[spec['entrypoint']],
                        Cmd=spec['command'], WorkingDir='/work', User='0:0', Tty=False, OpenStdin=False,
                        Env=['PYTHONDONTWRITEBYTECODE=1']),
            HostConfig=dict(NetworkMode='none', Binds=spec['binds'], Privileged=False, PidMode='', IpcMode='private'))
        control('exact owned container identity', lambda: validate_container(info, spec))
        mutations = [('name', ('Name',), '/foreign'), ('image', ('Image',), 'sha256:'+'3'*64),
                     ('owner', ('Config','Labels',OWNER_KEY), 'foreign'),
                     ('command', ('Config','Cmd'), ['.github/scripts/build.sh','firmware']),
                     ('entrypoint', ('Config','Entrypoint'), ['/bin/sh']),
                     ('directory', ('Config','WorkingDir'), '/elsewhere'),
                     ('user', ('Config','User'), '1000:1000'),
                     ('tty', ('Config','Tty'), True),
                     ('bytecode environment', ('Config','Env'), []),
                     ('network', ('HostConfig','NetworkMode'), 'host'),
                     ('binds', ('HostConfig','Binds'), ['/etc:/work']),
                     ('privileged', ('HostConfig','Privileged'), True)]
        for label, keys, value in mutations:
            changed = json.loads(json.dumps(info))
            target = changed
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            control('wrong owned ' + label, lambda changed=changed: validate_container(changed, spec), True, ValueError)
        ip_spec = container_spec(Path(os.environ['GITHUB_WORKSPACE']),temp,'hosted-ip-control',ISE_IMAGE,'coregen','base')
        ip_info = json.loads(json.dumps(info))
        ip_info.update(Name='/'+ip_spec['name'],Image=ISE_IMAGE,State=dict(Running=True),
                       NetworkSettings=dict(Networks=dict(bridge=dict(MacAddress=MAC))))
        ip_info['Config'].update(Labels={OWNER_KEY:ip_spec['owner']},Entrypoint=[ip_spec['entrypoint']],
                                 Cmd=ip_spec['command'],Env=['FAMILY=base'],MacAddress=MAC)
        ip_info['HostConfig'].update(NetworkMode='bridge',Binds=ip_spec['binds'])
        control('fixed CoreGen live bridge interface and report bind',lambda:validate_live_interface(ip_info,ip_spec))
        changed_ip = json.loads(json.dumps(ip_info))
        changed_ip['NetworkSettings']['Networks']['bridge']['MacAddress'] = '00:00:00:00:00:00'
        control('actual wrong MAC rejected despite requested MAC',lambda:validate_live_interface(changed_ip,ip_spec),True,ValueError)
        changed_ip = json.loads(json.dumps(ip_info))
        changed_ip['State']['Running'] = False
        control('stopped inspect cannot prove live interface',lambda:validate_live_interface(changed_ip,ip_spec),True,ValueError)
        changed_ip = json.loads(json.dumps(ip_info))
        changed_ip['HostConfig']['Binds'] = [ip_spec['binds'][0]]
        control('missing CoreGen report bind rejected',lambda:validate_container(changed_ip,ip_spec),True,ValueError)
        changed_ip = json.loads(json.dumps(ip_info))
        changed_ip['Config']['Env'] = ['FAMILY=atari']
        control('wrong CoreGen family environment',lambda:validate_container(changed_ip,ip_spec),True,ValueError)
        control('no arbitrary CoreGen image',lambda:container_spec(Path(os.environ['GITHUB_WORKSPACE']),temp,
                'hosted-ip-control','sha256:'+'9'*64,'coregen','base'),True,ValueError)
        control('no arbitrary CoreGen family',lambda:container_spec(Path(os.environ['GITHUB_WORKSPACE']),temp,
                'hosted-ip-control',ISE_IMAGE,'coregen','atari'),True,ValueError)
        def cleanup_case(kind):
            active, calls = [cid], []
            def command(label, argv):
                calls.append(argv)
                if argv[1] == 'ps':
                    if kind == 'inventory-failure' and label == 'cleanup-inventory':
                        raise RuntimeError('injected inventory capture failure')
                    return (''.join(x+'\n' for x in active)).encode()
                if argv[1] == 'inspect':
                    if kind == 'inspect-failure':
                        raise RuntimeError('injected inspect capture failure')
                    selected = json.loads(json.dumps(info))
                    if kind == 'foreign-owner':
                        selected['Config']['Labels'][OWNER_KEY] = 'different-owner'
                    return encoded([selected])
                if argv[1:3] == ['rm','--force']:
                    require(argv[-1] == cid, 'Only exact owned ID may be removed')
                    if kind == 'remove-failure':
                        raise RuntimeError('injected remove failure')
                    active.clear()
                    return (cid+'\n').encode()
                raise ValueError('Unexpected synthetic Docker control')
            def writer(cid, observed):
                if kind == 'state-writer-failure':
                    raise OSError('injected receipt write failure')
            known = {cid:info} if kind in ('inspect-failure','inventory-failure') else None
            result = cleanup_container(spec, command, known, writer)
            if kind == 'success':
                require(result['stoppedAndRemoved'] and not result['errors'] and not result['stateWriteErrors'], 'Positive cleanup')
            elif kind in ('state-writer-failure','inspect-failure','inventory-failure'):
                require(cid in result['removed'] and result['stoppedAndRemoved'] and
                        (result['errors'] or result['stateWriteErrors']), 'Evidence failure must not skip proved-owned removal')
            else:
                require(not result['stoppedAndRemoved'] and result['errors'], 'Unresolved cleanup cannot pass')
                if kind == 'foreign-owner':
                    require(not result['removalAttempts'], 'Unknown ownership must never be removed')
            write_json(temp / ('cleanup-'+kind+'.json'), dict(result=result, commands=calls))
        for kind in ('success','state-writer-failure','inspect-failure','inventory-failure','remove-failure','foreign-owner'):
            control('shared cleanup '+kind, lambda kind=kind: cleanup_case(kind))
        control('multiple owned inventory rejected', lambda: list_owned((cid+'\n'+'4'*64+'\n').encode()), True, ValueError)
        control('incomplete container ID rejected', lambda: list_owned(b'1234\n'), True, ValueError)
        source_archive_pin = dict(bytes=1, sha256='7caade189572d4463c281b48d1bc68b5f9f7070c40b02e220565a6b48b18ae2a')
        control('exact action-pinned source archive classification',lambda:same(
            known_source_archive('.github/docker/snescom.tar.xz',source_archive_pin),True,'Exact known archive class'))
        control('no general xz exemption',lambda:same(
            known_source_archive('elsewhere/snescom.tar.xz',source_archive_pin),False,'Other archive must remain unknown'))
        control('source archive substituted hash rejected',lambda:known_source_archive(
            '.github/docker/snescom.tar.xz',dict(source_archive_pin,sha256='0'*64)),True,ValueError)
        # Real temporary Git files verify source-byte and index snapshots without builds.
        checkout = temp / 'source-checkout'
        checkout.mkdir()
        (checkout / 'verilog').mkdir()
        write_new(checkout / 'verilog/source.txt', b'canonical source\n')
        def git_mutate(*args):
            result = subprocess.run(['git','-c','user.name=Hosted evidence control',
                '-c','user.email=hosted-control@example.invalid','-C',str(checkout),*args],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            require(result.returncode == 0, 'Hosted temporary Git setup failed')
        git_mutate('init','--quiet')
        git_mutate('add','--','verilog/source.txt')
        git_mutate('commit','--quiet','-m','Synthetic source control')
        control('actual canonical source/index snapshot', lambda: snapshot(checkout, temp/'snapshot-good'))
        (checkout / 'verilog/source.txt').write_bytes(b'changed source\n')
        control('changed tracked bytes snapshot fails after retention', lambda: snapshot(checkout, temp/'snapshot-changed'), True, ValueError)
        changed = json.loads(read_text(temp/'snapshot-changed.json'))
        require(changed['differences'] and not changed['unchangedCanonicalSourceAndIndex'] and changed['files'], 'Full failed snapshot retained')
        git_mutate('add','--','verilog/source.txt')
        control('changed index snapshot fails after retention', lambda: snapshot(checkout, temp/'snapshot-index'), True, ValueError)
        git_mutate('reset','--hard','--quiet','HEAD')
        (checkout / 'verilog/source.txt').chmod(0o755)
        control('executable source mode drift', lambda: snapshot(checkout, temp/'snapshot-mode'), True, ValueError)
        (checkout / 'verilog/source.txt').chmod(0o644)
        parent = git(checkout,'rev-parse','HEAD').decode('ascii').strip()
        write_new(checkout/'pinned.txt',b'exact pinned source\n')
        pin = dict(path='pinned.txt',mode='100644',**digest_file(checkout/'pinned.txt'))
        pins = dict(schema='post-sync-source-pins-v1',reviewedParent=parent,
                    productionVerilogTree=git(checkout,'rev-parse','HEAD:verilog').decode('ascii').strip(),
                    fixturePath='source-pins.json',changedPaths=['pinned.txt','source-pins.json'],files=[pin])
        write_json(checkout/'source-pins.json',pins)
        git_mutate('add','--','pinned.txt','source-pins.json')
        git_mutate('commit','--quiet','-m','Synthetic exact pin contract')
        control('actual immutable source pin contract',lambda:validate_pins(pins,checkout,checkout/'source-pins.json'))
        for label in ('parent','verilog-tree','changed-list','missing-pin','duplicate-pin','sha','bytes','blob','extra-field','fixture-selfpath'):
            changed_pins = json.loads(json.dumps(pins))
            if label == 'parent': changed_pins['reviewedParent'] = '0'*40
            elif label == 'verilog-tree': changed_pins['productionVerilogTree'] = '0'*40
            elif label == 'changed-list': changed_pins['changedPaths'] = ['source-pins.json']
            elif label == 'missing-pin': changed_pins['files'] = []
            elif label == 'duplicate-pin': changed_pins['files'].append(dict(pin))
            elif label == 'sha': changed_pins['files'][0]['sha256'] = '0'*64
            elif label == 'bytes': changed_pins['files'][0]['bytes'] = True
            elif label == 'blob': changed_pins['files'][0]['gitBlob'] = '0'*40
            elif label == 'extra-field': changed_pins['waive'] = True
            else: changed_pins['fixturePath'] = 'other.json'
            control('source pin mutation '+label,lambda changed_pins=changed_pins:
                    validate_pins(changed_pins,checkout,checkout/'source-pins.json'),True,ValueError)
        # Actual collect logic: generated text and binary identity; no binary contents.
        report_input = temp/'clean-reports'
        report_input.mkdir()
        write_new(report_input/'evidence.txt', b'complete text\n')
        write_new(checkout/'generated.log', b'generated complete log\n')
        (checkout/'generated.bin').write_bytes(b'\0\xff')
        control('complete generated-text and binary-inventory union', lambda: collect(checkout, report_input, temp/'collected-good'))
        result = json.loads(read_text(temp/'collected-good/collection-inputs.json'))
        require(result['softwareBinaryInventory'][0]['path'] == 'generated.bin' and not result['binaryContentsIncluded'], 'Binary contents must remain GitHub-only')
        generated = checkout/'generated.log'
        original_generated = read_text(generated)
        generated_pin = digest_file(generated)
        control('generated text inventory binds exact retained bytes', lambda: bound_generated_text(generated, generated_pin))
        generated.write_bytes(b'changed after inventory hash\n')
        try:
            control('generated text changed after inventory rejected', lambda: bound_generated_text(
                generated, generated_pin), True, ValueError)
        finally:
            generated.write_bytes(original_generated)
        (checkout/'unexpected.unknown').write_bytes(b'unknown')
        control('unknown generated output explicit rejection', lambda: collect(checkout, report_input, temp/'collected-unknown'), True, ValueError)
        require((temp/'collected-unknown-collection-failure.json').is_file() and not (temp/'collected-unknown').exists(), 'Complete rejection without partial publication')
        (checkout/'unexpected.unknown').unlink()
        (checkout/'unexpected.bit').write_bytes(b'not real FPGA data')
        control('generated FPGA product observation fails', lambda: no_fpga_products(checkout,temp/'forbidden-fpga.json'), True, ValueError)
        control('FPGA product excluded from software evidence', lambda: collect(checkout, report_input, temp/'collected-fpga'), True, ValueError)
        (checkout/'unexpected.bit').unlink()
        control('no generated FPGA products', lambda: no_fpga_products(checkout,temp/'no-fpga.json'))
        control('generic reports-only collector', lambda: collect(None, report_input, temp/'reports-only'))
        # Exercise the real os.walk/collect path, independent of runner user/root
        # permissions, by injecting a scandir error only at the nested directory.
        scan_root = temp/'scan-failure-reports'
        scan_nested = scan_root/'unreadable'
        scan_nested.mkdir(parents=True)
        write_new(scan_root/'visible.txt', b'visible complete report\n')
        write_new(scan_nested/'hidden.txt', b'must not silently omit\n')
        original_scandir = os.scandir
        def denied_scandir(path):
            if Path(path) == scan_nested:
                raise PermissionError(13, 'Injected hosted traversal failure', str(path))
            return original_scandir(path)
        try:
            os.scandir = denied_scandir
            control('actual traversal error rejects incomplete union', lambda: collect(
                None, scan_root, temp/'collected-scan-failure'), True, PermissionError)
        finally:
            os.scandir = original_scandir
        failure = json.loads(read_text(temp/'collected-scan-failure-collection-failure.json'))
        require(not (temp/'collected-scan-failure').exists() and
                failure['originalReportRootPreserved'] and not failure['partialOutputDirectoryExists'] and
                'PermissionError' in failure['error'] and (scan_nested/'hidden.txt').is_file(),
                'Traversal rejection must retain source and explicit incomplete-union failure')
        complete = True
    finally:
        # Keep all intentionally invalid raw/native control evidence on GitHub.
        # Do not mix this control sandbox into the production safe-text union.
        write_json(temp/'self-test-results.json', dict(schema='post-sync-evidence-controls-v1', controls=rows,
            complete=complete and bool(rows) and all(row['passed'] for row in rows), rawControlRoot=str(temp),
            localExecutionPermitted=False, classification='Synthetic hosted controls only; no hardware or native timing qualification'))
    require(rows and all(row['passed'] for row in rows), 'Hosted evidence controls incomplete')
    print(json.dumps(dict(controls=len(rows), rawControlRoot=str(temp), result='all defined shared-path controls passed'), sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['snapshot','verify-pins','capture','menus','coregen',
                                       'no-fpga-products','collect','collect-reports','image-probe','--self-test','self-test'])
    # The explicit top-level --self-test form is handled before argparse, so it
    # cannot be mistaken for a script argument or a container operation.
    if len(sys.argv) > 1 and sys.argv[1] == '--self-test':
        require(len(sys.argv) in (2,3), '--self-test accepts at most one explicit fresh control directory')
        self_test(sys.argv[2] if len(sys.argv) == 3 else None)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == 'capture':
        require('--' in sys.argv[2:], 'capture requires an explicit argument-vector separator')
        split = sys.argv.index('--', 2)
        front = argparse.ArgumentParser(description='Capture one owned command')
        front.add_argument('mode')
        front.add_argument('prefix')
        front.add_argument('--timeout-seconds', type=int, default=7200)
        args = front.parse_args(sys.argv[1:split])
        result = capture(sys.argv[split+1:], args.prefix, args.timeout_seconds)
        code = result['returncode']
        return code if isinstance(code,int) and 0 <= code <= 125 else 1
    parser.add_argument('args', nargs='*')
    parsed = parser.parse_args()
    mode, args = parsed.mode, parsed.args
    counts = {'snapshot':2,'verify-pins':1,'menus':3,'coregen':4,'no-fpga-products':2,
              'collect':3,'collect-reports':2,'image-probe':1,'self-test':0}
    require(mode in counts and len(args) == counts[mode], 'Wrong argument count for fixed mode')
    if mode == 'snapshot':
        snapshot(*args)
    elif mode == 'verify-pins':
        verify_pins(*args)
    elif mode == 'menus':
        typed_container(args[0],args[1],args[2],'menus')
    elif mode == 'coregen':
        typed_container(args[0],args[1],args[3],'coregen',args[2])
    elif mode == 'image-probe':
        image_probe(*args)
    elif mode == 'no-fpga-products':
        no_fpga_products(*args)
    elif mode == 'collect':
        print(json.dumps(collect(*args),sort_keys=True))
    elif mode == 'collect-reports':
        print(json.dumps(collect(None,*args),sort_keys=True))
    else:
        self_test()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('post-sync-evidence failure: ' + describe(error), file=sys.stderr)
        raise
