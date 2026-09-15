# Quran YouTube Feed — GitHub Actions Pipeline

## Role

You are working directly on the connected GitHub repository for the Quran application's YouTube Shorts feed.

Your task is to build the complete **backend-free YouTube content pipeline** using:

- GitHub Actions
- YouTube Data API v3
- GitHub repository secrets
- Python
- generated JSON feed
- GitHub Pages
- static HTTPS delivery

The Android application must **never call YouTube Data API directly** and must **never contain the YouTube API key**.

The repository itself acts as the source/control system, while GitHub Actions acts as the scheduled content-generation pipeline.

Do not ask the user to manually create code files, workflows, commits, or GitHub configuration that you can perform through the connected GitHub repository. Inspect the repository first, then implement everything that can be implemented automatically.

Do not expose, print, commit, or store the YouTube API key anywhere in the repository.

---

# 1. First inspect the connected repository

Before modifying anything:

1. Determine the repository owner/name.
2. Determine the default branch.
3. Inspect the existing directory structure.
4. Check whether `.github/workflows` already exists.
5. Check whether any existing GitHub Actions workflows exist.
6. Check whether `data`, `config`, or `scripts` directories already exist.
7. Check whether GitHub Pages configuration already exists.
8. Check the README and existing repository conventions.
9. Reuse existing conventions where practical.
10. Do not overwrite unrelated files.

If an existing YouTube feed pipeline already exists, improve it rather than blindly creating duplicates.

Do not modify the user's Android application code in this task unless explicitly requested.

The scope of this task is the GitHub content pipeline.

---

# 2. Target repository structure

Create or converge toward this structure:

```text
quran-youtube-feed/
├── .github/
│   └── workflows/
│       ├── refresh-youtube-feed.yml
│       └── deploy-youtube-feed-pages.yml
│
├── config/
│   └── youtube_sources.json
│
├── data/
│   └── youtube_feed.json
│
├── scripts/
│   └── fetch_youtube_feed.py
│
├── .gitignore
└── README.md
```

Do not create unnecessary files.

---

# 3. Security requirements

## 3.1 YouTube API key

The YouTube API key must be supplied to GitHub Actions through:

```text
YOUTUBE_API_KEY
```

using the GitHub Actions repository secret:

```text
${{ secrets.YOUTUBE_API_KEY }}
```

The key must never be:

- committed to Git
- stored in JSON
- stored in Python source
- stored in YAML
- stored in README
- stored in logs
- printed to stdout
- included in generated JSON
- included in artifacts
- included in GitHub Pages
- included in Android code

The Python script must read:

```python
import os

api_key = os.environ["YOUTUBE_API_KEY"]
```

Never use a hardcoded fallback API key.

If the environment variable is missing, fail clearly with a useful error such as:

```text
YOUTUBE_API_KEY environment variable is not configured.
```

Do not print the value.

---

# 4. GitHub Actions permissions

Use the principle of least privilege.

The feed refresh workflow should use:

```yaml
permissions:
  contents: write
```

Only give permissions required by the workflow.

The Pages deployment workflow should use the minimum permissions required for GitHub Pages deployment, such as:

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

Do not create a Personal Access Token.

Use the automatically provided:

```text
GITHUB_TOKEN
```

for repository commits.

---

# 5. YouTube API architecture

The architecture must be:

```text
GitHub Actions
      ↓
Python feed generator
      ↓
YouTube Data API v3
      ↓
validate/filter/deduplicate
      ↓
youtube_feed.json
      ↓
Git commit
      ↓
GitHub Pages
      ↓
public HTTPS JSON
```

The Android application is not part of the API request path.

The Android application will later consume:

```text
youtube_feed.json
```

over HTTPS.

---

# 6. Content source configuration

Create:

```text
config/youtube_sources.json
```

Use a normalized configuration format such as:

```json
{
  "queries": [
    "quran recitation shorts",
    "beautiful quran recitation",
    "quran ayah shorts",
    "surah recitation shorts"
  ],
  "channels": [],
  "playlists": [],
  "maxResultsPerQuery": 25,
  "targetFeedSize": 100,
  "minimumFeedSize": 30
}
```

Do not hardcode search queries directly into Python.

The Python script must read this configuration.

The architecture must support adding trusted channel IDs and playlist IDs later without changing Python code.

---

# 7. Primary content strategy

Support both:

## Search discovery

