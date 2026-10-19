import { Field, PanelHeader, Select, Toggle } from "../ui/controls";
import { useStore } from "../../store/project";
import { Voiceover } from "./Voiceover";

/** Voiceover and overall levels. Background music has its own Music panel. */
export function AudioPanel() {
  const doc = useStore((s) => s.doc!);
  const updateDoc = useStore((s) => s.updateDoc);
  const edl = doc.edl;
  const st = doc.settings;
  const audioCfg = edl?.audio;

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Audio" subtitle="Voiceover and levels. Music is in the Music panel." />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <Voiceover />
        <h3 className="mb-1 mt-2 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Levels</h3>
        <Field label="Loudness normalization">
          <Toggle label="Loudness normalization" checked={audioCfg ? audioCfg.normalize : st.normalizeAudio}
            onChange={(v) => updateDoc((d) => ({ ...d, settings: { ...d.settings, normalizeAudio: v }, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, normalize: v } } }))} />
        </Field>
        {audioCfg && (
          <>
            {audioCfg.normalize && (
              <Field label="Target loudness">
                <Select label="Target loudness" className="w-36" value={audioCfg.lufs}
                  options={[{ value: -14, label: "-14 LUFS · Social" }, { value: -16, label: "-16 LUFS · Web" }, { value: -23, label: "-23 LUFS · Broadcast" }]}
                  onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, lufs: v } } }))} />
              </Field>
            )}
            <Field label="Voice cleanup" hint="Rumble filter + noise reduction">
              <Toggle label="Voice cleanup" checked={audioCfg.clean} onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, clean: v } } }))} />
            </Field>
            <Field label="Fade in / out">
              <Toggle label="Fade in and out" checked={audioCfg.fades} onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, fades: v } } }))} />
            </Field>
          </>
        )}
        {!edl && <p className="mt-2 text-2xs text-fg-faint">More audio options appear after you generate an edit.</p>}
      </div>
    </div>
  );
}
