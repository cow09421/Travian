# Issue tracker

Issues are tracked as **local markdown files** under `.scratch/` in the repo root.

## Convention

- Each issue is a single `.md` file with a descriptive filename.
- One issue = one file.
- Use subdirectories under `.scratch/` to group related issues (e.g. `.scratch/map-scan/`, `.scratch/training/`).

## Lifecycle

1. Create a markdown file in `.scratch/` with the issue content.
2. Add triage labels in the frontmatter or as the first line.
3. When resolved, either delete the file or move it to `.scratch/archived/`.

## Required fields

Each issue should contain:

```markdown
# Title

**Labels:** 待評估

## Description

...

## Acceptance criteria

- [ ] ...
```