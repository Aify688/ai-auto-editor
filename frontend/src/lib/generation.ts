/** What the main button does, derived from what the project holds. Pure so it can be tested. */
export type GenerationMode = "edit" | "text" | "none";

export interface GenerationState {
  mode: GenerationMode;
  enabled: boolean;
  label: string;
  /** Why the button is disabled, or a gentle hint when it is not. */
  reason: string | null;
}

export const MAX_DESCRIPTION = 20000;

export function generationState(opts: {
  visualCount: number;
  readyCount: number;
  processing: boolean;
  instruction: string;
  running: boolean;
  hasEdit: boolean;
}): GenerationState {
  const { visualCount, readyCount, processing, instruction, running, hasEdit } = opts;
  const text = instruction.trim().length > 0;
  if (visualCount > 0) {
    const label = hasEdit ? "Re-run Auto Edit" : "Auto Edit Video";
    if (running) return { mode: "edit", enabled: false, label, reason: null };
    if (processing) return { mode: "edit", enabled: false, label, reason: "Waiting for media processing…" };
    if (!readyCount) return { mode: "edit", enabled: false, label, reason: "No usable media. Remove the failed files or upload again." };
    return { mode: "edit", enabled: true, label, reason: null };
  }
  const label = hasEdit ? "Regenerate AI Video" : "Generate AI Video";
  if (!text) return { mode: "none", enabled: false, label, reason: "Upload videos to edit, or describe a video to generate it with AI." };
  return { mode: "text", enabled: !running, label, reason: null };
}
