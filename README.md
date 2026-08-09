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

A [Python](https://www.python.org/) CLI (3.11+), installed per-user with no admin rights via a public
[Homebrew](https://brew.sh/) tap (co-primary) or [pipx](https://pipx.ppa.io/), with a self-contained
offline bundle for locked-down networks. Manages a folder of Markdown notes:

- Frontmatter-validated notes with a fixed type and status vocabulary
- Fast capture into an inbox, and a todo-first dashboard
- Wiki and relative-markdown links, with a link index and rename support
- Tag and metadata search
- Asset handling and local git auto-commit
- A pre-commit credential and key-material scan (private keys, public keys, AWS keys, GitHub tokens, Anthropic keys) before every auto-commit; corporate GitHub scans server-side as backstop. v1 does not attempt PII detection.

Full specification: [DESIGN.md](./DESIGN.md).

## Install

Needs Python 3.11+ and git. No admin rights, no sudo.

**Homebrew (co-primary, the only path with a real `brew upgrade` story):**

    brew tap kenschwartz/cairn https://github.com/kenschwartz/cairn
    brew install cairn

(The tap points at this repo directly; the formula lives in `Formula/cairn.rb`.
Upgrades: `brew update && brew upgrade cairn` after a new tag is cut.)

**pipx:**

    pipx install git+https://github.com/kenschwartz/cairn.git

**Offline zipapp (for a network where PyPI and github.com are unreachable at runtime):**
build the single-file `.pyz` on a connected machine, then copy it over. It bundles
Cairn and a pure-Python PyYAML, so it runs under any Python 3.11+ with nothing else
installed:

    python -m zipapp src --output cairn.pyz --python /usr/bin/env\ python3 --main cairn.cli:main

(For a fully self-contained bundle that needs no PyYAML on the host, copy the `yaml/`
package into `src/` before running zipapp. The release artifact `cairn-vX.Y.Z.pyz`
is built this way.)

## Quick start

    cairn init ~/my-vault        # folders, git, .gitignore, pre-commit + pre-push hooks
    cd ~/my-vault
    cairn new "First note" --tag onboard
    cairn doctor                 # verifies hooks, deps, config

Every successful write auto-commits to local git. The pre-commit hook scans for
credentials before any commit lands. Back up with a manual `git push` to an
allowlisted remote.

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

**Built and released (`v1.1.0`): the full feature set, all five phases.** 336 hermetic tests
passing. Installable via `brew tap kenschwartz/cairn https://github.com/kenschwartz/cairn &&
brew install cairn` (then `brew upgrade cairn` for new releases) or the self-contained offline
zipapp. Every phase was built cross-family (GLM-authored gating tests, Fable build, GLM review,
host-verify) per `orchestration/LOG.md`.

Commands: `init`, `doctor`, `new`, `capture`, `validate`, `remote add`, `search`, `dashboard`,
`rename`, `reindex`, `tags`, `tag rename`/`remove`, `asset add`. The pre-commit credential scan
and git hooks (pre-commit + pre-push) guard every write; `cairn doctor` verifies them.

Deferred to later releases (see [TODO.md](./TODO.md)): the v2 scan rules (entropy token,
`cairn:allow-secret` suppression, bounded history scan), tag merge, and a separate `homebrew-cairn`
tap repo if a bare `brew tap kenschwartz/cairn` is ever wanted.

A completeness pass and adversarial reviews have run on the design; see [REVIEW.md](./REVIEW.md).
Decisions that resolved DESIGN's open points are in [docs/decisions.md](./docs/decisions.md).

