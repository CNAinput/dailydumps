// Modelo derivado dos dados: catálogo de instrumentos, índices do OHLC e limiares de poucos ticks.
import { LOW_TICKS_MIN_DAYS, LOW_TICKS_RATIO } from "./config.js";
import { addDays, daysBetween, fmtInt, fmtNumber, median, normalizeText } from "./format.js";

export const TYPE_LABELS = { company: "Empresa", asset: "Ativo", index: "Índice" };
export const TYPE_OPTIONS = [["company", "Empresa"], ["asset", "Ativo"], ["index", "Índice"]];
export const EVENT_LABELS = { ipo: "IPO", split: "Split", issuance: "Emissão", delisting: "Retirada de cotação" };
export const EVENT_LETTERS = { ipo: "I", split: "S", issuance: "E", delisting: "R" };

export function keyOf(code, assetType) {
  return code + "|" + assetType;
}

export function makeInstrument(code, assetType, slug, name, indexCodes, indexFlag) {
  const isIndex = indexFlag === true || (assetType === "asset" && indexCodes.has(code));
  const type = isIndex ? "index" : assetType;
  return {
    key: keyOf(code, assetType),
    code,
    assetType,
    slug: slug || null,
    name: name || null,
    isIndex,
    type,
    label: TYPE_LABELS[type] || assetType,
    title: name || code,
    searchText: normalizeText(code + " " + (name || "")),
  };
}

// Enquanto o registo não diz quais são os índices, valem os que aparecem no resumo do último dia.
export function indexCodesFrom(latest) {
  const codes = new Set();
  const indices = latest && latest.summary && Array.isArray(latest.summary.indices) ? latest.summary.indices : [];
  for (const entry of indices) codes.add(entry.code);
  return codes;
}

export function buildCatalog(list, indexCodes) {
  const items = list.instruments.map((entry) =>
    makeInstrument(entry.code, entry.asset_type, entry.slug, entry.name, indexCodes));
  return {
    items,
    indexCodes,
    byKey: new Map(items.map((item) => [item.key, item])),
    bySlug: new Map(items.map((item) => [item.slug, item])),
  };
}

export function lookup(catalog, code, assetType) {
  return catalog.byKey.get(keyOf(code, assetType)) || makeInstrument(code, assetType, null, null, catalog.indexCodes);
}

// O snapshot sabe se o instrumento é um índice e o nome; o slug vem do catálogo.
export function instrumentFromSnapshot(entry, catalog) {
  const known = catalog.byKey.get(keyOf(entry.code, entry.asset_type));
  return makeInstrument(
    entry.code, entry.asset_type, known ? known.slug : null, entry.name || (known ? known.name : null),
    catalog.indexCodes, entry.is_index,
  );
}

export function indexOhlc(rows) {
  const byDate = new Map();
  const byKey = new Map();
  for (const row of rows) {
    if (!byDate.has(row.date)) byDate.set(row.date, []);
    byDate.get(row.date).push(row);
    if (!byKey.has(row.key)) byKey.set(row.key, []);
    byKey.get(row.key).push(row);
  }
  return { rows, byDate, byKey, dates: [...byDate.keys()].sort() };
}

// Dias arquivados, em ordem, com o que o manifesto acrescenta.
export function buildDays(datesJson, manifest) {
  const days = manifest && manifest.days ? manifest.days : {};
  return datesJson.dates.map((entry) => {
    const extra = days[entry.date] || {};
    return {
      date: entry.date,
      source: entry.source,
      partial: entry.partial,
      rows: entry.rows,
      generatedAt: extra.generated_at || null,
      sha256: extra.sha256 || null,
      regenerations: Array.isArray(extra.regenerations) ? extra.regenerations : [],
    };
  });
}

export function dayBaseline(days) {
  return { median: median(days.map((day) => day.rows)), enough: days.length >= LOW_TICKS_MIN_DAYS };
}

export function isLowDay(day, baseline) {
  return baseline.enough && day.rows < LOW_TICKS_RATIO * baseline.median;
}

export function instrumentBaselines(ohlcIndex) {
  const baselines = new Map();
  for (const [key, rows] of ohlcIndex.byKey) {
    baselines.set(key, { median: median(rows.map((row) => row.ticks)), enough: rows.length >= LOW_TICKS_MIN_DAYS });
  }
  return baselines;
}

export function isLowRow(row, baselines) {
  const baseline = baselines.get(row.key);
  return Boolean(baseline && baseline.enough && row.ticks < LOW_TICKS_RATIO * baseline.median);
}

export function neighbours(dates, date) {
  const at = dates.indexOf(date);
  return {
    previous: at > 0 ? dates[at - 1] : null,
    next: at >= 0 && at < dates.length - 1 ? dates[at + 1] : null,
  };
}

// Dias civis sem ficheiro entre o primeiro e o último dia arquivado.
export function missingDays(dates) {
  if (dates.length < 2) return [];
  const present = new Set(dates);
  const missing = [];
  for (let at = addDays(dates[0], 1); daysBetween(at, dates[dates.length - 1]) > 0; at = addDays(at, 1)) {
    if (!present.has(at)) missing.push(at);
  }
  return missing;
}

// Meses do mais recente para o mais antigo, cada um com os seus dias do mais recente para o mais antigo.
export function groupByMonth(dates) {
  const groups = new Map();
  for (const date of [...dates].sort().reverse()) {
    const month = date.slice(0, 7);
    if (!groups.has(month)) groups.set(month, []);
    groups.get(month).push(date);
  }
  return [...groups].map(([month, list]) => ({ month, dates: list }));
}

// Evento do JSON de um instrumento, com o mesmo formato do events.csv lido.
export function eventFromJson(entry, code, assetType) {
  return {
    date: entry.date,
    code,
    type: assetType,
    key: keyOf(code, assetType),
    event: entry.event,
    factor: entry.factor === undefined ? null : entry.factor,
    sharesBefore: entry.shares_before === undefined ? null : entry.shares_before,
    sharesAfter: entry.shares_after === undefined ? null : entry.shares_after,
    documentId: entry.document_id === undefined ? null : entry.document_id,
    notes: entry.notes || "",
  };
}

function plainFactor(factor) {
  return fmtNumber(factor, 0, 4);
}

export function describeEvent(event) {
  if (event.event === "split") {
    if (!Number.isFinite(event.factor) || event.factor <= 0) return "Split";
    return event.factor >= 1
      ? "Split 1 para " + plainFactor(event.factor)
      : "Split inverso " + plainFactor(1 / event.factor) + " para 1";
  }
  if (event.event === "issuance") {
    if (event.sharesBefore !== null && event.sharesAfter !== null) {
      return "Emissão de " + fmtInt(event.sharesAfter - event.sharesBefore) + " shares";
    }
    return "Emissão de shares";
  }
  if (event.event === "ipo") {
    return event.sharesAfter === null ? "IPO" : "IPO com " + fmtInt(event.sharesAfter) + " shares";
  }
  return EVENT_LABELS[event.event] || event.event;
}