Use YouTube Data API:

```text
search.list
```

for configured search queries.

## Curated sources

Support configured:

```text
channel IDs
playlist IDs
```

for more controlled content.

When possible, curated channels/playlists should be preferred over unrestricted keyword results.

Do not assume every YouTube search result is appropriate for the Quran app.

---

# 8. YouTube API calls

Use the API efficiently.

For search discovery:

```text
search.list
```

Collect video IDs.

Do not call:

```text
videos.list
```

once per video.

Instead batch video IDs where possible.

Example conceptual flow:

```text
search.list
    ↓
[A, B, C, D, E, ...]
    ↓
one or more videos.list calls
```

Use the minimum number of requests necessary.

The script should not make API requests merely because the Android application has opened the feed.

Only the scheduled GitHub Action fetches YouTube data.

---

# 9. Quota-awareness

Design the workflow around YouTube API quota constraints.

Do not call YouTube for every application user.

The intended behavior is:

```text
1000 app users
        ↓
0 YouTube Data API calls from Android
```

Only GitHub Actions uses the API.

Default schedule should be approximately every 6 hours.

That means:

```text
4 refreshes/day
```

The exact number of search queries must be configurable through:

```text
config/youtube_sources.json
```

The implementation must avoid unnecessary pagination.

Do not repeatedly fetch the same pages when the required feed size has already been reached.

---

# 10. Short-video filtering

The feed is for the application's Quran Shorts experience.

Do not blindly publish every search result.

At minimum validate:

```text
video exists
video is public
video is embeddable
video has usable metadata
video has an acceptable duration
video ID is valid
video is not duplicated
```

Use duration as an input to filtering, but do not incorrectly assume:

```text
videoDuration=short
```

means a YouTube Short specifically.

The system should distinguish between:

```text
short-duration video
```

and:

```text
actual YouTube Shorts classification
```

Do not claim that every video returned by a short-duration filter is a YouTube Short.

---

# 11. Content quality validation

The validation layer should be separate from API retrieval.

Create a clear pipeline:

```text
API response
    ↓
normalize
    ↓
validate
    ↓
filter
    ↓
deduplicate
    ↓
rank
    ↓
minimum-count check
    ↓
publish
```

Keep validation logic testable.

Possible validation checks:

```text
privacyStatus == public
embeddable == true
video ID exists
title exists
thumbnail exists
duration <= configured maximum
```

Also reject obviously unusable API responses.

Do not implement unreliable AI-based semantic classification unless explicitly requested.

For now use deterministic rules and configured sources/queries.

---

# 12. Deduplication

Deduplicate strictly by:

```text
videoId
```

The same video may appear in several search queries.

It must only appear once in the resulting feed.

Expected behavior:

```text
query 1 → video A
query 2 → video A
query 3 → video B

final:
A
B
```

not:

```text
A
A
B
```

---

# 13. Feed ranking

Keep ranking deterministic and simple.

Prioritize:

1. approved/curated sources
2. valid videos
3. recent videos
4. relevant content
5. stable ordering

Do not attempt to recreate YouTube's recommendation algorithm.

The final feed should be predictable.

---

# 14. Target feed size

Use configurable values:

```json
{
  "targetFeedSize": 100,
  "minimumFeedSize": 30
}
```

The script should attempt to produce approximately 100 valid videos.

Do not fail simply because exactly 100 cannot be obtained.

For example:

```text
100 → valid
80  → valid
50  → valid
30  → valid
29  → failure
10  → failure
0   → failure
```

The exact thresholds must come from configuration.

---

# 15. Critical failure protection

This is mandatory.

Never overwrite the existing valid feed with an invalid/empty feed.

The safe sequence must be:

```text
fetch
  ↓
validate
  ↓
generate temporary JSON
  ↓
validate generated JSON
  ↓
check minimum item count
  ↓
ONLY THEN replace youtube_feed.json
```

If the API fails:

```text
FAIL
↓
keep previous youtube_feed.json
```

If YouTube returns too few valid items:

```text
FAIL
↓
keep previous youtube_feed.json
```

If Python crashes:

```text
FAIL
↓
keep previous youtube_feed.json
```

The GitHub Action should exit with a non-zero status for a failed refresh.

---

# 16. Generated JSON format

Create:

```text
data/youtube_feed.json
```

with a stable schema.

Use:

