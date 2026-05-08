# vhs tape for the hero GIF.
# Usage:  brew install vhs  &&  vhs scripts/hero.tape
# Output: docs/images/hero.gif
#
# The demo feeds mock rate_limits JSON to `cs` so the bar shows believable
# numbers regardless of where you run it. No mutation of your real config.

Output docs/images/hero.gif

Set Shell "bash"
Set FontSize 18
Set FontFamily "JetBrainsMono Nerd Font Mono,Menlo,monospace"
Set Width 1100
Set Height 320
Set Padding 24
Set Theme "Dracula"
Set Framerate 30
Set PlaybackSpeed 1.0
Set TypingSpeed 35ms

# ---- Setup invisible: clean prompt + define the mock JSON in $J ----
Hide
Type "export PS1='$ '"
Enter
Type `J='{"session_id":"demo","model":{"display_name":"Opus 4.7"},"rate_limits":{"five_hour":{"used_percentage":58,"resets_at":'$(($(date +%s)+10020))',"status":"allow"},"seven_day":{"used_percentage":24,"resets_at":'$(($(date +%s)+304320))',"status":"allow"}}}'`
Enter
Type "clear"
Enter
Sleep 300ms
Show

# ---- Pitch line ----
Type "# Claude Code rate-limit usage, in your statusLine"
Enter
Sleep 1.2s
Type "# 3 styles × 9 themes — let's try a few:"
Enter
Sleep 1.2s

# ---- 1) classic / graphite ----
Type "echo $J | cs --style classic --theme graphite"
Enter
Sleep 2.2s

# ---- 2) capsule / dracula ----
Type "echo $J | cs --style capsule --theme dracula"
Enter
Sleep 2.2s

# ---- 3) hairline / nord ----
Type "echo $J | cs --style hairline --theme nord"
Enter
Sleep 2.2s

# ---- 4) classic / tokyo-night ----
Type "echo $J | cs --style classic --theme tokyo-night"
Enter
Sleep 2.5s

# ---- 5) call to action ----
Type "# pip install claude-statusbar && cs --setup"
Enter
Sleep 3s
