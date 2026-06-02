# Fresh Install Checklist

Use this when setting up Birddog on a new Raspberry Pi.

## 1. Prepare The Pi

- Flash 64-bit Raspberry Pi OS Bookworm.
- Boot the Pi and connect it to Ethernet or Wi-Fi.
- Use a good USB-C power supply.
- Plug the microphone or USB audio adapter into a USB-A port.
- Put the microphone somewhere sheltered if it is outside.

Update the base OS:

```bash
sudo apt-get update
sudo apt-get upgrade
sudo reboot
```

## 2. Confirm The Microphone

After reboot:

```bash
arecord -l
```

You should see at least one recording device. If not, fix the microphone before
installing; Birddog cannot show real birds until BirdNET-Pi can hear audio.

## 3. Clone Birddog

```bash
cd ~
git clone https://github.com/dlbone/birddog.git BirdNET-Pi
cd ~/BirdNET-Pi
```

## 4. Add The Gemini Key

The key is optional for detection, but needed for automatic bird artwork.

Recommended:

```bash
printf '%s\n' 'YOUR_GEMINI_API_KEY' > ~/gemini_api_key
chmod 600 ~/gemini_api_key
```

Or export it just for the install:

```bash
export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'
```

## 5. Run Preflight

```bash
./install.sh --check
```

Warnings about sudo credentials are normal; the real install will prompt when
needed. A microphone warning means the install can continue, but real bird
detections will not work until `arecord -l` shows a recording device. Fix any
`FAIL` lines before continuing. Memory or disk warnings mean the Pi may install
or record poorly; use a larger card/SSD or a Pi with more RAM if possible.

## 6. Install

With a key file:

```bash
./install.sh --gemini-key-file ~/gemini_api_key
```

With `GEMINI_API_KEY` exported:

```bash
./install.sh
```

The install now uses your current user context when creating systemd service
templates, so there are no hardcoded `admin` home-path assumptions.

Without a Gemini key:

```bash
./install.sh
```

Detections still work without a key, but new bird artwork will not generate
until a key is installed.

## 7. Verify

```bash
scripts/birddog_doctor.sh
```

A working install should show the microphone, BirdNET services, collage timer,
and local web endpoints as OK. Warnings are useful clues; `FAIL` lines need
attention.
For common fixes, see [troubleshooting.md](troubleshooting.md).

## 8. Open The Dashboard

From the same network:

```text
http://birddog.local
```

or:

```text
http://<pi-ip-address>
```

With Tailscale, use the Pi's Tailscale name or `100.x.y.z` address instead of
the `.local` name.

## 9. Wait For Real Detections

The collage updates from BirdNET-Pi detections. If the mic is quiet or BirdNET
has not detected anything yet, the collage may stay empty. Once a new species is
detected, Birddog will use cached artwork if it exists or queue new image
generation when a Gemini key is installed.
