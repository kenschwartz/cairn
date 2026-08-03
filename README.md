---
title: Cairn
status: active
project: cairn
---
# Cairn

A local-first Markdown note vault driven by a deterministic Python CLI. Ken's own
[Obsidian](https://obsidian.md/)-equivalent for a machine where Obsidian is not permitted.

**The idea, plainly: Ken cannot use Obsidian at work and needs an alternative.** Citizens does not
allow it, and [OneNote for Mac](https://support.microsoft.com/en-us/onenote/onenote-for-mac-help-and-learning/frequently-asked-questions-about-onenote-for-mac)
is the only sanctioned option and is inadequate. So Cairn replaces the parts of it that matter:
fast capture, todos, links, tags, and search over plain Markdown files that Ken owns.

Named for the stacked-stone trail marker. Notes as cairns you build yourself.

## What it is

A [Python](https://www.python.org/) CLI, installed per-user with no admin rights via a public
[Homebrew](https://brew.sh/) tap (co-primary) or [pipx](https://pipx.pypa.io/), with an offline
bundle for locked-down networks. Manages a folder of Markdown notes:

- Frontmatter-validated notes with a fixed type and status vocabulary
- Fast capture into an inbox, and a todo-first dashboard
- Wiki and relative-markdown links, with a link index and rename support
- Tag and metadata search
- Asset handling and local git auto-commit
- A pre-commit credential and key-material scan (private keys, public keys, AWS keys, GitHub tokens, Anthropic keys) before every auto-commit; corporate GitHub scans server-side as backstop. v1 does not attempt PII detection.

Full specification: [DESIGN.md](./DESIGN.md).

## Where it is built, and where it runs

**Built here**, on Ken's own Mac, using the Hermes agent fleet (decided 2026-08-03). Nothing in
Cairn depends on anything at the bank, so there is no reason to develop it anywhere else, and the
tooling here is far better than the single assistant available on the work machine.

**Deployed to** a locked-down corporate MacBook. That target is why the design insists on no admin
rights and a working offline install path: the real constraints are no sudo and no assumption that
PyPI or github.com is reachable. Homebrew is available there and is a co-primary install path; pipx
and the offline bundle cover the rest. These constraints are real and they stay; they describe the
deployment target, not this repository.

## What is NOT in this repository

No bank data, no customer data, no PII, no credentials, nothing proprietary. This is a note-taking
tool. The vaults Cairn manages at work are a separate thing entirely and never come here.

## Status

Design is complete and adversarially reviewed; no code yet. Phase 1 order is skeleton,
`cairn init`, `cairn doctor`, content scan, `cairn new`, then auto-commit, with hooks and the scan
landing before the first auto-commit. See the implementation phases in [DESIGN.md](./DESIGN.md).

A completeness pass has run on the design (see [REVIEW.md](./REVIEW.md)): two Opus passes on
2026-08-03. Testing documentation belongs in the design, and the prompts used to produce it are
captured alongside it.
