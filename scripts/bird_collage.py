#!/usr/bin/env python3
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import numpy as np
from scipy import ndimage
from PIL import Image


HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, "BirdNET-Pi")
DB_PATH = os.path.join(BASE_DIR, "scripts", "birds.db")
LABELS_PATH = os.path.join(BASE_DIR, "model", "l18n", "labels_en.json")
OUTPUT_DIR = os.path.join(HOME, "BirdSongs", "Extracted", "collage")
IMAGE_DIR = os.path.join(OUTPUT_DIR, "images")
INDEX_PATH = os.path.join(OUTPUT_DIR, "index.json")
META_PATH = os.path.join(OUTPUT_DIR, "species_meta.json")
STYLE_PATH = "/etc/birdnet/bird_collage_style.txt"
KEY_PATH = "/etc/birdnet/gemini_api_key"
DEFAULT_STYLE = (
    "ornithological field-guide watercolor painting, full body bird, pure white background, "
    "complete bird visible from beak to tail to feet, both legs and toes clearly visible, "
    "standing naturally, no cropped feet, no hidden feet, no branch, no perch, no twig, "
    "soft natural colors, detailed feathers, no text, no border, centered subject, "
    "natural feather edges that fade into the paper, no sticker outline, no white contour, "
    "no black contour, no vector art, no decal style, no transparency checkerboard, "
    "no Photoshop transparency grid, no black background, no colored background"
)
DEFAULT_MODEL = "gemini-2.5-flash-image"
TODAY_HOURS = -1
RANGE_HOURS = (1, 12, TODAY_HOURS, 24, 168, 1000000)


