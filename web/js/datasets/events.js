// Pesquisa de eventos: IPO, splits, emissões e retiradas de cotação do events.csv.
import { loadEvents } from "../api.js";
import { DOCUMENT_URL } from "../config.js";
import { loadCore } from "../core.js";
import { externalLink } from "../dom.js";
import { fmtInt, fmtNumber, normalizeText } from "../format.js";
import { EVENT_LABELS, describeEvent, lookup } from "../model.js";
import { dayLink, instrumentLink } from "../ui/blocks.js";

function shares(value) {
  return value === null ? "n/d" : fmtInt(value);
}

function dispatchLabel(id) {
  if (id === null) return "n/d";
  const label = "Despacho n.º " + id;
  return DOCUMENT_URL ? externalLink(DOCUMENT_URL.replace("{id}", String(id)), label) : label;
}

export const dataset = {
  id: "eventos",
  title: "Pesquisa de eventos",
  caption: "Eventos estruturais: data, instrumento, evento, shares, despacho e notas",
  emptyText: "Nenhum evento corresponde a estes filtros.",
  defaultSort: { key: "data", dir: "desc" },

  async init(ctx) {
    const [core, events] = await Promise.all([loadCore(ctx.signal), loadEvents(ctx.signal)]);
    for (const event of events) event.instrument = lookup(core.catalog, event.code, event.type);
    return { core, events, first: core.dates[0], last: core.dates[core.dates.length - 1] };
  },

  fields: () => [
    { name: "q", label: "Instrumento ou nota", type: "text", placeholder: "ex.: NEWTE" },
    {
      name: "evento", label: "Evento", type: "select",
      options: [["", "Todos"], ...Object.entries(EVENT_LABELS)],
    },
    { name: "de", label: "Desde", type: "date" },
    { name: "ate", label: "Até", type: "date" },
  ],

  load: async (state, ctx, init) => init,

  columns: () => [
    { key: "data", label: "Data", header: true, value: (event) => event.date, render: (event) => dayLink(event.date) },
    {
      key: "instrumento", label: "Instrumento",
      value: (event) => event.instrument.code, render: (event) => instrumentLink(event.instrument),
    },
    { key: "evento", label: "Evento", value: (event) => event.event + event.date, render: (event) => describeEvent(event) },
    {
      key: "factor", label: "Factor", num: true, value: (event) => event.factor,
      render: (event) => (event.factor === null ? "n/d" : fmtNumber(event.factor, 0, 4)),
    },
    { key: "antes", label: "Shares antes", num: true, value: (event) => event.sharesBefore, render: (event) => shares(event.sharesBefore) },
    { key: "depois", label: "Shares depois", num: true, value: (event) => event.sharesAfter, render: (event) => shares(event.sharesAfter) },
    { key: "despacho", label: "Despacho", num: true, value: (event) => event.documentId, render: (event) => dispatchLabel(event.documentId) },
    { key: "notas", label: "Notas", value: (event) => event.notes, render: (event) => event.notes || "n/d" },
  ],

  rows(data, state) {
    const query = normalizeText(state.q.trim());
    return data.events.filter((event) => {
      if (query && !(event.instrument.searchText.includes(query) || normalizeText(event.notes).includes(query))) return false;
      if (state.evento && event.event !== state.evento) return false;
      if (state.de && event.date < state.de) return false;
      if (state.ate && event.date > state.ate) return false;
      return true;
    });
  },

  summary(data, rows) {
    return (
      fmtInt(rows.length) + " de " + fmtInt(data.events.length) + (data.events.length === 1 ? " evento." : " eventos.") +
      " As datas seguem o dia do primeiro ficheiro gerado depois da alteração."
    );
  },
};
