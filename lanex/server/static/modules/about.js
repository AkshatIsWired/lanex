// about.js — "License & notices" now lives in the help sheet's About tab
// (shell.js renders it from /api/about: real NOTICE text only, never a copy).
export async function showAbout() {
  const { openHelp } = await import("./shell.js");
  openHelp("about");
}
