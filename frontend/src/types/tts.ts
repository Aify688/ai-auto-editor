export interface TtsVoice {
  name: string;
  lang: string;
  sample: string;
}

export interface TtsStatus {
  ok: boolean;
  engine: string;
  hint: string | null;
  voices: TtsVoice[];
}

export interface Preferences {
  whisperModel: string;
  whisperModels: { id: string; sizeMb: number; note: string }[];
  whisperCached: Record<string, boolean>;
}
