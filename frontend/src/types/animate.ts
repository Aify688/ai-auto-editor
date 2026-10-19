export interface ImageToVideoStatus {
  configured: boolean;
  provider: string;
  model: string;
  aspects: string[];
  minSeconds: number;
  maxSeconds: number;
  hint: string | null;
}

export interface AnimateOptions {
  mediaId: string;
  prompt: string;
  seconds: number;
  aspect: "16:9" | "9:16" | "1:1" | "4:5" | "original";
  intensity: "low" | "medium" | "high";
}
