/* Pure timeline operations (no DOM). Source of truth for split/trim/move/delete.
   Segment: {id, clip, start, end, break?} in SOURCE seconds. Output time = cumulative (end-start)/speed. */
(function (root) {
  const MIN = 0.2;
  let counter = 0;
  const newId = () => "s" + Date.now().toString(36).slice(-4) + (counter++).toString(36);

  function layout(segs, speed) {
    let t = 0;
    return segs.map((s) => {
      const dur = (s.end - s.start) / speed;
      const row = { seg: s, outStart: t, outDur: dur, outEnd: t + dur };
      t += dur;
      return row;
    });
  }
  const total = (segs, speed) => segs.reduce((a, s) => a + (s.end - s.start) / speed, 0);

  function at(lay, t) {
    for (let i = 0; i < lay.length; i++) if (t >= lay[i].outStart && t < lay[i].outEnd) return i;
    return lay.length ? lay.length - 1 : -1;
  }
  const outToSource = (row, t) => row.seg.start + (t - row.outStart) * (row.seg.end - row.seg.start) / row.outDur;

  /* split the segment under output time t; null if t is too close to an edge */
  function splitAt(segs, speed, t) {
    const lay = layout(segs, speed);
    const i = at(lay, t);
    if (i < 0) return null;
    const row = lay[i];
    if (t - row.outStart < MIN / speed || row.outEnd - t < MIN / speed) return null;
    const cut = +outToSource(row, t).toFixed(3);
    const a = { ...row.seg, end: cut };
    const b = { ...row.seg, id: newId(), start: cut };
    delete b.break;
    return segs.slice(0, i).concat([a, b], segs.slice(i + 1));
  }

  function remove(segs, id) {
    const out = segs.filter((s) => s.id !== id);
    if (out.length && segs.length && segs[0].id === id) delete out[0].break;
    return out;
  }

  /* side: "start" | "end"; value in source seconds */
  function trim(segs, id, side, value, clipDur) {
    return segs.map((s) => {
      if (s.id !== id) return s;
      const n = { ...s };
      if (side === "start") n.start = +Math.min(Math.max(0, value), s.end - MIN).toFixed(3);
      else n.end = +Math.max(Math.min(clipDur, value), s.start + MIN).toFixed(3);
      return n;
    });
  }

  function move(segs, id, newIndex) {
    const i = segs.findIndex((s) => s.id === id);
    if (i < 0) return segs;
    const out = segs.slice();
    const [item] = out.splice(i, 1);
    out.splice(Math.max(0, Math.min(newIndex, out.length)), 0, item);
    return out;
  }

  /* spans of a source-time cue on the output timeline (a cue can straddle cuts) */
  function cueSpans(cue, lay) {
    const out = [];
    for (const r of lay) {
      if (r.seg.clip !== cue.clip) continue;
      const lo = Math.max(r.seg.start, cue.start), hi = Math.min(r.seg.end, cue.end);
      if (hi - lo > 0.05) {
        const k = r.outDur / (r.seg.end - r.seg.start);
        out.push([r.outStart + (lo - r.seg.start) * k, r.outStart + (hi - r.seg.start) * k]);
      }
    }
    return out;
  }

  const api = { MIN, newId, layout, total, at, outToSource, splitAt, remove, trim, move, cueSpans };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TLOps = api;
})(typeof window !== "undefined" ? window : globalThis);
