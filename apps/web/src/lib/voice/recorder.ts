"use client";

/**
 * Microphone capture for talking with NOVA: MediaRecorder (webm/opus, or mp4/aac on Safari) with a simple
 * energy-based end-of-speech detection — recording stops after a pause once the user has spoken.
 * Audio stays in memory and is only sent to NOVA's own voice service.
 */
export interface Recording {
  blob: Blob;
  durationMs: number;
  heardSpeech: boolean;
}

export interface RecorderOptions {
  onLevel?: (level: number) => void; // 0..1, for the orb
  silenceMs?: number; // end of utterance after this pause
  maxMs?: number;
  noSpeechMs?: number; // give up when nothing is said
}

const MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

export function voiceSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
}

export class VoiceRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private context: AudioContext | null = null;
  private frame = 0;
  private chunks: Blob[] = [];
  private resolve: ((r: Recording) => void) | null = null;
  private started = 0;
  private heard = false;
  private cancelled = false;

  constructor(private readonly options: RecorderOptions = {}) {}

  async start(): Promise<Recording> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const mimeType = MIME_TYPES.find((m) => MediaRecorder.isTypeSupported(m));
    this.recorder = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.chunks = [];
    this.cancelled = false;
    this.heard = false;
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    const done = new Promise<Recording>((resolve) => (this.resolve = resolve));
    this.recorder.onstop = () => {
      const blob = new Blob(this.chunks, { type: this.recorder?.mimeType || "audio/webm" });
      this.cleanup();
      this.resolve?.({ blob, durationMs: performance.now() - this.started, heardSpeech: this.heard && !this.cancelled });
    };
    this.recorder.start(250);
    this.started = performance.now();
    this.watch();
    return done;
  }

  /** Ends the utterance now (button). */
  stop(): void {
    if (this.recorder?.state === "recording") this.recorder.stop();
  }

  /** Discards the recording. */
  cancel(): void {
    this.cancelled = true;
    this.stop();
  }

  private watch(): void {
    const { onLevel, silenceMs = 1300, maxMs = 45_000, noSpeechMs = 8000 } = this.options;
    if (!this.stream) return;
    this.context = new AudioContext();
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 1024;
    this.context.createMediaStreamSource(this.stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    let floor = 0.01;
    let lastVoice = performance.now();
    let voiced = 0;
    const tick = () => {
      analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, v) => sum + v * v, 0) / samples.length);
      floor = Math.min(Math.max(floor * 0.995 + rms * 0.005, 0.004), 0.05); // adaptive noise floor
      const speaking = rms > floor * 3 && rms > 0.012;
      const now = performance.now();
      onLevel?.(Math.min(1, rms * 12));
      if (speaking) {
        voiced += 1;
        lastVoice = now;
        if (voiced > 6) this.heard = true; // ≈100 ms of voice
      }
      const elapsed = now - this.started;
      if ((this.heard && now - lastVoice > silenceMs) || elapsed > maxMs || (!this.heard && elapsed > noSpeechMs)) {
        this.stop();
        return;
      }
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  private cleanup(): void {
    cancelAnimationFrame(this.frame);
    this.options.onLevel?.(0);
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.context?.close().catch(() => undefined);
    this.stream = null;
    this.context = null;
  }
}
