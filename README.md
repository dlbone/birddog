# Birddog

Birddog is a BirdNET-Pi fork with a field-guide style dashboard. It keeps the
normal BirdNET-Pi acoustic detection pipeline, then adds a live collage view
that turns detected species into locally cached bird artwork, recordings, and
simple field notes.

This project is based on [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi)
and the [BirdNET Analyzer](https://github.com/kahst/BirdNET-Analyzer). Respect
the upstream licenses and BirdNET non-commercial restrictions.

## What Birddog Adds

- Collage-first dashboard for recent visitors.
- Time ranges: `1h`, `12h`, `TODAY`, `24h`, `7d`, and `all`.
- Automatic image generation for newly detected species.
- Two cached images per species: collage cutout and modal/detail artwork.
- Local image cleanup, alpha-mask packing, and bird-shaped hit testing.
- Bird modal with description, stats, recordings, inline playback, and waveform.
- Manual image regeneration from the modal.
- Rebuild/install helpers for bringing up a Raspberry Pi again.

## Hardware

Tested target:

- Raspberry Pi 4 or 5.
- 64-bit Raspberry Pi OS.
- USB microphone or USB audio adapter.
- Reliable USB-C power supply for the Pi.
- Ethernet or Wi-Fi during setup.
- Optional: Tailscale for remote access.

Notes:

- The Pi USB-C port is for power on typical Raspberry Pi 4/5 setups.
- Plug the microphone into a USB-A port, or use a powered USB hub if you need
  more ports or the microphone draws too much power.
- A porch/outdoor mic placement helps, but protect the microphone from weather.
- Image generation needs internet access only when creating new bird images.
  Already cached images keep working offline.

More detail: [docs/hardware.md](docs/hardware.md).

## Quick Install

On a fresh Raspberry Pi OS install:

```bash
cd ~
git clone https://github.com/dlbone/birddog.git BirdNET-Pi
cd BirdNET-Pi
./install.sh --check
./install.sh
```

With a Gemini key ready:

```bash
./install.sh --gemini-key-file ~/gemini_api_key
```

The installer runs the base BirdNET-Pi install from this checkout and then
applies the Birddog dashboard, timer, image prompt, Python dependency, and
optional Gemini-key setup.
`./install.sh --check` is non-destructive; it verifies prerequisites without
prompting for sudo. If it warns that sudo credentials are not cached, the real
install can still prompt normally.
Advanced users can also run
`scripts/install_birddog_customizations.sh --check` to verify only the Birddog
customization layer.

If you already installed upstream BirdNET-Pi and want to switch that checkout to
Birddog:

```bash
cd ~/BirdNET-Pi
git remote add birddog https://github.com/dlbone/birddog.git
git fetch birddog
git checkout main
git reset --hard birddog/main
./install.sh --skip-birdnet
```

Only use `git reset --hard` on a fresh install or after backing up local work.
If you fork Birddog, replace the remote URL with your fork.

## Gemini Image Key

The only secret Birddog needs for its custom features is a Gemini API key. It is
used only to generate missing bird artwork. Bird detections still work without
it.

Preferred setup:

```bash
printf '%s\n' 'YOUR_GEMINI_API_KEY' > ~/gemini_api_key
chmod 600 ~/gemini_api_key
cd ~/BirdNET-Pi
scripts/install_birddog_customizations.sh --gemini-key-file ~/gemini_api_key
```

If you already have the key in your shell environment, the installer will pick
it up automatically:

```bash
export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'
cd ~/BirdNET-Pi
./install.sh
```

You can also pass the key directly, though the key-file or environment flow is
cleaner for normal use:

```bash
scripts/install_birddog_customizations.sh --gemini-key 'YOUR_GEMINI_API_KEY'
```

The installer stores the key at:

```text
/etc/birdnet/gemini_api_key
```

with `0600` permissions. `scripts/bird_collage.py` also honors
`GEMINI_API_KEY` for one-off command-line runs.
See `config/birddog.env.example` for optional local environment overrides.

Without a Gemini key:

- Existing cached bird images still display.
- New species still appear in the collage as initials/text.
- New image generation and modal regeneration are skipped.

## What The Installer Does

`scripts/install_birddog_customizations.sh`:

- Installs the collage prompt style to `/etc/birdnet/bird_collage_style.txt`.
- Installs the optional BirdSongs stream-data tmpfs mount.
- Installs and enables the `birdnet_collage.timer` index/image background job.
- Optionally installs Python dependencies from `requirements_custom.txt`.
- Optionally installs the Gemini key.
- Optionally restores a cached collage tarball.
- Builds the initial collage indexes if the BirdNET virtualenv is present.

Common full setup:

```bash
cd ~/BirdNET-Pi
./install.sh --gemini-key-file ~/gemini_api_key
```

## Runtime Data

Generated data lives outside the repo:

```text
~/BirdSongs/Extracted/collage/
```

That folder contains generated PNGs, metadata, alpha masks, and JSON indexes.
It is runtime cache, not source code.

BirdNET-Pi detections live in:

```text
~/BirdNET-Pi/scripts/birds.db
```

## Live Updates

The Collage page polls:

```text
scripts/collage_index.php
```

That endpoint rebuilds stale range indexes, refreshes missing metadata, and
starts background image generation for new species. The browser updates without
a full page refresh when species, counts, timestamps, or image availability
change.

## Access

From the same network:

```text
http://birdnetpi.local
```

or:

```text
http://<pi-ip-address>
```

With Tailscale, use the Pi Tailscale name or `100.x.y.z` address. Do not rely
on `.local` mDNS names over Tailscale.

## Manual Collage Commands

Rebuild all range indexes:

```bash
cd ~/BirdNET-Pi
birdnet/bin/python3 scripts/bird_collage.py --all-ranges --limit 28
```

Generate missing images for one range:

```bash
birdnet/bin/python3 scripts/bird_collage.py \
  --hours 24 \
  --limit 28 \
  --generate \
  --variant both \
  --max-new 2
```

Regenerate one species:

```bash
birdnet/bin/python3 scripts/bird_collage.py \
  --hours 24 \
  --limit 28 \
  --generate \
  --force \
  --variant both \
  --max-new 2 \
  --sci 'Cathartes aura'
```

Range meanings:

- `-1`: today since local midnight.
- `1`: past hour.
- `12`: past 12 hours.
- `24`: past 24 hours.
- `168`: past 7 days.
- `1000000`: all time.

## Backup

Before rebuilding a Pi, back up the runtime data you care about:

```bash
cd ~/BirdNET-Pi
git status
git push

tar -czf ~/birddog-collage-cache.tgz -C ~/BirdSongs/Extracted/collage .
sqlite3 ~/BirdNET-Pi/scripts/birds.db ".backup '$HOME/birddog-birds.db'"
sudo cp /etc/birdnet/gemini_api_key ~/gemini_api_key.backup
sudo chown "$(id -un):$(id -gn)" ~/gemini_api_key.backup
chmod 600 ~/gemini_api_key.backup
```

Copy these files off the Pi:

- `~/birddog-collage-cache.tgz`
- `~/birddog-birds.db`
- `~/gemini_api_key.backup`

## Restore

Restore the Gemini key:

```bash
cd ~/BirdNET-Pi
scripts/install_birddog_customizations.sh --gemini-key-file /path/to/gemini_api_key.backup
```

Restore generated bird art:

```bash
scripts/install_birddog_customizations.sh --restore-cache /path/to/birddog-collage-cache.tgz
```

Restore detection history only if you intentionally want the old BirdNET data:

```bash
cp /path/to/birddog-birds.db ~/BirdNET-Pi/scripts/birds.db
```

More detailed rebuild notes are in [docs/birddog-rebuild.md](docs/birddog-rebuild.md).

## Validation

After install, run the Birddog doctor:

```bash
cd ~/BirdNET-Pi
scripts/birddog_doctor.sh
```

It checks the local checkout, BirdNET virtualenv, Gemini key, microphone
visibility, core services, collage timer, runtime data folders, and local web
endpoints without changing system state.

Run the full non-destructive repo check:

```bash
scripts/check_open_source_ready.sh
```

GitHub Actions runs the same check on pushes and pull requests.

Check PHP:

```bash
php -l scripts/collage.php
php -l scripts/collage_index.php
php -l scripts/collage_regen.php
```

Check Python:

```bash
birdnet/bin/python3 -m py_compile scripts/bird_collage.py
```

Check the Gemini key:

```bash
sudo test -s /etc/birdnet/gemini_api_key && echo "Gemini key installed"
```

Check the background timer:

```bash
systemctl --no-pager status birdnet_collage.timer
```

## Development Notes

- Source lives in the repo.
- Generated collage assets and the Gemini key do not.
- Keep image prompts in `config/bird_collage_style.txt`.
- Keep Pi-specific recovery details in `docs/birddog-rebuild.md`.
- Upstream BirdNET-Pi docs remain the source of truth for classifier setup,
  BirdWeather, microphone tuning, and core service behavior.
