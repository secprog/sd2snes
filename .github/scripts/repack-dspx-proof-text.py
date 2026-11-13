#!/usr/bin/env python3
"""GitHub-only lossless consolidation of a pinned successful text proof bundle."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

SOURCE_RUN = 43459552100
SOURCE_JOB = 132002508458
SOURCE_HEAD = '28385f4638a56ab406e4150719dafea813884d8e'
ARTIFACT = 14054559816
ZIP_BYTES = 6069583
ZIP_SHA = '0054a89ff0e0d031a2862bc12226f293ba0514976af293a8c91da898ff7f4c64'
PRODUCERS = ['gold','gate','bad-capture-strobe','bad-capture-data','bad-capture-lane',
             'bad-address-range','bad-address-word','bad-init-wr','bad-x-strobe','bad-x-address']
MERGE = sorted(['producer/'+name+'/preparation-console.log' for name in PRODUCERS]
               + ['consumer/'+name+'/preparation-console.log' for name in ['gold','gate','bad-data']])


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2)+'\n').encode('utf-8')


def repack(raw, metadata, jobs, output):
    need(len(raw)==ZIP_BYTES and sha(raw)==ZIP_SHA, 'Original artifact ZIP identity changed')
    need(metadata['id']==ARTIFACT and metadata['name']=='dspx-stack-address-proof'
         and metadata['size_in_bytes']==ZIP_BYTES and metadata['digest']=='sha256:'+ZIP_SHA
         and metadata['workflow_run']['id']==SOURCE_RUN
         and metadata['workflow_run']['head_sha']==SOURCE_HEAD
         and not metadata['expired'], 'Fresh original artifact API identity changed')
    matching=[job for job in jobs['jobs'] if job['id']==SOURCE_JOB]
    need(len(matching)==1 and matching[0]['status']=='completed' and matching[0]['conclusion']=='success',
         'Original proof job is not successful')
    need(all(step['conclusion']=='success' for step in matching[0]['steps']), 'Original proof step did not succeed')
    files={};rows=[];seen=set();total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            name=info.filename;path=PurePosixPath(name);mode=(info.external_attr>>16)&0xffff
            need(name and not path.is_absolute() and '\\' not in name and ':' not in name
                 and all(part not in ('.','..') for part in path.parts), 'Unsafe original ZIP path')
            need(not stat.S_ISLNK(mode), 'Original ZIP symlink')
            if info.is_dir():
                continue
            need(stat.S_IFMT(mode) in (0,stat.S_IFREG), 'Original ZIP special file')
            need(name.casefold() not in seen, 'Duplicate original ZIP path');seen.add(name.casefold())
            need(path.suffix.lower() not in ('.bit','.bin','.ngc','.ncd','.xdl','.rom','.exe','.dll','.so','.tar','.zip','.ngd'), 'Non-text design product in original bundle')
            total+=info.file_size
            need(info.file_size<=3000000 and total<=112000000, 'Original text byte bounds exceeded')
            data=archive.read(info)
            data.decode('utf-8');need(b'\0' not in data, 'Non-text original file')
            files[name]=data;rows.append(dict(path=name,bytes=len(data),sha256=sha(data)))
    need(len(files)==1033 and total==96101866, 'Exact original proof file inventory changed')
    need(len(MERGE)==13 and all(name in files for name in MERGE), 'Missing fixed console consolidation inputs')
    bundle=[dict(path=name,bytes=len(files[name]),sha256=sha(files[name]),content=files[name].decode('utf-8')) for name in MERGE]
    for name in MERGE:
        del files[name]
    for name in ['repacked-console-bundle.json','repack-original-files.json','repack-receipt.json']:
        need(name not in files, 'Repack output collision')
    files['repacked-console-bundle.json']=encode(bundle)
    files['repack-original-files.json']=encode(rows)
    files['repack-receipt.json']=encode(dict(sourceRun=SOURCE_RUN,sourceJob=SOURCE_JOB,sourceHead=SOURCE_HEAD,
         artifact=ARTIFACT,sourceZipBytes=len(raw),sourceZipSha256=sha(raw),originalFileCount=1033,
         originalBytes=total,mergedFiles=MERGE,allOriginalBytesPreserved=True,
         change='Only13 exact preparation console copies consolidated into one reversible UTF8 JSON array; all other original files byte-identical. No proof/native command rerun, no gate changed.',
         outputFileCount=len(files)+1,localBounds=dict(files=1024,fileBytes=3000000,totalBytes=112000000)))
    need(len(files)<=1024 and sum(map(len,files.values()))<=112000000
         and all(len(data)<=3000000 for data in files.values()), 'Repacked local text bounds exceeded')
    output.mkdir(parents=True,exist_ok=False)
    for name,data in sorted(files.items()):
        path=output.joinpath(*PurePosixPath(name).parts);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print(json.dumps(dict(originalFiles=1033,outputFiles=len(files),originalBytes=total,
                         outputBytes=sum(map(len,files.values())),allOriginalBytesPreserved=True),indent=2))


if __name__ == '__main__':
    need(len(sys.argv)==5, 'Usage: SOURCE_ZIP API_DIRECTORY OUTPUT EXPECTED_SOURCE_HEAD')
    need(sys.argv[4]==SOURCE_HEAD, 'Caller source head changed')
    api=Path(sys.argv[2])
    repack(Path(sys.argv[1]).read_bytes(),json.loads((api/'artifact.json').read_text()),
           json.loads((api/'jobs.json').read_text()),Path(sys.argv[3]))
