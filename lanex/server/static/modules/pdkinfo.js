// pdkinfo.js — what a PDK is, in one line, and its layer stack for the Setup
// hero. Facts come from the open PDKs' own documentation; the stack shows layer
// order and count, not to scale.

const FAMILIES = [
  {
    match: /^sky130/,
    about: (n) => "SkyWater 130 nm" + (n === "sky130B" ? ", with the ReRAM option" : "") +
      ". Polysilicon, a local interconnect layer (li1) and five metal layers.",
    stack: ["poly", "li1", "met1", "met2", "met3", "met4", "met5"],
    node: "130 nm",
  },
  {
    match: /^gf180mcu/,
    about: (n) => {
      const m = { gf180mcuA: 3, gf180mcuB: 4, gf180mcuC: 5, gf180mcuD: 5 }[n] || 5;
      return "GlobalFoundries 180 nm MCU, " + m + " metal layers" +
        (n === "gf180mcuD" ? " with a thicker top metal" : "") + ".";
    },
    stack: (n) => {
      const m = { gf180mcuA: 3, gf180mcuB: 4, gf180mcuC: 5, gf180mcuD: 5 }[n] || 5;
      return ["poly2"].concat(Array.from({ length: m }, (_, i) => "metal" + (i + 1)));
    },
    node: "180 nm",
  },
  {
    match: /^ihp-sg13g2/,
    about: () => "IHP 130 nm SiGe BiCMOS. Five thin metal layers and two thick top metals.",
    stack: ["gatpoly", "metal1", "metal2", "metal3", "metal4", "metal5", "topmetal1", "topmetal2"],
    node: "130 nm",
  },
];

// Layer colour by name: poly, local interconnect, then metal N in the metN hue
// (top metals share the highest metal colours).
function hue(layer) {
  if (/poly/.test(layer)) return "--poly";
  if (layer === "li1") return "--li";
  if (/^topmetal/.test(layer)) return layer.endsWith("2") ? "--met5" : "--met4";
  const n = parseInt(layer.replace(/\D+/g, ""), 10);
  return "--met" + Math.min(Math.max(n || 1, 1), 5);
}

export function pdkFacts(name) {
  const fam = FAMILIES.find((f) => f.match.test(name || ""));
  if (!fam) return { about: "", stack: [], node: "" };
  const stack = typeof fam.stack === "function" ? fam.stack(name) : fam.stack;
  return { about: fam.about(name), stack, node: fam.node };
}

// The Setup hero's layer stack: one glowing bar per layer, top metal first,
// each a little narrower going down, then the substrate line.
export function stackHtml(name) {
  const { stack, node } = pdkFacts(name);
  if (!stack.length) return "";
  const n = stack.length;
  const rows = stack.slice().reverse().map((layer, i) => {
    const w = n > 1 ? Math.round(90 - (i * 54) / (n - 1)) : 90;
    return "<div class='ls-layer' style='--lc:var(" + hue(layer) + ");--lsw:" + w + "%' title='" + layer +
      "'><span class='ls-bar'></span><span class='ls-tag'>" + layer + "</span></div>";
  });
  return rows.join("") + "<div class='ls-sub'>substrate · " + node + "</div>";
}
