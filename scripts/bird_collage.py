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
INDEX_SCHEMA_VERSION = 4
NEW_BIRD_BADGE_HOURS = 24
_IMAGE_LIBS = None
_LABELS_CACHE = None
_META_CACHE = None


def image_libs():
    global _IMAGE_LIBS
    if _IMAGE_LIBS is None:
        import numpy as np
        from scipy import ndimage
        from PIL import Image
        _IMAGE_LIBS = (np, ndimage, Image)
    return _IMAGE_LIBS


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


def db_data_mtime():
    paths = (DB_PATH, f"{DB_PATH}-wal", f"{DB_PATH}-shm")
    mtimes = [os.path.getmtime(path) for path in paths if os.path.exists(path)]
    return max(mtimes) if mtimes else 0


def load_labels():
    global _LABELS_CACHE
    if _LABELS_CACHE is not None:
        return _LABELS_CACHE
    try:
        with open(LABELS_PATH, "r", encoding="utf-8") as handle:
            _LABELS_CACHE = json.load(handle)
    except FileNotFoundError:
        _LABELS_CACHE = {}
    return _LABELS_CACHE


def load_meta_cache():
    global _META_CACHE
    if _META_CACHE is None:
        _META_CACHE = read_json(META_PATH, {})
    return _META_CACHE


def ensure_detection_indexes(conn):
    conn.execute(
        "CREATE INDEX IF NOT EXISTS detections_Date_Time "
        "ON detections (Date, Time)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS detections_Sci_Name_Date_Time "
        "ON detections (Sci_Name, Date, Time)"
    )


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


