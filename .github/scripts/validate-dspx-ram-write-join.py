#!/usr/bin/env python3
"""GitHub-only complete RAM write/control/scan combinational proof and strict native timing.
Preserves the full original bitwise reconvergent DP expression and every state/data/interface.
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
FRAGMENTS = {'baseline': '4d0199bf639629284546858b2b92abcd840b48a9', 'path': 'verilog/sd2snes_dsp/upd77c25.v', 'goldSha256': '8e82c280d3b69fd273ffd468b5de4b06fd82fbf3a352b9948d70ef214b9253ff', 'gateSha256': '6752b72b69997b6005b6db8aef29fd1d8500466af16b82ac4a32cfe8e2d80e96', 'original': 'wire ram_web = reg_we_rising & DP_enable & ~ss_regwin & ~ss_ctrl;', 'replacement': "`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_RAM_WRITE_JOIN_BEGIN\nwire ram_web;\nwire ram_write_ctrl_block = ss_window_en & (DP_ADDR == 11'h7ff);\nwire ram_write_scan_block = ss_window_en & ss_frozen & (DP_ADDR[10:8] == 3'b110);\ndspx_ram_write_join ram_write_join_lut(\n  .strobe(reg_we_rising), .dp_enabled(DP_enable),\n  .scan_block(ram_write_scan_block), .ctrl_block(ram_write_ctrl_block), .write_enable(ram_web)\n);\n// DSPX_RAM_WRITE_JOIN_END\n`else\nwire ram_web = reg_we_rising & DP_enable & ~ss_regwin & ~ss_ctrl;\n`endif\n`else\nwire ram_web = reg_we_rising & DP_enable & ~ss_regwin & ~ss_ctrl;\n`endif", 'body': "// DSPX_RAM_WRITE_JOIN_BEGIN\nwire ram_web;\nwire ram_write_ctrl_block = ss_window_en & (DP_ADDR == 11'h7ff);\nwire ram_write_scan_block = ss_window_en & ss_frozen & (DP_ADDR[10:8] == 3'b110);\ndspx_ram_write_join ram_write_join_lut(\n  .strobe(reg_we_rising), .dp_enabled(DP_enable),\n  .scan_block(ram_write_scan_block), .ctrl_block(ram_write_ctrl_block), .write_enable(ram_web)\n);\n// DSPX_RAM_WRITE_JOIN_END", 'helpers': '// DSPX_RAM_WRITE_HELPER_BEGIN\n// Keep the complete original bitwise expression, including reconvergent X\n// behavior. The independent address blockers are ready before the DP select.\n(* LUT_MAP="yes" *)\nmodule dspx_ram_write_join(input strobe, dp_enabled, scan_block, ctrl_block, output write_enable);\nassign write_enable = strobe & dp_enabled & ~(dp_enabled & scan_block) & ~(dp_enabled & ctrl_block);\nendmodule\n// DSPX_RAM_WRITE_HELPER_END', 'tail': '\n`ifdef MK2\n`ifdef DSP_COMP\n// DSPX_RAM_WRITE_HELPER_BEGIN\n// Keep the complete original bitwise expression, including reconvergent X\n// behavior. The independent address blockers are ready before the DP select.\n(* LUT_MAP="yes" *)\nmodule dspx_ram_write_join(input strobe, dp_enabled, scan_block, ctrl_block, output write_enable);\nassign write_enable = strobe & dp_enabled & ~(dp_enabled & scan_block) & ~(dp_enabled & ctrl_block);\nendmodule\n// DSPX_RAM_WRITE_HELPER_END\n`endif\n`endif\n', 'ctrl': "assign ss_ctrl = ss_window_en & DP_enable & (DP_ADDR == 11'h7ff);", 'scan': "assign ss_regwin = ss_window_en & DP_enable & ss_frozen & (DP_ADDR[10:8] == 3'b110);", 'sourceScope': 'Only MK2+DSP_COMP RAM port-B write-enable expression shape; original ss_ctrl/ss_regwin outputs, address/window/freeze guards, every state/data/interface and all other source bytes remain unchanged.'}

HEADER="""module ram_write_model(input reg_we_rising,DP_enable,ss_window_en,ss_frozen,
input [10:0] DP_ADDR,output [2:0] observed);
wire ss_ctrl,ss_regwin;
"""
TRAILER="""
assign observed = {ss_ctrl,ss_regwin,ram_web};
endmodule
"""
def compile_model(text,output,name):
    output.mkdir()
    (output/'model.v').write_text(text)
    run(['iverilog','-g2012','-tnull','-s','ram_write_model','model.v'],output,'syntax')
    script=('read_verilog -sv -formal model.v\nhierarchy -check -top ram_write_model\nflatten\n'
            'proc -ifx -noopt\nsetundef -undriven -undef\nopt_clean\ncheck -assert\nwrite_json flat.json\n'
            'rename -top '+name+'\nwrite_json compiled.json\n')
    (output/'prepare.ys').write_text(script);run(['yosys','-s','prepare.ys'],output,'preparation')
    design=json.loads((output/'compiled.json').read_text());need(set(design['modules'])=={name},'Unexpected compiled model')
    m=design['modules'][name]
    need(set(m['ports'])=={'reg_we_rising','DP_enable','ss_window_en','ss_frozen','DP_ADDR','observed'},'Complete actual control interface missing')
    need(sum(len(p['bits']) for p in m['ports'].values() if p['direction']=='input')==15 and len(m['ports']['observed']['bits'])==3,'Control widths changed')
    need(not any('init' in n.get('attributes',{}) for n in m['netnames'].values()),'Unexpected initialization')
    need(all(c['type'].startswith('$') and not any(t in c['type'].lower() for t in ['ff','latch','mem']) and c['type'] not in ['$anyseq','$anyconst','$assume','$assert'] for c in m['cells'].values()),'Hidden state, assumptions or blackbox')
    save(output/'model-audit.json',dict(module=name,inputBits=15,outputBits=3,stateBits=0,noAssumptions=True,actualFullControlInputs=True))

def prove_pair(gold,gate,output,mode,expected):
    output.mkdir();flags='-set-def-inputs ' if mode=='binary' else ''
    script=('read_json '+str(gold/'compiled.json')+'\nread_json '+str(gate/'compiled.json')+'\n'
            'miter -equiv -make_assert -make_outputs -make_outcmp gold gate miter\n'
            'hierarchy -check -top miter\nflatten -wb\nopt_clean\ncheck -assert\nwrite_json miter.json\n'
            'sat -verify -enable_undef '+flags+'-prove-asserts -show-inputs -show-outputs -dump_json counterexample.json -timeout 180\n')
    (output/'prove.ys').write_text(script);code,log=run(['yosys','-s','prove.ys'],output,'proof',expected=None)
    m=json.loads((output/'miter.json').read_text())['modules']['miter']
    actual={k[3:]:v for k,v in m['ports'].items() if v['direction']=='input' and k.startswith('in_')}
    need(set(actual)=={'reg_we_rising','DP_enable','ss_window_en','ss_frozen','DP_ADDR'} and sum(len(v['bits']) for v in actual.values())==15,'Live actual inputs omitted')
    need(any(c['type']=='$eqx' and c['connections']['Y']==m['ports']['cmp_observed']['bits'] for c in m['cells'].values()),'Strict X comparison missing')
    need(any(c['type']=='$assert' for c in m['cells'].values()) and not any(c['type']=='$assume' or any(t in c['type'].lower() for t in ['ff','latch','mem']) for c in m['cells'].values()),'Assertions/assumptions/state changed')
    if expected:
        need(code==0 and 'SAT proof finished - no model found: SUCCESS!' in log,'Complete RAM write control not equivalent')
    else:
        need(code!=0 and 'SAT proof finished - model found: FAIL!' in log and (output/'counterexample.json').is_file(),'Bad-source control lacks actual counterexample')
    row=dict(mode=mode,expectedPass=expected,actualExit=code,inputPorts=5,inputBits=15,outputBits=3,stateBits=0,strictX=True,noAssumptions=True,noCycleSkips=True)
    save(output/'proof-review.json',row);return row

def proof(output):
    output.mkdir(parents=True,exist_ok=True)
    original=subprocess.check_output(['git','show',BASE+':'+SOURCE]).decode();gate=Path(SOURCE).read_text()
    need(sha(original.encode())==FRAGMENTS['goldSha256'] and sha(gate.encode())==FRAGMENTS['gateSha256'],'Full UPD source identity changed')
    need(once(original,FRAGMENTS['original'],FRAGMENTS['replacement'])+FRAGMENTS['tail']==gate,'Change not limited to exact RAM write expression and combinational helper')
    need(subprocess.check_output(['git','diff','--name-only',BASE,'HEAD','--','verilog']).decode().splitlines()==[SOURCE],'Unreviewed production edit')
    for text in [original,gate]:
        need(text.count(FRAGMENTS['ctrl'])==text.count(FRAGMENTS['scan'])==1,'Actual ss_ctrl/regwin outputs changed')
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
        need(FRAGMENTS['body'] in paths[1].read_text() and FRAGMENTS['helpers'] in paths[1].read_text(),'Actual preprocessed helper/body missing')
        shared=FRAGMENTS['ctrl']+'\n'+FRAGMENTS['scan']+'\n'
        golden=HEADER+FRAGMENTS['original']+'\n'+shared+TRAILER
        candidate=HEADER+FRAGMENTS['body']+'\n'+shared+TRAILER+FRAGMENTS['helpers']+'\n'
        folder=output/('config-'+str(index));folder.mkdir()
        compile_model(golden,folder/'gold','gold');compile_model(candidate,folder/'gate','gate')
        for mode in ['binary','xstate']:
            results.append(prove_pair(folder/'gold',folder/'gate',folder/mode,mode,True))
        if first is None:first=(folder/'gold',candidate)
    gold,candidate=first
    full='assign write_enable = strobe & dp_enabled & ~(dp_enabled & scan_block) & ~(dp_enabled & ctrl_block);'
    ctrl="wire ram_write_ctrl_block = ss_window_en & (DP_ADDR == 11'h7ff);"
    scan="wire ram_write_scan_block = ss_window_en & ss_frozen & (DP_ADDR[10:8] == 3'b110);"
    mutations=[
        ('missing-strobe',full,full.replace('strobe & ','')),
        ('missing-dp',full,full.replace('strobe & dp_enabled &','strobe &')),
        ('missing-control-window',full,'assign write_enable = strobe & dp_enabled & ~(dp_enabled & scan_block);'),
        ('missing-scan-window',full,'assign write_enable = strobe & dp_enabled & ~(dp_enabled & ctrl_block);'),
        ('wrong-control-address',ctrl,ctrl.replace("11'h7ff","11'h7fe")),
        ('wrong-scan-bank',scan,scan.replace("3'b110","3'b101")),
        ('missing-freeze',scan,scan.replace(' & ss_frozen','')),
        ('missing-window-enable',ctrl,ctrl.replace('ss_window_en & ','')),
        ('x-dp-absorption',full,'assign write_enable = strobe & dp_enabled & ~scan_block & ~ctrl_block;'),
        ('x-control-address',ctrl,ctrl.replace(" == 11'h7ff"," === 11'h7ff")),
        ('x-strobe-guard',full,full.replace('strobe &',"(strobe !== 1'b0) &"))]
    for label,before,after in mutations:
        folder=output/label;compile_model(once(candidate,before,after),folder,'gate')
        results.append(prove_pair(gold,folder,output/(label+'-binary'),'binary',label.startswith('x-')))
        if label.startswith('x-'):results.append(prove_pair(gold,folder,output/(label+'-xstate'),'xstate',False))
    save(output/'preprocessor-configurations.json',configs);save(output/'full-control-results.json',results)
    sums=[sha(p.read_bytes())+'  '+p.relative_to(output).as_posix() for p in sorted(output.rglob('*')) if p.is_file() and p.name!='SHA256SUMS']
    (output/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
    (output/'verified.txt').write_text('Complete15input/3output actual RAM write,control-window andscan-window functions proved forbinary andunrestrictedX in4targetconfigs;11actualbadsourcecounterexamples includebinary-equivalentwrongXabsorption. No source state/reset/clock/data/interface change. Otherconfigs unchanged. No wholemapped/timing/hardware claim.\n')

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
    families = ['ram_write_join_lut']
    bindings = {family: [] for family in families}
    for component, body in instances.items():
        for slot, logical, equation in re.findall(r'\b(F|G):([^:\s]+):#LUT:([^\s]+)', body):
            for family in families:
                prefix = 'snes_dspx/' + family
                if logical == prefix or logical.startswith(prefix + '/'):
                    bindings[family].append(dict(component=component, slot=slot, logical=logical, equation=equation))
    save(output / 'ram-write-lut-observed-bindings.json', bindings)
    selected = {row['component'] for rows in bindings.values() for row in rows}
    selected_nets = {name for name, body in nets.items() if any(comp in selected for _, comp, _ in PIN.findall(body))}
    for name in selected_nets:
        selected.update(comp for direction, comp, _ in PIN.findall(nets[name]) if direction == 'outpin' and comp in instances)
    body = '\n\n'.join([instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]) + '\n'
    need(len(selected) <= 400 and len(selected_nets) <= 700 and len(body.encode()) <= 3000000, 'Bounded neighborhood exceeded; no truncation')
    (output / 'ram-write-luts-raw.txt').write_text(body)
    save(output / 'ram-write-physical-index.json', dict(sourceBytes=len(raw), sourceSha256=sha(raw), totalInstances=len(instances),
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
    for unit in ['dspx_ram_write_join']:
        need(property_seen(syr, unit), 'Combinational LUT_MAP not recognized: ' + unit)
    physical = json.loads((report / 'physical/ram-write-physical-index.json').read_text())
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
    property_cases=[('bare unit','Set property "LUT_MAP = yes" for unit <dspx_ram_write_join>.',True),
                    ('dot parameter','Set property "LUT_MAP = yes" for unit <dspx_ram_write_join.1>.',True),
                    ('underscore parameter','Set property "LUT_MAP = yes" for unit <dspx_ram_write_join_2>.',True),
                    ('property disabled','Set property "LUT_MAP = no" for unit <dspx_ram_write_join.1>.',False),
                    ('unrelated unit','Set property "LUT_MAP = yes" for unit <other.1>.',False)]
    property_rows=[dict(name=name,expected=expected,observed=property_seen(text,'dspx_ram_write_join'),passed=property_seen(text,'dspx_ram_write_join')==expected) for name,text,expected in property_cases]
    save(output/'property-controls.json',property_rows)
    need(all(x['passed'] for x in property_rows),'Actual parameterized property controls failed')

    families = ['ram_write_join_lut']
    fixture = '\n'.join('inst "part' + str(i) + '" "SLICEL", cfg " F:snes_dspx/' + family + ':#LUT:D=A1 ";' for i, family in enumerate(families)) + '\n'
    cases = [('one actual helper LUT', fixture, True),
             ('missing helper', fixture.replace('ram_write_join_lut', 'other'), False),
             ('FF is not LUT', fixture.replace('F:snes_dspx/ram_write_join_lut:#LUT:D=A1', 'FFX:snes_dspx/ram_write_join_lut:#FF'), False),
             ('duplicate instance', fixture + 'inst "part0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture + 'net "n";\nnet "n";\n', False),
             ('incomplete record', fixture + 'net "incomplete"', False),
             ('two physical aliases', fixture + 'inst "extra" "SLICEL", cfg " F:snes_dspx/ram_write_join_lut/x:#LUT:D=A1 ";\n', False),
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
