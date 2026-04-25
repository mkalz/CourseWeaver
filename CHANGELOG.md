# Changelog

## v0.1.0 - 2026-04-25

### Added
- AI weekly summary generation with provider support for OpenAI-compatible APIs and Gemini.
- Audio generation for weekly summaries using Gemini TTS or ElevenLabs.
- Optional PDF extracted-text audio generation with minimum length threshold.
- Two-phase processing pipeline: first generate all summaries, then generate audio.
- Job artifact tracking in `files/ai_jobs/` with input/output markdown files and `manifest.jsonl`.
- Resume mode improvements for missing audio generation based on existing outputs and manifest state.
- Gemini TTS health reporting (GREEN/YELLOW/RED) and status indicators in the Web UI.

### Changed
- PDF text extraction is now embedded directly into week pages instead of requiring separate pages.
- External downloadable link fallback now uses inline source warnings instead of creating separate note pages.
- Gemini TTS throttling defaults and adaptive backoff tuning to reduce rate-limit failures.
- Web UI now exposes full AI/TTS controls, PDF audio presets, and richer run statistics.

### Fixed
- Resolved PCM audio decoding issues by wrapping Gemini L16 PCM responses into WAV.
- Fixed duplicate filename collisions for mirrored files and generated audio assets.
- Corrected `parse_float` scope issue in Web UI backend.
- Improved retry handling for 429/5xx errors, including `Retry-After` support.
