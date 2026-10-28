// Pesquisa de dias: uma linha por instrumento e dia (abertura, máximo, mínimo, fecho, variação e ticks).
import { loadCore } from "../core.js";
import { h } from "../dom.js";
import { fmtCoins, fmtInt, fmtNumber, normalizeText } from "../format.js";
import { TYPE_OPTIONS, isLowRow } from "../model.js";
import { chip, dayLink, delta, instrumentLink, ticksHref, typeChip } from "../ui/blocks.js";

function numberOrNull(text) {
  if (text === "" || text === undefined) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function price(key, label, field) {
  return { key, label, num: true, value: (row) => row[field], render: (row) => fmtCoins(row[field]) };
}

export const dataset = {
  id: "dias",
  title: "Pesquisa de dias",
  caption: "Dias e instrumentos: preços de abertura, máximo, mínimo e fecho, variação e ticks",
  emptyText: "Nenhum dia corresponde a estes filtros.",
  defaultSort: { key: "data", dir: "desc" },

  async init(ctx) {
    const core = await loadCore(ctx.signal);
    return { core, first: core.dates[0], last: core.dates[core.dates.length - 1] };
  },

  fields: (init) => [
    { name: "q", label: "Código ou nome", type: "text", placeholder: "ex.: NEWTE" },
    { name: "tipo", label: "Tipo", type: "select", options: [["", "Todos"], ...TYPE_OPTIONS] },
    { name: "de", label: "Desde", type: "date", min: init.first, max: init.last },
    { name: "ate", label: "Até", type: "date", min: init.first, max: init.last },
    {
      name: "min", label: "Variação mínima (%)", type: "number", min: "0", step: "any",
      hint: "Em valor absoluto, da abertura ao fecho do dia.",
    },
    {
      name: "sentido", label: "Sentido", type: "select",
      options: [["", "Subida ou descida"], ["up", "Só subidas"], ["down", "Só descidas"]],
    },
  ],

  load: async (state, ctx, init) => init.core,

  columns: (core) => [
    { key: "data", label: "Data", header: true, value: (row) => row.date, render: (row) => dayLink(row.date) },
    {
      key: "instrumento", label: "Instrumento",
      value: (row) => row.instrument.code, render: (row) => instrumentLink(row.instrument),
    },
    { key: "tipo", label: "Tipo", value: (row) => row.instrument.label, render: (row) => typeChip(row.instrument) },
    price("abertura", "Abertura", "open"),
    price("maximo", "Máximo", "high"),
    price("minimo", "Mínimo", "low"),
    price("fecho", "Fecho", "close"),
    { key: "variacao", label: "Variação", num: true, value: (row) => row.change, render: (row) => delta(row.change) },
    {
      key: "ticks", label: "Ticks", num: true, value: (row) => row.ticks,
      render: (row) => [
        isLowRow(row, core.baselines) ? chip("poucos", "warn", "Menos ticks do que o habitual neste instrumento") : null,
        isLowRow(row, core.baselines) ? " " : null,
        h("a", { href: ticksHref(row.date, row.instrument.slug) }, fmtInt(row.ticks)),
      ],
    },
  ],

  rows(core, state) {
    const query = normalizeText(state.q.trim());
    const minimum = numberOrNull(state.min);
    return core.ohlc.rows.filter((row) => {
      if (query && !row.instrument.searchText.includes(query)) return false;
      if (state.tipo && row.instrument.type !== state.tipo) return false;
      if (state.de && row.date < state.de) return false;
      if (state.ate && row.date > state.ate) return false;
      if (minimum !== null && !(Math.abs(row.change) >= minimum)) return false;
      if (state.sentido === "up" && !(row.change > 0)) return false;
      if (state.sentido === "down" && !(row.change < 0)) return false;
      return true;
    });
  },

  summary(core, rows, state) {
    const days = new Set(rows.map((row) => row.date)).size;
    const instruments = new Set(rows.map((row) => row.key)).size;
    const minimum = numberOrNull(state.min);
    return (
      fmtInt(rows.length) + (rows.length === 1 ? " linha" : " linhas") + ", " + fmtInt(days) + (days === 1 ? " dia" : " dias") +
      " e " + fmtInt(instruments) + (instruments === 1 ? " instrumento" : " instrumentos") +
      (minimum !== null ? ", com variação de pelo menos " + fmtNumber(minimum, 0, 2) + " %" : "") + "."
    );
  },
};
