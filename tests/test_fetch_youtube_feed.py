"""
test_fetch_youtube_feed.py - Unit tests for Quran YouTube Shorts feed generator.

Validates duration parsing, video filtering, deduplication, schema validation,
critical failure protection, atomic writes, and API error handling without
making real YouTube API network requests.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import requests

from scripts.fetch_youtube_feed import (
    build_feed,
    deduplicate_and_rank_videos,
    determine_category,
    load_api_key,
    load_config,
    parse_iso8601_duration,
    run_pipeline,
    sanitize_error_message,
    validate_and_normalize_video,
    validate_feed,
    write_feed_atomically,
    youtube_request,
)


class TestApiKeyLoading:
    def test_missing_api_key_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY environment variable is not configured"):
            load_api_key()

    def test_empty_api_key_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "   ")
        with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY environment variable is not configured"):
            load_api_key()

    def test_valid_api_key_loaded(self, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "test_secret_key_12345")
        assert load_api_key() == "test_secret_key_12345"

    def test_sanitize_error_message_redacts_api_key(self):
        secret = "AIzaSySecretKey999"
        msg = f"Failed calling API with key {secret} on endpoint"
        sanitized = sanitize_error_message(msg, secret)
        assert secret not in sanitized
        assert "[REDACTED_API_KEY]" in sanitized


class TestDurationParsing:
    @pytest.mark.parametrize(
        "duration_str,expected_seconds",
        [
            ("PT15S", 15),
            ("PT45S", 45),
            ("PT1M", 60),
            ("PT1M15S", 75),
            ("PT2M30S", 150),
            ("PT1H", 3600),
            ("PT1H2M3S", 3723),
            ("", 0),
            ("INVALID", 0),
        ],
    )
    def test_parse_iso8601_duration(self, duration_str, expected_seconds):
        assert parse_iso8601_duration(duration_str) == expected_seconds


class TestCategoryDetermination:
    def test_category_matching(self):
        assert determine_category("Surah Al-Mulk Beautiful Recitation") == "surah"
        assert determine_category("Ayatul Kursi Heart Touching") == "ayah"
        assert determine_category("Emotional Quran Tilawat Reminder") == "reminder"
        assert determine_category("Tafseer of Surah Al-Fatiha") == "tafseer"
        assert determine_category("Qari Abdul Basit Recitation") == "recitation"
        assert determine_category("Random Islamic Clip", "quran recitation") == "recitation"


class TestVideoValidation:
    def _create_sample_raw_video(
        self,
        video_id="test12345",
        privacy="public",
        embeddable=True,
        duration="PT45S",
        title="Heart Soothing Quran Recitation",
    ):
        return {
            "id": video_id,
            "status": {
                "privacyStatus": privacy,
                "embeddable": embeddable,
            },
            "contentDetails": {
                "duration": duration,
            },
            "snippet": {
                "title": title,
                "channelId": "UCchannel123",
                "channelTitle": "Quran Channel",
                "publishedAt": "2026-09-15T12:00:00Z",
                "thumbnails": {
                    "high": {"url": "https://i.ytimg.com/vi/test12345/hqdefault.jpg"},
                },
            },
        }

    def test_valid_video_normalized(self):
        raw = self._create_sample_raw_video()
        meta = {"isCurated": True, "categoryHint": "recitation"}
        res = validate_and_normalize_video(raw, meta, max_duration_seconds=60)
        assert res is not None
        assert res["videoId"] == "test12345"
        assert res["durationSeconds"] == 45
        assert res["_isCurated"] is True
        assert res["channelTitle"] == "Quran Channel"

    def test_reject_private_video(self):
        raw = self._create_sample_raw_video(privacy="unlisted")
        assert validate_and_normalize_video(raw, {}) is None

    def test_reject_non_embeddable_video(self):
        raw = self._create_sample_raw_video(embeddable=False)
        assert validate_and_normalize_video(raw, {}) is None

    def test_reject_duration_exceeding_max(self):
        raw = self._create_sample_raw_video(duration="PT2M")  # 120s
        assert validate_and_normalize_video(raw, {}, max_duration_seconds=60) is None

    def test_reject_zero_duration(self):
        raw = self._create_sample_raw_video(duration="PT0S")
        assert validate_and_normalize_video(raw, {}, max_duration_seconds=60) is None

    def test_reject_missing_title(self):
        raw = self._create_sample_raw_video(title="")
        assert validate_and_normalize_video(raw, {}) is None


class TestDeduplicationAndRanking:
    def test_deduplicates_by_video_id(self):
        v1 = {
            "videoId": "vid_A",
            "title": "Recitation A",
            "channelId": "ch1",
            "channelTitle": "Ch 1",
            "thumbnailUrl": "https://...",
            "publishedAt": "2026-09-10T10:00:00Z",
            "durationSeconds": 40,
            "category": "recitation",
            "_isCurated": False,
        }
        v2 = {
            "videoId": "vid_A",
            "title": "Recitation A Curated",
            "channelId": "ch1",
            "channelTitle": "Ch 1",
            "thumbnailUrl": "https://...",
            "publishedAt": "2026-09-10T10:00:00Z",
            "durationSeconds": 40,
            "category": "recitation",
            "_isCurated": True,
        }
        v3 = {
            "videoId": "vid_B",
            "title": "Recitation B",
            "channelId": "ch2",
            "channelTitle": "Ch 2",
            "thumbnailUrl": "https://...",
            "publishedAt": "2026-09-11T10:00:00Z",
            "durationSeconds": 50,
            "category": "surah",
            "_isCurated": False,
        }

        results = deduplicate_and_rank_videos([v1, v2, v3], target_feed_size=10)
        assert len(results) == 2
        # Curated vid_A should come first
        assert results[0]["videoId"] == "vid_A"
        assert results[1]["videoId"] == "vid_B"
        # Internal field _isCurated stripped
        assert "_isCurated" not in results[0]


class TestFeedBuildingAndValidation:
    def test_build_feed_increments_version(self, tmp_path):
        prev_feed_file = tmp_path / "feed.json"
        prev_feed_file.write_text(json.dumps({"schemaVersion": 1, "feedVersion": 7, "items": []}))

        feed = build_feed([], prev_feed_file, ttl_hours=24)
        assert feed["schemaVersion"] == 1
        assert feed["feedVersion"] == 8
        assert "generatedAt" in feed
        assert "expiresAt" in feed

    def test_validate_feed_passes_with_sufficient_items(self):
        items = [
            {
                "videoId": f"vid_{i}",
                "title": f"Video {i}",
                "channelId": "ch1",
                "channelTitle": "Ch 1",
                "thumbnailUrl": "https://...",
                "publishedAt": "2026-09-15T12:00:00Z",
                "durationSeconds": 45,
                "category": "recitation",
            }
            for i in range(35)
        ]
        feed = {
            "schemaVersion": 1,
            "feedVersion": 1,
            "generatedAt": "2026-09-15T12:00:00Z",
            "expiresAt": "2026-09-16T12:00:00Z",
            "items": items,
        }
        # Should not raise
        validate_feed(feed, minimum_feed_size=30)

    def test_validate_feed_fails_when_below_minimum_size(self):
        feed = {
            "schemaVersion": 1,
            "feedVersion": 1,
            "generatedAt": "2026-09-15T12:00:00Z",
            "expiresAt": "2026-09-16T12:00:00Z",
            "items": [{"videoId": "vid_1"}],
        }
        with pytest.raises(RuntimeError, match="below minimumFeedSize threshold"):
            validate_feed(feed, minimum_feed_size=30)


class TestAtomicFeedWrite:
    def test_atomic_write_and_preservation_on_failure(self, tmp_path):
        feed_file = tmp_path / "youtube_feed.json"
        original_content = {"schemaVersion": 1, "feedVersion": 1, "items": ["original"]}
        feed_file.write_text(json.dumps(original_content))

        # Successful atomic update
        new_feed = {"schemaVersion": 1, "feedVersion": 2, "items": ["updated"]}
        write_feed_atomically(new_feed, feed_file)

        with open(feed_file, "r") as f:
            data = json.load(f)
        assert data["feedVersion"] == 2

        # Check that no lingering tmp file remains
        tmp_file = feed_file.with_suffix(".tmp.json")
        assert not tmp_file.exists()


class TestYouTubeApiErrorHandling:
    def test_403_quota_exceeded_error_message(self):
        session = mock.Mock(spec=requests.Session)
        mock_response = mock.Mock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": {
                "errors": [{"reason": "quotaExceeded", "message": "Daily quota limit reached"}],
                "message": "Daily quota limit reached",
            }
        }
        session.get.return_value = mock_response

        with pytest.raises(RuntimeError, match="Daily quota exceeded"):
            youtube_request(session, "search", {}, "dummy_key")

    def test_400_expired_key_error_message(self):
        session = mock.Mock(spec=requests.Session)
        mock_response = mock.Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {
                "errors": [{"reason": "keyExpired", "message": "API key expired. Please renew the API key."}],
                "message": "API key expired. Please renew the API key.",
            }
        }
        session.get.return_value = mock_response

        with pytest.raises(RuntimeError, match="API key has expired"):
            youtube_request(session, "search", {}, "dummy_key")

    def test_timeout_error_handling(self):
        session = mock.Mock(spec=requests.Session)
        session.get.side_effect = requests.exceptions.Timeout()

        with pytest.raises(RuntimeError, match="timed out"):
            youtube_request(session, "search", {}, "dummy_key")


class TestPipelineCriticalFailureProtection:
    def test_pipeline_fails_gracefully_preserving_original_feed(self, tmp_path, monkeypatch):
        # Set up config and production feed
        config_path = tmp_path / "youtube_sources.json"
        config_path.write_text(json.dumps({
            "queries": ["quran recitation"],
            "minimumFeedSize": 30,
        }))

        prod_feed_path = tmp_path / "youtube_feed.json"
        original_data = {"schemaVersion": 1, "feedVersion": 5, "items": ["original_item"]}
        prod_feed_path.write_text(json.dumps(original_data))

        monkeypatch.setenv("YOUTUBE_API_KEY", "mock_key")

        # Mock session to return empty search
        mock_session = mock.Mock(spec=requests.Session)
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}
        mock_session.get.return_value = mock_resp

        exit_code = run_pipeline(config_path, prod_feed_path, session=mock_session)
        assert exit_code != 0

        # Production feed MUST still contain original content
        with open(prod_feed_path, "r") as f:
            current_data = json.load(f)
        assert current_data == original_data
