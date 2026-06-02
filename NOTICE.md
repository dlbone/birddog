# Notices

Birddog is a fork/adaptation of BirdNET-Pi with a custom field-guide dashboard,
collage image pipeline, setup helpers, and Raspberry Pi rebuild tooling.

## Upstream Projects

- BirdNET-Pi: originally by Patrick McGuire and later maintained at
  `https://github.com/Nachtzuster/BirdNET-Pi`.
- BirdNET / BirdNET-Lite / BirdNET Analyzer: from the K. Lisa Yang Center for
  Conservation Bioacoustics at the Cornell Lab of Ornithology and collaborators.
- BirdNET Analyzer project: `https://github.com/kahst/BirdNET-Analyzer`.

The repository includes BirdNET model files and labels inherited from the
upstream BirdNET-Pi project. Follow the upstream BirdNET and BirdNET-Pi license
terms, including the non-commercial restriction.

## License

The top-level repository license is Creative Commons
Attribution-NonCommercial-ShareAlike 4.0 International, matching the inherited
BirdNET-Pi/BirdNET-Lite license notice in `LICENSE`.

Birddog-specific dashboard, collage, install, and documentation changes are
distributed as an adaptation under the same license family unless a file says
otherwise.

## Generated And Local Data

Generated bird artwork, local detections, recordings, runtime indexes, and the
Gemini API key are not source code and should not be committed.

Important local paths:

- `/etc/birdnet/gemini_api_key`
- `~/BirdSongs/Extracted/collage/`
- `~/BirdNET-Pi/scripts/birds.db`

The installer and `.gitignore` are set up to keep those out of the repository.

## Third-Party Components

Some vendored frontend or utility files carry their own notices or licenses in
their source directories, for example `scripts/filemanager/LICENSE`. Keep those
files with the code they cover.
