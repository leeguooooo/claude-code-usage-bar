# vhs tape for the hero GIF.
# Usage:  brew install vhs  &&  vhs scripts/hero.tape
# Output: docs/images/hero.gif
#
# The demo feeds mock rate_limits JSON to `cs` (run from this checkout) so the
# bar shows believable numbers anywhere. $HOME is a temp dir, so the visible
# `cs config set` calls never touch your real config. Shows the three looks.

Output docs/images/hero.gif

Set Shell "bash"
Set FontSize 18
Set FontFamily "JetBrainsMono Nerd Font Mono,Menlo,monospace"
Set Width 1100
Set Height 420
Set Padding 24
Set Theme "Dracula"
Set Framerate 30
Set PlaybackSpeed 1.0
Set TypingSpeed 35ms

# ---- Setup invisible: clean prompt, isolated $HOME (so `cs config set` never
# touches your real config), `cs` from this checkout, mock JSON in $J ----
Hide
Type "export PS1='$ ' REPO=$PWD HOME=$(mktemp -d) CLAUDE_STATUSBAR_NO_UPDATE=1 && cd $HOME"
Enter
Type `cs() { PYTHONPATH=$REPO/src python3 -c 'import sys;from claude_statusbar.cli import main;sys.exit(main())' "$@"; }`
Enter
Type "cs config set show_project_branch false >/dev/null; cs config set show_ocs false >/dev/null; cs config set looks_seen 99 >/dev/null"
Enter
Type `J='{"session_id":"demo","model":{"display_name":"Opus 5.5"},"context_window":{"used_percentage":42},"rate_limits":{"five_hour":{"used_percentage":31,"resets_at":'$(($(date +%s)+5940))',"status":"allow"},"seven_day":{"used_percentage":64,"resets_at":'$(($(date +%s)+230400))',"status":"allow"}}}'`
Enter
Type `printf '\033c'`
Enter
Sleep 300ms
Show

# ---- Pitch line ----
Type "# Claude Code rate-limit usage, in your statusLine"
Enter
Sleep 1.2s

# ---- 1) default: aurora, block bars ----
Type "echo $J | cs"
Enter
Sleep 2.4s

# ---- 2) aurora, thin line ----
Type "cs config set bar_glyph thin"
Enter
Sleep 0.6s
Type "echo $J | cs"
Enter
Sleep 2.4s

# ---- 3) classic ----
Type "cs config set style classic"
Enter
Sleep 0.6s
Type "echo $J | cs"
Enter
Sleep 2.6s

# ---- 4) call to action ----
Type "# install: github.com/leeguooooo/claude-code-usage-bar"
Enter
Sleep 3s
