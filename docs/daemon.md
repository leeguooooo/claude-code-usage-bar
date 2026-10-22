# Fast mode (daemon) — default since v3.6.0

`cs --setup` writes `cs render` + `refreshInterval: 1` by default. A long-lived `cs daemon` pre-renders into `~/.cache/claude-statusbar/rendered.ansi`; the statusLine command (`cs render`) is a thin reader that just `cat`s the file. Each tick is ~3-5ms, so total CPU stays under 1% continuously. The legacy inline path (~30ms/tick, ~3% CPU at 1Hz) is still available via `cs --setup --inline`.

```bash
cs --setup               # default: daemon mode, auto-starts the daemon
cs --setup --inline      # opt out, use legacy inline path
cs daemon status         # check the daemon is alive
cs daemon stop           # stop the daemon (statusLine falls back to inline)
cs daemon start          # start it again
```

Crash safety: if the daemon dies or freezes, `cs render` notices `rendered.meta.json` is older than 5s and falls back to inline render — and lazily re-spawns the daemon in the background. You never see a frozen status line.

## Optional: auto-start on login (launchd / systemd)

Lazy-spawn (above) covers most cases — the daemon comes up on first `cs render`. If you want stronger guarantees (auto-start at login, OS restarts the daemon on crash, survives reboots without `cs render` needing to fire first):

```bash
cs daemon install        # installs ~/Library/LaunchAgents (macOS) or
                          # ~/.config/systemd/user (Linux), starts the daemon
cs daemon service        # report whether the OS-level service is registered
cs daemon uninstall      # remove the LaunchAgent / systemd unit
```

On macOS, the LaunchAgent has `KeepAlive=true` and `ThrottleInterval=10` — kill the daemon and launchd respawns it within 10 seconds. On Linux, the systemd user unit uses `Restart=always` (you may need `loginctl enable-linger $USER` for the daemon to survive logout).

## Refresh and caching

Display ticks stay at one second; data collection follows its own schedule:

| Data | Refresh policy |
| --- | --- |
| Countdown and elapsed time | Recomputed from timestamps on each render |
| Context, model and session cost | Latest statusLine input |
| Transcript activity | Reuse unchanged snapshots; read only appended tail bytes, with a bounded rebuild after replacement or truncation |
| Git dirty / ahead / behind | Shared per worktree, 30-second cache, one refresh at a time |
| Configuration and language progress | Reload when file metadata changes |
| Balance and optional model caps | Shared per account, background refresh; failures are cached |

The native reader is included in macOS arm64 and Linux x86_64 release archives.
Pip/uv installations continue to use the Python client. Existing `cs render`
commands keep working; binary upgrades take effect on the next invocation.

Optional model-specific weekly limits can be enabled with
`cs config set show_per_model true`. This explicitly enables read-only OAuth
credential access (`~/.claude/.credentials.json`, or the macOS login Keychain)
and background requests to Anthropic's undocumented usage endpoint. No token
is logged or stored in a cache. Requests are account-scoped, cached for five
minutes, and disabled by default; unsupported responses hide the segment.
Relay/no-quota sessions never request these limits. The segment appears on
its own line below the main usage row, using the same battery and projection.
