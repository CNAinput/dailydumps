// Dados partilhados pelas páginas: último dia, instrumentos, OHLC e estado de cada dia arquivado.
import { loadDates, loadInstrumentList, loadLatest, loadManifest, loadOhlc } from "./api.js";
import {
  buildCatalog, buildDays, dayBaseline, indexCodesFrom, indexOhlc, instrumentBaselines, lookup,
} from "./model.js";
import { settle } from "./ui/states.js";

export async function loadCore(signal) {
  const [latest, datesJson, list, rows, manifest] = await Promise.all([
    loadLatest(signal),
    loadDates(signal),
    loadInstrumentList(signal),
    loadOhlc(signal),
    settle(loadManifest(signal)),
  ]);
  const catalog = buildCatalog(list, indexCodesFrom(latest));
  for (const row of rows) row.instrument = lookup(catalog, row.code, row.type);
  const ohlc = indexOhlc(rows);
  const days = buildDays(datesJson, manifest.value || null);
  return {
    latest,
    catalog,
    ohlc,
    days,
    dates: days.map((day) => day.date),
    dayMap: new Map(days.map((day) => [day.date, day])),
    baseline: dayBaseline(days),
    baselines: instrumentBaselines(ohlc),
    manifestError: manifest.error || null,
  };
}
