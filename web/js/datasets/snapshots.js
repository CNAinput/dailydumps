// Pesquisa de capitalização: o estado do mercado no fecho, nos dias arquivados com snapshot.
import { loadSnapshot } from "../api.js";
import { SNAPSHOTS_MAX_DAYS, TICKS_CONCURRENCY } from "../config.js";
import { loadCore } from "../core.js";
import { fmtCoins, fmtDate, fmtInt, fmtNumber, isDate, normalizeText } from "../format.js";
import { TYPE_OPTIONS, instrumentFromSnapshot } from "../model.js";
import { CAP_NOTE, dayLink, instrumentLink, typeChip } from "../ui/blocks.js";
import { InputError, mapLimit } from "../ui/explorer.js";
import { settle } from "../ui/states.js";

export const dataset = {
  id: "capitalizacao",
  title: "Pesquisa de capitalização",
  caption: "Capitalização no fecho: preço, shares autorizadas, shares em circulação e capitalização",
  emptyText: "Nenhum registo corresponde a estes filtros.",
  defaultSort: { key: "data", dir: "desc" },

  async init(ctx) {
    const core = await loadCore(ctx.signal);
    const daily = core.days.filter((day) => day.source === "daily").map((day) => day.date);
    return { core, daily, first: core.dates[0], last: core.dates[core.dates.length - 1] };
  },

  fields: (init) => [
    { name: "q", label: "Código ou nome", type: "text", placeholder: "ex.: NEWTE" },
    { name: "tipo", label: "Tipo", type: "select", options: [["", "Todos"], ...TYPE_OPTIONS] },
    { name: "de", label: "Desde", type: "date", min: init.first, max: init.last, reload: true },
    { name: "ate", label: "Até", type: "date", min: init.first, max: init.last, reload: true },
  ],

  loadKey: (state) => state.de + "|" + state.ate,

  async load(state, ctx, init, progress) {
    if ((state.de && !isDate(state.de)) || (state.ate && !isDate(state.ate))) {
      throw new InputError("Uma das datas não é válida.");
    }
    const days = init.daily.filter((date) => (!state.de || date >= state.de) && (!state.ate || date <= state.ate));
    if (days.length > SNAPSHOTS_MAX_DAYS) {
      throw new InputError("O intervalo tem " + days.length + " dias com snapshot e o máximo por pesquisa é " + SNAPSHOTS_MAX_DAYS + ".");
    }
    const results = await mapLimit(days, TICKS_CONCURRENCY, (date) => settle(loadSnapshot(date, ctx.signal)), progress);
    const rows = [];
    const failures = [];
    results.forEach((result, index) => {
      if (result.error) {
        failures.push(days[index]);
        return;
      }
      for (const entry of result.value.instruments) {
        const instrument = instrumentFromSnapshot(entry, init.core.catalog);
        rows.push({
          date: days[index],
          key: instrument.key,
          instrument,
          price: entry.price,
          total: entry.shares_total,
          circulating: entry.shares_in_circulation,
          share: entry.shares_total > 0 ? (entry.shares_in_circulation / entry.shares_total) * 100 : NaN,
          cap: entry.market_cap,
        });
      }
    });
    if (rows.length === 0 && failures.length > 0) throw new Error("Não foi possível carregar nenhum snapshot.");
    return { rows, failures, available: init.daily.length };
  },

  columns: () => [
    { key: "data", label: "Data", header: true, value: (row) => row.date, render: (row) => dayLink(row.date) },
    {
      key: "instrumento", label: "Instrumento",
      value: (row) => row.instrument.code, render: (row) => instrumentLink(row.instrument),
    },
    { key: "tipo", label: "Tipo", value: (row) => row.instrument.label, render: (row) => typeChip(row.instrument) },
    { key: "preco", label: "Preço", num: true, value: (row) => row.price, render: (row) => fmtCoins(row.price) },
    { key: "autorizadas", label: "Shares autorizadas", num: true, value: (row) => row.total, render: (row) => fmtInt(row.total) },
    { key: "circulacao", label: "Em circulação", num: true, value: (row) => row.circulating, render: (row) => fmtInt(row.circulating) },
    {
      key: "percentagem", label: "% em circulação", num: true, value: (row) => row.share,
      render: (row) => (Number.isFinite(row.share) ? fmtNumber(row.share, 2) + " %" : "n/d"),
    },
    { key: "capitalizacao", label: "Capitalização", num: true, value: (row) => row.cap, render: (row) => fmtCoins(row.cap) },
  ],

  rows(data, state) {
    const query = normalizeText(state.q.trim());
    return data.rows.filter((row) => {
      if (query && !row.instrument.searchText.includes(query)) return false;
      if (state.tipo && row.instrument.type !== state.tipo) return false;
      return true;
    });
  },

  summary(data, rows) {
    if (data.available === 0) {
      return (
        "Ainda não há dias arquivados com snapshot: só os dias gerados logo a seguir ao fecho (origem " +
        "«daily») o têm, e os arquivados depois do fecho (backfill) não."
      );
    }
    const days = new Set(rows.map((row) => row.date)).size;
    return (
      fmtInt(rows.length) + (rows.length === 1 ? " registo" : " registos") + " em " + fmtInt(days) +
      (days === 1 ? " dia. " : " dias. ") + CAP_NOTE +
      (data.failures.length > 0 ? " Não foi possível carregar " + data.failures.map(fmtDate).join(", ") + "." : "")
    );
  },
};
