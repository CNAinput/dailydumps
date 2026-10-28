// Formatação pt-PT: números, percentagens, datas e instantes em hora de Lisboa.
import { TIMEZONE } from "./config.js";

export const NA = "n/d";
export const NBSP = " ";
export const COIN = "¢";
export const DAY_MS = 86400000;
const HOUR_MS = 3600000;

const numberFormats = new Map();

function numberFormat(min, max, signed) {
  const key = min + ":" + max + ":" + signed;
  let format = numberFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat("pt-PT", {
      minimumFractionDigits: min,
      maximumFractionDigits: max,
      signDisplay: signed ? "exceptZero" : "auto",
    });
    numberFormats.set(key, format);
  }
  return format;
}

function pad(value) {
  return String(value).padStart(2, "0");
}

// Arredonda a `decimals` casas com a metade para longe de zero, como o Decimal do arquivo.
export function roundHalfUp(value, decimals = 2) {
  if (!Number.isFinite(value)) return NaN;
  const sign = value < 0 ? -1 : 1;
  const scaled = Number(Math.abs(value).toFixed(10) + "e" + decimals);
  const result = sign * Number(Math.round(scaled) + "e-" + decimals);
  return result === 0 ? 0 : result;
}

export function fmtNumber(value, min = 2, max = min) {
  return Number.isFinite(value) ? numberFormat(min, max, false).format(value) : NA;
}

export function fmtInt(value) {
  return fmtNumber(value, 0, 0);
}

export function fmtCoins(value) {
  return Number.isFinite(value) ? fmtNumber(value, 2) + NBSP + COIN : NA;
}

export function fmtPct(value) {
  if (!Number.isFinite(value)) return NA;
  return numberFormat(2, 2, true).format(roundHalfUp(value, 2)) + NBSP + "%";
}

// Variação da abertura ao fecho, já arredondada a 2 casas.
export function variation(open, close) {
  if (!(open > 0) || !Number.isFinite(close)) return NaN;
  return roundHalfUp(((close - open) / open) * 100, 2);
}

export function direction(value) {
  if (!Number.isFinite(value)) return "none";
  const rounded = roundHalfUp(value, 2);
  return rounded > 0 ? "up" : rounded < 0 ? "down" : "flat";
}

export const ARROWS = { up: "▲", down: "▼", flat: "=", none: "" };
export const DIRECTION_WORDS = { up: "subida", down: "descida", flat: "sem variação", none: "" };

// Datas civis AAAA-MM-DD, sem passar pelo fuso do browser.
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function dayMs(iso) {
  const match = typeof iso === "string" ? DATE_RE.exec(iso) : null;
  return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : NaN;
}

