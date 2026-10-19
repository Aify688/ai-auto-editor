import type { AudioEffect } from "../types";

// Mirrors video_editor/audiofx.py.
export const AUDIO_EFFECTS: { value: AudioEffect; label: string; hint: string }[] = [
  { value: "none", label: "None", hint: "Original sound" },
  { value: "denoise", label: "Reduce noise", hint: "Cuts hiss and background hum" },
  { value: "voice", label: "Voice enhance", hint: "Clearer, fuller speech" },
  { value: "deep", label: "Deep voice", hint: "Lower pitch" },
  { value: "chipmunk", label: "Chipmunk", hint: "Higher pitch" },
  { value: "robot", label: "Robot", hint: "Metallic voice" },
  { value: "echo", label: "Echo", hint: "Room echo" },
  { value: "radio", label: "Radio", hint: "Narrow band, like a radio" },
];
