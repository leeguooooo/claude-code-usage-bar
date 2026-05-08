---
name: Feature request
about: Suggest a new style, theme, segment, or behavior.
title: ''
labels: enhancement
assignees: ''
---

## What you want

Describe the feature in one or two sentences.

## Why

What problem does this solve? Concrete usage scenario beats abstract argument.

## Sketch

If relevant: a mockup of how the bar would look with the change. ASCII is fine.

```
[your-mockup-here]
```

## Constraints to keep in mind

`cs` runs ~60×/min in Claude Code's `statusLine` hook. New features should not:

- Add heavy import-time deps to the render path (`tests/test_import_perf.py` pins this)
- Break the visual identity (battery bar, `[ ]`, emoji clocks, ` | `, `(used/size)` parens are part of the product)
- Require new external services or daemons beyond the existing optional `cs daemon`

If your idea conflicts with these, that's fine — just acknowledge the tradeoff.
