import { CheckCircle2, CircleSlash, Sparkles } from "lucide-react";
import { useMemo } from "react";
import { fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { LOOKS, STYLES, TRANSITIONS } from "../../lib/styles";
import { useStore } from "../../store/project";
import { Empty, PanelHeader, cx } from "../ui/controls";

function Engines() {
  const sys = useStore((s) => s.system);
  if (!sys) return null;
  const rows = [
    { ok: sys.ffmpeg.ok, label: `FFmpeg ${sys.ffmpeg.version ?? ""}`, hint: sys.ffmpeg.hint },
    { ok: sys.sceneDetection.ok, label: sys.sceneDetection.engine, hint: sys.sceneDetection.hint },
    { ok: sys.transcription.ok, label: sys.transcription.engine, hint: sys.transcription.hint },
    { ok: sys.transitions.ok, label: "Transitions (xfade)", hint: null },
    { ok: sys.musicDucking.ok, label: "Music ducking", hint: null },
  ];
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-xs" title={r.ok ? "" : r.hint ?? ""}>
          {r.ok ? <CheckCircle2 size={13} className="text-success" /> : <CircleSlash size={13} className="text-danger" />}
          <span className={r.ok ? "text-fg-muted" : "text-danger"}>{r.label}</span>
        </div>
      ))}
    </div>
  );
}

export function InsightsPanel() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const media = useStore((s) => s.media);
  const selected = useStore((s) => s.selectedClipId);
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const names = Object.fromEntries(media.map((m) => [m.id, m.name]));

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="AI Edit" subtitle="How your edit was made." />
      <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        {!edl || !lay || !edl.clips.length ? (
          <>
            <Empty icon={<Sparkles size={18} />} title="No AI edit yet" text="Generate a video to see the scenes, scores and decisions behind it." />
            <div className="rounded-md bg-panel2 p-3 text-xs text-fg-muted">
              <div className="mb-1.5 font-medium text-fg">Pipeline</div>
              <ol className="list-decimal space-y-0.5 pl-4">
                <li>Analyze motion, sharpness, faces, audio</li>
                <li>Detect scenes and silence</li>
                <li>Score and select highlights by style</li>
                <li>Arrange, trim, transition, crop</li>
                <li>Captions, music, loudness</li>
                <li>Render with FFmpeg</li>
              </ol>
            </div>
          </>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["Style", STYLES[edl.style].name],
                ["Length", fmtDuration(lay.duration)],
                ["Clips", String(edl.clips.length)],
                ["Transition", edl.transition && lay.transition ? `${TRANSITIONS.find((t) => t.value === edl.transition!.type)?.label} ${lay.transition}s` : "Cuts"],
                ["Grade", LOOKS.find((l) => l.value === edl.look)?.label ?? "–"],
                ["Beat sync", edl.beat ? `${Math.round(60 / edl.beat)} BPM` : "Off"],
              ].map(([k, v]) => (
                <div key={k} className="rounded bg-panel2 px-2 py-1.5">
                  <div className="text-2xs text-fg-faint">{k}</div>
                  <div className="truncate text-xs text-fg">{v}</div>
                </div>
              ))}
            </div>
            <div>
              <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-fg-muted">Clips</h3>
              <div className="space-y-1">
                {lay.clips.map((lc) => (
                  <button
                    key={lc.clip.id}
                    onClick={() => {
                      useStore.getState().selectClip(lc.clip.id);
                      useStore.getState().setPreviewMode("edit");
                      useStore.getState().seek(lc.outStart);
                    }}
                    className={cx(
                      "flex w-full items-center gap-2 rounded px-2 py-1 text-left transition-colors",
                      selected === lc.clip.id ? "bg-primary-muted" : "hover:bg-panel2",
                    )}
                  >
                    <span className="w-9 shrink-0 text-2xs tabular-nums text-fg-faint">{lc.outStart.toFixed(1)}s</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-fg" title={names[lc.clip.mediaId]}>{lc.clip.label}</span>
                    {lc.clip.score != null && (
                      <span className="flex w-12 shrink-0 items-center" title={`Score ${lc.clip.score.toFixed(2)}`}>
                        <span className="h-1 rounded bg-primary" style={{ width: `${Math.min(1, lc.clip.score) * 100}%` }} />
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-fg-muted">Decisions</h3>
              <ul className="space-y-1 rounded bg-panel2 p-2">
                {edl.notes.map((n, i) => (
                  <li key={i} className="text-2xs leading-4 text-fg-muted">• {n}</li>
                ))}
              </ul>
            </div>
          </>
        )}
        <div>
          <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-fg-muted">Local engines</h3>
          <Engines />
        </div>
      </div>
    </div>
  );
}