def slugify(value):
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "bird"


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_labels():
    try:
        with open(LABELS_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def api_key():
    return os.environ.get("GEMINI_API_KEY", "").strip() or read_text(KEY_PATH)


def local_rarity(total_count):
    total_count = int(total_count or 0)
    if total_count >= 25:
        return "common"
    if total_count >= 8:
        return "regular"
    if total_count >= 3:
        return "occasional"
    return "new"


def image_path_for(sci_name, com_name, variant="collage"):
    digest_source = f"{sci_name}|{com_name}" if variant == "collage" else f"{sci_name}|{com_name}|{variant}"
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    suffix = "" if variant == "collage" else f"-{variant}"
    return os.path.join(IMAGE_DIR, f"{slugify(com_name)}{suffix}-{digest}.png")


def get_species(hours, limit):
    labels = load_labels()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    today_only = hours == TODAY_HOURS
    all_time = (hours <= 0 and hours != TODAY_HOURS) or hours >= 1000000
    cutoff = (dt.datetime.now() - dt.timedelta(hours=max(1, hours))).strftime("%Y-%m-%d %H:%M:%S")
    recent_sql = """
        SELECT
          d.Sci_Name,
          COALESCE(NULLIF(d.Com_Name, ''), d.Sci_Name) AS Com_Name,
          COUNT(*) AS RecentCount,
          MAX(d.Date || ' ' || d.Time) AS LastHeard,
          MIN(d.Date || ' ' || d.Time) AS FirstHeard,
          SUM(CASE WHEN d.Date = DATE('now', 'localtime') THEN 1 ELSE 0 END) AS TodayCount,
          (
            SELECT COUNT(*) FROM detections all_d
            WHERE all_d.Sci_Name = d.Sci_Name
          ) AS TotalCount
        FROM detections d
        WHERE (
          ? = 1
          OR (? = 1 AND d.Date = DATE('now', 'localtime'))
          OR (? = 0 AND datetime(d.Date || ' ' || d.Time) >= datetime(?))
        )
        GROUP BY d.Sci_Name
        ORDER BY datetime(LastHeard) DESC
        LIMIT ?
    """
    rows = conn.execute(
        recent_sql,
        (1 if all_time else 0, 1 if today_only else 0, 1 if today_only else 0, cutoff, limit),
    ).fetchall()
    if not rows and not today_only:
        fallback_sql = """
            SELECT
              d.Sci_Name,
              COALESCE(NULLIF(d.Com_Name, ''), d.Sci_Name) AS Com_Name,
              COUNT(*) AS RecentCount,
              MAX(d.Date || ' ' || d.Time) AS LastHeard,
              MIN(d.Date || ' ' || d.Time) AS FirstHeard,
              SUM(CASE WHEN d.Date = DATE('now', 'localtime') THEN 1 ELSE 0 END) AS TodayCount,
              COUNT(*) AS TotalCount
            FROM detections d
            GROUP BY d.Sci_Name
            ORDER BY datetime(LastHeard) DESC
            LIMIT ?
        """
        rows = conn.execute(fallback_sql, (limit,)).fetchall()
    species = []
    for row in rows:
        sci_name = row["Sci_Name"]
        com_name = row["Com_Name"] or labels.get(sci_name, sci_name)
        image_path = image_path_for(sci_name, com_name)
        detail_image_path = image_path_for(sci_name, com_name, "detail")
        rel_image = os.path.relpath(image_path, os.path.join(HOME, "BirdSongs", "Extracted"))
        rel_detail_image = os.path.relpath(detail_image_path, os.path.join(HOME, "BirdSongs", "Extracted"))
        recordings = conn.execute(
            """
            SELECT Date, Time, File_Name, Confidence
            FROM detections
            WHERE Sci_Name = ?
            ORDER BY Date DESC, Time DESC
            LIMIT 6
            """,
            (sci_name,),
        ).fetchall()
        species.append({
            "sci_name": sci_name,
            "com_name": com_name,
            "recent_count": row["RecentCount"],
            "today_count": row["TodayCount"] or 0,
            "total_count": row["TotalCount"],
            "last_heard": row["LastHeard"],
            "first_heard": row["FirstHeard"],
            "image": rel_image,
            "detail_image": rel_detail_image,
            "has_image": os.path.exists(image_path),
            "has_detail_image": os.path.exists(detail_image_path),
            "slug": slugify(f"{com_name}-{sci_name}"),
            "recordings": [
                {
                    "date": rec["Date"],
                    "time": rec["Time"],
                    "file_name": rec["File_Name"],
                    "confidence": rec["Confidence"],
                }
                for rec in recordings
            ],
        })
    conn.close()
    return species


def fetch_wikipedia_summary(sci_name, com_name):
    titles = [sci_name, com_name]
    headers = {"User-Agent": "BirdNET-Pi collage metadata"}
    for title in titles:
        if not title:
            continue
        quoted = urllib.parse.quote(title.replace(" ", "_"))
        request = urllib.request.Request(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quoted}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue
        extract = data.get("extract", "").strip()
        if extract:
            return {
                "description": extract,
                "source_url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "source": "Wikipedia",
            }
    return {
        "description": "",
        "source_url": "",
        "source": "",
    }


def enrich_metadata(species, fetch_missing=True):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cache = read_json(META_PATH, {})
    changed = False
    today = dt.date.today().isoformat()
    for bird in species:
        sci_name = bird.get("sci_name", "")
        cached = cache.get(sci_name, {})
        if fetch_missing and not cached.get("description"):
            cached = fetch_wikipedia_summary(sci_name, bird.get("com_name", ""))
            cached["date_created"] = today
            changed = True
        genus = sci_name.split(" ", 1)[0] if sci_name else ""
        bird["description"] = cached.get("description", "")
        bird["description_source"] = cached.get("source", "")
        bird["description_url"] = cached.get("source_url", "")
        bird["genus"] = cached.get("genus") or genus
        bird["rarity"] = local_rarity(bird.get("total_count"))
        cached["genus"] = bird["genus"]
        cache[sci_name] = cached
    if changed:
        tmp_path = f"{META_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(cache, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, META_PATH)


def prompt_for(com_name, sci_name, variant="collage"):
    style = read_text(STYLE_PATH) or DEFAULT_STYLE
    if variant == "detail":
        return (
            f"{style}. Subject: {com_name} ({sci_name}). "
            "Create an alternate field-guide portrait showing the bird flying in midair, wings spread, "
            "legs and feet visible if anatomically visible in flight, no branch, no perch, no twig, "
            "slightly more detailed and suitable for a species detail modal. "
            "Depict the bird accurately for species identification. "
            "Show the complete bird; do not crop the wings, tail, head, or feet. "
            "Single bird only. The bird must not have a sticker-like outline, die-cut edge, "
            "stroke, halo, border, or artificial contour around the body. "
            "Place it on a flat pure white background (#ffffff) only; do not draw a checkerboard, "
            "Photoshop transparency grid, black background, or colored background."
        )
    return (
        f"{style}. Subject: {com_name} ({sci_name}). "
        "Depict the bird accurately for species identification. "
        "Show the complete bird including both legs, feet, and toes; do not crop or hide the feet. "
        "The collage image must contain only the bird body, with no branch, no perch, no twig, no leaves, and no ground. "
        "Single bird only. The bird must not have a sticker-like outline, die-cut edge, "
        "stroke, halo, border, or artificial contour around the body. "
        "Place it on a flat pure white background (#ffffff) only; do not draw a checkerboard, "
        "Photoshop transparency grid, black background, or colored background."
    )


def transparent_image(path):
    image = Image.open(path).convert("RGBA")
    data = np.array(image)
    rgb = data[:, :, :3].astype(np.int16)
    alpha = data[:, :, 3]
    near_white = (
        (rgb[:, :, 0] >= 228)
        & (rgb[:, :, 1] >= 228)
        & (rgb[:, :, 2] >= 220)
        & ((rgb.max(axis=2) - rgb.min(axis=2)) <= 32)
    )
    seed = np.zeros(near_white.shape, dtype=bool)
    seed[0, :] = near_white[0, :]
    seed[-1, :] = near_white[-1, :]
    seed[:, 0] = near_white[:, 0]
    seed[:, -1] = near_white[:, -1]
    background = ndimage.binary_propagation(seed, mask=near_white)

    alpha[background] = 0
    data[:, :, 3] = alpha
    image = Image.fromarray(data)

    alpha = np.array(image.getchannel("A"))
    coords = np.argwhere(alpha > 96)
    if coords.size:
        y0, x0 = coords.min(axis=0)
        y1, x1 = coords.max(axis=0) + 1
        pad = 10
        x0 = max(0, int(x0) - pad)
        y0 = max(0, int(y0) - pad)
        x1 = min(image.width, int(x1) + pad)
        y1 = min(image.height, int(y1) + pad)
        image = image.crop((x0, y0, x1, y1))
    return image


def make_background_transparent(path):
    transparent_image(path).save(path)


def atomic_make_background_transparent(path):
    tmp_path = f"{path}.tmp-{os.getpid()}.png"
    transparent_image(path).save(tmp_path)
    os.replace(tmp_path, path)


def bitpack_mask(mask):
    flat = mask.astype(np.uint8).reshape(-1)
    out = bytearray((len(flat) + 7) // 8)
    for idx, value in enumerate(flat):
        if value:
            out[idx >> 3] |= 1 << (7 - (idx & 7))
    return base64.b64encode(bytes(out)).decode("ascii")


def image_mask_metadata(path, max_dim=88):
    image = Image.open(path).convert("RGBA")
    width, height = image.size
    alpha = np.array(image.getchannel("A"))
    opaque = alpha > 96
    coords = np.argwhere(opaque)
    if coords.size == 0:
        return {
            "image_width": width,
            "image_height": height,
            "mask": None,
        }

    scale = min(1.0, float(max_dim) / max(width, height))
    mask_w = max(1, int(round(width * scale)))
    mask_h = max(1, int(round(height * scale)))
    small = image.getchannel("A").resize((mask_w, mask_h), Image.Resampling.LANCZOS)
    small_alpha = np.array(small)
    # Dilate the mask slightly. This bakes in a visual gap during packing
    # while still letting silhouettes nest tighter than rectangles.
    small_mask = ndimage.binary_dilation(small_alpha > 96, iterations=1)

    return {
        "image_width": width,
        "image_height": height,
        "mask": {
            "w": mask_w,
            "h": mask_h,
            "bits": bitpack_mask(small_mask),
        },
    }


def call_imagen(prompt, key, model):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1",
            "personGeneration": "dont_allow",
        },
    }
    result = post_json(url, payload, key)
    predictions = result.get("predictions") or []
    if not predictions:
        raise RuntimeError(f"Gemini image request returned no predictions: {result}")
    image_b64 = (
        predictions[0].get("bytesBase64Encoded")
        or predictions[0].get("image", {}).get("imageBytes")
        or predictions[0].get("imageBytes")
    )
    if not image_b64:
        raise RuntimeError(f"Gemini image response did not include image bytes: {result}")
    return base64.b64decode(image_b64)


