// Explorador genérico de um conjunto de dados: filtros, ordenação, paginação e estado no endereço.
//
// dataset: {
//   id, title, caption, emptyText,
//   init(ctx) -> init               carrega o que é preciso para montar os filtros
//   fields(init) -> [definição]     filtros; os que têm `reload` só valem ao carregar em «Pesquisar»
//   loadKey(state, init) -> texto   muda quando é preciso voltar a carregar
//   load(state, ctx, init, progress) -> dados
//   columns(dados, state, init), rows(dados, state, init), defaultSort: { key, dir }
//   summary(dados, linhas, state) -> texto, extra(dados, linhas, state, ctx, init) -> nó | { el, destroy }
// }
import { isAbort } from "../api.js";
import { clear, h } from "../dom.js";
import { fmtInt } from "../format.js";
import { createField } from "./form.js";
import { errorBox } from "./states.js";
import { createTable } from "./table.js";

const DEBOUNCE_MS = 220;

// Erro de quem pesquisa (intervalo inválido, por exemplo): mostra-se como aviso e não como falha.
export class InputError extends Error {
  constructor(message) {
    super(message);
    this.name = "InputError";
  }
}

function validValue(def, value) {
  if (def.type !== "select") return value;
  return def.options.some(([option]) => option === value) ? value : def.default || "";
}

