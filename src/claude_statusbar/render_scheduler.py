"""Two warm workers: a stalled session cannot block daemon heartbeats."""
import json
import os
import signal
import subprocess
import sys
import time


class Scheduler:
    def __init__(self):
        self.workers = []
        self.due = {}
        self.failures = {}
        self.sessions = []
        self.scan_at = 0
        self.metrics_at = 0
        self.spawn_at = 0
        self.count = 0
        self.timeouts = 0
        self.durations = []

    def _start(self):
        p = subprocess.Popen(
            [sys.executable, '-m', 'claude_statusbar.render_worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True)
        os.set_blocking(p.stdout.fileno(), False)
        os.set_blocking(p.stdin.fileno(), False)
        w = dict(p=p, sid=None, received=b'', sending=b'')
        self.workers.append(w)
        return w

    def _stop(self, w):
        p = w['p']
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait(timeout=2)
        p.stdin.close()
        p.stdout.close()
        self.workers.remove(w)

    def close(self):
        for w in list(self.workers):
            self._stop(w)

    def tick(self, interval):
        from . import daemon as d
        now = time.monotonic()
        if now >= self.scan_at:
            self.sessions = d._active_sessions()
            self.scan_at = now + 1
            for table in (self.due, self.failures):
                for sid in list(table):
                    if sid not in self.sessions:
                        del table[sid]
        for w in list(self.workers):
            sid = w['sid']
            if w['p'].poll() is not None or (sid and now - w['start'] > d.RENDER_TIMEOUT_S + 1):
                if sid:
                    self.timeouts += 1
                    self._backoff(sid, now)
                self._stop(w)
                continue
            if not sid:
                continue
            try:
                if w['sending']:
                    n = os.write(w['p'].stdin.fileno(), w['sending'])
                    w['sending'] = w['sending'][n:]
                data = os.read(w['p'].stdout.fileno(), 65536)
                w['received'] += data
            except BlockingIOError:
                pass
            except OSError:
                self._backoff(sid, now)
                self._stop(w)
                continue
            if len(w['received']) > 1024 * 1024:
                self._backoff(sid, now)
                self._stop(w)
                continue
            if b'\n' in w['received']:
                try:
                    result = json.loads(w['received'])
                    if isinstance(result, str) and result:
                        if d._publish_render(sid, w['payload'], result, min(30, max(5, interval * 2))) is False:
                            raise OSError('cache publish failed')
                        self.count += 1
                        self.durations.append(now - w['start'])
                        self.durations = self.durations[-128:]
                        if now - w['start'] >= d.SLOW_RENDER_S:
                            self._backoff(sid, now)
                        else:
                            self.failures.pop(sid, None)
                            self.due[sid] = now + interval
                    else:
                        self._backoff(sid, now)
                except (ValueError, OSError):
                    self._backoff(sid, now)
                w.update(sid=None, received=b'')
        busy = {w['sid'] for w in self.workers if w['sid']}
        ready = sorted((s for s in self.sessions if s not in busy and self.due.get(s, 0) <= now),
                       key=lambda s: self.due.get(s, 0))
        for sid in ready:
            w = next((w for w in self.workers if w['sid'] is None), None)
            if w is None:
                if len(self.workers) >= 2:
                    break
                if now < self.spawn_at:
                    break
                try:
                    w = self._start()
                except OSError:
                    self.spawn_at = now + 5
                    break
            try:
                p = d.session_stdin_path(sid)
                if p.stat().st_size > 512 * 1024:
                    self._backoff(sid, now)
                    continue
                payload = p.read_text(encoding='utf-8')
                json.loads(payload)
            except (OSError, ValueError):
                self._backoff(sid, now)
                continue
            w.update(sid=sid, start=now, payload=payload,
                     sending=(json.dumps(payload) + '\n').encode())

        if now >= self.metrics_at:
            samples = sorted(self.durations)
            from .cache import atomic_write_text
            atomic_write_text(d._cache_dir() / 'scheduler.json', json.dumps({
                'generated_at': time.time(), 'pid': os.getpid(),
                'active_sessions': len(self.sessions), 'workers': len(self.workers),
                'busy_workers': sum(w['sid'] is not None for w in self.workers),
                'render_count': self.count, 'worker_timeouts_or_crashes': self.timeouts,
                'render_p95_seconds': samples[min(len(samples)-1, int(len(samples)*.95))] if samples else None,
            }), durable=False)
            self.metrics_at = now + 5

    def _backoff(self, sid, now):
        count = min(4, self.failures.get(sid, 0) + 1)
        self.failures[sid] = count
        self.due[sid] = now + min(30, 5 * 2 ** (count - 1))