```json
{
  "schemaVersion": 1,
  "feedVersion": 1,
  "generatedAt": "2026-09-15T12:00:00Z",
  "expiresAt": "2026-09-16T12:00:00Z",
  "items": [
    {
      "videoId": "VIDEO_ID",
      "title": "Video title",
      "channelId": "CHANNEL_ID",
      "channelTitle": "Channel name",
      "thumbnailUrl": "https://...",
      "publishedAt": "2026-09-14T12:00:00Z",
      "durationSeconds": 45,
      "category": "recitation"
    }
  ]
}
```

Do not copy the complete raw YouTube API response into the JSON.

Generate a small normalized manifest containing only information needed by the Android feed.

---

# 17. Feed version

Every successful feed generation must increment:

```text
feedVersion
```

Do not increment the version when the workflow fails.

The version should be deterministic and easy for the Android app to compare.

If the existing feed contains:

```text
feedVersion: 17
```

the next successful feed should become:

```text
feedVersion: 18
```

Do not reset to 1 on every run.

---

# 18. Timestamps

Generate:

```text
generatedAt
expiresAt
```

using UTC ISO-8601 timestamps.

Do not use local machine time without timezone information.

The Android application should later be able to determine:

```text
when feed was generated
when it should be considered stale
```

Use a sensible expiration window such as 24 hours unless the repository configuration specifies otherwise.

---

# 19. Category normalization

Each generated item should contain a simple category.

For example:

```text
recitation
ayah
surah
reminder
tafseer
other
```

Do not perform complex semantic inference.

For keyword-based results, use deterministic category mapping based on the configured query/source.

For curated channels/playlists, allow the configuration to specify the category.

---

# 20. Existing feed compatibility

The resulting JSON must remain independent of the Android implementation.

Do not create Android-specific classes or Kotlin code in this repository.

The purpose of the JSON is to provide a stable content contract.

The future Android model can map it to:

```text
YouTubeShort
```

and then to the existing:

```text
FeedItem
```

architecture.

---

# 21. Python dependencies

Use a minimal dependency set.

Prefer:

```text
requests
isodate
```

plus Python standard-library modules.

Do not introduce unnecessary frameworks.

The workflow should install pinned or appropriately bounded versions where practical.

The script should work with Python 3.12.

---

# 22. Python implementation quality

The Python script must:

- use functions with clear responsibilities
- use type hints where useful
- handle HTTP errors
- handle malformed API responses
- handle missing fields
- handle quota errors
- handle rate-limit errors
- handle network failures
- avoid printing secrets
- produce useful log output
- return non-zero exit code on failure
- never partially overwrite the production feed

Structure the code approximately as:

```text
load_config()
load_api_key()
youtube_request()
search_videos()
fetch_video_details()
parse_duration()
validate_video()
deduplicate_videos()
rank_videos()
build_feed()
validate_feed()
write_feed_atomically()
```

Do not put all logic into one giant function.

---

# 23. Atomic feed generation

Never directly write production JSON while it is still being generated.

Use a temporary file.

Conceptual flow:

```text
youtube_feed.json
       ↑
old valid feed

youtube_feed.tmp.json
       ↑
new candidate

validate candidate
       ↓
replace production file
```

If validation fails, delete the temporary file and leave the production feed unchanged.

---

# 24. GitHub Actions refresh workflow

Create:

```text
.github/workflows/refresh-youtube-feed.yml
```

The workflow should:

1. run on manual dispatch
2. run on a 6-hour schedule
3. checkout the repository
4. configure Python
5. install dependencies
6. expose `YOUTUBE_API_KEY` through the environment
7. run the feed generator
8. validate the generated file
9. commit only when the feed changed
10. push using `GITHUB_TOKEN`

Use:

```yaml
permissions:
  contents: write
```

Do not create a PAT.

The workflow must not echo secrets.

---

# 25. Manual workflow execution

Include:

```yaml
workflow_dispatch:
```

This is mandatory.

The workflow must first be manually testable before relying on the scheduled execution.

Do not remove the manual trigger after adding the schedule.

---

# 26. Scheduled execution

After the workflow is complete, use:

```yaml
schedule:
  - cron: "0 */6 * * *"
```

Keep the schedule easy to locate and modify.

Do not create multiple overlapping refresh schedules.

Use one feed refresh workflow.

---

# 27. No-op commits

Do not create a Git commit when:

```text
youtube_feed.json
```

