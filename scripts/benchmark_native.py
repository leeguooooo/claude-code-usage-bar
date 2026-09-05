"""Offline acceptance for the built release bundle; no user's cache is read."""
import argparse
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    parser.add_argument('--ticks', type=int, default=5)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='cs-benchmark-') as directory:
        home = Path(directory)
        root = home / '.cache' / 'claude-statusbar'
        for i in range(16):
            p = root / 'sessions' / f's{i}'
            p.mkdir(parents=True)
            (p/'rendered.ansi').write_text(f'fixture-{i}\n')
            (p/'rendered.meta.json').write_text(json.dumps(dict(
                generated_at=time.time(), daemon_started_at=time.time()+1,
                stale_after_seconds=30, native_protocol=1, columns='', pid=os.getpid())))
        env = {**os.environ, 'HOME': str(home), 'COLUMNS':'',
               'CLAUDE_STATUSBAR_NO_UPDATE':'1'}
        cpu = []
        wall = []
        for tick in range(args.ticks):
            started = time.monotonic()
            for i in range(16):
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                t = time.monotonic()
                result = subprocess.run([str(binary), 'render'],
                    input=json.dumps({'session_id':f's{i}'}), text=True,
                    capture_output=True, env=env, timeout=5, check=True)
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                assert result.stdout == f'fixture-{i}\n', result.stdout
                cpu.append(1000*((after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime)))
                wall.append(1000*(time.monotonic()-t))
            if tick+1 < args.ticks:
                time.sleep(max(0, 1-(time.monotonic()-started)))
        p95 = sorted(cpu)[int(.95*len(cpu))]
        print(json.dumps(dict(sessions=16, ticks=args.ticks, invocations=len(cpu),
            cpu_p95_ms=round(p95,3), cpu_mean_ms=round(statistics.mean(cpu),3),
            wall_p95_ms=round(sorted(wall)[int(.95*len(wall))],3),
            estimated_one_core_percent_at_16hz=round(statistics.mean(cpu)*16/10,2)), indent=2))
        assert p95 < 10, f'cache-hit CPU p95 {p95:.2f}ms exceeds 10ms'


if __name__ == '__main__':
    main()