def call_gemini_image(prompt, key, model):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseModalities": ["IMAGE"]
        }
    }
    result = post_json(url, payload, key)
    candidates = result.get("candidates") or []
    for candidate in candidates:
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                return base64.b64decode(inline_data["data"])
    raise RuntimeError(f"Gemini image response did not include image bytes: {result}")


def post_json(url, payload, key):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Gemini image request failed: HTTP {exc.code}: {body}") from exc


def generate_image(species, key, model, force=False, variant="collage"):
    field = "detail_image" if variant == "detail" else "image"
    output_path = os.path.join(HOME, "BirdSongs", "Extracted", species[field])
    if os.path.exists(output_path) and not force:
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    prompt = prompt_for(species["com_name"], species["sci_name"], variant)
    if model.startswith("imagen-"):
        image_bytes = call_imagen(prompt, key, model)
    else:
        image_bytes = call_gemini_image(prompt, key, model)
    tmp_path = f"{output_path}.tmp-{os.getpid()}.png"
    with open(tmp_path, "wb") as handle:
        handle.write(image_bytes)
    make_background_transparent(tmp_path)
    os.replace(tmp_path, output_path)
    if variant == "detail":
        species["has_detail_image"] = True
    else:
        species["has_image"] = True
    return True


def index_path_for_hours(hours):
    if hours == TODAY_HOURS:
        return os.path.join(OUTPUT_DIR, "index-today.json")
    if hours <= 0 or hours >= 1000000:
        return os.path.join(OUTPUT_DIR, "index-all.json")
    return os.path.join(OUTPUT_DIR, f"index-{int(hours)}h.json")


