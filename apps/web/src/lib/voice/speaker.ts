"use client";

/** NOVA's voice: synthesized by NOVA's own voice service (Piper), played in the browser; can be interrupted. */
export class VoicePlayer {
  private audio: HTMLAudioElement | null = null;
  private url: string | null = null;
  private abort: AbortController | null = null;

  async speak(text: string, language: "fr" | "en"): Promise<void> {
    this.stop();
    this.abort = new AbortController();
    const response = await fetch("/api/v1/voice/speak", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ text: text.slice(0, 2000), language }),
      signal: this.abort.signal,
    });
    if (!response.ok) throw new Error(`speak ${response.status}`);
    this.url = URL.createObjectURL(await response.blob());
    const audio = new Audio(this.url);
    this.audio = audio;
    await new Promise<void>((resolve, reject) => {
      audio.onended = () => resolve();
      audio.onpause = () => resolve(); // stopped (barge-in)
      audio.onerror = () => reject(new Error("audio playback failed"));
      void audio.play().catch(reject);
    });
    this.release();
  }

  stop(): void {
    this.abort?.abort();
    this.audio?.pause();
    this.release();
  }

  private release(): void {
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
    this.audio = null;
  }
}

export async function transcribe(blob: Blob, language?: "fr" | "en"): Promise<{ text: string; language: string }> {
  const form = new FormData();
  const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", blob, `speech.${ext}`);
  if (language) form.append("language", language);
  const response = await fetch("/api/v1/voice/transcribe", { method: "POST", body: form, credentials: "include" });
  if (!response.ok) throw new Error(`transcribe ${response.status}`);
  return response.json();
}
