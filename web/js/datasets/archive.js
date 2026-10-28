// Dias arquivados: origem, ticks, hora de geração e avisos de cada dia.
import { loadCore } from "../core.js";
import { h } from "../dom.js";
import { fmtDate, fmtInstant, fmtInt, normalizeText } from "../format.js";
import { isLowDay } from "../model.js";
import { dayChips, dayLink } from "../ui/blocks.js";

export const dataset = {
  id: "arquivo",
  title: "Dias arquivados",
  caption: "Dias arquivados: origem, ticks, hora de geração, avisos e soma de controlo",
  emptyText: "Nenhum dia corresponde a estes filtros.",
  defaultSort: { key: "data", dir: "desc" },

  async init(ctx) {
    const core = await loadCore(ctx.signal);
    const days = core.days.map((day) => ({ ...day, low: isLowDay(day, core.baseline) }));
    return { core, days };
  },

  fields: () => [
    { name: "q", label: "Data", type: "text", placeholder: "ex.: 2026-10 ou 13/10" },
    {
      name: "origem", label: "Origem", type: "select",
      options: [["", "Todas"], ["daily", "Arquivado no fecho"], ["backfill", "Arquivado depois do fecho"]],
    },
    {
      name: "aviso", label: "Avisos", type: "select",
      options: [["", "Todos os dias"], ["poucos", "Poucos ticks"], ["parcial", "Parcial"], ["regenerado", "Regenerado"]],
    },
  ],

  load: async (state, ctx, init) => init,

  columns: (data) => [
    { key: "data", label: "Data", header: true, value: (day) => day.date, render: (day) => dayLink(day.date) },
    {
      key: "avisos", label: "Estado", value: (day) => (day.source === "daily" ? 0 : 1) + (day.partial ? 2 : 0) + (day.low ? 4 : 0),
      render: (day) => h("span", { class: "chips-inline" }, dayChips(day, data.core.baseline).flatMap((item) => [item, " "])),
    },
    { key: "ticks", label: "Ticks", num: true, value: (day) => day.rows, render: (day) => fmtInt(day.rows) },
    {
      key: "gerado", label: "Gerado em (Lisboa)", value: (day) => day.generatedAt,
      render: (day) => (day.generatedAt ? fmtInstant(day.generatedAt) : "n/d"),
    },
    {
      key: "sha256", label: "SHA-256 do ficheiro de ticks", value: (day) => day.sha256,
      render: (day) => (day.sha256 ? h("code", { class: "mono hash" }, day.sha256) : "n/d"),
    },
  ],

  rows(data, state) {
    const query = normalizeText(state.q.trim());
    return data.days.filter((day) => {
      if (query && !(day.date.includes(query) || fmtDate(day.date).includes(query))) return false;
      if (state.origem && day.source !== state.origem) return false;
      if (state.aviso === "poucos" && !day.low) return false;
      if (state.aviso === "parcial" && !day.partial) return false;
      if (state.aviso === "regenerado" && day.regenerations.length === 0) return false;
      return true;
    });
  },

  summary: (data, rows) => fmtInt(rows.length) + " de " + fmtInt(data.days.length) + (data.days.length === 1 ? " dia." : " dias."),
};
