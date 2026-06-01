---
name: Bug report
about: Report a Birddog install, dashboard, image, or playback problem
title: ''
labels: bug
assignees: ''

---

## What happened?

Describe the problem and what you expected instead.

## Where did it happen?

- [ ] Fresh install
- [ ] Upgrade from upstream BirdNET-Pi
- [ ] Collage/dashboard
- [ ] Modal/recording playback
- [ ] Image generation or regeneration
- [ ] Microphone/detection pipeline

## Hardware

- Raspberry Pi model:
- OS/version:
- Microphone or USB audio adapter:
- Storage size/type:
- Network: Ethernet / Wi-Fi / Tailscale / other

## Setup

- Install command used:
- Birddog commit:
- Browser/device:
- Gemini key installed? yes / no / not sure

## Checks

Please paste the output of the relevant commands.

```bash
cd ~/BirdNET-Pi
git status --short --branch
scripts/birddog_doctor.sh
scripts/check_open_source_ready.sh
./install.sh --check
```

For microphone or detection issues:

```bash
systemctl --no-pager status birdnet_recording birdnet_analysis birdnet_log
```

## Screenshots or logs

Screenshots of the dashboard/modal help. For logs, paste only the relevant
section and remove secrets such as API keys, passwords, and public tunnel URLs.
