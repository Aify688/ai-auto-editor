// node tests/test_timeline_ops.js
const assert = require("assert");
const T = require("../ui/timeline_component/ops.js");
const segs = [{ id: "a", clip: 0, start: 0, end: 4 }, { id: "b", clip: 0, start: 6, end: 10, break: true }];

// layout + total (speed 2 halves durations)
assert.strictEqual(T.total(segs, 1), 8);
assert.strictEqual(T.total(segs, 2), 4);
const lay = T.layout(segs, 1);
assert.deepStrictEqual([lay[1].outStart, lay[1].outEnd], [4, 8]);

// split inside segment b at output 6 -> source 8
const sp = T.splitAt(segs, 1, 6);
assert.strictEqual(sp.length, 3);
assert.deepStrictEqual([sp[1].start, sp[1].end, sp[2].start, sp[2].end], [6, 8, 8, 10]);
assert.ok(!sp[2].break && sp[1].break, "break stays on first half only");
assert.strictEqual(T.splitAt(segs, 1, 4.05), null, "too close to an edge");

// delete ripples; deleting the first drops the break flag from the new first
const del = T.remove(segs, "a");
assert.strictEqual(del.length, 1);
assert.ok(!del[0].break);
assert.strictEqual(T.total(del, 1), 4);

// trim clamps to min length and clip bounds
assert.strictEqual(T.trim(segs, "a", "end", 100, 8)[0].end, 8);
assert.strictEqual(T.trim(segs, "a", "end", 0.01, 8)[0].end, 0.2);
assert.strictEqual(T.trim(segs, "b", "start", 9.95, 10)[1].start, 9.8);
assert.strictEqual(T.trim(segs, "a", "start", -3, 8)[0].start, 0);

// move reorders
assert.deepStrictEqual(T.move(segs, "a", 1).map((s) => s.id), ["b", "a"]);

// cue spans straddling the cut are split across segments
const spans = T.cueSpans({ clip: 0, start: 3, end: 7 }, lay);
assert.deepStrictEqual(spans, [[3, 4], [4, 5]]);
assert.deepStrictEqual(T.cueSpans({ clip: 1, start: 0, end: 5 }, lay), []);
console.log("timeline ops: all passed");