def write_index(species, hours):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "hours": hours,
        "species_count": len(species),
        "species": species,
    }
    index_path = index_path_for_hours(hours)
    tmp_path = f"{index_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, index_path)
    if int(hours) == 24:
        tmp_path = f"{INDEX_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, INDEX_PATH)


def attach_image_metadata(species):
    for bird in species:
        image_path = os.path.join(HOME, "BirdSongs", "Extracted", bird["image"])
        bird["has_image"] = os.path.exists(image_path)
        detail_image = bird.get("detail_image")
        if not detail_image:
            detail_path = image_path_for(bird["sci_name"], bird["com_name"], "detail")
            detail_image = os.path.relpath(detail_path, os.path.join(HOME, "BirdSongs", "Extracted"))
            bird["detail_image"] = detail_image
        detail_path = os.path.join(HOME, "BirdSongs", "Extracted", detail_image)
        bird["has_detail_image"] = os.path.exists(detail_path)
        bird.pop("image_width", None)
        bird.pop("image_height", None)
        bird.pop("mask", None)
        if not bird["has_image"]:
            continue
        try:
            meta = image_mask_metadata(image_path)
        except Exception as exc:
            print(f"Could not read mask for {bird['com_name']}: {exc}", file=sys.stderr)
            continue
        bird["image_width"] = meta["image_width"]
        bird["image_height"] = meta["image_height"]
        if meta["mask"]:
            bird["mask"] = meta["mask"]
        if bird["has_detail_image"]:
            try:
                atomic_make_background_transparent(detail_path)
            except Exception as exc:
                print(f"Could not clean detail image for {bird['com_name']}: {exc}", file=sys.stderr)


def read_existing_species():
    for path in (index_path_for_hours(24), INDEX_PATH):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
                return payload.get("species") or []
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return []


def read_existing_species_for_hours(hours):
    try:
        with open(index_path_for_hours(hours), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
            return payload.get("species") or []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def build_index(args, hours):
    species = get_species(hours, args.limit)
    if args.generate and species:
        key = api_key()
        if not key:
            print("No GEMINI_API_KEY or /etc/birdnet/gemini_api_key; wrote index only.", file=sys.stderr)
        else:
            generated = 0
            for bird in species:
                if args.sci and bird.get("sci_name") != args.sci:
                    continue
                if generated >= args.max_new:
                    break
                variants = ("collage", "detail") if args.variant == "both" else (args.variant,)
                for variant in variants:
                    if generated >= args.max_new:
                        break
                    has_field = "has_detail_image" if variant == "detail" else "has_image"
                    if bird.get(has_field) and not args.force:
                        continue
                    try:
                        generate_image(bird, key, args.model, args.force, variant)
                        generated += 1
                    except Exception as exc:
                        print(f"Could not generate {variant} image for {bird['com_name']}: {exc}", file=sys.stderr)
                    time.sleep(1)

    attach_image_metadata(species)
    enrich_metadata(species, fetch_missing=not args.skip_enrich)
    write_index(species, hours)
    print(f"Wrote {index_path_for_hours(hours)} with {len(species)} species.")


def main():
    parser = argparse.ArgumentParser(description="Build BirdNET-Pi bird collage image index.")
    parser.add_argument("--hours", type=int, default=24, help="recent detection window")
    parser.add_argument("--all-ranges", action="store_true", help="build every collage time-window index")
    parser.add_argument("--limit", type=int, default=28, help="max birds in the collage")
    parser.add_argument("--generate", action="store_true", help="generate missing images with Gemini")
    parser.add_argument("--force", action="store_true", help="regenerate existing images")
    parser.add_argument("--model", default=os.environ.get("GEMINI_IMAGE_MODEL", DEFAULT_MODEL))
    parser.add_argument("--max-new", type=int, default=3, help="max new images per run")
    parser.add_argument("--sci", default="", help="only generate images for this scientific name")
    parser.add_argument("--variant", choices=("collage", "detail", "both"), default="both", help="image variant to generate")
    parser.add_argument("--skip-enrich", action="store_true", help="skip slow external metadata lookups")
    args = parser.parse_args()

    if args.all_ranges:
        for hours in RANGE_HOURS:
            build_index(args, hours)
    else:
        build_index(args, args.hours)


if __name__ == "__main__":
    main()
