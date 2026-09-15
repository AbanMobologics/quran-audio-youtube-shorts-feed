#!/usr/bin/env python3
"""
fetch_youtube_feed.py - Scheduled YouTube Shorts Feed Generator

Fetches, validates, deduplicates, and ranks Quran YouTube Shorts metadata
using the YouTube Data API v3 and writes an atomic static JSON feed.

Designed for GitHub Actions scheduled execution.
Never logs or prints the API key.
Never replaces a valid feed if fewer than minimumFeedSize items are retrieved.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("fetch_youtube_feed")

# Base API URLs
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Duration regex fallback for ISO-8601 strings (e.g. PT45S, PT1M10S, PT1H2M3S)
ISO_DURATION_REGEX = re.compile(
    r"^P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


def load_api_key() -> str:
    """Safely retrieves the YouTube Data API key from environment.

    Raises:
        RuntimeError: If YOUTUBE_API_KEY environment variable is not configured.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY environment variable is not configured.")
    return api_key


def load_config(config_path: Path) -> dict[str, Any]:
    """Loads and validates feed source configuration.

    Args:
        config_path: Path to the JSON configuration file.

    Returns:
        dict: Parsed configuration dictionary with default fallbacks.
    """
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Apply sensible defaults
    config.setdefault("queries", [
        "quran recitation shorts",
        "beautiful quran recitation",
        "quran ayah shorts",
        "surah recitation shorts",
    ])
    config.setdefault("channels", [])
    config.setdefault("playlists", [])
    config.setdefault("maxResultsPerQuery", 25)
    config.setdefault("targetFeedSize", 100)
    config.setdefault("minimumFeedSize", 30)
    config.setdefault("feedTtlHours", 24)
    config.setdefault("maxDurationSeconds", 60)

    return config


def parse_iso8601_duration(duration_str: str) -> int:
    """Parses an ISO-8601 duration string into total integer seconds.

    Supports isodate library if available, with robust regex fallback.

    Args:
        duration_str: ISO-8601 duration string (e.g., 'PT45S', 'PT1M', 'PT1M15S').

    Returns:
        int: Duration in seconds.
    """
    if not duration_str:
        return 0

    try:
        import isodate  # type: ignore

        parsed = isodate.parse_duration(duration_str)
        return int(parsed.total_seconds())
    except (ImportError, Exception):
        match = ISO_DURATION_REGEX.match(duration_str)
        if not match:
            return 0

        parts = match.groupdict()
        days = int(parts["days"] or 0)
        hours = int(parts["hours"] or 0)
        minutes = int(parts["minutes"] or 0)
        seconds = int(parts["seconds"] or 0)
        return days * 86400 + hours * 3600 + minutes * 60 + seconds


def sanitize_error_message(msg: str, api_key: str | None = None) -> str:
    """Removes any accidental occurrence of the API key from error strings."""
    if api_key and api_key in msg:
        msg = msg.replace(api_key, "[REDACTED_API_KEY]")
    return msg


