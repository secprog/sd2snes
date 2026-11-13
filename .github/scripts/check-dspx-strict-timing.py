#!/usr/bin/env python3
"""GitHub-only strict DSPX report checks, including unscored negative slack."""
import copy
import json
import os
import re
import sys
from pathlib import Path

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("GitHub-hosted execution only")

MAP = ('map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 68 '
       '-register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy '
       '-pr b -bp -power off -o main_map.ncd main.ngd main.pcf')
PERIODS = {'TS_CLKIN': ('CLKIN', '24.01'), 'TS_SPI_SCK': ('SPI_SCK', '48.1'),
           'TS_SNES_SYSCLK': ('SNES_SYSCLK', '21.5'), 'TS_CLK21': ('CLK21', '96.04')}


def require(value, message):
    if not value:
        raise ValueError(message)


def validate(text):
    par, twr, pcf, mrp = (text[n] for n in ('par', 'twr', 'pcf', 'mrp'))
    require(len(re.findall(r'^par -w -ol high -xe c -t 68 main_map\.ncd main\.ncd main\.pcf\s*$', par, re.M)) == 1,
            'Original single PAR command and seed required')
    command = re.search(r'Command Line\s*:\s*(.*?)\s*Target Device', mrp, re.S)
    require(command is not None and ' '.join(command.group(1).split()) == MAP, 'Original MAP options required')
    require(len(re.findall(r'/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr', twr)) == 1,
            'Original single TRACE command required')
    require('All signals are completely routed.' in par, 'Complete routing required')
    scores = re.findall(r'Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)', par)
    require(scores == [('0', '0', '0', '0')], 'Exactly one all-zero PAR summary required')
    trace = re.findall(r'Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)', twr)
    require(trace == [('0', '0', '0', '0')], 'Exactly one all-zero TRACE summary required')
    slack_lines = [line for line in twr.splitlines() if line.lstrip().startswith('Slack')]
    require(bool(slack_lines), 'Expected actual slack records')
    slack = []
    for line in slack_lines:
        match = re.match(r'\s*Slack(?:\s+\([^)]*\))?:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))ns\b', line)
        require(match is not None, 'Unrecognized slack record')
        value = float(match.group(1))
        require(value >= 0, 'Negative displayed slack including unscored hold path')
        slack.append(value)
    jitter = re.findall(r'^SYSTEM_JITTER\s*=\s*([^;\r\n]+);', pcf, re.M)
    require(jitter == ['480 ps'], 'Original 480ps jitter required')
    period_rows = re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;', pcf)
    periods = {name: (group, freq) for name, group, freq in period_rows}
    require(len(period_rows) == 4 and periods == PERIODS, 'All four original period constraints required')
    require(set(re.findall(r'^(TS_\w+)\s*=', pcf, re.M)) == set(PERIODS), 'Unexpected timing specification')
    return dict(reportedTimingPassed=True, fullyRouted=True, parScore=0, setupScore=0, holdScore=0,
                componentSwitchingScore=0, traceErrors=0, displayedNegativeSlackPaths=0,
                displayedSlackRecords=len(slack), minimumDisplayedSlackNs=min(slack), periods=periods,
                systemJitterPs=480, unconstrainedIoSignoff=False, hardwareQualified=False,
                limits='Existing reported constraints only. Native exit and unconstrained I/O audit are separate.')


