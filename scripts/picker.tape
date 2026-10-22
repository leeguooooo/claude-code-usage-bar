# vhs tape for the README's top GIF: the interactive `cs theme` picker.
# Usage:  TRIM=0 scripts/build-hero-gif.sh scripts/picker.tape
# Output: docs/images/picker.gif
#
# Runs `cs` from this checkout against a temp $HOME (so nothing touches your
# real config) with mock usage numbers, in English.

Output docs/images/picker.gif

Set Shell "bash"
Set FontSize 18
Set FontFamily "JetBrainsMono Nerd Font Mono,Menlo,monospace"
Set Width 1240
Set Height 470
Set Padding 24
Set Theme "Dracula"
Set Framerate 30
Set PlaybackSpeed 1.0
Set TypingSpeed 45ms

Hide
Type "export PS1='$ ' REPO=$PWD HOME=$(mktemp -d) CLAUDE_STATUSBAR_NO_UPDATE=1 LANG=en_US.UTF-8 && cd $HOME"
Enter
Type `cs() { PYTHONPATH=$REPO/src python3 -c 'import sys;from claude_statusbar.cli import main;sys.exit(main())' "$@"; }`
Enter
Type "for kv in 'lang en' 'show_project_branch false' 'show_ocs false'; do cs config set $kv >/dev/null; done"
Enter
Type `J='{"session_id":"demo","model":{"display_name":"Opus 5.5"},"context_window":{"used_percentage":42,"total_input_tokens":420000,"total_output_tokens":0,"context_window_size":1000000},"rate_limits":{"five_hour":{"used_percentage":31,"resets_at":'$(($(date +%s)+5940))',"status":"allow"},"seven_day":{"used_percentage":64,"resets_at":'$(($(date +%s)+230400))',"status":"allow"}}}'`
Enter
Type "mkdir -p ~/.cache/claude-statusbar && echo $J > ~/.cache/claude-statusbar/last_stdin.json"
Enter
Type `printf '\033c'`
Enter
Sleep 300ms
Show

Type "cs theme"
Sleep 400ms
Enter
Sleep 2.2s
Down
Sleep 1.4s
Down
Sleep 1.4s
Up
Sleep 1.2s
Enter
Sleep 1.2s
Type "echo $J | cs"
Enter
Sleep 3s
