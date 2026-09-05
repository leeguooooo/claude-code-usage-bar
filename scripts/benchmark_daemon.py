"""Isolated 16-session release-bundle integration. Never touches live sessions."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='cs-daemon-bench-') as directory:
        home = Path(directory)
        repo = home/'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        root = home/'.cache'/'claude-statusbar'
        cfg = home/'.claude'
        cfg.mkdir()
        (cfg/'claude-statusbar.json').write_text(json.dumps(dict(
            show_language=False, show_balance=False, show_party=False,
            show_mode=False, show_ip_risk=False, show_fp_risk=False,
            auto_upgrade=False)))
        env = {**os.environ, 'HOME':str(home), 'COLUMNS':'',
               'CLAUDE_STATUSBAR_NO_UPDATE':'1', 'CS_API_MODE':'on'}
        payloads = []
        for i in range(16):
            data = json.dumps(dict(session_id=f's{i}',
                model={'id':'fixture', 'display_name':'Fixture'},
                workspace={'current_dir':str(repo)},
                context_window={'used_percentage':10, 'context_window_size':200000},
                _cs_env={'CS_API_MODE':'on'})).encode()
            payloads.append(data)
            p = root/'sessions'/f's{i}'
            p.mkdir(parents=True)
            (p/'last_stdin.json').write_bytes(data)
        daemon = subprocess.Popen([str(binary), 'daemon', '_run'], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            routes = Counter()
            peak = 0
            max_age = 0
            warm_routes = Counter()
            ready = False
            warm_ticks = 0
            cold_start_seconds = None
            benchmark_start = time.monotonic()
            for tick in range(30):
                start = time.monotonic()
                trace = home/f'trace-{tick}'
                children = [subprocess.Popen([str(binary),'render'], env={**env, 'CS_PERF_TRACE_DIR':str(trace)},
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in payloads]
                peak = max(peak, sum(p.poll() is None for p in children))
                for child, payload in zip(children, payloads):
                    child.stdin.write(payload)
                    child.stdin.close()
                for child in children:
                    child.wait(timeout=10)
                    output = child.stdout.read()
                    error = child.stderr.read()
                    child.stdout.close()
                    child.stderr.close()
                    assert child.returncode == 0 and output, error.decode()
                counts = Counter(json.loads(p.read_text())['route'] for p in trace.glob('*.json'))
                routes.update(counts)
                if not ready and counts['cache'] == 16:
                    ready = True
                    cold_start_seconds = time.monotonic() - benchmark_start
                if ready:
                    warm_ticks += 1
                    warm_routes.update(counts)
                    for p in (root/'sessions').glob('*/rendered.meta.json'):
                        max_age = max(max_age, time.time()-json.loads(p.read_text())['generated_at'])
                if warm_ticks == 5:
                    break
                time.sleep(max(0, 1-(time.monotonic()-start)))
            assert daemon.poll() is None, daemon.stderr.read().decode()
            metrics = json.loads((root/'scheduler.json').read_text())
            git = [json.loads(p.read_text()) for p in (root/'git').glob('*.json')]
            count = sum(p.get('refresh_count',0) for p in git)
            print(json.dumps(dict(routes=routes, warm_routes=warm_routes,
                cold_start_seconds=cold_start_seconds,
                max_cache_age_seconds=round(max_age,3), peak_burst_clients=peak,
                git_refreshes=count, scheduler=metrics), indent=2))
            assert warm_routes['python'] == 0 and warm_routes['cache'] == 80
            assert count == 1 and metrics['workers'] == 2
            assert max_age < 5
        finally:
            daemon.terminate()
            try:
                daemon.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()
            daemon.stderr.close()


if __name__ == '__main__':
    main()