export function isoFromDayMs(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

export function isDate(text) {
  const ms = dayMs(text);
  return Number.isFinite(ms) && isoFromDayMs(ms) === text;
}

export function addDays(iso, days) {
  return isoFromDayMs(dayMs(iso) + days * DAY_MS);
}

export function daysBetween(first, last) {
  return Math.round((dayMs(last) - dayMs(first)) / DAY_MS);
}

export function fmtDate(iso) {
  const match = typeof iso === "string" ? DATE_RE.exec(iso) : null;
  return match ? match[3] + "/" + match[2] + "/" + match[1] : NA;
}

export function fmtShortDate(ms, withYear) {
  const iso = isoFromDayMs(ms);
  return iso.slice(8, 10) + "/" + iso.slice(5, 7) + (withYear ? "/" + iso.slice(2, 4) : "");
}

const longDate = new Intl.DateTimeFormat("pt-PT", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const weekdayName = new Intl.DateTimeFormat("pt-PT", { weekday: "long", timeZone: "UTC" });
const monthName = new Intl.DateTimeFormat("pt-PT", { month: "long", year: "numeric", timeZone: "UTC" });

export function fmtLongDate(iso) {
  return isDate(iso) ? longDate.format(new Date(dayMs(iso))) : NA;
}

export function fmtWeekday(iso) {
  return isDate(iso) ? weekdayName.format(new Date(dayMs(iso))) : NA;
}

// "2026-10" ou uma data completa: "outubro de 2026".
export function fmtMonth(iso) {
  const day = iso.length === 7 ? iso + "-01" : iso;
  return isDate(day) ? monthName.format(new Date(dayMs(day))) : NA;
}

// Instantes: o arquivo guarda UTC com sufixo Z e mostra-se em hora de Lisboa.
const TS_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$/;

export function parseUtc(text) {
  const match = typeof text === "string" ? TS_RE.exec(text) : null;
  if (!match) return NaN;
  const millis = match[7] ? Number(match[7].slice(0, 3).padEnd(3, "0")) : 0;
  return Date.UTC(
    Number(match[1]), Number(match[2]) - 1, Number(match[3]),
    Number(match[4]), Number(match[5]), Number(match[6]), millis,
  );
}

const lisbonFormat = new Intl.DateTimeFormat("pt-PT", {
  timeZone: TIMEZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

export function lisbonParts(ms) {
  const parts = {};
  for (const part of lisbonFormat.formatToParts(new Date(ms))) {
    if (part.type !== "literal") parts[part.type] = Number(part.value);
  }
  return parts;
}

export function lisbonDate(ms) {
  const parts = lisbonParts(ms);
  return parts.year + "-" + pad(parts.month) + "-" + pad(parts.day);
}

export function fmtClock(ms, seconds = false) {
  const parts = lisbonParts(ms);
  return pad(parts.hour) + ":" + pad(parts.minute) + (seconds ? ":" + pad(parts.second) : "");
}

export function fmtInstantMs(ms, seconds = false) {
  const parts = lisbonParts(ms);
  return pad(parts.day) + "/" + pad(parts.month) + "/" + parts.year + " " + fmtClock(ms, seconds);
}

export function fmtInstant(text, seconds = false) {
  const ms = parseUtc(text);
  return Number.isFinite(ms) ? fmtInstantMs(ms, seconds) : NA;
}

// Instante UTC da meia-noite de Lisboa (há dias de 23 e de 25 horas).
const midnights = new Map();

export function lisbonMidnightMs(iso) {
  if (midnights.has(iso)) return midnights.get(iso);
  const base = dayMs(iso);
  let result = NaN;
  for (const offset of [0, HOUR_MS]) {
    const parts = lisbonParts(base - offset);
    if (parts.hour === 0 && parts.minute === 0 && parts.day === Number(iso.slice(8, 10))) {
      result = base - offset;
      break;
    }
  }
  midnights.set(iso, result);
  return result;
}

// Diferença entre a hora de parede de Lisboa e o UTC, em milissegundos.
export function lisbonOffsetMs(ms) {
  const parts = lisbonParts(ms);
  return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second) - Math.floor(ms / 1000) * 1000;
}

// Nos dias com mudança de hora (23 ou 25 horas), a partir de `at` a hora de parede difere em `minutes` do tempo decorrido.
export function lisbonDayShift(iso) {
  const start = lisbonMidnightMs(iso);
  const end = lisbonMidnightMs(addDays(iso, 1));
  if (end - start === DAY_MS) return null;
  const before = lisbonOffsetMs(start);
  for (let ms = start + HOUR_MS; ms < end; ms += HOUR_MS) {
    const offset = lisbonOffsetMs(ms);
    if (offset !== before) return { at: ms, minutes: (offset - before) / 60000 };
  }
  return null;
}

// Último dia cujo fecho (23:00 de Lisboa) já passou.
export function lastClosedDay(nowMs = Date.now()) {
  const parts = lisbonParts(nowMs);
  const today = parts.year + "-" + pad(parts.month) + "-" + pad(parts.day);
  return parts.hour >= 23 ? today : addDays(today, -1);
}

export function normalizeText(text) {
  return String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function median(values) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (sorted.length === 0) return NaN;
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
