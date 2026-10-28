// Um dia: resumo do fecho, instrumentos, eventos, capitalização no fecho e ticks.
import { githubUrl, loadEvents, loadSnapshot, loadSummary, pricesPath } from "../api.js";
import { loadCore } from "../core.js";
import { externalLink, h, uniqueId } from "../dom.js";
import {
  addDays, fmtCoins, fmtDate, fmtInstant, fmtInt, fmtLongDate, fmtMonth, fmtNumber, fmtWeekday, isDate, lisbonMidnightMs,
} from "../format.js";
import { describeEvent, groupByMonth, instrumentFromSnapshot, lookup, neighbours } from "../model.js";
import {
  CAP_NOTE, dayChips, dayHref, dayNotes, instrumentLink, kvList, summaryBlock, ticksPanel, typeChip,
} from "../ui/blocks.js";
import { dayTable } from "../ui/daytable.js";
import { fill } from "../ui/states.js";
import { createTable } from "../ui/table.js";

// Escolha do dia: anterior, seguinte, último e uma lista agrupada por mês.
function picker(core, date) {
  const id = uniqueId("dia");
  const { previous, next } = date ? neighbours(core.dates, date) : { previous: null, next: null };
  const select = h(
    "select",
    { id },
    h("option", { value: "", selected: !date }, "Escolher um dia..."),
    groupByMonth(core.dates).map((group) =>
      h(
        "optgroup",
        { label: fmtMonth(group.month) },
        group.dates.map((item) => h("option", { value: item, selected: item === date }, fmtDate(item) + " (" + fmtWeekday(item) + ")")),
      ),
    ),
  );
  select.addEventListener("change", () => {
    if (select.value) location.hash = dayHref(select.value);
  });
  return h(
    "div",
    { class: "day-picker" },
    previous ? h("a", { class: "button", href: dayHref(previous) }, "← Dia anterior") : null,
    h("label", { for: id }, "Dia"),
    select,
    next ? h("a", { class: "button", href: dayHref(next) }, "Dia seguinte →") : null,
    date !== core.latest.date ? h("a", { class: "button", href: dayHref(core.latest.date) }, "Último dia") : null,
  );
}

function notArchived(core, reason) {
  const first = core.dates[0];
  const last = core.dates[core.dates.length - 1];
  return [
    h("p", { class: "note note-warn", role: "alert" }, reason + " O arquivo vai de " + fmtDate(first) + " a " + fmtDate(last) + "."),
    picker(core, null),
  ];
}

function summarySection(core, ctx, date) {
  const host = h("div");
  fill(host, {
    signal: ctx.signal,
    load: () => (date === core.latest.date ? Promise.resolve(core.latest.summary) : loadSummary(date, ctx.signal)),
    render: (summary) => summaryBlock(summary, core.catalog),
    loading: "A carregar o resumo...",
  });
  return [h("h2", null, "Resumo do fecho"), host];
}

function eventsSection(core, ctx, date) {
  const host = h("div");
  fill(host, {
    signal: ctx.signal,
    load: () => loadEvents(ctx.signal),
    loading: "A carregar os eventos...",
    render: (events) => {
      const today = events.filter((event) => event.date === date);
      if (today.length === 0) return null;
      return [
        h("h2", null, "Eventos neste dia"),
        h(
          "ul",
          null,
          today.map((event) =>
            h(
              "li",
              null,
              instrumentLink(lookup(core.catalog, event.code, event.type)),
              ": " + describeEvent(event),
              event.documentId === null ? "" : " (despacho n.º " + event.documentId + ")",
              event.notes ? ". " + event.notes : "",
            ),
          ),
        ),
      ];
    },
  });
  return host;
}