export async function mountExplorer(container, ctx, dataset) {
  const { signal } = ctx;
  const root = h("div", { class: "explorer" });
  container.append(root);

  let init = null;
  try {
    init = dataset.init ? await dataset.init(ctx) : null;
  } catch (error) {
    if (signal.aborted || isAbort(error)) return;
    root.append(errorBox(error, ctx.retry));
    return;
  }
  if (signal.aborted) return;

  const defs = dataset.fields(init);
  const fields = defs.map(createField);
  const defaults = Object.fromEntries(defs.map((def) => [def.name, def.default || ""]));
  const state = { ...defaults };
  defs.forEach((def) => {
    if (ctx.query[def.name] !== undefined) state[def.name] = validValue(def, ctx.query[def.name]);
  });
  fields.forEach((field) => field.write(state[field.def.name]));

  let sort = { ...dataset.defaultSort };
  const sortable = new Set(dataset.sortKeys || []);
  if (ctx.query.ordem && (sortable.size === 0 || sortable.has(ctx.query.ordem))) {
    sort = { key: ctx.query.ordem, dir: ctx.query.dir === "asc" ? "asc" : "desc" };
  }

  const searchButton = h("button", { type: "submit", class: "button button-primary" }, "Pesquisar");
  const clearButton = h("button", { type: "button", class: "button" }, "Limpar filtros");
  const form = h(
    "form",
    { class: "filters", novalidate: "", role: "search", "aria-label": dataset.title },
    h("div", { class: "filters-grid" }, fields.map((field) => field.el)),
    h("div", { class: "filters-actions" }, searchButton, clearButton),
  );
  const notice = h("div", { class: "result-notice", hidden: true });
  const status = h("p", { class: "result-status", role: "status" });
  const extraHost = h("div", { class: "result-extra" });
  const tableHost = h("div", { class: "result-table" });
  root.append(form, notice, status, extraHost, tableHost);

  let data = null;
  let loadedKey = null;
  let table = null;
  let extraHandle = null;
  let token = 0;
  let timer = 0;

  ctx.onCleanup(() => {
    clearTimeout(timer);
    if (extraHandle && extraHandle.destroy) extraHandle.destroy();
  });

  function readState() {
    for (const field of fields) state[field.def.name] = field.read();
  }

  function showNotice(message, kind) {
    clear(notice);
    notice.hidden = !message;
    if (!message) return;
    notice.setAttribute("role", kind === "alert" ? "alert" : "status");
    notice.append(h("p", { class: kind === "alert" ? "note note-warn" : "note" }, message));
  }

  function syncUrl() {
    const query = {};
    for (const def of defs) {
      if (state[def.name] !== defaults[def.name]) query[def.name] = state[def.name];
    }
    if (sort.key !== dataset.defaultSort.key || sort.dir !== dataset.defaultSort.dir) {
      query.ordem = sort.key;
      query.dir = sort.dir;
    }
    ctx.replaceQuery(query);
  }

  function progressBox(label) {
    const text = h("span", null, label);
    const bar = h("progress", { max: 1, value: 0, "aria-label": "Progresso do carregamento" });
    const box = h("div", { class: "state state-loading", role: "status" }, h("span", { class: "spinner", "aria-hidden": "true" }), text, bar);
    return {
      box,
      update({ done, total, label: next }) {
        bar.max = total;
        bar.value = done;
        text.textContent = next || "A carregar " + fmtInt(done) + " de " + fmtInt(total) + "...";
      },
    };
  }

  function clearExtra() {
    if (extraHandle && extraHandle.destroy) extraHandle.destroy();
    extraHandle = null;
    clear(extraHost);
  }

  function renderExtra(rows) {
    clearExtra();
    if (!dataset.extra) return;
    const made = dataset.extra(data, rows, state, ctx, init);
    if (!made) return;
    extraHandle = made instanceof Node ? { el: made } : made;
    extraHost.append(extraHandle.el);
  }

  function apply() {
    if (data === null) return;
    const rows = dataset.rows(data, state, init);
    if (!table) {
      table = createTable({
        caption: dataset.caption || dataset.title,
        columns: dataset.columns(data, state, init),
        sort,
        emptyText: dataset.emptyText,
        rowClass: dataset.rowClass ? (row) => dataset.rowClass(row, data) : null,
        onSort: (next) => {
          sort = next;
          syncUrl();
        },
      });
      clear(tableHost);
      tableHost.append(table.el);
    }
    table.update(rows, sort);
    status.textContent = dataset.summary
      ? dataset.summary(data, rows, state)
      : fmtInt(rows.length) + (rows.length === 1 ? " resultado." : " resultados.");
    renderExtra(rows);
    syncUrl();
  }

  function reset() {
    data = null;
    loadedKey = null;
    table = null;
    status.textContent = "";
    clearExtra();
  }

  async function ensureData() {
    const key = dataset.loadKey ? dataset.loadKey(state, init) : "estatico";
    if (data !== null && key === loadedKey) return true;
    token += 1;
    const mine = token;
    reset();
    showNotice("");
    clear(tableHost);
    const progress = progressBox("A carregar...");
    tableHost.append(progress.box);
    try {
      const loaded = await dataset.load(state, ctx, init, progress.update);
      if (signal.aborted || mine !== token) return false;
      data = loaded;
      loadedKey = key;
      clear(tableHost);
      return true;
    } catch (error) {
      if (signal.aborted || isAbort(error) || mine !== token) return false;
      clear(tableHost);
      if (error instanceof InputError) {
        showNotice(error.message, "alert");
      } else {
        tableHost.append(errorBox(error, () => run()));
      }
      return false;
    }
  }

  async function run() {
    readState();
    if (await ensureData()) apply();
  }

  fields.forEach((field) => {
    const typed = field.def.type === "text" || field.def.type === "number";
    if (field.def.reload) {
      field.input.addEventListener("change", () => showNotice("Carrega em «Pesquisar» para aplicar o novo intervalo."));
      return;
    }
    field.input.addEventListener(typed ? "input" : "change", () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        readState();
        apply();
      }, typed ? DEBOUNCE_MS : 0);
    });
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(timer);
    run();
  });

  clearButton.addEventListener("click", () => {
    clearTimeout(timer);
    fields.forEach((field) => field.write(defaults[field.def.name]));
    sort = { ...dataset.defaultSort };
    table = null;
    run();
  });

  await run();
}

// Corre `task` sobre os itens com no máximo `limit` pedidos em paralelo e relata o progresso.
export async function mapLimit(items, limit, task, progress) {
  const results = new Array(items.length);
  let next = 0;
  let done = 0;
  async function worker() {
    while (next < items.length) {
      const index = next;
      next += 1;
      results[index] = await task(items[index], index);
      done += 1;
      if (progress) progress({ done, total: items.length });
    }
  }
  if (progress) progress({ done: 0, total: items.length });
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}
