# Looks

`cs` has three looks, all on the `graphite` palette:

**Aurora, block bars** — the default. Each bar cell blends green → amber → red
by position, so a fuller bar reaches further into the red.

![aurora, block bars](images/look-aurora.png)

**Aurora, thin line** — same colors, a thin `━` line instead of `■` blocks.

![aurora, thin line](images/look-thin.png)

**Classic** — the original `[battery] | pipe` layout, unchanged.

![classic](images/look-classic.png)

```bash
cs theme                         # interactive: live preview, ↑/↓ or 1-3, Enter applies
cs config set bar_glyph block    # aurora, block bars (default)
cs config set bar_glyph thin     # aurora, thin line
cs config set style classic      # classic
cs config set style aurora       # back to aurora
cs preview                       # all three, with your real numbers
cs --style classic               # try once without saving
```

When a release adds or changes looks, an interactive `cs upgrade` opens the
picker for you, and the bar shows a faint `✦ New looks available · run cs theme`
line until you've opened it once (background auto-upgrades can't prompt).

To tune a color rather than the whole look, override the severity colors:
`cs config set color_ok "#4ec85b"` (also `color_warn`, `color_hot`,
`color_worktree`; an empty string restores the default).

Before 3.50.0 there were also `capsule` and `hairline` styles and eight more
themes. Configs that still name them fall back to aurora / graphite.

## Slash commands inside Claude Code

After `cs --setup` (or `cs install-commands`):

| Slash command | What it does |
|---------------|--------------|
| `/statusbar`                          | Show current config and the looks |
| `/statusbar-preview`                  | Render the three looks with your real data |
| `/statusbar-style block\|thin\|classic` | Switch look |
| `/statusbar-doctor`                   | Self-diagnostic — paste output in bug reports |
| `/statusbar-reset`                    | Wipe config back to defaults |
