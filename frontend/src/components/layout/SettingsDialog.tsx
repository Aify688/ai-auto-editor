import { Check, CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { Preferences, TtsStatus } from "../../types/tts";
import { Modal, cx } from "../ui/controls";

function Row({ ok, label, detail }: { ok: boolean; label: string; detail?: string | null }) {
  return (
    <div className="flex items-start gap-2 py-1.5 text-xs">
      {ok ? <Check size={14} className="mt-px shrink-0 text-success" /> : <CircleAlert size={14} className="mt-px shrink-0 text-warning" />}
      <div className="min-w-0">
        <div className="text-fg">{label}</div>
        {detail && <div className="text-2xs text-fg-faint">{detail}</div>}
      </div>
    </div>
  );
}

/** Settings: the speech-to-text model and what this computer can and cannot do. Everything runs locally. */
export function SettingsDialog() {
  const open = useStore((s) => s.settingsOpen);
  const setOpen = useStore((s) => s.setSettingsOpen);
  const system = useStore((s) => s.system);
  const toast = useStore((s) => s.toast);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [tts, setTts] = useState<TtsStatus | null>(null);

  useEffect(() => {
    if (!open) return;
    api.preferences().then(setPrefs).catch(() => toast("Couldn't load settings.", "error"));
    api.ttsVoices().then(setTts).catch(() => undefined);
  }, [open, toast]);

  const choose = async (model: string) => {
    try {
      setPrefs(await api.setPreferences({ whisperModel: model }));
      useStore.getState().setSystem(await api.system());
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <Modal open={open} onClose={() => setOpen(false)} title="Settings" width={520}>
      <div className="space-y-5 px-5 py-4">
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Caption model</h3>
          <p className="mb-2 mt-0.5 text-2xs text-fg-faint">Larger models understand speech better but are slower. A model downloads once, the first time captions use it, then works offline.</p>
          <div role="radiogroup" aria-label="Caption model" className="space-y-1">
            {prefs?.whisperModels.map((m) => (
              <button
                key={m.id}
                role="radio"
                aria-checked={prefs.whisperModel === m.id}
                onClick={() => choose(m.id)}
                className={cx("flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-xs", prefs.whisperModel === m.id ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]")}
              >
                <span>
                  <span className="font-medium capitalize text-fg">{m.id}</span>
                  <span className="ml-2 text-fg-muted">{m.note}</span>
                </span>
                <span className="shrink-0 pl-2 text-2xs tabular-nums text-fg-faint">{prefs.whisperCached[m.id] ? "Downloaded" : `${m.sizeMb} MB`}</span>
              </button>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">On this computer</h3>
          <div className="mt-1 divide-y divide-line/50">
            <Row ok={!!system?.ffmpeg.ok} label="FFmpeg video engine" detail={system?.ffmpeg.ok ? `Version ${system.ffmpeg.version}` : system?.ffmpeg.hint} />
            <Row ok={!!system?.transcription.ok} label="AI captions (Whisper)" detail={system?.transcription.engine} />
            <Row ok={!!system?.backgroundRemoval?.ok} label="Background removal" detail={system?.backgroundRemoval?.ok ? system.backgroundRemoval.engine : system?.backgroundRemoval?.hint} />
            <Row ok={!!tts?.ok} label="Text to speech" detail={tts?.ok ? `${tts.engine}, ${tts.voices.length} voices` : tts?.hint} />
            <Row ok={!!system?.transitions.ok} label="Transitions" />
            <Row ok={!!system?.musicDucking.ok} label="Music ducking under speech" />
          </div>
        </section>

        <p className="text-2xs text-fg-faint">Your videos never leave this computer. Projects are stored in {system?.dataDir}.</p>
      </div>
    </Modal>
  );
}
