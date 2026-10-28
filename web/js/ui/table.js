// Tabela ordenável por coluna, com paginação por "mostrar mais" e alternativa em texto para leitores de ecrã.
import { PAGE_SIZE } from "../config.js";
import { clear, h } from "../dom.js";
import { fmtInt } from "../format.js";

const collator = new Intl.Collator("pt-PT", { numeric: true, sensitivity: "base" });

function missing(value) {
  return value === null || value === undefined || (typeof value === "number" && Number.isNaN(value));
}

// Ordena por `column.value`; o que não tem valor fica sempre no fim.
export function sortRows(rows, column, direction) {
  const sign = direction === "desc" ? -1 : 1;
  return [...rows].sort((left, right) => {
    const a = column.value(left);
    const b = column.value(right);
    if (missing(a) || missing(b)) {
      if (missing(a) && missing(b)) return 0;
      return missing(a) ? 1 : -1;
    }
    const result = typeof a === "number" && typeof b === "number" ? a - b : collator.compare(String(a), String(b));
    return sign * result;
  });
}

// columns: { key, label, num, header, sortable, value(row), render(row), firstDir }
export function createTable({ caption, columns, sort, pageSize = PAGE_SIZE, emptyText = "Sem resultados.", rowClass, onSort }) {
  const state = { rows: [], sorted: [], sort: sort || null, shown: pageSize };
  const root = h("div", { class: "table-block" });
  const wrap = h("div", { class: "table-wrap", role: "region", tabindex: "0", "aria-label": caption });
  const info = h("p", { class: "table-info" });
  const more = h("button", { type: "button", class: "button button-quiet" });
  const empty = h("p", { class: "table-empty" }, emptyText);
  const head = h("tr");
  const body = h("tbody");
  const table = h("table", { class: "data" }, h("caption", { class: "sr-only" }, caption), h("thead", null, head), body);
  wrap.append(table);
  root.append(wrap, info, more, empty);

  function columnOf(key) {
    return columns.find((column) => column.key === key);
  }

  function toggle(column) {
    const same = state.sort && state.sort.key === column.key;
    const first = column.firstDir || (column.num ? "desc" : "asc");
    const direction = same ? (state.sort.dir === "asc" ? "desc" : "asc") : first;
    state.sort = { key: column.key, dir: direction };
    state.shown = pageSize;
    resort();
    renderBody();
    renderHead();
    if (onSort) onSort(state.sort);
  }

  function renderHead() {
    clear(head);
    for (const column of columns) {
      const sortable = column.sortable !== false;
      const active = sortable && state.sort && state.sort.key === column.key;
      const th = h("th", { scope: "col", class: column.num ? "num" : null });
      if (sortable) {
        th.setAttribute("aria-sort", active ? (state.sort.dir === "asc" ? "ascending" : "descending") : "none");
        th.append(
          h(
            "button",
            { type: "button", class: "sort-button", on: { click: () => toggle(column) } },
            column.label,
            h("span", { class: "sort-mark", "aria-hidden": "true" }, active ? (state.sort.dir === "asc" ? "▲" : "▼") : "↕"),
          ),
        );
      } else {
        th.append(column.label);
      }
      head.append(th);
    }
  }

  function resort() {
    const column = state.sort ? columnOf(state.sort.key) : null;
    state.sorted = column ? sortRows(state.rows, column, state.sort.dir) : state.rows;
  }

  function renderRow(row) {
    const tr = h("tr", { class: rowClass ? rowClass(row) : null });
    for (const column of columns) {
      const content = column.render ? column.render(row) : column.value(row);
      tr.append(
        column.header
          ? h("th", { scope: "row", class: column.num ? "num" : null }, content)
          : h("td", { class: column.num ? "num" : null }, content),
      );
    }
    return tr;
  }

  function renderBody() {
    clear(body);
    const total = state.sorted.length;
    const visible = state.sorted.slice(0, state.shown);
    for (const row of visible) body.append(renderRow(row));
    wrap.hidden = total === 0;
    empty.hidden = total !== 0;
    const remaining = total - visible.length;
    info.hidden = total === 0;
    info.textContent = remaining > 0
      ? "A mostrar " + fmtInt(visible.length) + " de " + fmtInt(total) + " linhas."
      : fmtInt(total) + (total === 1 ? " linha." : " linhas.");
    more.hidden = remaining <= 0;
    more.textContent = "Mostrar mais " + fmtInt(Math.min(pageSize, remaining)) + " (restam " + fmtInt(remaining) + ")";
  }

  more.addEventListener("click", () => {
    state.shown += pageSize;
    renderBody();
    if (more.hidden) wrap.focus();
  });

  function update(rows, nextSort) {
    state.rows = rows;
    if (nextSort) state.sort = nextSort;
    state.shown = pageSize;
    resort();
    renderHead();
    renderBody();
  }

  renderHead();
  renderBody();
  return { el: root, update, getSort: () => state.sort };
}
