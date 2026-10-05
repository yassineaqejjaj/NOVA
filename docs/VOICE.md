# Voice for NOVA's orb

**Status: implemented** (phase 1 + self-hosted TTS) — see §7. Goal: talk to the orb (speech-to-text, STT), let it answer aloud (text-to-speech, TTS), and make the orb
express *listening* and *speaking* — in French and English — without weakening NOVA's security model
(C0–C3 classification, audit, redaction).

## 1. What already exists and what voice needs

| Need | In NOVA today | Missing |
|---|---|---|
| Orb with states | `NovaOrb` (idle, thinking, working, waiting, clarification, completed), 7 colors | `listening`, `speaking` states driven by audio level |
| Input | composer (`useSendIntent`), slash Skills | microphone capture → transcript in the composer |
| Output | streamed answers (`LLMProvider.stream`, SSE) | sentence-by-sentence speech of the answer |
| Language | interface FR/EN, NOVA answers in the request language | STT/TTS language selection (follows the interface or the detected language) |
| LLM | vLLM / OpenAI-compatible / **Anthropic Claude** | — (Anthropic offers no STT/TTS API: voice needs a separate engine) |

## 2. Speech-to-text options

| Option | Where audio goes | Quality FR/EN | Latency | Cost / infra | Verdict |
|---|---|---|---|---|---|
| **Web Speech API** (`SpeechRecognition`) | Chrome/Edge: Google/Microsoft cloud; Safari: Apple (partly on-device); **not in Firefox** | Good | Real-time, interim results | None | Prototype only: audio leaves to a third party chosen by the browser — incompatible with C2/C3 work |
| **Self-hosted Whisper** (`faster-whisper`, CTranslate2 int8) as a Railway service | Stays in NOVA's infrastructure | Very good on FR with `small`/`medium`; `base` acceptable | Push-to-talk: transcript a few seconds after release on CPU; real-time needs a GPU | One CPU service (2–4 GB RAM for `small`), open source (MIT) | **Recommended** |
| Cloud STT (Deepgram, AssemblyAI, Azure, Google, OpenAI) | Third-party processor | Excellent, streaming | Lowest | Per-minute pricing, DPA required | Possible later if a processor is approved |

## 3. Text-to-speech options

| Option | Where text goes | Voice quality | Latency | Cost / infra | Verdict |
|---|---|---|---|---|---|
| **Browser `speechSynthesis`** | Local OS voices are on-device (macOS/iOS/Windows); Chrome's "Google" voices are **network** voices | OS-dependent, decent on Apple devices | Instant | None | **Phase 1**, restricted to `voice.localService === true` voices |
| **Piper** (self-hosted, MIT) | Stays in NOVA | Clear, slightly synthetic; several FR voices | Very fast on CPU | Tiny CPU service | **Phase 2**: one consistent "voice of NOVA" on every device |
| Kokoro-82M (self-hosted, Apache-2.0) | Stays in NOVA | More natural; FR voice available | Fast on CPU | Small CPU service | Alternative to Piper — quality to validate in French |
| XTTS-v2 | Stays in NOVA | Very natural, voice cloning | Needs a GPU | **Non-commercial licence (CPML)** | Excluded |
| Cloud TTS (ElevenLabs, Azure Neural, OpenAI) | Third-party processor | Best | Low, streaming | Per-character pricing, DPA | Only with an approved processor |

## 4. Interaction design

* **Push-to-talk** in the composer (mic button, or hold `Space` when the composer is empty): the orb switches to
  *listening*, its halo follows the microphone level (Web Audio `AnalyserNode`); on release the transcript fills the
  composer — the user reviews it and sends (no blind execution of a misheard request).
* **Read aloud**: a "Listen" control on NOVA's answers, and an optional "speak answers" toggle; speech starts at the
  first complete sentence of the stream (sentence chunking), the orb switches to *speaking* and pulses with the audio.
* **Barge-in**: speaking again (or pressing the mic) stops playback.
* **Hands-free mode** (later): voice activity detection (Silero VAD, MIT) to start/stop listening automatically.
* **Language**: the interface language by default; Whisper can also detect it per utterance.

## 5. Security and compliance

* Microphone only on explicit user action; no audio is stored — only the transcript, which is treated exactly like typed
  input (audit, PII redaction, prompt-injection defenses).
* **C2/C3**: reading an answer aloud can expose confidential content to people nearby. When an answer carries C2/C3
  context, speaking is off by default and the orb shows the classification before speaking.
* With self-hosted Whisper/Piper no new data processor is introduced; the Anthropic API remains the only external one.
* Browser STT (Web Speech API) would send audio to the browser vendor's cloud: excluded for production.

## 6. Recommendation

1. **Phase 1 (≈ 2 days)** — `voice` service on Railway with `faster-whisper` (`small`, int8) behind
   `POST /api/v1/voice/transcribe` (audio from `MediaRecorder`, webm/opus); push-to-talk in the composer; orb
   *listening*/*speaking* states; read-aloud with local browser voices; FR/EN; C2/C3 rule above; E2E tests with a
   recorded sample.
2. **Phase 2 (≈ 2–3 days)** — Piper (or Kokoro after a French listening test) behind `POST /api/v1/voice/speak`
   (streamed audio) for one consistent NOVA voice; sentence-level streaming from the LLM stream; barge-in.
3. **Phase 3 (optional)** — hands-free mode (VAD), and a GPU host if real-time transcription becomes necessary.

Open questions for the product owner: which voice personality (choice of 2–3 Piper/Kokoro voices to listen to),
whether speaking answers aloud should ever be allowed for C2/C3 content, and whether a cloud speech processor could
be approved later for lower latency.


## 7. What is implemented

* **Voice service** (`services/voice`, image `infrastructure/docker/voice.Dockerfile`, ≈2 GB with models): faster-whisper
  `small` (int8, CPU) for `POST /transcribe`, Piper (`fr_FR-siwis-medium`, `en_US-amy-medium`) for `POST /speak`.
  Private network only, `X-Voice-Token` shared with NOVA's API; nothing stored or logged.
* **NOVA API** relays `POST /api/v1/voice/transcribe|speak` and `GET /api/v1/voice/status` for signed-in users
  (`NOVA_VOICE_URL`, `NOVA_VOICE_TOKEN`).
* **Talking with NOVA** (`components/voice/voice-session.tsx`): opened from the composer microphone, the Home orb or
  ⌘K. The orb listens (end of speech detected after a pause), the transcript is sent as an **autonomous** request
  (`autonomy=execute_automatically`: NOVA runs workflows without confirmation; external writes still follow
  company policy), NOVA's progress drives the orb, and the answer is spoken and captioned; in hands-free mode it
  listens again. Questions are asked aloud and answered by voice; decisions are answered "yes/no".
  Tapping the microphone (or Space) interrupts NOVA.
* **C2/C3 rule**: an answer built on Confidential or Secret context is never read aloud — NOVA says it is on screen
  (tested end-to-end).
* Measured on a laptop CPU: speech synthesis ≈0.5 s per sentence; transcription ≈1× real time (container) — a 5-second
  request is understood in a few seconds.
