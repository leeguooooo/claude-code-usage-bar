# Windows installer for claude-statusbar (the `cs` status line for Claude Code).
#   irm https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.ps1 | iex
# Requires uv (https://docs.astral.sh/uv/) — it stops with install hints if uv
# is missing and never downloads anything outside this repo and PyPI. Installs
# the package as a uv tool (uv brings its own Python), puts the tool directory
# on the user PATH, then runs `cs --setup`. Re-run to upgrade.
# Wrapped in a script block so `irm | iex` doesn't leave settings in your shell.
& {
    $ErrorActionPreference = 'Stop'

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host 'uv is required but was not found. Install it first, open a new terminal, then re-run:'
        Write-Host '    winget install --id=astral-sh.uv -e'
        Write-Host '  or see https://docs.astral.sh/uv/getting-started/installation/'
        throw 'uv not found'
    }

    uv tool install --upgrade claude-statusbar
    if ($LASTEXITCODE) { throw 'uv tool install failed' }
    uv tool update-shell  # adds the tool bin dir to the user PATH (new terminals)
    $env:Path = "$(uv tool dir --bin);$env:Path"

    cs --setup
    if ($LASTEXITCODE) { throw 'cs --setup failed' }
    Write-Host 'Done. Restart Claude Code to see the status bar.'
}
