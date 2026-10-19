import { Mic } from "lucide-react";
import { useEffect, useState } from "react";
import { uid } from "../../lib/format";
import { layout } from "../../lib/layout";
import { withAudioClips } from "../../lib/timelineOps";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { TtsStatus } from "../../types/tts";
import { Button, Field, Select, Slider } from "../ui/controls";

const LIMIT = 1500;

/** Text to speech: generates a voice track with the local engine and drops it on the audio timeline at the playhead. */
export function Voiceover() {
  const project = useStore((s) => s.project);
  const updateDoc = useStore((s) => s.updateDoc);
  const toast = useStore((s) => s.toast);
  const [status, setStatus] = useState<TtsStatus | null>(null);
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const [rate, setRate] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.ttsVoices().then((s) => {
      setStatus(s);
      setVoice((v) => v || (s.voices.find((x) => x.name === "Samantha")?.name ?? s.voices.find((x) => x.lang === "en-US")?.name ?? s.voices.find((x) => x.lang.startsWith("en"))?.name ?? s.voices[0]?.name ?? ""));
    }).catch(() => setStatus({ ok: false, engine: "unavailable", hint: "Couldn't reach the server.", voices: [] }));
  }, []);

  const generate = async () => {
    if (!project || !text.trim()) return;
    setBusy(true);
    try {
      const media = await api.tts(project.id, { text: text.trim(), voice, rate });
      useStore.getState().setMedia([...useStore.getState().media.filter((m) => m.id !== media.id), media]);
      // wait for ingest (duration, waveform), then place it at the playhead
      let ready = media;
      for (let i = 0; i < 60 && ready.status === "processing"; i++) {
        await new Promise((r) => setTimeout(r, 500));
        await useStore.getState().refreshMedia();
        ready = useStore.getState().media.find((m) => m.id === media.id) ?? ready;
      }
      if (ready.status !== "ready") throw new Error("The voice track did not finish processing.");
      const at = useStore.getState().time;
      updateDoc((d) => {
        if (!d.edl) return d;
        const start = Math.min(at, Math.max(0, layout(d.edl).duration - 0.2));
        const clip = { id: uid("a"), mediaId: ready.id, kind: "audio" as const, start, trimIn: 0, duration: null, volume: 1, fadeIn: 0, fadeOut: 0, loop: false, duck: false };
        return { ...d, edl: withAudioClips(d.edl, [...d.edl.audioClips, clip]) };
      });
      toast("Voiceover added to the audio timeline.");
      setText("");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const hasEdl = !!useStore((s) => s.doc?.edl);
  return (
    <div className="mb-4 rounded-xl border border-line bg-panel2 px-3 py-3">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted"><Mic size={13} /> Text to speech</h3>
      {status && !status.ok ? (
        <p className="mt-1.5 text-2xs text-fg-faint">{status.hint ?? "No speech engine found on this computer."}</p>
      ) : (
        <>
          <textarea
            aria-label="Voiceover text"
            value={text}
            maxLength={LIMIT}
            onChange={(e) => setText(e.target.value)}
            placeholder="Type what the voice should say…"
            className="mt-2 h-20 w-full resize-none rounded-lg border border-line bg-app p-2 text-xs text-fg outline-none focus:border-primary"
          />
          <Field label="Voice">
            <Select label="Voice" className="w-40" value={voice} options={(status?.voices ?? []).map((v) => ({ value: v.name, label: `${v.name} (${v.lang})` }))} onChange={setVoice} />
          </Field>
          <Field label="Speed" hint={`${rate.toFixed(2)}x`}>
            <div className="w-32"><Slider label="Speech speed" min={0.6} max={1.6} step={0.05} value={rate} onChange={setRate} /></div>
          </Field>
          <Button variant="primary" size="sm" className="mt-2 w-full" disabled={busy || !text.trim() || !hasEdl || !voice} onClick={generate}>
            {busy ? "Generating…" : "Generate voiceover"}
          </Button>
          {!hasEdl && <p className="mt-1 text-2xs text-fg-faint">Generate or add clips first, then add a voiceover.</p>}
          <p className="mt-1 text-2xs text-fg-faint">{status?.engine}. Runs on this computer; nothing is uploaded.</p>
        </>
      )}
    </div>
  );
}
