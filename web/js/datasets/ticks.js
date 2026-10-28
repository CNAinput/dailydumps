// Pesquisa de ticks: todos os preços registados em um ou mais dias, lidos do GitHub só quando pedidos.
import { describeError, loadTicks } from "../api.js";
import { TICKS_CONCURRENCY, TICKS_MAX_DAYS } from "../config.js";
import { loadCore } from "../core.js";
import { h } from "../dom.js";
import { fmtCoins, fmtDate, fmtInstantMs, fmtInt, isDate, roundHalfUp } from "../format.js";
import { TYPE_OPTIONS, lookup } from "../model.js";
import { delta, instrumentLink, typeChip } from "../ui/blocks.js";
import { createLineChart } from "../ui/chart.js";
import { InputError, mapLimit } from "../ui/explorer.js";
import { settle } from "../ui/states.js";

function minutesOf(text) {
  const match = /^(\d{2}):(\d{2})$/.exec(text || "");
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function numberOrNull(text) {
  if (text === "" || text === undefined) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

export const dataset = {
  id: "ticks",
  title: "Pesquisa de ticks",
  caption: "Ticks de preço: instante em hora de Lisboa, instrumento, preço e variação face ao tick anterior",
  emptyText: "Nenhum tick corresponde a estes filtros.",
  defaultSort: { key: "instante", dir: "asc" },

  async init(ctx) {
    const core = await loadCore(ctx.signal);
    return { core, first: core.dates[0], last: core.dates[core.dates.length - 1] };
  },

  fields: (init) => [
    { name: "de", label: "Desde", type: "date", min: init.first, max: init.last, default: init.last, reload: true },
    {
      name: "ate", label: "Até", type: "date", min: init.first, max: init.last, default: init.last, reload: true,
      hint: "No máximo " + TICKS_MAX_DAYS + " dias por pesquisa.",
    },
    {
      name: "i", label: "Instrumento", type: "select",
      options: [["", "Todos"], ...init.core.catalog.items.map((item) => [item.slug, item.code + (item.name ? " (" + item.name + ")" : "")])],
    },
    { name: "tipo", label: "Tipo", type: "select", options: [["", "Todos"], ...TYPE_OPTIONS] },
    { name: "h1", label: "Hora desde (Lisboa)", type: "time" },
    { name: "h2", label: "Hora até (Lisboa)", type: "time" },
    { name: "pmin", label: "Preço mínimo (¢)", type: "number", min: "0", step: "any" },
    { name: "pmax", label: "Preço máximo (¢)", type: "number", min: "0", step: "any" },
    {
      name: "salto", label: "Salto mínimo (%)", type: "number", min: "0", step: "any",
      hint: "Variação face ao tick anterior do mesmo instrumento.",
    },
  ],

  loadKey: (state) => state.de + "|" + state.ate,

  async load(state, ctx, init, progress) {
    if (!isDate(state.de) || !isDate(state.ate)) throw new InputError("Indica as duas datas do intervalo.");
    if (state.de > state.ate) throw new InputError("A data inicial tem de ser anterior ou igual à data final.");
    const days = init.core.dates.filter((date) => date >= state.de && date <= state.ate);
    if (days.length === 0) throw new InputError("Não há dias arquivados nesse intervalo.");
    if (days.length > TICKS_MAX_DAYS) {
      throw new InputError(
        "O intervalo tem " + days.length + " dias arquivados e o máximo por pesquisa é " + TICKS_MAX_DAYS + ". Reduz o intervalo.",
      );
    }
    const results = await mapLimit(days, TICKS_CONCURRENCY, (date) => settle(loadTicks(date, ctx.signal)), progress);
    const failures = [];
    const rows = [];
    results.forEach((result, index) => {
      if (result.error) failures.push({ date: days[index], error: result.error });
      else for (const row of result.value) rows.push(row);
    });
    if (rows.length === 0 && failures.length > 0) throw failures[0].error;
    // Os dias são ficheiros distintos: a variação encadeia-se de um dia para o seguinte.
    const previous = new Map();
    for (const row of rows) {
      row.instrument = lookup(init.core.catalog, row.code, row.type);
      const before = previous.get(row.key);
      row.step = before === undefined ? NaN : roundHalfUp(((row.price - before) / before) * 100, 2);
      previous.set(row.key, row.price);
    }
    return { rows, failures, days };
  },

  columns: () => [
    { key: "instante", label: "Instante (Lisboa)", header: true, value: (row) => row.ms, render: (row) => fmtInstantMs(row.ms, true) },
    {
      key: "instrumento", label: "Instrumento",
      value: (row) => row.instrument.code, render: (row) => instrumentLink(row.instrument),
    },
    { key: "tipo", label: "Tipo", value: (row) => row.instrument.label, render: (row) => typeChip(row.instrument) },
    { key: "preco", label: "Preço", num: true, value: (row) => row.price, render: (row) => fmtCoins(row.price) },
    { key: "salto", label: "Face ao tick anterior", num: true, value: (row) => row.step, render: (row) => delta(row.step) },
  ],

  rows(data, state) {
    const from = minutesOf(state.h1);
    const to = minutesOf(state.h2);
    const lowest = numberOrNull(state.pmin);
    const highest = numberOrNull(state.pmax);
    const jump = numberOrNull(state.salto);
    return data.rows.filter((row) => {
      if (state.i && row.instrument.slug !== state.i) return false;
      if (state.tipo && row.instrument.type !== state.tipo) return false;
      if (from !== null && row.minute < from) return false;
      if (to !== null && row.minute > to) return false;
      if (lowest !== null && row.price < lowest) return false;
      if (highest !== null && row.price > highest) return false;
      if (jump !== null && !(Math.abs(row.step) >= jump)) return false;
      return true;
    });
  },

  summary(data, rows) {
    const instruments = new Set(rows.map((row) => row.key)).size;
    const loaded = data.days.length - data.failures.length;
    return (
      fmtInt(rows.length) + " de " + fmtInt(data.rows.length) + " ticks, " + fmtInt(instruments) +
      (instruments === 1 ? " instrumento" : " instrumentos") + ", em " + fmtInt(loaded) + (loaded === 1 ? " dia." : " dias.")
    );
  },

  extra(data, rows) {
    const box = h("div");
    if (data.failures.length > 0) {
      box.append(
        h(
          "div",
          { class: "note note-warn", role: "alert" },
          h("p", null, "Não foi possível carregar os ticks de " + data.failures.length + (data.failures.length === 1 ? " dia" : " dias") + ":"),
          h("ul", null, data.failures.map((item) => h("li", null, fmtDate(item.date) + ". " + describeError(item.error)))),
        ),
      );
    }
    const keys = new Set(rows.map((row) => row.key));
    if (keys.size !== 1 || rows.length < 2) {
      box.append(h("p", { class: "muted" }, "Escolhe um instrumento para ver o gráfico do preço."));
      return { el: box };
    }
    const instrument = rows[0].instrument;
    const chart = createLineChart({
      points: rows.map((row) => ({ x: row.ms, y: row.price })),
      kind: "time",
      height: 280,
      ariaLabel:
        "Gráfico do preço de " + instrument.title + " entre " + fmtInstantMs(rows[0].ms) + " e " +
        fmtInstantMs(rows[rows.length - 1].ms) + ". A tabela abaixo tem os mesmos valores.",
      describePoint: (point) => fmtInstantMs(point.x, true) + ": " + fmtCoins(point.y),
    });
    box.append(h("h3", { class: "block-title" }, "Preço de " + instrument.title), chart.el);
    return { el: box, destroy: chart.destroy };
  },
};
