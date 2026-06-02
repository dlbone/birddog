# Birddog

Birddog is a BirdNET-Pi fork with a field-guide style dashboard. It keeps the
normal BirdNET-Pi acoustic detection pipeline and adds a live bird collage,
species details, generated artwork, and inline recording playback.

This project is based on [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi)
and the [BirdNET Analyzer](https://github.com/kahst/BirdNET-Analyzer). Respect
the upstream licenses and BirdNET non-commercial restrictions. See
[NOTICE.md](NOTICE.md) for attribution and generated-data notes.

## Hardware

Reference build:

- Raspberry Pi 4 Model B Rev 1.5.
- 64-bit Raspberry Pi OS Bookworm.
- USB-C power supply.
- USB microphone or USB audio adapter in a USB-A port.
- 32 GB or larger storage.
- Wi-Fi or Ethernet.
- Optional Tailscale for remote access.

More detail: [docs/hardware.md](docs/hardware.md).

## Install

For a blank Pi, follow [docs/fresh-install-checklist.md](docs/fresh-install-checklist.md).

Short version:

```bash
cd ~
git clone https://github.com/dlbone/birddog.git BirdNET-Pi
cd BirdNET-Pi
./install.sh --check
./install.sh
```

Install writes systemd service files from templates using the installer user and
home directory, so it works on non-`admin` systems without path edits.

Open:

```text
http://birddog.local
```

or:

```text
http://<pi-ip-address>
```

## Gemini Key

Birddog uses Gemini only for generating missing bird artwork. Bird detections
still work without it.

Recommended:

```bash
printf '%s\n' 'YOUR_GEMINI_API_KEY' > ~/gemini_api_key
chmod 600 ~/gemini_api_key
cd ~/BirdNET-Pi
./install.sh --gemini-key-file ~/gemini_api_key
```

You can also export the key before install:

```bash
export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'
./install.sh
```

The installer stores the key at `/etc/birdnet/gemini_api_key` with `0600`
permissions.

## Verify

After install:

```bash
cd ~/BirdNET-Pi
scripts/birddog_doctor.sh
```

Before committing changes:

```bash
scripts/check_open_source_ready.sh
```

GitHub Actions runs the same readiness check on pushes and pull requests.

## Useful Docs

- Fresh install: [docs/fresh-install-checklist.md](docs/fresh-install-checklist.md)
- Hardware: [docs/hardware.md](docs/hardware.md)
- Troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)
- Rebuild/backup/restore: [docs/birddog-rebuild.md](docs/birddog-rebuild.md)
- Contributing: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security: [SECURITY.md](SECURITY.md)

## Runtime Data

Generated images, recordings, local detections, indexes, and secrets live
outside the repo. Important paths:

```text
~/BirdSongs/Extracted/collage/
~/BirdNET-Pi/scripts/birds.db
/etc/birdnet/gemini_api_key
```

These are intentionally ignored by git.
