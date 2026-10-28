// Acesso aos dados: pedidos canceláveis, erros que explicam o motivo e cache em memória.
import { REPO_URL, RAW_URL, TICKS_BASE } from "./config.js";
import { checkCsv, parseCsv } from "./csv.js";
import { lisbonDayShift, lisbonMidnightMs, parseUtc, variation } from "./format.js";

export class DataError extends Error {
  constructor(path, kind, detail) {
    super(path + ": " + kind + (detail ? " " + detail : ""));
    this.name = "DataError";
    this.path = path;
    this.kind = kind;
    this.detail = detail;
  }
}

export function isAbort(error) {
  return Boolean(error) && error.name === "AbortError";
}

function abortError() {
  return new DOMException("Pedido cancelado.", "AbortError");
}

// Texto para o utilizador. Diz o ficheiro e o motivo.
export function describeError(error) {
  if (!(error instanceof DataError)) return error && error.message ? error.message : "Erro desconhecido.";
  const name = "«" + error.path + "»";
  if (error.kind === "http") {
    return error.detail === 404
      ? "Não foi possível carregar " + name + ": o ficheiro não existe no servidor (HTTP 404)."
      : "Não foi possível carregar " + name + ": o servidor respondeu HTTP " + error.detail + ".";
  }
  if (error.kind === "network") {
    return "Não foi possível carregar " + name + ": falha de rede ou pedido bloqueado pelo browser" +
      (error.detail ? " (" + error.detail + ")" : "") + ".";
  }
  return "Não foi possível ler " + name + ": " + error.detail + ".";
}

function originOf(url) {
  try {
    const origin = new URL(url, document.baseURI);
    return origin.origin === location.origin ? "" : origin.host;
  } catch {
    return "";
  }
}

async function request(url, path, parse, signal) {
  let response;
  try {
    response = await fetch(url, { signal, cache: "no-cache" });
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new DataError(path, "network", originOf(url));
  }
  if (!response.ok) throw new DataError(path, "http", response.status);
  let text;
  try {
    text = await response.text();
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new DataError(path, "network", originOf(url));
  }
  try {
    return parse(text);
  } catch (error) {
    throw new DataError(path, "parse", error.message);
  }
}

// Pedidos partilhados: cada consumidor tem o seu sinal e o pedido só é cancelado quando nenhum precisa dele.
const cache = new Map();

function consume(entry, url, signal) {
  if (signal && signal.aborted) return Promise.reject(abortError());
  entry.refs += 1;
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (action) => {
      if (settled) return false;
      settled = true;
      entry.refs -= 1;
      if (signal) signal.removeEventListener("abort", onAbort);
      action();
      return true;
    };
    function onAbort() {
      finish(() => reject(abortError()));
      if (entry.refs === 0 && !entry.done) {
        entry.controller.abort();
        if (cache.get(url) === entry) cache.delete(url);
      }
    }
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
    entry.promise.then(
      (value) => finish(() => resolve(value)),
      (error) => finish(() => reject(error)),
    );
  });
}

function load(url, path, parse, signal) {
  if (signal && signal.aborted) return Promise.reject(abortError());
  let entry = cache.get(url);
  if (!entry) {
    const controller = new AbortController();
    entry = { controller, done: false, refs: 0 };
    const created = entry;
    created.promise = request(url, path, parse, controller.signal).then(
      (value) => {
        created.done = true;
        return value;
      },
      (error) => {
        if (cache.get(url) === created) cache.delete(url);
        throw error;
      },
    );
    cache.set(url, created);
  }
  return consume(entry, url, signal);
}

function parseJson(text) {
  return JSON.parse(text);
}

function getJson(path, signal) {
  return load(path, path, parseJson, signal);
}

function getText(path, parse, signal) {
  return load(path, path, parse, signal);
}

export const OHLC_HEADER = ["date", "code", "asset_type", "open", "high", "low", "close", "ticks"];
export const EVENTS_HEADER = [
  "date", "code", "asset_type", "event", "factor", "shares_before", "shares_after", "document_id", "notes",
];
export const PRICES_HEADER = ["ts_utc", "code", "asset_type", "price"];