def parse_detection_timestamp(value):
    text = str(value or "").strip()
    if not text or text == "manual seed":
        return None
    stamp = text[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def is_new_bird(first_heard, now=None, badge_hours=NEW_BIRD_BADGE_HOURS):
    first_seen = parse_detection_timestamp(first_heard)
    if first_seen is None:
        return False
    now = now or dt.datetime.now()
    age = now - first_seen
    return dt.timedelta(0) <= age <= dt.timedelta(hours=badge_hours)


def image_path_for(sci_name, com_name, variant="collage"):
    digest_source = f"{sci_name}|{com_name}" if variant == "collage" else f"{sci_name}|{com_name}|{variant}"
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    suffix = "" if variant == "collage" else f"-{variant}"
    return os.path.join(IMAGE_DIR, f"{slugify(com_name)}{suffix}-{digest}.png")


def open_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-2000")
    ensure_detection_indexes(conn)
    return conn


def get_species(hours, limit, conn=None, labels=None, recordings_cache=None):
    labels = labels if labels is not None else load_labels()
    close_conn = conn is None
    if close_conn:
        conn = open_db()
    else:
        ensure_detection_indexes(conn)
    today_only = hours == TODAY_HOURS
    all_time = (hours <= 0 and hours != TODAY_HOURS) or hours >= 1000000
    cutoff = dt.datetime.now() - dt.timedelta(hours=max(1, hours))
    cutoff_date = cutoff.strftime("%Y-%m-%d")
    cutoff_time = cutoff.strftime("%H:%M:%S")
    def fetch_rows(use_all_time):
        if use_all_time:
            index_hint = "INDEXED BY detections_Sci_Name_Date_Time"
            where_sql = ""
            params = []
        elif today_only:
            index_hint = "INDEXED BY detections_Date_Time"
            where_sql = "WHERE d.Date = DATE('now', 'localtime')"
            params = []
        else:
            index_hint = "INDEXED BY detections_Date_Time"
            where_sql = "WHERE (d.Date > ? OR (d.Date = ? AND d.Time >= ?))"
            params = [cutoff_date, cutoff_date, cutoff_time]
        recent_sql = f"""
            WITH recent AS (
              SELECT
                d.Sci_Name,
                COALESCE(NULLIF(MAX(d.Com_Name), ''), d.Sci_Name) AS Com_Name,
                COUNT(*) AS RecentCount,
                MAX(d.Date || ' ' || d.Time) AS LastHeard
              FROM detections d {index_hint}
              {where_sql}
              GROUP BY d.Sci_Name
              ORDER BY LastHeard DESC
              LIMIT ?
            )
            SELECT
              r.Sci_Name,
              r.Com_Name,
              r.RecentCount,
              r.LastHeard,
              MIN(a.Date || ' ' || a.Time) AS FirstHeard,
              SUM(CASE WHEN a.Date = DATE('now', 'localtime') THEN 1 ELSE 0 END) AS TodayCount,
              COUNT(*) AS TotalCount
            FROM recent r
            JOIN detections a INDEXED BY detections_Sci_Name_Date_Time
              ON a.Sci_Name = r.Sci_Name
            GROUP BY r.Sci_Name, r.Com_Name, r.RecentCount, r.LastHeard
            ORDER BY r.LastHeard DESC
        """
        return conn.execute(recent_sql, tuple(params + [limit])).fetchall()

    def fetch_recordings_by_species(sci_names, per_species_limit):
        if not sci_names:
            return {}
        # Single-query batched fetch avoids N+1 SELECTs for each bird, and
        # ROW_NUMBER keeps SQLite from returning years of old rows when we
        # only need a few recordings for the modal.
        placeholders = ",".join(["?"] * len(sci_names))
        rows = conn.execute(
            f"""
            WITH ranked AS (
              SELECT
                Sci_Name,
                Date,
                Time,
                File_Name,
                Confidence,
                ROW_NUMBER() OVER (
                  PARTITION BY Sci_Name
                  ORDER BY Date DESC, Time DESC
                ) AS rn
              FROM detections INDEXED BY detections_Sci_Name_Date_Time
              WHERE Sci_Name IN ({placeholders})
            )
            SELECT Sci_Name, Date, Time, File_Name, Confidence
            FROM ranked
            WHERE rn <= ?
            ORDER BY Sci_Name, Date DESC, Time DESC
            """,
            tuple(sci_names) + (per_species_limit,),
        ).fetchall()
        grouped = {sci_name: [] for sci_name in sci_names}
        for row in rows:
            bucket = grouped.get(row["Sci_Name"])
            if bucket is not None:
                bucket.append({
                    "date": row["Date"],
                    "time": row["Time"],
                    "file_name": row["File_Name"],
                    "confidence": row["Confidence"],
                })
        return grouped

    rows = fetch_rows(all_time)
    sci_names = [row["Sci_Name"] for row in rows]
    all_recordings = fetch_recordings_by_species(sci_names, 6) if rows else {}
    species = []
    for row in rows:
        sci_name = row["Sci_Name"]
        com_name = row["Com_Name"] or labels.get(sci_name, sci_name)
        image_path = image_path_for(sci_name, com_name)
        detail_image_path = image_path_for(sci_name, com_name, "detail")
        rel_image = os.path.relpath(image_path, os.path.join(HOME, "BirdSongs", "Extracted"))
        rel_detail_image = os.path.relpath(detail_image_path, os.path.join(HOME, "BirdSongs", "Extracted"))
        cache_key = (hours, sci_name)
        if recordings_cache is not None and cache_key in recordings_cache:
            recordings = recordings_cache[cache_key]
        else:
            recordings = all_recordings.get(sci_name, [])
            if recordings_cache is not None:
                recordings_cache[cache_key] = recordings
        species.append({
            "sci_name": sci_name,
            "com_name": com_name,
            "recent_count": row["RecentCount"],
            "today_count": row["TodayCount"] or 0,
            "total_count": row["TotalCount"],
            "last_heard": row["LastHeard"],
            "first_heard": row["FirstHeard"],
            "is_new_bird": is_new_bird(row["FirstHeard"]),
            "image": rel_image,
            "detail_image": rel_detail_image,
            "has_image": os.path.exists(image_path),
            "has_detail_image": os.path.exists(detail_image_path),
            "slug": slugify(f"{com_name}-{sci_name}"),
            "recordings": [
                {
                    "date": rec["date"],
                    "time": rec["time"],
                    "file_name": rec["file_name"],
                    "confidence": rec["confidence"],
                }
                for rec in recordings
            ],
        })
    if close_conn:
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
    cache = load_meta_cache()
    changed = False
    today = dt.date.today().isoformat()
    retry_before = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    for bird in species:
        sci_name = bird.get("sci_name", "")
        cached = cache.get(sci_name, {})
        checked_at = cached.get("date_created", "")
        should_fetch = (
            fetch_missing
            and (
                "description" not in cached
                or (not cached.get("description") and checked_at < retry_before)
            )
        )
        if should_fetch:
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
    np, ndimage, Image = image_libs()
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
    np, _, _ = image_libs()
    flat = mask.astype(np.uint8).reshape(-1)
    out = bytearray((len(flat) + 7) // 8)
    for idx, value in enumerate(flat):
        if value:
            out[idx >> 3] |= 1 << (7 - (idx & 7))
    return base64.b64encode(bytes(out)).decode("ascii")


def image_mask_metadata(path, max_dim=88):
    np, ndimage, Image = image_libs()
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


def payload_signature(species):
    source = json.dumps(species, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(source.encode("utf-8")).hexdigest()


def write_index(species, hours):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    payload = {
        "index_schema": INDEX_SCHEMA_VERSION,
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "hours": hours,
        "species_count": len(species),
        "payload_sig": payload_signature(species),
        "species": species,
    }
    index_path = index_path_for_hours(hours)
    tmp_path = f"{index_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.write("\n")
    os.replace(tmp_path, index_path)
    if int(hours) == 24:
        tmp_path = f"{INDEX_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(tmp_path, INDEX_PATH)


def reusable_image_meta(existing_by_species, bird):
    if not existing_by_species:
        return None
    existing = existing_by_species.get(bird["sci_name"])
    if not existing:
        return None
    if existing.get("image") != bird.get("image"):
        return None
    if existing.get("detail_image") != bird.get("detail_image"):
        return None
    if existing.get("image_version") != bird.get("image_version"):
        return None
    if not existing.get("has_image"):
        return None
    if not existing.get("image_width") or not existing.get("image_height"):
        return None
    if not existing.get("mask"):
        return None
    return existing


def attach_image_metadata(species, existing_by_species=None, image_meta_cache=None):
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
        bird.pop("image_version", None)
        bird.pop("detail_image_version", None)
        if bird["has_image"]:
            bird["image_version"] = int(os.path.getmtime(image_path))
        if bird["has_detail_image"]:
            bird["detail_image_version"] = int(os.path.getmtime(detail_path))
        if not bird["has_image"]:
            continue
        existing = reusable_image_meta(existing_by_species, bird)
        if existing:
            bird["image_width"] = existing["image_width"]
            bird["image_height"] = existing["image_height"]
            bird["mask"] = existing["mask"]
            continue
        cache_key = (image_path, bird.get("image_version"))
        meta = image_meta_cache.get(cache_key) if image_meta_cache is not None else None
        if meta is None:
            try:
                meta = image_mask_metadata(image_path)
            except Exception as exc:
                print(f"Could not read mask for {bird['com_name']}: {exc}", file=sys.stderr)
                continue
            if image_meta_cache is not None:
                image_meta_cache[cache_key] = meta
        bird["image_width"] = meta["image_width"]
        bird["image_height"] = meta["image_height"]
        if meta["mask"]:
            bird["mask"] = meta["mask"]


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


def bird_image_present(bird, variant):
    field = "detail_image" if variant == "detail" else "image"
    flag = "has_detail_image" if variant == "detail" else "has_image"
    rel_path = bird.get(field)
    if not rel_path:
        return False
    abs_path = os.path.join(HOME, "BirdSongs", "Extracted", rel_path)
    return bool(bird.get(flag)) and os.path.exists(abs_path)


def metadata_lookup_pending(bird, meta_cache=None):
    if bird.get("description"):
        return False
    cache = meta_cache if meta_cache is not None else load_meta_cache()
    cached = cache.get(bird.get("sci_name", ""), {})
    if cached.get("description"):
        return False
    checked_at = cached.get("date_created", "")
    retry_before = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    if "description" in cached and checked_at >= retry_before:
        return False
    return True


def index_has_pending_work(payload, args):
    species = payload.get("species") or []
    variants = ("collage", "detail") if args.variant == "both" else (args.variant,)
    meta_cache = None if args.skip_enrich else load_meta_cache()
    for bird in species:
        if args.sci and bird.get("sci_name") != args.sci:
            continue
        if bird_image_present(bird, "collage") and not (
            bird.get("image_width") and bird.get("image_height") and bird.get("mask")
        ):
            return True
        if args.generate:
            for variant in variants:
                if not bird_image_present(bird, variant):
                    return True
        if not args.skip_enrich and metadata_lookup_pending(bird, meta_cache):
            return True
    return False


def index_is_current(hours, args):
    index_path = index_path_for_hours(hours)
    if not os.path.exists(index_path):
        return False
    if os.path.getmtime(__file__) > os.path.getmtime(index_path):
        return False
    if db_data_mtime() > os.path.getmtime(index_path):
        return False
    payload = read_json(index_path, {})
    if payload.get("index_schema") != INDEX_SCHEMA_VERSION:
        return False
    if not payload.get("species") and payload.get("species_count", 0):
        return False
    return not index_has_pending_work(payload, args)


def indexes_are_current(hours_list, args):
    if args.force:
        return False
    return all(index_is_current(hours, args) for hours in hours_list)


def build_index(args, hours, conn=None, labels=None, recordings_cache=None, image_meta_cache=None):
    species = get_species(
        hours,
        args.limit,
        conn=conn,
        labels=labels,
        recordings_cache=recordings_cache,
    )
    existing_by_species = {}
    if not args.force:
        existing_by_species = {
            bird.get("sci_name"): bird
            for bird in read_existing_species_for_hours(hours)
            if bird.get("sci_name")
        }
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
                generated_any = False
                for variant in variants:
                    has_field = "has_detail_image" if variant == "detail" else "has_image"
                    if bird.get(has_field) and not args.force:
                        continue
                    try:
                        generate_image(bird, key, args.model, args.force, variant)
                        generated_any = True
                    except Exception as exc:
                        print(f"Could not generate {variant} image for {bird['com_name']}: {exc}", file=sys.stderr)
                    time.sleep(1)
                if generated_any:
                    generated += 1

    attach_image_metadata(species, existing_by_species, image_meta_cache=image_meta_cache)
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
    parser.add_argument("--max-new", type=int, default=3, help="max species to generate per run")
    parser.add_argument("--sci", default="", help="only generate images for this scientific name")
    parser.add_argument("--variant", choices=("collage", "detail", "both"), default="both", help="image variant to generate")
    parser.add_argument("--skip-enrich", action="store_true", help="skip slow external metadata lookups")
    parser.add_argument("--if-stale", action="store_true", help="exit without rebuilding when indexes are already current")
    args = parser.parse_args()

    hours_list = RANGE_HOURS if args.all_ranges else (args.hours,)
    if args.if_stale and indexes_are_current(hours_list, args):
        print("Collage indexes already current; nothing to do.")
        return

    labels = load_labels()
    if args.all_ranges:
        conn = open_db()
        recordings_cache = {}
        image_meta_cache = {}
        try:
            for hours in hours_list:
                build_index(
                    args,
                    hours,
                    conn=conn,
                    labels=labels,
                    recordings_cache=recordings_cache,
                    image_meta_cache=image_meta_cache,
                )
        finally:
            conn.close()
    else:
        build_index(args, args.hours, labels=labels)


if __name__ == "__main__":
    main()
