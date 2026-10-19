export interface MusicLicense {
  label: string;
  url: string | null;
  commercialOk: boolean;
  adaptOk: boolean;
}

export interface MusicResult {
  id: string;
  provider: "library" | "jamendo";
  title: string;
  artist: string;
  duration: number;
  genres: string[];
  moods: string[];
  license: MusicLicense;
  previewUrl: string;
  attribution: string;
}

export interface MusicSearch {
  results: MusicResult[];
  notices: string[];
}

export interface MusicProviderStatus {
  id: string;
  name: string;
  configured: boolean;
  license: string;
  tracks?: number;
  hint?: string | null;
}

export interface MusicAddResult {
  mediaId: string;
  media: import("./index").Media | null;
  attribution: string;
  license: MusicLicense;
}
