# Quran YouTube Shorts Feed — GitHub Actions Pipeline

An automated, backend-free YouTube Shorts content pipeline that generates, validates, and serves a static HTTPS JSON feed for the Quran application.

The mobile application never communicates directly with the YouTube Data API and never bundles an API key. Instead, GitHub Actions runs on a scheduled cadence to query the YouTube Data API v3, sanitize and deduplicate video metadata, validate quality constraints, and deploy the resulting feed directly to GitHub Pages.

---

## 1. Architecture Overview

```text
GitHub Actions Schedule (Every 6 hours)
                 ↓
      fetch_youtube_feed.py
                 ↓
        YouTube Data API v3 (search.list + videos.list batching)
                 ↓
        Quality & Duration Validation (<= 60s, embeddable, public)
                 ↓
        Strict Deduplication & Ranking
                 ↓
        Threshold & Failure Protection (Atomic Write to data/youtube_feed.json)
                 ↓
        Automated Git Commit (Only if modified)
                 ↓
        GitHub Pages Deployment
                 ↓
        Static Public HTTPS Feed
                 ↓
        Quran Android Client (Zero API key / Zero direct quota)
```

---

## 2. Public Endpoint

The production feed is hosted via GitHub Pages:

- **Direct Feed JSON**:
  `https://abanmobologics.github.io/quran-audio-youtube-shorts-feed/youtube_feed.json`
- **Pages Landing Page**:
  `https://abanmobologics.github.io/quran-audio-youtube-shorts-feed/`

---

## 3. Repository Structure

```text
quran-audio-youtube-shorts-feed/
├── .github/
│   └── workflows/
│       ├── refresh-youtube-feed.yml       # Scheduled & manual feed generator workflow
│       └── deploy-youtube-feed-pages.yml  # GitHub Pages deployment workflow
│
├── config/
│   └── youtube_sources.json               # Configured search queries, channels & thresholds
│
├── data/
│   └── youtube_feed.json                  # Production static JSON feed
│
├── scripts/
│   ├── __init__.py
│   └── fetch_youtube_feed.py              # Main pipeline script
│
├── tests/
│   ├── __init__.py
│   └── test_fetch_youtube_feed.py         # Unit tests covering parsing, validation, error handling
│
├── .gitignore                             # Ignores temp files, caches, virtual environments
├── requirements.txt                       # Minimal pinned dependencies
└── README.md                              # Pipeline documentation
```

---

## 4. Security & API Key Management

The YouTube Data API key is provided securely using GitHub Actions repository secrets:

- **Secret Name**: `YOUTUBE_API_KEY`
- Configured in: **GitHub Repository Settings → Secrets and variables → Actions → Repository secrets**

### Security Guarantees:
- The API key is **never** committed to Git, printed in logs, or written to output files.
- The Python generator reads `os.environ["YOUTUBE_API_KEY"]` directly. If missing or empty, it immediately aborts with an informative message without printing secret values.
- Internal error formatters redact any unexpected key occurrences from diagnostic strings before logging.

---

## 5. Feed Schema Specification

The `data/youtube_feed.json` file adheres to a strict schema:

```json
{
  "schemaVersion": 1,
  "feedVersion": 1,
  "generatedAt": "2026-09-15T12:00:00Z",
  "expiresAt": "2026-09-16T12:00:00Z",
  "items": [
    {
      "videoId": "p0y1lA-f8f4",
      "title": "Heart Soothing Quran Recitation | Surah Al-Mulk",
      "channelId": "UCqJkWu_2x6g89K4D4wL_QJw",
      "channelTitle": "Quran Weekly",
      "thumbnailUrl": "https://i.ytimg.com/vi/p0y1lA-f8f4/hqdefault.jpg",
      "publishedAt": "2026-09-10T14:30:00Z",
      "durationSeconds": 48,
      "category": "surah"
    }
  ]
}
```

### Feed Properties:
- `schemaVersion`: Version of the JSON structure (currently `1`).
- `feedVersion`: Monotonically increasing counter incremented on each successful update.
- `generatedAt`: UTC timestamp in ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`).
- `expiresAt`: Cache expiration hint for the Android client (UTC ISO-8601).
- `items`: Ordered array of validated Quran shorts metadata. No direct streaming URLs are included; only YouTube `videoId` and presentation metadata.

---

## 6. Quota Optimization Strategy

YouTube Data API v3 has a default quota of 10,000 units per day. This pipeline is carefully engineered to operate well below this limit:

1. **Scheduled Interval**: Runs every 6 hours (`0 */6 * * *`), resulting in 4 runs per day.
2. **Search Discovery**: Issues targeted `search.list` calls for configured queries.
3. **Batch Video Details**: Candidate video IDs are batched into requests of up to 50 IDs per `videos.list` call (`part=snippet,contentDetails,status`), reducing quota cost from 1 unit per video to 1 unit per 50 videos.
4. **Android Client Independence**: Whether 100 or 1,000,000 users open the Quran app, zero YouTube API calls originate from user devices. All traffic hits GitHub Pages (or an upstream CDN).

---

## 7. Critical Failure Protection & Atomic Writes

The production feed `data/youtube_feed.json` is protected against corruption or partial generation:

1. **Candidate Verification**: Videos are staged into `data/youtube_feed.tmp.json`.
2. **Threshold Guard**: The generator verifies that `len(items) >= minimumFeedSize` (default: 30). If YouTube returns an insufficient number of valid videos or errors out (e.g., quota exceeded or network failure), the script aborts with a non-zero exit code.
3. **Preservation of Existing Feed**: On failure, the temporary file is removed and the previous valid production feed remains completely untouched.
4. **Atomic Swap**: Only when the candidate passes full schema and count validation is `os.replace` used to atomically update `data/youtube_feed.json`.

---

## 8. Modifying Sources and Curated Content

Source queries and curated channels/playlists can be customized in `config/youtube_sources.json`:

```json
{
  "queries": [
    "quran recitation shorts",
    "beautiful quran recitation",
    "quran ayah shorts",
    "surah recitation shorts"
  ],
  "channels": [
    {
      "id": "UC_SOME_CHANNEL_ID",
      "category": "recitation"
    }
  ],
  "playlists": [
    {
      "id": "PL_SOME_PLAYLIST_ID",
      "category": "surah"
    }
  ],
  "maxResultsPerQuery": 25,
  "targetFeedSize": 100,
  "minimumFeedSize": 30,
  "feedTtlHours": 24,
  "maxDurationSeconds": 60
}
```

- **Queries**: Keywords used for YouTube search discovery.
- **Channels**: Trusted channel IDs whose shorts should be prioritized.
- **Playlists**: Curated playlist IDs whose items should be ingested.
- **targetFeedSize**: The maximum number of videos in the final published feed.
- **minimumFeedSize**: Safety cutoff. If fewer than this number of items pass validation, the update aborts.

---

## 9. Running and Testing

### Local Unit Testing
```bash
# Setup environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run unit tests
pytest tests/ -v
```

### Manual Workflow Trigger via GitHub CLI
```bash
gh workflow run "Refresh YouTube Feed"
```

### Manual Workflow Trigger via GitHub Web UI
1. Navigate to **Actions** tab in the repository.
2. Select **Refresh YouTube Feed** from the left sidebar.
3. Click **Run workflow** → select branch `main` → click **Run workflow**.

Upon successful feed refresh, the **Deploy YouTube Feed to GitHub Pages** workflow automatically triggers and publishes the updated JSON to GitHub Pages.
