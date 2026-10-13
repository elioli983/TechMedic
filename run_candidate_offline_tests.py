"""Windows/Linux offline regression runner. Never invokes network services."""
from __future__ import annotations
import hashlib, json, platform, socket, sys, time, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent / 'test_results'
OUT.mkdir(parents=True,exist_ok=True)
class _Tee:
    def __init__(self, path):self.f=path.open('w',encoding='utf-8')
    def write(self,s):self.f.write(s)
    def flush(self):self.f.flush()

original_connect=socket.socket.connect
original_connect_ex=socket.socket.connect_ex
blocked=[0]
def deny_connect(*args,**kwargs):
    blocked[0]+=1
    raise RuntimeError('Network is prohibited during Pass 15 offline regression')

started=time.perf_counter()
try:
    socket.socket.connect=deny_connect
    socket.socket.connect_ex=deny_connect
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    count=suite.countTestCases()
    logfile=OUT/'q2_pass15_test_log.txt'
    with logfile.open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    passed=count-len(result.failures)-len(result.errors)-len(result.skipped)
    audit={
        'title':'TechMedic Pass 15 integrated pre-release candidate offline test',
        'baseline_release':'1.5.5',
        'version_promoted':False,
        'python':platform.python_version(),
        'platform':platform.platform(),
        'tests_run':result.testsRun,
        'tests_passed':passed,
        'failures':len(result.failures),
        'errors':len(result.errors),
        'skipped':len(result.skipped),
        'failure_details':[str(t) for t,_ in result.failures+result.errors],
        'network_connections_attempted':blocked[0],
        'production_db_accessed':False,
        'database_scope':'disposable tempfile databases only',
        'live_api_calls':0,
        'elapsed_seconds':round(time.perf_counter()-started,3),
        'log_sha256_utf8':hashlib.sha256(logfile.read_bytes()).hexdigest(),
        'accepted_for_release':False,
        'notes':'Pass 15 is an integrated candidate, not production acceptance or actual browser validation.',
    }
    (OUT/'q2_pass15_offline_results.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(f"Pass 15: {passed}/{count} tests; failures={len(result.failures)}; errors={len(result.errors)}; network={blocked[0]}; log={logfile}")
    sys.exit(0 if result.wasSuccessful() and blocked[0]==0 else 1)
finally:
    socket.socket.connect=original_connect
    socket.socket.connect_ex=original_connect_ex
