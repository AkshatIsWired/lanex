// timingAdvisor.js — actionable next-step based on the metric hero set.

import { state } from "./state.js";
import { fmt } from "./api.js";

export function renderTimingAdvisor() {
  const root = document.getElementById("timing-advisor");
  if (!root) return;

  const ws_setup = state.metrics?.["timing__setup__ws"];
  const tns_setup = state.metrics?.["timing__setup__tns"];
  const ws_hold = state.metrics?.["timing__hold__ws"];
  const tns_hold = state.metrics?.["timing__hold__tns"];

  const card = document.createElement("div");
  card.className = "adv-card";

  let direction = "✅ Timing closed";
  let action = "Validate final views and you're done.";
  if (ws_setup === undefined || ws_setup === null) {
    direction = "Awaiting signoff";
    action = "Run the full flow to see final metrics here.";
  } else if (ws_setup < 0 || tns_setup < 0) {
    direction = "Setup violation";
    action =
      "Lower PL_TARGET_DENSITY_PCT (e.g. to 55) to give the placer room. " +
      "If that can't help, try SYNTH_STRATEGY AREA 1, then DELAY 2.";
  } else if (ws_hold < 0 || tns_hold < 0) {
    direction = "Hold violation";
    action =
      "Re-run from OpenROAD.CTS so hold buffers can be inserted. " +
      "If still failing, raise PL_RESIZER_HOLD_SLACK_MARGIN and check the hold corner is feasible.";
  }

  card.innerHTML =
    "<div class='title'>Timing closure</div>" +
    "<div class='what'>" + direction + "</div>" +
    "<div class='why'>" +
      "WNS(setup)=<b" + fmt.titleAttr(ws_setup) + ">" + fmt.metric(ws_setup) + "·ns</b> · " +
      "TNS(setup)=<b" + fmt.titleAttr(tns_setup) + ">" + fmt.metric(tns_setup) + "·ns</b><br/>" +
      "WNS(hold)=<b" + fmt.titleAttr(ws_hold) + ">" + fmt.metric(ws_hold) + "·ns</b> · " +
      "TNS(hold)=<b" + fmt.titleAttr(tns_hold) + ">" + fmt.metric(tns_hold) + "·ns</b>" +
    "</div>" +
    "<div class='try'>" + fmt.escape(action) + "</div>";
  root.innerHTML = "";
  root.appendChild(card);
}
