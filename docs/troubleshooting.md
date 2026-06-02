# Troubleshooting

Start with:

```bash
cd ~/BirdNET-Pi
scripts/birddog_doctor.sh
```

The doctor is non-destructive. It checks hardware, the BirdNET virtualenv,
Gemini key, runtime data, microphone visibility, services, and local web
endpoints.

## No Birds Are Showing Up

Check the microphone first:

```bash
arecord -l
```

You need at least one ALSA recording device. If none appears:

- Make sure the microphone is in a USB-A port, not the Pi USB-C power port.
- Try a powered USB hub if the mic draws too much current.
- Reboot after changing USB audio hardware.
- Run `scripts/birddog_doctor.sh` again.

Then check the core services:

```bash
systemctl --no-pager status birdnet_recording birdnet_analysis birdnet_log
```

If the services are running and the mic is visible, wait for BirdNET-Pi to
detect real audio. The collage only updates from detections.

## Collage Is Empty But Detections Exist

Rebuild the range indexes:

```bash
cd ~/BirdNET-Pi
birdnet/bin/python3 scripts/bird_collage.py --all-ranges --limit 28
```

Check the timer:

```bash
systemctl --no-pager status birdnet_collage.timer
```

If the timer is missing, rerun the Birddog customization install:

```bash
scripts/install_birddog_customizations.sh
```

## New Birds Show Text Instead Of Images

This usually means artwork has not generated yet.

Check the Gemini key:

```bash
sudo test -s /etc/birdnet/gemini_api_key && echo "Gemini key installed"
```

Install or replace the key:

```bash
scripts/install_birddog_customizations.sh --gemini-key-file ~/gemini_api_key
```

Then queue image generation:

```bash
birdnet/bin/python3 scripts/bird_collage.py \
  --hours 24 \
  --limit 28 \
  --generate \
  --variant both \
  --max-new 2
```

## Dashboard Is Not Reachable

From the Pi, check local HTTP:

```bash
curl -I http://127.0.0.1/
```

Check Caddy:

```bash
systemctl --no-pager status caddy
```

From another device on the same network, try:

```text
http://birddog.local
```

or:

```text
http://<pi-ip-address>
```

With Tailscale, use the Tailscale device name or `100.x.y.z` address. Do not
expect `.local` mDNS names to work over Tailscale.

## Image Generation Is Slow

Birddog generates images in small batches so the Pi stays responsive. New
species may appear as text first, then gain artwork later. Existing cached
images continue to work without internet access.

## Before Filing An Issue

Include:

```bash
cd ~/BirdNET-Pi
git status --short --branch
scripts/birddog_doctor.sh
scripts/check_open_source_ready.sh
./install.sh --check
```

Remove secrets such as API keys, passwords, and public tunnel URLs from logs.
