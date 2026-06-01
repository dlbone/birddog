# Birddog Hardware Notes

This is the hardware class Birddog is designed around. BirdNET-Pi can run on
other machines, but this setup has enough headroom for the collage UI, image
processing, and continuous recording.

## Known-Good Setup

- Raspberry Pi 4 or Raspberry Pi 5.
- 64-bit Raspberry Pi OS Bookworm.
- Official-quality USB-C power supply for the Pi.
- USB microphone or USB audio adapter plugged into a USB-A port.
- microSD card or SSD with enough space for recordings.
- Wi-Fi or Ethernet.
- Optional Tailscale for remote access.

## Microphone Placement

- Put the microphone outside or near an open window when possible.
- Keep it under cover; do not expose it directly to rain.
- Reduce wind contact with a foam windscreen or sheltered placement.
- If the mic is unreliable from a Pi USB-A port, use a powered USB hub.

## USB-C And USB-A

On common Raspberry Pi 4/5 setups, USB-C is for power. Use the USB-A ports for
the microphone. Do not try to power the Pi from a USB-A port unless you are
using hardware specifically designed for that; undervoltage will cause bad
recordings, service crashes, or corrupt storage.

## Storage

BirdNET-Pi can write a lot of recordings. Start with at least 32 GB. Use a
larger card or SSD if you preserve recordings.

Generated Birddog art and indexes live in:

```text
~/BirdSongs/Extracted/collage/
```

Those files are safe to back up and restore, but they are not source code.
