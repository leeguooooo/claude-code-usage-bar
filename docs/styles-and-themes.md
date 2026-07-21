# Styles & themes

The default style (`classic`) stays the same forever. Two alternative styles, plus a palette of seven themes, are opt-in.

```bash
cs --style capsule  --theme graphite   # try once
cs --style hairline --theme twilight   # try once
cs config set style capsule            # persist
cs config set theme twilight
cs styles                              # list available styles
cs themes                              # list available themes
cs preview                             # render every style × theme together
```

## Styles

| Style | Look |
|-------|------|
| `classic`  | Original `[bar] \| pipe` engineering layout. Default. |
| `capsule`  | Each metric is a colored pill — type badge (`◷ 5H` / `☷ 7D` / `◆` / `📚`) on the left, value, severity dot on the right. Subway-signage feel. |
| `hairline` | One-character mini-bar (`▁▃▆█`) per metric, dashed `┊` separators, tight typography. Maximally calm. |

**Capsule** — `graphite` · `twilight` · `nord` · `dracula` · `sakura` · `linen` · `mono` · `catppuccin-mocha` · `tokyo-night`

![capsule + graphite](images/capsule-graphite.svg)
![capsule + twilight](images/capsule-twilight.svg)
![capsule + nord](images/capsule-nord.svg)
![capsule + dracula](images/capsule-dracula.svg)
![capsule + sakura](images/capsule-sakura.svg)
![capsule + linen](images/capsule-linen.svg)
![capsule + mono](images/capsule-mono.svg)

**Hairline** — same theme set, different layout

![hairline + graphite](images/hairline-graphite.svg)
![hairline + nord](images/hairline-nord.svg)
![hairline + dracula](images/hairline-dracula.svg)
![hairline + sakura](images/hairline-sakura.svg)
![hairline + mono](images/hairline-mono.svg)

**Classic** — kept identical to the pre-v2.7 look

![classic + graphite](images/classic-graphite.svg)

## Themes

| Theme | Vibe |
|-------|------|
| `graphite` | Cool dark graphite — default, fits most dark terminals |
| `twilight` | Soft purples/roses — warm dark |
| `linen`    | Cream/beige — for light terminal themes |
| `nord`     | Nord palette — familiar Arctic blue |
| `dracula`  | Dracula palette — high-contrast purple/black |
| `sakura`   | Pink/cream — soft, light backgrounds |
| `mono`     | Pure grayscale — no chromatic distraction |
| `catppuccin-mocha` | Catppuccin Mocha — community-favorite pastel, easy on long viewing |
| `tokyo-night` | Tokyo Night — deeper neon-blue mood with restrained accents |

Style and theme are independent: any of the **3 styles × 9 themes = 27 combinations**.

## Slash commands inside Claude Code

After running `cs --setup` (or `cs install-commands`), the following slash commands work inside Claude Code:

| Slash command | What it does |
|---------------|--------------|
| `/statusbar`               | Show current config + lists styles/themes |
| `/statusbar-preview`       | Render every style × theme combination using your real data |
| `/statusbar-style <name>`  | Switch style (`classic` / `capsule` / `hairline`) |
| `/statusbar-theme <name>`  | Switch theme (`graphite` / `twilight` / `linen` / `nord` / `dracula` / `sakura` / `mono` / `catppuccin-mocha` / `tokyo-night`) |
| `/statusbar-doctor`        | Self-diagnostic — paste output in bug reports |
| `/statusbar-reset`         | Wipe config back to defaults |
