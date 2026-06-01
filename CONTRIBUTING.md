# Contributing

Birddog is a BirdNET-Pi fork, so keep changes compatible with the upstream
service layout unless a Birddog-specific file clearly owns the behavior.

## Local Checks

Before opening a pull request or publishing a fork, run:

```bash
scripts/check_open_source_ready.sh
```

That command checks shell, PHP, Python, installer preflights, docs, and common
secret/runtime artifact mistakes.

## Installer Changes

The public install path is:

```bash
./install.sh
```

The lower-level Birddog-only customization path is:

```bash
scripts/install_birddog_customizations.sh
```

Both installers have non-destructive preflight modes:

```bash
./install.sh --check
scripts/install_birddog_customizations.sh --check
```

Keep install scripts non-root. They should use `sudo` internally only for
system locations such as `/etc/birdnet` and `/etc/systemd/system`.

## Do Not Commit

- Gemini keys.
- `scripts/birds.db`.
- generated recordings.
- generated collage images or indexes.
- BirdNET virtualenv files.
- local install logs.

The `.gitignore` and readiness script cover the common cases, but still check
`git status` before committing.

## Generated Runtime Data

Runtime data belongs under:

```text
~/BirdSongs/Extracted/collage/
```

Source code, docs, templates, and prompt configuration belong in the repo.
