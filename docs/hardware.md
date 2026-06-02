# Birddog Hardware Notes

This is the hardware class Birddog is designed around. BirdNET-Pi can run on
other machines, but this setup has enough headroom for the collage UI, image
processing, and continuous recording.

## Reference Build

This repo is maintained against this class of setup:

- Raspberry Pi 4 Model B Rev 1.5.
- 64-bit Raspberry Pi OS Bookworm.
- USB-C power supply dedicated to powering the Pi.
- USB microphone or USB audio adapter connected through a USB-A port.
- Microphone placed outside on a covered porch/back porch area.
- Wi-Fi or Ethernet on the home network.
- Optional Tailscale for phone/laptop access away from home.

The exact USB microphone model is not important to Birddog; it just needs to
show up as an ALSA recording device (`arecord -l`). If it does not, BirdNET-Pi
will not hear anything and the collage will not update with real detections.

## Compatible Setup

- Raspberry Pi 4 or Raspberry Pi 5.
- 64-bit Raspberry Pi OS Bookworm.
- Official-quality USB-C power supply for the Pi.
- USB microphone or USB audio adapter plugged into a USB-A port.
- microSD card or SSD with enough space for recordings.
- Wi-Fi or Ethernet.
- Optional Tailscale for remote access.

## Shopping Checklist

- Raspberry Pi 4/5.
- Official or high-quality USB-C power adapter for that Pi model.
- 32 GB or larger microSD card; use an SSD if preserving lots of recordings.
- USB microphone, USB sound card with microphone input, or a powered USB hub
  plus microphone if the mic is unstable from Pi power alone.
- Foam windscreen or sheltered enclosure for outdoor/porch placement.
- Weather-safe extension/placement plan; do not expose the mic directly to rain.

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
