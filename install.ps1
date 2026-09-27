# Windows installer for claude-statusbar (the `cs` status line for Claude Code).
#   irm https://raw.githubusercontent.com/leeguooooo/claude-code-usage-bar/main/install.ps1 | iex
# Installs uv if missing (Astral's official installer, no admin), installs the
# package as a uv tool (uv brings its own Python), puts the tool directory on
# the user PATH, then runs `cs --setup`. Re-run to upgrade.
# Wrapped in a script block so `irm | iex` doesn't leave settings in your shell.
& {
    $ErrorActionPreference = 'Stop'

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host 'Installing uv...'
        powershell -NoProfile -ExecutionPolicy ByPass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        if ($LASTEXITCODE) { throw 'uv install failed' }
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }

    uv tool install --upgrade claude-statusbar
    if ($LASTEXITCODE) { throw 'uv tool install failed' }
    uv tool update-shell  # adds the tool bin dir to the user PATH (new terminals)
    $env:Path = "$(uv tool dir --bin);$env:Path"

    cs --setup
    Write-Host 'Done. Restart Claude Code to see the status bar.'
}