didn't change.

Use:

```bash
git diff --cached --quiet
```

or an equivalent safe check.

Expected behavior:

```text
feed changed
→ commit + push

feed unchanged
→ no commit
→ workflow succeeds
```

---

# 28. GitHub Pages deployment

Create:

```text
.github/workflows/deploy-youtube-feed-pages.yml
```

The deployment workflow must publish only the public feed content.

Do not publish:

```text
config/youtube_sources.json
```

unless intentionally required.

Do not publish:

```text
scripts/
```

Do not publish secrets.

Prepare a Pages directory such as:

```text
public/
└── youtube_feed.json
```

Optionally include a minimal:

```text
public/index.html
```

but the important public resource is:

```text
youtube_feed.json
```

---

# 29. Pages deployment trigger

Do not rely on a simple push workflow if the feed refresh commit is made with `GITHUB_TOKEN`.

Instead, trigger Pages deployment when the refresh workflow completes successfully.

Use:

```yaml
workflow_run:
  workflows:
    - "Refresh YouTube Feed"
  types:
    - completed
```

and ensure deployment happens only when:

```text
conclusion == success
```

This prevents deploying a failed refresh.

---

# 30. Pages permissions

Use only the required permissions:

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

Use GitHub's current official Pages deployment actions.

Do not invent a custom deployment mechanism.

---

# 31. Public endpoint

The final public resource must be accessible from an HTTPS URL similar to:

```text
https://<github-username>.github.io/<repository-name>/youtube_feed.json
```

The exact URL must be determined from the connected repository owner/name.

Do not hardcode an assumed username.

Document the final URL in `README.md` once Pages is configured.

---

# 32. GitHub Pages configuration

If repository settings can be configured through the available GitHub integration, configure Pages appropriately.

Otherwise, create the workflow correctly and clearly document the single remaining UI setting the user must enable.

Do not claim that Pages is fully active unless it has actually been verified.

After deployment, verify the public JSON URL.

---

# 33. HTTP and CDN behavior

The feed is a static JSON resource.

Do not build a server.

The architecture is:

```text
GitHub Actions
→ GitHub repository
→ GitHub Pages
→ HTTPS
→ static JSON
```

Treat GitHub Pages as the first delivery layer.

The architecture should remain portable so the feed can later be moved behind:

```text
Cloudflare
```

or another CDN without changing the JSON schema.

Do not add Cloudflare unless explicitly requested.

---

# 34. README documentation

Update or create `README.md`.

Document:

```text
Project purpose
Repository structure
How the YouTube API key is supplied
Required repository secret
How the workflow works
How to manually run the workflow
Scheduled refresh interval
JSON schema
GitHub Pages URL
Quota strategy
Failure protection
How to modify queries
How to add trusted channels/playlists
```

Never document the actual API key.

Use:

```text
YOUTUBE_API_KEY
```

as the secret name only.

---

# 35. Repository secret verification

You cannot read the secret value back.

Do not attempt to retrieve or expose it.

The workflow should verify only that the environment variable exists.

For example:

```python
if not api_key:
    raise RuntimeError(...)
```

Do not log:

```text
api_key
```

even partially.

---

# 36. Google API behavior

The script should provide clear diagnostics for common YouTube API failures, including:

```text
403 quota exceeded
403 forbidden
400 invalid request
401/403 credential problems
404 missing resource
429 rate limiting
network timeout
malformed JSON
```

But never print the API key.

---

# 37. Feed expiry and YouTube data freshness

Do not treat the generated JSON as a permanent archive.

Refresh it regularly.

The normal six-hour workflow is intentionally far shorter than the maximum storage period allowed by current YouTube API policy.

The generated feed should contain:

```text
generatedAt
expiresAt
```

and the Android application can later reject extremely stale feeds.

---

# 38. Do not download or extract YouTube media

The pipeline must store metadata/video IDs only.

Never implement:

```text
YouTube → MP4 download
YouTube → MP3 extraction
YouTube → audio extraction
YouTube → local cached video
```

The Android application will later play the video through the supported YouTube embedded player.

---

# 39. Do not create fake media URLs

Never generate:

```text
mp4Url
audioUrl
streamUrl
```

from YouTube.

Only store the YouTube:

```text
videoId
```

and presentation metadata required by the app.

---

# 40. Validation tests

Before finalizing, test the Python code locally inside the GitHub Actions environment or through a CI-style execution.

