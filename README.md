# Birddog

Birddog is our customized BirdNET-Pi build for a Raspberry Pi bird dashboard.
It keeps the normal BirdNET-Pi acoustic detection pipeline, then adds a live,
visual collage interface that turns detected species into locally cached bird
art.

This repo is based on [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi),
which builds on the [BirdNET Analyzer](https://github.com/kahst/BirdNET-Analyzer).
Respect the upstream licenses and non-commercial restrictions.

## What This Version Adds

- A Collage view as the default dashboard.
- Time ranges: `1h`, `12h`, `TODAY`, `24h`, `7d`, and `all`.
- Automatic species artwork generation for newly detected birds.
- Two cached images per species: one collage cutout and one modal/detail image.
- Alpha-mask based collage packing and hit testing.
- Manual modal image regeneration.
- Local image/background cleanup so cached art keeps working without AI access.
- Rebuild docs and install helper scripts for recovering a Raspberry Pi.

## Hardware

Recommended:

- Raspberry Pi 4 or 5.
- 64-bit Raspberry Pi OS.
- USB microphone or USB audio adapter.
- Reliable power supply.
- Network access for first setup and image generation.

BirdNET-Pi itself supports more Pi models, but this customized UI is intended
for a modern Pi with enough headroom for the web UI and image processing.

## Fresh Install

Start from a normal BirdNET-Pi install. For this fork, the base installer is:

```bash
curl -s https://raw.githubusercontent.com/Nachtzuster/BirdNET-Pi/main/newinstaller.sh | bash
```

After BirdNET-Pi is installed, clone this repo or switch the install to this
repo:

```bash
cd /home/admin
git clone https://github.com/dlbone/birddog.git BirdNET-Pi
cd /home/admin/BirdNET-Pi
```

If you are applying this to an existing BirdNET-Pi checkout, add the repo as a
remote and pull the Birddog branch:

```bash
cd /home/admin/BirdNET-Pi
git remote add birddog git@github.com:dlbone/birddog.git
git fetch birddog
git checkout main
git reset --hard birddog/main
```

Only use `git reset --hard` on a fresh install or after backing up local work.

## Gemini Image Key

The only secret required by the collage image generator is a Gemini API key.
Install it on the Pi at:

```bash
sudo mkdir -p /etc/birdnet
echo 'YOUR_GEMINI_API_KEY' | sudo tee /etc/birdnet/gemini_api_key >/dev/null
sudo chmod 600 /etc/birdnet/gemini_api_key
```

You can also use an environment variable:

```bash
export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'
```

The file is preferred for this install.

Without a Gemini key:

- Existing cached bird images still work.
- New species still appear in the collage as text/initials.
- New image generation and manual regeneration do not work.

## Apply Birddog Customizations

Run:

```bash
cd /home/admin/BirdNET-Pi
scripts/install_birddog_customizations.sh --install-python-deps
```

This installs the prompt style config, optional tmpfs mount template, Python
dependencies, and builds the initial collage indexes.

The collage cache is stored outside the repo:

```text
/home/admin/BirdSongs/Extracted/collage/
```

That folder contains generated images and JSON indexes. It is runtime data, not
source code.

## Access The Dashboard

From the same network:

```text
http://birdnetpi.local
```

or:

```text
http://<pi-ip-address>
```

If using Tailscale, use the Pi's Tailscale name or `100.x.y.z` address. Do not
expect `.local` mDNS names to work reliably over Tailscale.

The default view is the Birddog Collage.

## How Live Updates Work

BirdNET-Pi writes detections into:

```text
/home/admin/BirdNET-Pi/scripts/birds.db
```

The Collage page polls:

```text
scripts/collage_index.php
```

That endpoint rebuilds stale range indexes and triggers image generation for
new species. The browser updates dynamically without a full page refresh when
species, counts, timestamps, or image availability change.

## Manual Index Build

To rebuild all collage ranges:

```bash
cd /home/admin/BirdNET-Pi
for h in -1 1 12 24 168 1000000; do
  /home/admin/BirdNET-Pi/birdnet/bin/python3 scripts/bird_collage.py --hours "$h" --limit 28
done
```

Range meanings:

- `-1`: today since local midnight.
- `1`: past hour.
- `12`: past 12 hours.
- `24`: past 24 hours.
- `168`: past 7 days.
- `1000000`: all time.

To generate missing images during a build:

```bash
/home/admin/BirdNET-Pi/birdnet/bin/python3 scripts/bird_collage.py \
  --hours 24 \
  --limit 28 \
  --generate \
  --variant both \
  --max-new 2
```

To regenerate one species:

```bash
/home/admin/BirdNET-Pi/birdnet/bin/python3 scripts/bird_collage.py \
  --hours 24 \
  --limit 28 \
  --generate \
  --force \
  --variant both \
  --max-new 2 \
  --sci 'Anas platyrhynchos'
```

## Backup Before Rebuilding A Pi

Push repo changes:

```bash
cd /home/admin/BirdNET-Pi
git push
```

Back up runtime data:

```bash
tar -czf /home/admin/birddog-collage-cache.tgz -C /home/admin/BirdSongs/Extracted/collage .
sqlite3 /home/admin/BirdNET-Pi/scripts/birds.db ".backup '/home/admin/birddog-birds.db'"
sudo cp /etc/birdnet/gemini_api_key /home/admin/gemini_api_key.backup
```

Copy these files off the Pi:

- `/home/admin/birddog-collage-cache.tgz`
- `/home/admin/birddog-birds.db`
- `/home/admin/gemini_api_key.backup`

More detailed recovery notes are in:

```text
docs/birddog-rebuild.md
```

## Restore Runtime Data

Restore the Gemini key:

```bash
sudo mkdir -p /etc/birdnet
sudo install -m 0600 gemini_api_key.backup /etc/birdnet/gemini_api_key
```

Restore generated bird art:

```bash
scripts/install_birddog_customizations.sh --restore-cache /path/to/birddog-collage-cache.tgz
```

Restore detection history:

```bash
cp /path/to/birddog-birds.db /home/admin/BirdNET-Pi/scripts/birds.db
```

## Repo Remotes

This repo commonly has two remotes:

```text
origin   upstream BirdNET-Pi
birddog  private Birddog repo
```

Check:

```bash
git remote -v
```

Push Birddog work to the private repo:

```bash
git push birddog main
```

If using SSH, the Pi needs a GitHub SSH key installed. If using HTTPS, use a
GitHub personal access token with access to the private repo.

## Troubleshooting

Check whether image generation can read the key:

```bash
sudo test -s /etc/birdnet/gemini_api_key && echo "Gemini key installed"
```

Check PHP syntax:

```bash
php -l scripts/collage.php
php -l scripts/collage_index.php
php -l scripts/collage_regen.php
```

Check Python syntax:

```bash
/home/admin/BirdNET-Pi/birdnet/bin/python3 -m py_compile scripts/bird_collage.py
```

Force rebuild today's collage:

```bash
/home/admin/BirdNET-Pi/birdnet/bin/python3 scripts/bird_collage.py --hours -1 --limit 28
```

If a species appears as initials first, that usually means the detection arrived
before image generation finished. The page should update once cached images are
available.

## Upstream BirdNET-Pi

For core BirdNET-Pi documentation, microphone setup, BirdWeather integration,
recording settings, and service troubleshooting, refer to upstream:

- <https://github.com/Nachtzuster/BirdNET-Pi>
- <https://github.com/mcguirepr89/BirdNET-Pi/wiki>

Birddog changes the dashboard and image-generation layer. It does not change the
basic BirdNET classifier model or the fact that acoustic detections can be
wrong and should be reviewed before being treated as confirmed observations.
