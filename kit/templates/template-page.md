---
title: Document Template
owner: Docs team
department: Operations
classification: internal
status: draft
version: "2.0"
last_reviewed: "2026-10-21"
review_cycle_days: 180
tags:
  - template
---

# Document Template

How to write a new page for the portal, or change an existing one.

## Purpose

Every page in the portal starts from the same template, so that ownership,
classification and review dates are always filled in.

## How to contribute

1. Download [template.md](https://nerdience-resources.pages.dev/downloads/template.md)
   and, for reference, [example.md](https://nerdience-resources.pages.dev/downloads/example.md)
   (also on the portal front page).
2. Fill in the template in any text editor (Notepad, VS Code, …). Keep the part
   between the two `---` lines and replace the values.
3. Email the file to the docs team at **wikki@nerdience.com**. Say which section it
   belongs to, or put it in the `folder:` line.
4. The docs team checks it, adds it to the right folder in GitHub, and it
   appears in the menu and section pages automatically after the next deploy.

To change an existing page, email the docs team the page name and the change.

## The template

```markdown
---
title: Your Document Title
owner: Team that owns this content
department: Your department
classification: internal        # public | internal | restricted
status: draft
version: "0.1"
last_reviewed: "YYYY-MM-DD"
review_cycle_days: 90
tags:
  - topic
# folder: people/policies
---

# Your Document Title

## Purpose

Why this document exists (shown on the section page card).

## Scope

What this document covers.

## Content

The document content.

## Related Resources

Links to related pages or authoritative systems.
```

## Rules

- Never put passwords, tokens, salaries, bank details or personal data in a page.
- `restricted` pages are only accepted in sites whose audience allows them; the
  docs team will place them accordingly.
