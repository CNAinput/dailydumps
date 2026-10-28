// Lista de instrumentos que alguma vez tiveram preços no arquivo.
import { loadCore } from "../core.js";
import { fmtCoins, fmtDate, fmtInt, normalizeText } from "../format.js";
import { TYPE_OPTIONS } from "../model.js";
import { dayLink, delta, instrumentLink, typeChip } from "../ui/blocks.js";

export const dataset = {
  id: "instrumentos",
  title: "Instrumentos",
  caption: "Instrumentos: tipo, período com dados, último fecho e variação do último dia",
  emptyText: "Nenhum instrumento corresponde a estes filtros.",
  defaultSort: { key: "instrumento", dir: "asc" },

  async init(ctx) {
    const core = await loadCore(ctx.signal);
    const items = core.catalog.items.map((instrument) => {
      const rows = core.ohlc.byKey.get(instrument.key) || [];
      const last = rows.length > 0 ? rows[rows.length - 1] : null;
      return {
        instrument,
        first: rows.length > 0 ? rows[0].date : null,
        last: last ? last.date : null,
        days: rows.length,
        close: last ? last.close : NaN,
        change: last ? last.change : NaN,
      };
    });
    return { core, items };
  },

  fields: () => [
    { name: "q", label: "Código ou nome", type: "text", placeholder: "ex.: NEWTE" },
    { name: "tipo", label: "Tipo", type: "select", options: [["", "Todos"], ...TYPE_OPTIONS] },
  ],

  load: async (state, ctx, init) => init,

  columns: () => [
    {
      key: "instrumento", label: "Instrumento", header: true,
      value: (item) => item.instrument.code, render: (item) => instrumentLink(item.instrument),
    },
    { key: "tipo", label: "Tipo", value: (item) => item.instrument.label, render: (item) => typeChip(item.instrument) },
    {
      key: "primeiro", label: "Primeiro dia", value: (item) => item.first,
      render: (item) => (item.first ? dayLink(item.first) : "n/d"),
    },
    {
      key: "ultimo", label: "Último dia", value: (item) => item.last,
      render: (item) => (item.last ? dayLink(item.last) : "n/d"),
    },
    { key: "dias", label: "Dias com dados", num: true, value: (item) => item.days, render: (item) => fmtInt(item.days) },
    { key: "fecho", label: "Último fecho", num: true, value: (item) => item.close, render: (item) => fmtCoins(item.close) },
    { key: "variacao", label: "Variação no último dia", num: true, value: (item) => item.change, render: (item) => delta(item.change) },
  ],

  rows(data, state) {
    const query = normalizeText(state.q.trim());
    return data.items.filter((item) => {
      if (query && !item.instrument.searchText.includes(query)) return false;
      if (state.tipo && item.instrument.type !== state.tipo) return false;
      return true;
    });
  },

  summary: (data, rows) =>
    fmtInt(rows.length) + " de " + fmtInt(data.items.length) + " instrumentos." +
    (data.core.dates.length > 0 ? " Dados de " + fmtDate(data.core.dates[0]) + " a " + fmtDate(data.core.dates[data.core.dates.length - 1]) + "." : ""),
};
