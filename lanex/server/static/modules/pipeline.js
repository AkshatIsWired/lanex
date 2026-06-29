// pipeline.js — ECharts-based interactive node-graph for the flow.

import { api, fmt } from "./api.js";
import { state } from "./state.js";

let _chart;

const STATUS_COLOR = {
  pending: "#6e7681",
  running: "#58a6ff",
  done: "#3fb950",
  failed: "#f85149",
  skipped: "#6e7681",
};

const STAGES = [
  ["Synthesis", ["yosys", "jsonheader", "synthchecks", "unmapped"]],
  ["Lint", ["verilator", "lint"]],
  ["Floorplan", ["floorplan", "tapendcap", "cutrows", "macroplacement"]],
  ["Power", ["pdn", "power", "removepdn"]],
  ["Placement", ["placement", "globalplacement", "detailedplacement", "ioplacement"]],
  ["CTS", ["cts", "timingpostcts"]],
  ["Antenna", ["antenna", "diode"]],
  ["Routing", ["routing", "globals", "detailedroute", "repairdesign", "routingobstruction"]],
  ["Signoff", ["drc", "lvs", "xor", "stream", "fillinsertion", "sta", "rcx", "irdrop", "antennareport", "magic", "klayout", "render"]],
  ["Misc", []],
];

function bucketOf(id) {
  const l = (id || "").toLowerCase();
  for (const [name, kws] of STAGES) {
    if (kws.some((k) => l.includes(k))) return name;
  }
  return "Misc";
}

function buildData() {
  const byStage = new Map(STAGES.map(([s]) => [s, []]));
  state.steps.forEach((step) => byStage.get(bucketOf(step.id)).push(step));
  const nodes = [];
  const links = [];
  let prevNodeId = null;
  const statuses = (state.pipeline || []).reduce((m, p) => {
    m[p.id] = p.status;
    return m;
  }, Object.assign({}, state.stepStatuses));
  STAGES.forEach(([stage], si) => {
    const arr = byStage.get(stage);
    arr.forEach((s, idx) => {
      const status = statuses[s.id] || s.status || "pending";
      nodes.push({
        id: s.id,
        category: stage,
        x: (si + 1) * 12,
        y: 4 + idx * 2.4,
        symbolSize: state.selectedStepId === s.id ? 38 : 28,
        itemStyle: {
          color: STATUS_COLOR[status] || STATUS_COLOR.pending,
        },
        label: {
          show: true,
          position: "right",
          color: "#c9d1d9",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 11,
          formatter: () => truncate(s.id, 28),
        },
        meta: { stage, status },
      });
      if (idx > 0) {
        const prev = arr[idx - 1];
        links.push({ source: prev.id, target: s.id, lineStyle: { color: "#30363d", curveness: 0.2 } });
      } else if (prevNodeId) {
        links.push({ source: prevNodeId, target: s.id, lineStyle: { color: "#30363d", type: "dashed", curveness: 0.3 } });
      }
      prevNodeId = s.id;
    });
  });
  return { nodes, links, categories: STAGES.map(([name]) => ({ name, itemStyle: { color: "#6e7681" } })) };
}

function truncate(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function renderPipeline() {
  if (typeof window.echarts === "undefined") return setTimeout(renderPipeline, 200);
  const dom = document.getElementById("pipeline");
  if (!dom) return;
  const ec = window.echarts;
  if (!_chart) {
    _chart = ec.init(dom, "dark", { renderer: "canvas" });
    // ECharts reports series clicks as componentType "series" + seriesType
    // "graph"; the node vs edge distinction is dataType. Gating on
    // componentType === "graph" never matched, so node clicks did nothing.
    _chart.on("click", (params) => {
      if (params.dataType === "node" && params.data && params.data.id) {
        selectStep(params.data.id);
      }
    });
    _chart.on("contextmenu", async (params) => {
      if (params.dataType === "node" && params.data && params.data.id) {
        const id = params.data.id;
        const { choiceDialog, alertDialog } = await import("./dialog.js");
        const action = await choiceDialog({
          title: "Step: " + id,
          choices: [
            { label: "Run from here", value: "frm" },
            { label: "Run to here", value: "to" },
            { label: "Skip this step", value: "skip" },
            { label: "Reproducible CLI", value: "repro" },
            { label: "Help", value: "help" },
          ],
        });
        if (action === "frm") dispatchPartial({ frm: id });
        if (action === "to") dispatchPartial({ to: id });
        if (action === "skip") dispatchPartial({ skip: id });
        if (action === "repro") api.reproducible(id).then((r) => alertDialog({ title: "Reproducible", body: r.path || "n/a" }));
        if (action === "help") showHelp(id);
      }
    });
    window.addEventListener("resize", () => _chart && _chart.resize());
  }
  const { nodes, links, categories } = buildData();
  _chart.setOption({
    backgroundColor: "transparent",
    legend: [{ data: STAGES.map(([s]) => s), textStyle: { color: "#c9d1d9" }, right: 8, top: 8 }],
    tooltip: {
      formatter: (p) => p.dataType === "node"
        ? "<b>" + p.data.id + "</b><br/>Stage: " + p.data.meta.stage + "<br/>Status: " + p.data.meta.status
        : "",
      backgroundColor: "#161b22",
      borderColor: "#30363d",
      textStyle: { color: "#c9d1d9" },
    },
    series: [{
      type: "graph",
      layout: "none",
      roam: true,
      draggable: true,
      categories,
      symbol: "circle",
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [4, 8],
      data: nodes,
      links,
      lineStyle: { color: "#30363d", width: 2, curveness: 0.2 },
      emphasis: { focus: "adjacency", lineStyle: { width: 4 } },
    }],
  });
}

function dispatchPartial(detail) {
  if (detail.frm) document.getElementById("run-from").value = detail.frm;
  if (detail.to) document.getElementById("run-to").value = detail.to;
  if (detail.skip) document.getElementById("run-skip").value = detail.skip;
  document.getElementById("btn-run").click();
}

function showHelp(id) {
  window.open("https://librelane.org/usage/steps.html#" + encodeURIComponent(id), "_blank", "noopener");
}

export function selectStep(id) {
  state.selectedStepId = id;
  renderPipeline();
  document.dispatchEvent(new CustomEvent("g:step_selected", { detail: { id } }));
}
