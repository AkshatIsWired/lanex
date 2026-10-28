// intlcache.js — cached Intl formatters.
//
// Number#toLocaleString and Date#toLocale*String build a new Intl formatter on
// every call (about 0.1 ms each, 0.6 ms on a slow laptop). A table of 300 runs
// formats a few thousand numbers and dates per render, so the formatters are
// made once per (locale, options) and reused. The output is the same string:
// ECMA-402 defines toLocaleString(l, o) as new Intl.NumberFormat(l, o).format(x).

const NF = new Map();
const DF = new Map();

const keyOf = (locale, opts) => (Array.isArray(locale) ? locale.join(",") : String(locale)) + "|" + (opts ? JSON.stringify(opts) : "");

export function numberFormat(locale, opts) {
  const k = keyOf(locale, opts);
  let f = NF.get(k);
  if (!f) { f = new Intl.NumberFormat(locale, opts); NF.set(k, f); }
  return f;
}

// n.toLocaleString(locale, opts), with the formatter cached.
export function localeNum(n, locale = "en-US", opts) {
  return numberFormat(locale, opts).format(n);
}

function dateFormat(locale, opts) {
  const k = keyOf(locale, opts);
  let f = DF.get(k);
  if (!f) { f = new Intl.DateTimeFormat(locale, opts); DF.set(k, f); }
  return f;
}

const DATE_KEYS = ["weekday", "year", "month", "day"];
const TIME_KEYS = ["dayPeriod", "hour", "minute", "second", "fractionalSecondDigits"];
const has = (o, keys) => !!o && keys.some((k) => o[k] !== undefined);

// The Date#toLocale*String defaults (ECMA-402 ToDateTimeOptions): the default
// fields are added only when the caller gave none the method looks for.
function withDefaults(opts, required, defaults) {
  let need = true;
  if ((required === "date" || required === "any") && has(opts, DATE_KEYS)) need = false;
  if ((required === "time" || required === "any") && has(opts, TIME_KEYS)) need = false;
  if (opts && (opts.dateStyle !== undefined || opts.timeStyle !== undefined)) need = false;
  if (!need) return opts;
  const o = { ...(opts || {}) };
  if (defaults === "date" || defaults === "all") { o.year = "numeric"; o.month = "numeric"; o.day = "numeric"; }
  if (defaults === "time" || defaults === "all") { o.hour = "numeric"; o.minute = "numeric"; o.second = "numeric"; }
  return o;
}

// d.toLocaleString / toLocaleDateString / toLocaleTimeString, cached.
export function localeDateTime(d, locale, opts) { return dateFormat(locale, withDefaults(opts, "any", "all")).format(d); }
export function localeDate(d, locale, opts) { return dateFormat(locale, withDefaults(opts, "date", "date")).format(d); }
export function localeTime(d, locale, opts) { return dateFormat(locale, withDefaults(opts, "time", "time")).format(d); }