def self_test(output):
    positive = dict(par='par -w -ol high -xe c -t 68 main_map.ncd main.ncd main.pcf\n'
                   'All signals are completely routed.\nTiming Score: 0 (Setup: 0, Hold: 0, Component Switching Limit: 0)\n',
                   twr='/opt/ISE/trce -v 10 -n 10 -u 10\n-fastpaths main.ncd main.pcf -o main.twr\n'
                   'Slack: 0.000ns\nSlack (setup path): 0.206ns\nSlack (hold path): 0.179ns\n'
                   'Timing errors: 0  Score: 0  (Setup/Max: 0, Hold: 0)\n',
                   mrp='Command Line : ' + MAP + '\nTarget Device : xc3s400\n',
                   pcf='SYSTEM_JITTER = 480 ps;\n' + ''.join(
                       f'{name} = PERIOD TIMEGRP "{group}" {freq} MHz HIGH 50%;\n'
                       for name, (group, freq) in PERIODS.items()))
    cases = [('all three slack forms pass', positive, True)]
    mutations = [
        ('negative plain slack', 'twr', 'Slack: 0.000ns', 'Slack: -0.001ns'),
        ('negative setup slack', 'twr', 'Slack (setup path): 0.206ns', 'Slack (setup path): -0.206ns'),
        ('negative hold slack despite zero summary', 'twr', 'Slack (hold path): 0.179ns', 'Slack (hold path): -3.216ns'),
        ('unknown slack form', 'twr', 'Slack: 0.000ns', 'Slack changed: 0.000ns'),
        ('PAR nonzero', 'par', 'Setup: 0,', 'Setup: 1,'),
        ('PAR component switching nonzero', 'par', 'Component Switching Limit: 0', 'Component Switching Limit: 1'),
        ('TRACE nonzero', 'twr', 'Timing errors: 0', 'Timing errors: 1'),
        ('TRACE hold nonzero', 'twr', 'Hold: 0)', 'Hold: 1)'),
        ('incomplete routing', 'par', 'All signals are completely routed.', 'Not all signals routed.'),
        ('PAR seed changed', 'par', '-t 68', '-t 69'),
        ('MAP options changed', 'mrp', '-logic_opt on', '-logic_opt off'),
        ('TRACE options changed', 'twr', '-fastpaths', ''),
        ('jitter relaxed', 'pcf', '480 ps', '0 ps'),
        ('period relaxed', 'pcf', '96.04 MHz', '90.0 MHz'),
        ('period omitted', 'pcf', 'TS_SPI_SCK = PERIOD TIMEGRP "SPI_SCK" 48.1 MHz HIGH 50%;', ''),
    ]
    for name, key, old, new in mutations:
        require(positive[key].count(old) == 1, 'Unambiguous negative-control mutation')
        changed = copy.deepcopy(positive)
        changed[key] = changed[key].replace(old, new)
        cases.append((name, changed, False))
    for name, key, addition in (
            ('duplicate PAR summary', 'par', 'Timing Score: 0 (Setup: 0, Hold: 0, Component Switching Limit: 0)\n'),
            ('duplicate TRACE summary', 'twr', 'Timing errors: 0 Score: 0 (Setup/Max: 0, Hold: 0)\n'),
            ('duplicate jitter', 'pcf', 'SYSTEM_JITTER = 0 ps;\n'),
            ('extra timing specification', 'pcf', 'TS_extra = PERIOD TIMEGRP "extra" 1 MHz HIGH 50%;\n')):
        changed = copy.deepcopy(positive); changed[key] += addition
        cases.append((name, changed, False))
    rows = []
    for name, text, expected in cases:
        error = None
        try:
            validate(text)
            accepted = True
        except ValueError as failure:
            accepted, error = False, str(failure)
        rows.append(dict(name=name, expectedAcceptance=expected, accepted=accepted, error=error, passed=accepted == expected))
    Path(output).write_text(json.dumps(dict(controls=rows, passed=all(x['passed'] for x in rows)), indent=2)+'\n')
    require(all(x['passed'] for x in rows), 'Strict report parser adversarial controls failed')
    print(f"Passed {len(rows)} strict report parser controls, including real setup/hold slack syntax")


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        self_test(sys.argv[2])
    elif len(sys.argv) == 2:
        report = Path(sys.argv[1]); root = report/'native-reports'
        files = dict(par='main.par', twr='main.twr', pcf='main.pcf', mrp='main_map.mrp')
        result = validate({key: (root/name).read_text(encoding='utf-8') for key,name in files.items()})
        (report/'report-timing-validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    else:
        raise SystemExit('Usage: check-dspx-strict-timing.py REPORT | --self-test OUTPUT')