function numbers(values, line) {
  for (const value of values) {
    if (!Number.isFinite(value)) throw new Error("valor numérico inválido na linha " + line);
  }
}

export function parseOhlc(text) {
  const rows = checkCsv(parseCsv(text), OHLC_HEADER);
  return rows.map(([date, code, type, open, high, low, close, ticks], index) => {
    const row = {
      date, code, type, key: code + "|" + type,
      open: Number(open), high: Number(high), low: Number(low), close: Number(close), ticks: Number(ticks),
    };
    numbers([row.open, row.high, row.low, row.close, row.ticks], index + 2);
    row.change = variation(row.open, row.close);
    return row;
  });
}

function optionalNumber(text) {
  return text === "" ? null : Number(text);
}

export function parseEvents(text) {
  const rows = checkCsv(parseCsv(text), EVENTS_HEADER);
  return rows.map(([date, code, type, event, factor, before, after, documentId, notes]) => ({
    date, code, type, key: code + "|" + type, event, notes,
    factor: optionalNumber(factor),
    sharesBefore: optionalNumber(before),
    sharesAfter: optionalNumber(after),
    documentId: optionalNumber(documentId),
  }));
}

export function parseSums(text) {
  return text.split("\n").filter((line) => line !== "").map((line) => {
    const match = /^([0-9a-f]{64}) {2}(.+)$/.exec(line);
    if (!match) throw new Error("linha inválida: " + line.slice(0, 40));
    return { sha256: match[1], path: match[2] };
  });
}

// `minute` é o minuto da hora de parede de Lisboa nesse dia (0 a 1439), também nos dias de 23 e 25 horas.
export function parsePrices(text, date) {
  const rows = checkCsv(parseCsv(text), PRICES_HEADER);
  const midnight = lisbonMidnightMs(date);
  const shift = lisbonDayShift(date);
  return rows.map(([stamp, code, type, price], index) => {
    const ms = parseUtc(stamp);
    const elapsed = Math.floor((ms - midnight) / 60000);
    const minute = shift && ms >= shift.at ? elapsed + shift.minutes : elapsed;
    const row = { ms, minute, date, code, type, key: code + "|" + type, price: Number(price) };
    numbers([ms, row.price], index + 2);
    return row;
  });
}

export function pricesPath(date) {
  return "prices/" + date.slice(0, 4) + "/" + date + ".csv";
}

// Endereços para ligações: o raw serve o ficheiro e o blob é a página do GitHub.
export function rawUrl(path) {
  return RAW_URL + path;
}

export function githubUrl(path) {
  return REPO_URL + "/blob/main/" + path;
}

export const loadLatest = (signal) => getJson("latest.json", signal);
export const loadDates = (signal) => getJson("dates.json", signal);
export const loadInstrumentList = (signal) => getJson("instruments.json", signal);
export const loadInstrument = (slug, signal) => getJson("instruments/" + slug + ".json", signal);
export const loadOhlc = (signal) => getText("daily/ohlc.csv", parseOhlc, signal);
export const loadOhlcAdjusted = (signal) => getText("daily/ohlc_adjusted.csv", parseOhlc, signal);
export const loadEvents = (signal) => getText("events.csv", parseEvents, signal);
export const loadManifest = (signal) => getJson("manifest.json", signal);
export const loadStatus = (signal) => getJson("status.json", signal);
export const loadSums = (signal) => getText("SHA256SUMS", parseSums, signal);
export const loadDividends = (signal) => getJson("dividends.json", signal);
export const loadTaxes = (signal) => getJson("taxes.json", signal);
export const loadSummary = (date, signal) => getJson("summary/" + date + ".json", signal);
export const loadSnapshot = (date, signal) => getJson("snapshots/" + date + ".json", signal);

export function loadTicks(date, signal) {
  const path = pricesPath(date);
  return load(TICKS_BASE + path, path, (text) => parsePrices(text, date), signal);
}
