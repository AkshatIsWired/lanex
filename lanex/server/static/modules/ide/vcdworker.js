// vcdworker.js — parses a VCD dump off the page's thread (module worker,
// started by vcd.js readVCD). In: { bytes: Uint8Array }. Out: progress
// messages, then { type: "done", vcd: <packed> } with the times transferred.

import { parseVCD, packVCD } from "./vcd.js";

self.onmessage = (e) => {
  try {
    const text = new TextDecoder().decode(e.data.bytes);
    let last = 0;
    const vcd = parseVCD(text, {
      onProgress: (p) => { if (p - last >= 0.02) { last = p; self.postMessage({ type: "progress", p }); } },
    });
    const { msg, transfer } = packVCD(vcd);
    self.postMessage({ type: "done", vcd: msg }, transfer);
  } catch (ex) {
    self.postMessage({ type: "error", error: String((ex && ex.message) || ex) });
  }
};
