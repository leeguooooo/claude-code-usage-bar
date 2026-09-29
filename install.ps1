# Windows installer for claude-statusbar (the `cs` status line for Claude Code).
#   irm https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.ps1 | iex
# Needs uv (https://docs.astral.sh/uv/). If uv is missing it installs it with
# winget (Microsoft's package manager, built into Windows 10/11) — it never runs
# a remote install script; without winget it stops with install hints. Installs
# the package as a uv tool (uv brings its own Python), puts the tool directory
# on the user PATH, then runs `cs --setup`. Re-run to upgrade.
# Wrapped in a script block so `irm | iex` doesn't leave settings in your shell.
& {
    $ErrorActionPreference = 'Stop'

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            Write-Host 'uv not found; installing it with winget...'
            winget install --id=astral-sh.uv -e --accept-source-agreements --accept-package-agreements
            # winget updates the persisted PATH, not this session's; reload it.
            $env:Path = @(
                [Environment]::GetEnvironmentVariable('Path', 'User'),
                [Environment]::GetEnvironmentVariable('Path', 'Machine'),
                "$env:LOCALAPPDATA\Microsoft\WinGet\Links",
                $env:Path
            ) -join ';'
        }
        if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
            Write-Host 'uv is required but could not be installed automatically. Install it, open a new terminal, then re-run:'
            Write-Host '    winget install --id=astral-sh.uv -e'
            Write-Host '  or see https://docs.astral.sh/uv/getting-started/installation/'
            throw 'uv not found'
        }
    }

    uv tool install --upgrade claude-statusbar
    if ($LASTEXITCODE) { throw 'uv tool install failed' }
    uv tool update-shell  # adds the tool bin dir to the user PATH (new terminals)
    $env:Path = "$(uv tool dir --bin);$env:Path"

    cs --setup
    if ($LASTEXITCODE) { throw 'cs --setup failed' }
    Write-Host 'Done. Restart Claude Code to see the status bar.'
}
