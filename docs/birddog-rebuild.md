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
- `templates/home-admin-BirdSongs-StreamData.mount`: tmpfs mount for transient
  stream data.
- `requirements_custom.txt`: extra Python packages needed by this install.

Generated detection data, the BirdNET virtualenv, local DBs, recordings, and
generated collage images are intentionally not treated as source code.

## Backup Before Burning Down The Pi

Run these from the current working Pi:

```bash
cd /home/admin/BirdNET-Pi
git status
git push birddog main

tar -czf /home/admin/birddog-collage-cache.tgz -C /home/admin/BirdSongs/Extracted/collage .
sqlite3 /home/admin/BirdNET-Pi/scripts/birds.db ".backup '/home/admin/birddog-birds.db'"
sudo cp /etc/birdnet/gemini_api_key /home/admin/gemini_api_key.backup
```

Copy the three backup files somewhere off the Pi if you need the generated art,
detection history, and Gemini key after a full rebuild:

- `/home/admin/birddog-collage-cache.tgz`
- `/home/admin/birddog-birds.db`
- `/home/admin/gemini_api_key.backup`

## Fresh Pi Restore

1. Install Raspberry Pi OS and BirdNET-Pi normally.
2. Clone this repo or your GitHub fork:

```bash
cd /home/admin
git clone https://github.com/YOUR_GITHUB_USER/birddog-birdnet-pi.git BirdNET-Pi
cd /home/admin/BirdNET-Pi
```

3. Restore secrets and optional cache:

```bash
sudo mkdir -p /etc/birdnet
sudo install -m 0600 /path/to/gemini_api_key.backup /etc/birdnet/gemini_api_key

scripts/install_birddog_customizations.sh --restore-cache /path/to/birddog-collage-cache.tgz
```

4. If rebuilding the Python environment too:

```bash
scripts/install_birddog_customizations.sh --install-python-deps
```

5. Restore detection history only if you intentionally want the old DB:

```bash
cp /path/to/birddog-birds.db /home/admin/BirdNET-Pi/scripts/birds.db
```

6. Build the collage indexes:

```bash
for h in -1 1 12 24 168 1000000; do
  /home/admin/BirdNET-Pi/birdnet/bin/python3 /home/admin/BirdNET-Pi/scripts/bird_collage.py --hours "$h" --limit 28
done
```

## GitHub Remote Setup

The local `origin` points at upstream BirdNET-Pi:

```text
https://github.com/Nachtzuster/BirdNET-Pi.git
```

Do not push custom work there. Create your own private GitHub repo, then add it
as a second remote:

```bash
cd /home/admin/BirdNET-Pi
git remote add birddog git@github.com:YOUR_GITHUB_USER/birddog-birdnet-pi.git
git push -u birddog main
```

If using HTTPS instead of SSH:

```bash
git remote add birddog https://github.com/YOUR_GITHUB_USER/birddog-birdnet-pi.git
git push -u birddog main
```
