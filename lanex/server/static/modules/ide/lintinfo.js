// lintinfo.js — what Verilator's warning codes mean, in plain words, and which
// ones are only style noise inside a testbench. Shown in the IDE's Problems
// panel so a beginner learns what to fix and an expert can skim the code.
// Wording follows the Verilator manual's "Errors and Warnings" chapter.

export const LINT_INFO = {
  ALWCOMBORDER: "A combinational block reads a signal before it assigns it. Assign it first.",
  ASCRANGE: "The bit range counts up ([0:7]). Most code and tools expect [7:0].",
  ASSIGNDLY: "A delay (#) on an assign. Synthesis ignores it; leave it for testbenches.",
  BLKANDNBLK: "The same signal gets both = and <= assignments. Pick one kind.",
  BLKLOOPINIT: "A loop initialises an array with = inside a clocked block. Use <=, or a reset.",
  BLKSEQ: "A blocking assignment (=) in a clocked block. Use <= for flip-flops.",
  CASEINCOMPLETE: "The case doesn't cover every value. Add a default branch.",
  CASEOVERLAP: "Two case items match the same value, so the first one wins.",
  CASEX: "casex treats x as don't-care, which hides bugs. Use casez with ?.",
  CMPCONST: "This comparison is always true or always false.",
  COMBDLY: "A delayed assignment (<=) in a combinational block. Use = there.",
  DECLFILENAME: "The module name doesn't match the file name.",
  DEFPARAM: "defparam is deprecated. Pass parameters with #( .NAME(value) ).",
  EOFNEWLINE: "The file doesn't end with a newline.",
  GENUNNAMED: "A generate block has no label. Add one (begin : gen_name).",
  IMPLICIT: "A wire is used without being declared, so Verilog made a 1-bit one. Declare it.",
  INITIALDLY: "A delayed assignment (<=) in an initial block. Use = there.",
  LATCH: "Not every path assigns this signal, so synthesis builds a latch. Assign it in every branch or give it a default.",
  MULTIDRIVEN: "Two always blocks drive the same signal. Drive it from one place.",
  MULTITOP: "More than one module is never instantiated, so there are several tops.",
  PINCONNECTEMPTY: "A port is connected to nothing with .port(). Connect it or leave it out on purpose.",
  PINMISSING: "An instance doesn't connect one of the module's ports.",
  PINNOCONNECT: "An output port of an instance isn't connected.",
  PROCASSINIT: "A signal has an initial value and is also assigned in an always block. Set it with a reset instead.",
  SELRANGE: "A bit select is outside the signal's range.",
  STMTDLY: "A delay (#) inside procedural code. Fine in a testbench; synthesis ignores it.",
  SYNCASYNCNET: "The same reset is used both synchronously and asynchronously.",
  TIMESCALEMOD: "Some files set a `timescale and others don't.",
  UNDRIVEN: "Nothing drives this signal, so it stays x (or floats).",
  UNOPTFLAT: "A combinational loop through this signal. Usually harmless in simulation, worth a look.",
  UNSIGNED: "An unsigned value is compared with < 0 (or similar), which is always false.",
  UNUSED: "This signal is declared but never read.",
  UNUSEDGENVAR: "This genvar is never used.",
  UNUSEDPARAM: "This parameter is never used.",
  UNUSEDSIGNAL: "This signal is declared but never read.",
  VARHIDDEN: "A local name hides one from an outer scope.",
  WIDTH: "The two sides have different bit widths, so Verilog pads or cuts bits.",
  WIDTHCONCAT: "A concatenation contains an unsized constant. Give it a width (8'd5).",
  WIDTHEXPAND: "A narrower value is padded with zeros to fit a wider one. Size it to match.",
  WIDTHTRUNC: "A wider value is cut to fit a narrower one, losing the top bits. Size it to match.",
  WIDTHXZEXPAND: "An x or z constant is widened. Size it to match.",
};

// Codes that point at style, not mistakes, when they turn up in code that only
// simulates (unused outputs of the DUT, delays, initial values). Folded away
// in testbench files; never in design files.
export const TESTBENCH_STYLE = new Set([
  "UNUSED", "UNUSEDSIGNAL", "UNUSEDPARAM", "UNUSEDGENVAR", "UNDRIVEN", "PROCASSINIT", "INITIALDLY",
  "STMTDLY", "DECLFILENAME", "BLKSEQ", "TIMESCALEMOD", "PINCONNECTEMPTY", "WIDTH", "WIDTHEXPAND",
  "WIDTHTRUNC", "WIDTHCONCAT", "EOFNEWLINE", "VARHIDDEN", "MULTITOP", "ASSIGNDLY", "COMBDLY",
]);

export function explain(code) {
  return LINT_INFO[code] || "";
}