At minimum test:

```text
missing API key
invalid API response
duplicate videos
too few valid videos
successful feed generation
existing feed preservation on failure
JSON schema validity
duration parsing
empty search response
```

Do not perform real YouTube API calls unless the configured secret is available to the workflow.

Do not fabricate successful API results.

---

# 41. Run the workflow manually

After creating the workflow:

1. Commit the implementation.
2. Trigger `Refresh YouTube Feed` manually.
3. Inspect the workflow result.
4. Inspect generated `data/youtube_feed.json`.
5. Verify the feed contains valid items.
6. Verify no secret appears in logs.
7. Verify a commit is created only when the feed changes.
8. Verify Pages deployment runs after successful refresh.
9. Verify the public JSON URL.

Do not tell the user that this succeeded unless you can actually verify it.

---

# 42. Git commits

You are authorized to make the repository changes required for this task.

Use clear commits.

Recommended commit sequence:

```text
feat: add YouTube feed generator
```

then:

```text
ci: add YouTube feed refresh workflow
```

then:

```text
ci: deploy YouTube feed to GitHub Pages
```

However, if the connected GitHub tooling works better with a single coherent commit, a single commit is acceptable.

Do not modify unrelated project history.

---

# 43. Important: existing repository contents

Before committing:

- preserve unrelated files
- do not overwrite existing workflows
- do not delete existing automation
- do not change Android code
- do not change package names
- do not change application behavior
- do not commit generated secrets
- do not remove existing README content unnecessarily

Merge into the existing repository structure cleanly.

---

# 44. Final verification checklist

Before declaring the task complete, verify:

```text
[ ] Repository inspected
[ ] Config file created
[ ] Python generator created
[ ] Feed JSON created
[ ] Refresh workflow created
[ ] Pages deployment workflow created
[ ] No API key in repository
[ ] YOUTUBE_API_KEY referenced only through secrets
[ ] Workflow uses least-privilege permissions
[ ] GITHUB_TOKEN used instead of PAT
[ ] Manual workflow supported
[ ] Six-hour schedule configured
[ ] API calls are quota-aware
[ ] Video IDs are deduplicated
[ ] Videos are validated
[ ] Minimum feed threshold exists
[ ] Existing feed is protected on failures
[ ] JSON schema is stable
[ ] feedVersion exists
[ ] generatedAt exists
[ ] expiresAt exists
[ ] YouTube media is never downloaded
[ ] Feed contains metadata/video IDs only
[ ] Pages deployment is configured
[ ] Public JSON endpoint is known/verified
[ ] README documents the setup
[ ] Git changes are committed
[ ] Final repository state is clean
```

---

# 45. Final report to the user

After completing the work, report only what was actually accomplished.

Include:

```text
Repository:
<owner/repository>

Files created/updated:
<list>

GitHub Actions:
<status>

YouTube feed generator:
<status>

GitHub Pages:
<status>

Public feed URL:
<URL if verified>

Manual workflow:
<name>

Scheduled refresh:
<schedule>

Remaining manual configuration:
<only if something cannot be performed through the connected integration>
```

Do not claim that a secret was configured unless the connected tooling actually allows and confirms that operation.

Do not expose secret values.

Do not claim GitHub Pages is live until the public endpoint has been verified.

---

# 46. Final architectural contract

The finished repository must implement exactly this architecture:

```text
                    GITHUB ACTIONS
                         │
                  every 6 hours
                         │
                         ▼
               fetch_youtube_feed.py
                         │
                         ▼
                YouTube Data API v3
                         │
              ┌──────────┴──────────┐
              │                     │
        search.list            videos.list
              │                     │
              └──────────┬──────────┘
                         ▼
                     validate
                         ▼
                    deduplicate
                         ▼
                       rank
                         ▼
                 minimum check
                         ▼
                 youtube_feed.json
                         │
                         ▼
                     Git commit
                         │
                         ▼
                    GitHub Pages
                         │
                         ▼
                HTTPS static JSON
                         │
                         ▼
                   Android app
                         │
                         ▼
                  existing feed
               /        |         \
              /         |          \
     Native Short   YouTube Short   Ad
```

The YouTube Data API must exist only on the GitHub Actions side.

The Android application must consume only the generated static JSON feed.

The design must support future movement from GitHub Pages to a CDN without changing the feed schema or the Android data contract.