def youtube_request(
    session: requests.Session,
    endpoint: str,
    params: dict[str, Any],
    api_key: str,
    timeout: int = 15,
) -> dict[str, Any]:
    """Executes a YouTube Data API v3 request with quota awareness and error diagnostics.

    Never logs the API key or raw URL containing the key.

    Args:
        session: Persistent requests session.
        endpoint: API endpoint relative to base (e.g., 'search', 'videos').
        params: Request query parameters (excluding key).
        api_key: YouTube API key.
        timeout: Request timeout in seconds.

    Returns:
        dict: Parsed JSON response.

    Raises:
        RuntimeError: On HTTP or API error with diagnostic details.
    """
    url = f"{YOUTUBE_API_BASE}/{endpoint}"
    req_params = dict(params)
    req_params["key"] = api_key
    headers = {
        "Referer": "https://github.com/AbanMobologics/quran-audio-youtube-shorts-feed",
        "User-Agent": "QuranShortsFeedPipeline/1.0",
    }

    try:
        response = session.get(url, params=req_params, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        raise RuntimeError(f"YouTube API request to '{endpoint}' timed out after {timeout} seconds.")
    except requests.exceptions.RequestException as e:
        clean_err = sanitize_error_message(str(e), api_key)
        raise RuntimeError(f"YouTube API network error for '{endpoint}': {clean_err}")

    if response.status_code != 200:
        status_code = response.status_code
        try:
            err_data = response.json().get("error", {})
            err_msg = err_data.get("message", "Unknown error")
            errors = err_data.get("errors", [])
            reasons = [e.get("reason", "") for e in errors if isinstance(e, dict)]
        except Exception:
            err_msg = response.text[:200]
            reasons = []

        sanitized_msg = sanitize_error_message(err_msg, api_key)

        if status_code == 403:
            if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                raise RuntimeError(
                    f"YouTube API Error [403]: Daily quota exceeded. Details: {sanitized_msg}"
                )
            raise RuntimeError(
                f"YouTube API Error [403]: Access forbidden/permissions issue. Details: {sanitized_msg}"
            )
        elif status_code == 400:
            if "expired" in sanitized_msg.lower() or "keyexpired" in "".join(reasons).lower():
                raise RuntimeError(
                    f"YouTube API Error [400]: API key has expired. Please renew or create a new API key in Google Cloud Console. Details: {sanitized_msg}"
                )
            raise RuntimeError(
                f"YouTube API Error [400]: Invalid request parameter. Details: {sanitized_msg}"
            )
        elif status_code == 401:
            raise RuntimeError(
                f"YouTube API Error [401]: Invalid credentials or unauthorized API key. Details: {sanitized_msg}"
            )
        elif status_code == 404:
            raise RuntimeError(
                f"YouTube API Error [404]: Requested resource not found. Details: {sanitized_msg}"
            )
        elif status_code == 429:
            raise RuntimeError(
                f"YouTube API Error [429]: Too many requests / rate limit reached. Details: {sanitized_msg}"
            )
        else:
            raise RuntimeError(
                f"YouTube API Error [{status_code}] on '{endpoint}': {sanitized_msg}"
            )

    try:
        return response.json()
    except ValueError as e:
        raise RuntimeError(f"Malformed JSON response from YouTube API '{endpoint}': {e}")


def determine_category(title: str, query_hint: str = "") -> str:
    """Assigns a normalized category based on text indicators.

    Categories: 'recitation', 'ayah', 'surah', 'reminder', 'tafseer', 'other'.
    """
    text = f"{title} {query_hint}".lower()

    if any(k in text for k in ["tafseer", "tafsir", "explanation"]):
        return "tafseer"
    if any(k in text for k in ["ayah", "ayat", "verse", "kursi"]):
        return "ayah"
    if any(k in text for k in ["surah", "soorah", "sura"]):
        return "surah"
    if any(k in text for k in ["reminder", "tadabbur", "reflection", "lesson"]):
        return "reminder"
    if any(k in text for k in ["recitation", "tilawat", "tajweed", "quran", "qari"]):
        return "recitation"

    return "other"


def is_unrecoverable_api_error(error_msg: str) -> bool:
    """Checks whether an error represents a non-retryable credential or quota failure."""
    lower = error_msg.lower()
    fatal_tokens = [
        "quota exceeded",
        "quotaexceeded",
        "dailylimitexceeded",
        "api key has expired",
        "api key expired",
        "invalid credentials",
        "unauthorized api key",
        "api key not valid",
    ]
    return any(token in lower for token in fatal_tokens)


def search_videos(
    session: requests.Session,
    api_key: str,
    queries: list[Any],
    max_results_per_query: int,
) -> list[dict[str, Any]]:
    """Performs search discovery for short Quran videos across configured queries.

    Uses search.list with type=video and videoDuration=short.
    """
    candidates: list[dict[str, Any]] = []

    for q_item in queries:
        if isinstance(q_item, dict):
            query_str = q_item.get("query", "")
            preset_cat = q_item.get("category", "")
        else:
            query_str = str(q_item)
            preset_cat = ""

        if not query_str.strip():
            continue

        logger.info("Searching YouTube for query: '%s'", query_str)
        params = {
            "part": "id,snippet",
            "type": "video",
            "videoDuration": "short",
            "q": query_str,
            "maxResults": min(max_results_per_query, 50),
        }

        try:
            data = youtube_request(session, "search", params, api_key)
        except RuntimeError as e:
            if is_unrecoverable_api_error(str(e)):
                raise
            logger.warning("Search query '%s' failed: %s", query_str, e)
            continue

        items = data.get("items", [])
        logger.info("Found %d search results for query: '%s'", len(items), query_str)

        for it in items:
            vid_id = it.get("id", {}).get("videoId")
            if vid_id:
                candidates.append({
                    "videoId": vid_id,
                    "isCurated": False,
                    "categoryHint": preset_cat or query_str,
                })

    return candidates


def fetch_playlist_videos(
    session: requests.Session,
    api_key: str,
    playlists: list[Any],
) -> list[dict[str, Any]]:
    """Fetches video IDs from curated playlists."""
    candidates: list[dict[str, Any]] = []

    for pl in playlists:
        pl_id = pl.get("id") if isinstance(pl, dict) else str(pl)
        cat = pl.get("category", "recitation") if isinstance(pl, dict) else "recitation"

        if not pl_id:
            continue

        logger.info("Fetching playlist items for playlist: '%s'", pl_id)
        params = {
            "part": "snippet,contentDetails",
            "playlistId": pl_id,
            "maxResults": 50,
        }

        try:
            data = youtube_request(session, "playlistItems", params, api_key)
        except RuntimeError as e:
            if is_unrecoverable_api_error(str(e)):
                raise
            logger.warning("Playlist '%s' fetch failed: %s", pl_id, e)
            continue

        for it in data.get("items", []):
            vid_id = it.get("contentDetails", {}).get("videoId") or it.get("snippet", {}).get("resourceId", {}).get("videoId")
            if vid_id:
                candidates.append({
                    "videoId": vid_id,
                    "isCurated": True,
                    "categoryHint": cat,
                })

    return candidates


def fetch_channel_videos(
    session: requests.Session,
    api_key: str,
    channels: list[Any],
) -> list[dict[str, Any]]:
    """Fetches candidate video IDs from curated channels."""
    candidates: list[dict[str, Any]] = []

    for ch in channels:
        ch_id = ch.get("id") if isinstance(ch, dict) else str(ch)
        cat = ch.get("category", "recitation") if isinstance(ch, dict) else "recitation"

        if not ch_id:
            continue

        logger.info("Searching curated channel: '%s'", ch_id)
        params = {
            "part": "id,snippet",
            "channelId": ch_id,
            "type": "video",
            "videoDuration": "short",
            "maxResults": 25,
        }

        try:
            data = youtube_request(session, "search", params, api_key)
        except RuntimeError as e:
            if is_unrecoverable_api_error(str(e)):
                raise
            logger.warning("Channel '%s' search failed: %s", ch_id, e)
            continue

        for it in data.get("items", []):
            vid_id = it.get("id", {}).get("videoId")
            if vid_id:
                candidates.append({
                    "videoId": vid_id,
                    "isCurated": True,
                    "categoryHint": cat,
                })

    return candidates


def batch_fetch_video_details(
    session: requests.Session,
    api_key: str,
    video_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetches details for video IDs in batches of up to 50 via videos.list.

    Drastically minimizes API quota usage (1 quota unit per 50 videos).
    """
    details_map: dict[str, dict[str, Any]] = {}
    chunk_size = 50

    for i in range(0, len(video_ids), chunk_size):
        chunk = video_ids[i:i + chunk_size]
        joined_ids = ",".join(chunk)
        logger.info("Batch fetching details for %d videos (batch %d)", len(chunk), (i // chunk_size) + 1)

        params = {
            "part": "snippet,contentDetails,status",
            "id": joined_ids,
            "maxResults": len(chunk),
        }

        data = youtube_request(session, "videos", params, api_key)
        for item in data.get("items", []):
            vid_id = item.get("id")
            if vid_id:
                details_map[vid_id] = item

    return details_map


def validate_and_normalize_video(
    raw_video: dict[str, Any],
    candidate_meta: dict[str, Any],
    max_duration_seconds: int = 60,
) -> dict[str, Any] | None:
    """Validates video quality, privacy, embeddability, and duration constraints.

    Returns normalized dictionary matching feed item schema, or None if rejected.
    """
    status = raw_video.get("status", {})
    snippet = raw_video.get("snippet", {})
    content_details = raw_video.get("contentDetails", {})

    # 1. Video must be public
    if status.get("privacyStatus") != "public":
        return None

    # 2. Video must be embeddable
    if not status.get("embeddable", True):
        return None

    # 3. Valid duration <= max_duration_seconds (and > 0)
    duration_iso = content_details.get("duration", "")
    duration_secs = parse_iso8601_duration(duration_iso)
    if duration_secs <= 0 or duration_secs > max_duration_seconds:
        return None

    # 4. Mandatory metadata check
    video_id = raw_video.get("id")
    title = snippet.get("title", "").strip()
    channel_id = snippet.get("channelId", "").strip()
    channel_title = snippet.get("channelTitle", "").strip()
    published_at = snippet.get("publishedAt", "").strip()

    if not (video_id and title and channel_id and channel_title and published_at):
        return None

    # Pick best available thumbnail URL
    thumbnails = snippet.get("thumbnails", {})
    thumb_url = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url")
        or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    )

    category = determine_category(title, candidate_meta.get("categoryHint", ""))

    return {
        "videoId": video_id,
        "title": title,
        "channelId": channel_id,
        "channelTitle": channel_title,
        "thumbnailUrl": thumb_url,
        "publishedAt": published_at,
        "durationSeconds": duration_secs,
        "category": category,
        "_isCurated": candidate_meta.get("isCurated", False),
    }


def deduplicate_and_rank_videos(
    valid_videos: list[dict[str, Any]],
    target_feed_size: int,
) -> list[dict[str, Any]]:
    """Deduplicates strictly on videoId, giving precedence to curated items,

    and ranks by curated status then publication recency.
    """
    seen_ids: set[str] = set()
    unique_items: list[dict[str, Any]] = []

    # Sort first: curated first, then newest publishedAt descending
    sorted_candidates = sorted(
        valid_videos,
        key=lambda v: (
            1 if v.get("_isCurated") else 0,
            v.get("publishedAt", ""),
        ),
        reverse=True,
    )

    for item in sorted_candidates:
        vid_id = item["videoId"]
        if vid_id not in seen_ids:
            seen_ids.add(vid_id)
            # Remove internal sort helper field
            clean_item = {k: v for k, v in item.items() if not k.startswith("_")}
            unique_items.append(clean_item)

    # Bound to targetFeedSize if we exceeded it
    if len(unique_items) > target_feed_size:
        unique_items = unique_items[:target_feed_size]

    return unique_items


def load_previous_feed_version(feed_file: Path) -> int:
    """Reads the previous feedVersion from an existing production feed file."""
    if not feed_file.is_file():
        return 0
    try:
        with open(feed_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return int(data.get("feedVersion", 0))
    except Exception as e:
        logger.warning("Could not read previous feedVersion from %s: %s", feed_file, e)
        return 0


def build_feed(
    items: list[dict[str, Any]],
    previous_feed_path: Path,
    ttl_hours: int = 24,
) -> dict[str, Any]:
    """Constructs the normalized feed manifest conforming to the schema."""
    prev_version = load_previous_feed_version(previous_feed_path)
    new_version = prev_version + 1

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)

    return {
        "schemaVersion": 1,
        "feedVersion": new_version,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAt": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": items,
    }


def validate_feed(feed: dict[str, Any], minimum_feed_size: int) -> None:
    """Validates the generated feed structure and enforces minimum size.

    Raises:
        RuntimeError: If feed schema is violated or item count is below threshold.
    """
    if not isinstance(feed, dict):
        raise RuntimeError("Feed must be a JSON object.")

    if feed.get("schemaVersion") != 1:
        raise RuntimeError(f"Invalid schemaVersion: {feed.get('schemaVersion')}")

    if not isinstance(feed.get("feedVersion"), int) or feed["feedVersion"] < 1:
        raise RuntimeError(f"Invalid feedVersion: {feed.get('feedVersion')}")

    if not feed.get("generatedAt") or not feed.get("expiresAt"):
        raise RuntimeError("Missing generatedAt or expiresAt timestamp.")

    items = feed.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Feed 'items' property must be a list.")

    if len(items) < minimum_feed_size:
        raise RuntimeError(
            f"Feed validation failed: generated {len(items)} items, below minimumFeedSize threshold ({minimum_feed_size})."
        )

    required_keys = {
        "videoId",
        "title",
        "channelId",
        "channelTitle",
        "thumbnailUrl",
        "publishedAt",
        "durationSeconds",
        "category",
    }

    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            raise RuntimeError(f"Item at index {idx} is not an object.")
        missing = required_keys - set(it.keys())
        if missing:
            raise RuntimeError(f"Item {idx} missing required properties: {missing}")


def write_feed_atomically(feed: dict[str, Any], output_path: Path) -> None:
    """Writes the feed to a temporary file, validates it, then atomically replaces output_path.

    Safely protects existing production feed from corruption or partial writes.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(".tmp.json")

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(feed, f, indent=2, ensure_ascii=False)
            f.write("\n")

        # Read back and verify written content
        with open(temp_path, "r", encoding="utf-8") as f:
            reloaded = json.load(f)
            if reloaded.get("feedVersion") != feed.get("feedVersion"):
                raise RuntimeError("Temporary feed file verification failed.")

        # Atomic replacement
        os.replace(temp_path, output_path)
        logger.info("Successfully atomically updated production feed: %s", output_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def run_pipeline(
    config_path: Path,
    feed_output_path: Path,
    session: requests.Session | None = None,
) -> int:
    """Main execution pipeline.

    Returns:
        int: 0 on success, non-zero on failure.
    """
    logger.info("Starting Quran YouTube Shorts feed pipeline...")

    try:
        api_key = load_api_key()
        config = load_config(config_path)
    except Exception as e:
        logger.error("Configuration / secret initialization error: %s", e)
        return 1

    http_session = session or requests.Session()

    try:
        # 1. Collect candidate video IDs across sources
        candidates: list[dict[str, Any]] = []

        # Curated playlists
        if config.get("playlists"):
            candidates.extend(fetch_playlist_videos(http_session, api_key, config["playlists"]))

        # Curated channels
        if config.get("channels"):
            candidates.extend(fetch_channel_videos(http_session, api_key, config["channels"]))

        # Search queries
        if config.get("queries"):
            candidates.extend(
                search_videos(
                    http_session,
                    api_key,
                    config["queries"],
                    config.get("maxResultsPerQuery", 25),
                )
            )

        logger.info("Total candidate video entries gathered: %d", len(candidates))

        # Unique video IDs
        unique_candidate_ids = list({c["videoId"]: c for c in candidates}.keys())
        logger.info("Unique candidate video IDs: %d", len(unique_candidate_ids))

        if not unique_candidate_ids:
            raise RuntimeError("No candidate video IDs were found from any configured source.")

        # 2. Batch fetch full video details
        details_map = batch_fetch_video_details(http_session, api_key, unique_candidate_ids)
        logger.info("Retrieved video details for %d videos", len(details_map))

        # 3. Validate & normalize
        valid_items: list[dict[str, Any]] = []
        meta_by_id = {c["videoId"]: c for c in candidates}

        for vid_id, raw_detail in details_map.items():
            meta = meta_by_id.get(vid_id, {})
            normalized = validate_and_normalize_video(
                raw_detail,
                meta,
                max_duration_seconds=config.get("maxDurationSeconds", 60),
            )
            if normalized:
                valid_items.append(normalized)

        logger.info("Valid short videos after quality/duration filtering: %d", len(valid_items))

        # 4. Deduplicate and rank
        final_items = deduplicate_and_rank_videos(
            valid_items,
            target_feed_size=config.get("targetFeedSize", 100),
        )
        logger.info("Final processed feed item count: %d", len(final_items))

        # 5. Build feed manifest
        feed = build_feed(
            final_items,
            previous_feed_path=feed_output_path,
            ttl_hours=config.get("feedTtlHours", 24),
        )

        # 6. Validate generated feed against minimum size threshold
        validate_feed(feed, minimum_feed_size=config.get("minimumFeedSize", 30))

        # 7. Atomically write to production file
        write_feed_atomically(feed, feed_output_path)

        logger.info(
            "Pipeline successfully generated feed v%d with %d items.",
            feed["feedVersion"],
            len(final_items),
        )
        return 0

    except Exception as e:
        logger.error("Feed generation failed: %s", e)
        logger.info("Preserving existing production feed without changes.")
        return 1


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    config_file = repo_root / "config" / "youtube_sources.json"
    feed_file = repo_root / "data" / "youtube_feed.json"

    exit_code = run_pipeline(config_file, feed_file)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
