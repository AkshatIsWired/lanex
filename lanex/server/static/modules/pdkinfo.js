// pdkinfo.js — what a PDK is, in one line, and its layer stack for the Setup
// hero. Facts come from the open PDKs' own documentation; the drawing is a
// schematic cross-section (layer order and count), not to scale.

const FAMILIES = [
  {
    match: /^sky130/,
    about: (n) => "SkyWater 130 nm" + (n === "sky130B" ? ", with the ReRAM option" : "") +
      ". Polysilicon, a local interconnect layer (li1) and five metal layers.",
    stack: ["poly", "li1", "met1", "met2", "met3", "met4", "met5"],
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
  },
  {
    match: /^ihp-sg13g2/,
    about: () => "IHP 130 nm SiGe BiCMOS. Five thin metal layers and two thick top metals.",
    stack: ["gatpoly", "metal1", "metal2", "metal3", "metal4", "metal5", "topmetal1", "topmetal2"],
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
  if (!fam) return { about: "", stack: [] };
  const stack = typeof fam.stack === "function" ? fam.stack(name) : fam.stack;
  return { about: fam.about(name), stack };
}

// An SVG cross-section: layers stacked bottom-up with via columns joining them.
export function stackSvg(name) {
  const { stack } = pdkFacts(name);
  if (!stack.length) return "";
  const W = 220, row = 20, gap = 8, labelW = 74;
  const H = stack.length * (row + gap) + 26;
  const barX = labelW, barW = W - labelW;
  let g = "";
  stack.forEach((layer, i) => {
    const y = H - 26 - (i + 1) * (row + gap) + gap;
    // Upper metals have wider pitch, so each layer is drawn a little wider.
    const inset = Math.max(0, (stack.length - 1 - i) * 7);
    g += "<rect x='" + (barX + inset) + "' y='" + y + "' width='" + (barW - inset * 2) +
      "' height='" + row + "' fill='var(" + hue(layer) + ")'/>";
    g += "<text x='0' y='" + (y + row - 6) + "' class='stk-lbl'>" + layer + "</text>";
    if (i > 0) {
      // Two vias down to the layer below.
      const vy = y + row;
      for (const vx of [barX + barW * 0.36, barX + barW * 0.62]) {
        g += "<rect x='" + (vx - 3) + "' y='" + vy + "' width='6' height='" + gap + "' class='stk-via'/>";
      }
    }
  });
  g += "<rect x='" + barX + "' y='" + (H - 20) + "' width='" + barW + "' height='14' class='stk-sub'/>";
  g += "<text x='0' y='" + (H - 9) + "' class='stk-lbl'>substrate</text>";
  return "<svg viewBox='0 0 " + W + " " + H + "' width='" + W + "' height='" + H +
    "' role='img' aria-label='" + name + " layer stack, " + stack.length + " layers'>" + g + "</svg>";
}
