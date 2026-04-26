# Mock Audio ASR Provider

`mock` is the default audio ASR provider for `read` when handling `.wav` and `.mp3` files.

It does not call any external service. It returns a deterministic placeholder transcript that includes the audio file name. This makes it suitable for local development, tests, and verifying that the audio read pipeline is wired correctly before configuring a real ASR vendor.

## Configuration

```json
{
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "audio_asr": {
            "provider": "mock"
          }
        }
      }
    }
  }
}
```

If `audio_asr` is omitted, `mock` is used automatically.

## Behavior

- Supported file extensions: `.wav`, `.mp3`
- Network access: none
- Credentials: none
- Output format: markdown transcript
- Cache: stored under `.picho/cache/files`, keyed by source file mtime and ASR-related config

Example output:

```markdown
# Audio transcription

- File: sample.mp3
- Provider: mock

## Transcript

[Mock ASR transcript for sample.mp3. No external speech recognition service was called.]
```
