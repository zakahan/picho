# Volcengine Audio ASR Provider

`volcengine` transcribes `.wav` and `.mp3` files through Volcengine Doubao Speech ASR.

The provider accepts local audio files from the `read` tool. Because the ASR API consumes an audio URL, the provider first uploads the local file to Volcengine TOS with public-read access, then submits the resulting URL to the ASR task API and polls until a transcript is available.

## Flow

1. `read` receives a `.wav` or `.mp3` file.
2. `parser_audio.py` selects `audio_asr.provider = "volcengine"`.
3. `audio/volcengine.py` uploads the local file to TOS.
4. The TOS public URL is submitted to Doubao Speech ASR.
5. The ASR result is converted to a common `AudioTranscript`.
6. `parser_audio.py` renders the transcript as markdown and caches it.

## Configuration

```json
{
  "agent": {
    "builtin": {
      "tool_config": {
        "read": {
          "audio_asr": {
            "provider": "volcengine",
            "language": "zh-CN",
            "enable_punc": true,
            "enable_itn": true,
            "include_utterances": true,
            "timeout_seconds": 60,
            "poll_interval_seconds": 2,
            "volcengine": {
              "tos_bucket": "my-bucket",
              "tos_region": "cn-beijing",
              "sample_rate": 16000,
              "channel": 1,
              "codec": "raw"
            }
          }
        }
      }
    }
  }
}
```

`tos_bucket` is optional if `DEFAULT_TOS_BUCKET` is set.

## Environment Variables

Credential values are read from environment variables, not from the config file.

Default variable names:

| Variable | Purpose |
|----------|---------|
| `VOLCENGINE_ACCESS_KEY` | TOS access key |
| `VOLCENGINE_SECRET_KEY` | TOS secret key |
| `VOLCENGINE_SPEECH_API_KEY` | Doubao Speech ASR API key |
| `DEFAULT_TOS_BUCKET` | TOS bucket when `tos_bucket` is omitted |

The config can override the variable names:

```json
{
  "audio_asr": {
    "provider": "volcengine",
    "volcengine": {
      "tos_bucket_env": "MY_TOS_BUCKET",
      "tos_access_key_env": "MY_VOLC_AK",
      "tos_secret_key_env": "MY_VOLC_SK",
      "speech_api_key_env": "MY_ASR_KEY"
    }
  }
}
```

## Options

Shared `audio_asr` options:

| Field | Default | Description |
|-------|---------|-------------|
| `language` | `null` | ASR language code, for example `zh-CN`; `null` lets the provider auto-detect when supported |
| `enable_punc` | `false` | Enable punctuation |
| `enable_itn` | `true` | Enable inverse text normalization |
| `enable_ddc` | `false` | Enable semantic smoothing |
| `enable_speaker_info` | `false` | Enable speaker diarization |
| `include_utterances` | `true` | Include sentence-level timestamps in markdown |
| `include_words` | `false` | Reserved for providers that return word-level details |
| `vad_segment` | `false` | Enable VAD segmentation |
| `timeout_seconds` | `60` | Maximum wait time for the ASR result |
| `poll_interval_seconds` | `2` | Query interval while the ASR task is processing |

Volcengine-specific options:

| Field | Default | Description |
|-------|---------|-------------|
| `tos_bucket` | `null` | TOS bucket; falls back to `tos_bucket_env` |
| `tos_bucket_env` | `DEFAULT_TOS_BUCKET` | Environment variable for the TOS bucket |
| `tos_region` | `cn-beijing` | TOS region |
| `tos_access_key_env` | `VOLCENGINE_ACCESS_KEY` | Environment variable for the TOS access key |
| `tos_secret_key_env` | `VOLCENGINE_SECRET_KEY` | Environment variable for the TOS secret key |
| `speech_api_key_env` | `VOLCENGINE_SPEECH_API_KEY` | Environment variable for the ASR API key |
| `sample_rate` | `16000` | Audio sample rate sent to ASR |
| `channel` | `1` | Audio channel count |
| `codec` | `raw` | Audio codec, usually `raw` |

## Output

The provider returns text and, when available, sentence-level utterances. The shared audio parser renders them as markdown:

```markdown
# Audio transcription

- File: meeting.wav
- Provider: volcengine
- Task ID: ...
- Duration: 12000 ms

## Transcript

...

## Utterances

- [00:00.000 --> 00:01.800] ...
```

## Notes

- The uploaded TOS object is public-read because the ASR API consumes a URL.
- ASR results are cached under the configured cache root's `files` directory.
- The cache key includes the source file mtime and key ASR options so switching providers or language does not reuse an incompatible transcript.
