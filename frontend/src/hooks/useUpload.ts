import { api } from "../services/api";
import { useStore } from "../store/project";
import { uid } from "../lib/format";

const EXTS = ["mp4", "mov", "webm", "jpg", "jpeg", "png", "mp3", "wav"];
export const ACCEPT = EXTS.map((e) => "." + e).join(",");

/** Upload files one at a time with real byte progress; validation errors are shown per file. */
export async function uploadFiles(files: File[]) {
  const { project, system, setUploads, setMedia, toast } = useStore.getState();
  if (!project) return;
  const maxMb = system?.limits.maxUploadMb ?? 4096;
  const queue: { file: File; id: string }[] = [];
  for (const file of files) {
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    const id = uid("u");
    let error: string | null = null;
    if (!EXTS.includes(ext)) error = `Unsupported type .${ext || "?"}. Use ${EXTS.join(", ").toUpperCase()}.`;
    else if (file.size > maxMb * 1024 * 1024) error = `Larger than the ${maxMb} MB limit.`;
    else if (file.size === 0) error = "File is empty.";
    setUploads((u) => [...u, { id, name: file.name, progress: 0, error }]);
    if (!error) queue.push({ file, id });
  }
  for (const { file, id } of queue) {
    try {
      const media = await api.upload(project.id, file, (p) =>
        setUploads((u) => u.map((x) => (x.id === id ? { ...x, progress: p } : x))),
      );
      if (useStore.getState().project?.id !== project.id) return;
      setMedia([...useStore.getState().media.filter((m) => m.id !== media.id), media]);
      setUploads((u) => u.filter((x) => x.id !== id));
      if (!useStore.getState().selectedMediaId && media.kind !== "audio") useStore.getState().selectMedia(media.id);
    } catch (e) {
      setUploads((u) => u.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)));
    }
  }
  if (queue.length) toast(`${queue.length} file(s) uploaded, processing…`);
}