function snapshotSection(core, ctx, date, day) {
  if (day.source !== "daily") return null;
  const host = h("div");
  fill(host, {
    signal: ctx.signal,
    load: () => loadSnapshot(date, ctx.signal),
    loading: "A carregar a capitalização...",
    render: (snapshot) => {
      const rows = snapshot.instruments.map((entry) => ({
        instrument: instrumentFromSnapshot(entry, core.catalog),
        price: entry.price,
        total: entry.shares_total,
        circulating: entry.shares_in_circulation,
        cap: entry.market_cap,
      }));
      const table = createTable({
        caption: "Capitalização no fecho de " + fmtDate(date),
        sort: { key: "capitalizacao", dir: "desc" },
        columns: [
          {
            key: "instrumento", label: "Instrumento", header: true,
            value: (row) => row.instrument.code, render: (row) => instrumentLink(row.instrument),
          },
          { key: "tipo", label: "Tipo", value: (row) => row.instrument.label, render: (row) => typeChip(row.instrument) },
          { key: "preco", label: "Preço", num: true, value: (row) => row.price, render: (row) => fmtCoins(row.price) },
          { key: "autorizadas", label: "Shares autorizadas", num: true, value: (row) => row.total, render: (row) => fmtInt(row.total) },
          { key: "circulacao", label: "Em circulação", num: true, value: (row) => row.circulating, render: (row) => fmtInt(row.circulating) },
          { key: "capitalizacao", label: "Capitalização", num: true, value: (row) => row.cap, render: (row) => fmtCoins(row.cap) },
        ],
      });
      table.update(rows);
      return [
        h("p", { class: "muted" }, CAP_NOTE),
        table.el,
      ];
    },
  });
  return [h("h2", null, "Capitalização no fecho"), host];
}

function hoursOf(date) {
  return (lisbonMidnightMs(addDays(date, 1)) - lisbonMidnightMs(date)) / 3600000;
}

function view(core, ctx, heading) {
  const requested = ctx.params.date;
  const date = requested || core.latest.date;
  if (!isDate(date)) return notArchived(core, "O endereço não tem uma data válida (AAAA-MM-DD).");
  const day = core.dayMap.get(date);
  if (!day) return notArchived(core, "O dia " + fmtDate(date) + " não está no arquivo.");
  if (!requested) ctx.replaceHash(["dia", date]);
  heading.textContent = "Dia " + fmtDate(date);
  ctx.setTitle("Dia " + fmtDate(date));

  const rows = core.ohlc.byDate.get(date) || [];
  const path = pricesPath(date);
  const hours = hoursOf(date);
  const facts = [
    ["Data", fmtWeekday(date) + ", " + fmtLongDate(date)],
    ["Ticks no dia", fmtInt(day.rows)],
    ["Instrumentos com ticks", fmtInt(rows.length)],
    ["Ficheiro gerado a", day.generatedAt ? fmtInstant(day.generatedAt, true) + " (hora de Lisboa)" : "n/d"],
  ];
  if (day.sha256) facts.push(["SHA-256 do ficheiro de ticks", h("code", { class: "mono hash" }, day.sha256)]);
  const parts = [
    picker(core, date),
    h("ul", { class: "chips", "aria-label": "Estado do dia" }, dayChips(day, core.baseline).map((item) => h("li", null, item))),
    ...dayNotes(day, core.baseline),
  ];
  if (hours !== 24) {
    parts.push(
      h(
        "p",
        { class: "note" },
        "Este dia teve " + fmtNumber(hours, 0) + " horas por causa da mudança de hora. O mercado abre sempre das 11:00 às 23:00 de Lisboa.",
      ),
    );
  }
  parts.push(kvList(facts), ...summarySection(core, ctx, date));
  parts.push(
    h("h2", null, "Instrumentos"),
    dayTable(rows, core, { full: true, caption: "Instrumentos em " + fmtDate(date) + ": abertura, máximo, mínimo, fecho, variação e ticks" }),
  );
  const snapshot = snapshotSection(core, ctx, date, day);
  if (snapshot) parts.push(...snapshot);
  parts.push(eventsSection(core, ctx, date));
  parts.push(
    h("h2", null, "Ticks e ficheiros"),
    ticksPanel(date, day.rows),
    h(
      "ul",
      null,
      h("li", null, h("a", { href: "summary/" + date + ".json" }, "Resumo do fecho (JSON)")),
      day.source === "daily" ? h("li", null, h("a", { href: "snapshots/" + date + ".json" }, "Snapshot (JSON)")) : null,
      h("li", null, externalLink(githubUrl(path), "Ficheiro de ticks no GitHub")),
    ),
  );
  return parts;
}

export async function render(ctx) {
  const requested = ctx.params.date;
  const title = requested && isDate(requested) ? "Dia " + fmtDate(requested) : "Dia";
  ctx.setTitle(title);
  const heading = h("h1", null, title);
  const host = h("div");
  ctx.main.append(heading, host);
  await fill(host, {
    signal: ctx.signal,
    load: () => loadCore(ctx.signal),
    render: (core) => view(core, ctx, heading),
    loading: "A carregar os dados do dia...",
  });
}
