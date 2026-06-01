# Security

Birddog is intended for a Raspberry Pi on a trusted home network.

## Secrets

Do not commit:

- `/etc/birdnet/gemini_api_key`
- BirdNET-Pi config files containing passwords
- `scripts/birds.db`
- generated recordings or private logs

The recommended Gemini key path is:

```text
/etc/birdnet/gemini_api_key
```

Use `scripts/install_birddog_customizations.sh --gemini-key-file PATH` or
`./install.sh --gemini-key-file PATH` to install it with `0600` permissions.

## Network Exposure

Do not expose the BirdNET-Pi web UI directly to the public internet. Use a VPN
such as Tailscale if you need remote access.

## Reporting Issues

For security-sensitive issues, do not post secrets, logs with tokens, or private
network details in public issues. Reproduce with redacted logs when possible.
