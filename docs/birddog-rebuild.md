# Birddog Raspberry Pi Rebuild

This repo is intended to preserve the custom Birddog BirdNET-Pi dashboard and
collage work so the Raspberry Pi can be rebuilt from a clean install.

## What Is Tracked

- `homepage/views.php` and `homepage/style.css`: make Collage the default view
  and hide the stock BirdNET-Pi chrome for that view.
- `scripts/collage.php`: the live collage UI.
- `scripts/collage_index.php`: polling endpoint that rebuilds stale range
  indexes and auto-generates missing collage/modal images.
- `scripts/collage_regen.php`: manual modal image regeneration endpoint.
- `scripts/bird_collage.py`: image generation, background cleanup, alpha masks,
  range indexes, and metadata.
- `config/bird_collage_style.txt`: the prompt style installed to
  `/etc/birdnet/bird_collage_style.txt`.
- `scripts/install_birddog_customizations.sh`: installs the dashboard extras
  and generates user-specific systemd units for collage refresh and transient
  stream data.
- `requirements_custom.txt`: extra Python packages needed by this install.

Generated detection data, the BirdNET virtualenv, local DBs, recordings, and
generated collage images are intentionally not treated as source code.

## Backup Before Burning Down The Pi

Run these from the current working Pi:

```bash
cd ~/BirdNET-Pi
git status
# If you maintain your own fork, push your source changes before wiping the Pi.
git push

tar -czf ~/birddog-collage-cache.tgz -C ~/BirdSongs/Extracted/collage .
sqlite3 ~/BirdNET-Pi/scripts/birds.db ".backup '$HOME/birddog-birds.db'"
sudo cp /etc/birdnet/gemini_api_key ~/gemini_api_key.backup
```

Copy the three backup files somewhere off the Pi if you need the generated art,
detection history, and Gemini key after a full rebuild:

- `~/birddog-collage-cache.tgz`
- `~/birddog-birds.db`
- `~/gemini_api_key.backup`

## Fresh Pi Restore

1. Install Raspberry Pi OS.
2. Clone Birddog or your GitHub fork:

```bash
cd ~
git clone https://github.com/dlbone/birddog.git BirdNET-Pi
cd ~/BirdNET-Pi
```

3. Restore secrets and install BirdNET-Pi plus Birddog:

```bash
./install.sh --gemini-key-file /path/to/gemini_api_key.backup
```

4. Restore optional generated image cache:

```bash
scripts/install_birddog_customizations.sh --restore-cache /path/to/birddog-collage-cache.tgz
```

5. Restore detection history only if you intentionally want the old DB:

```bash
cp /path/to/birddog-birds.db ~/BirdNET-Pi/scripts/birds.db
```

6. Build the collage indexes:

```bash
for h in -1 1 12 24 168 1000000; do
  ~/BirdNET-Pi/birdnet/bin/python3 ~/BirdNET-Pi/scripts/bird_collage.py --hours "$h" --limit 28
done
```

## GitHub Fork Setup

If you want your own copy, fork Birddog on GitHub and set `origin` to your fork:

```bash
cd ~/BirdNET-Pi
git remote set-url origin https://github.com/YOUR_GITHUB_USER/birddog.git
git push -u origin main
```

Keep upstream BirdNET-Pi as a separate remote only if you plan to pull upstream
changes manually.
