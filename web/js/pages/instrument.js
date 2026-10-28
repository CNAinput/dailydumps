// Um instrumento: série diária com gráfico, eventos, dividendos, capitalização e tabela de dias.
import { DataError, loadDividends, loadInstrument, loadSnapshot } from "../api.js";
import { loadCore } from "../core.js";
import { h, uniqueId } from "../dom.js";
import { dayMs, fmtCoins, fmtDate, fmtInstant, fmtInt, fmtNumber, fmtPct, variation } from "../format.js";
import { describeEvent, eventFromJson, lookup, makeInstrument } from "../model.js";
import { toHash } from "../router.js";
import { CAP_NOTE, dayHref, delta, kvList, ticksHref, typeChip } from "../ui/blocks.js";
import { createLineChart } from "../ui/chart.js";
import { fill, settle } from "../ui/states.js";
import { createTable } from "../ui/table.js";

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

async function loadAll(slug, signal) {
  const [core, instrument] = await Promise.all([loadCore(signal), settle(loadInstrument(slug, signal))]);
  if (instrument.error) {
    const error = instrument.error;
    if (error instanceof DataError && error.kind === "http" && error.detail === 404) return { core, data: null };
    throw error;
  }
  return { core, data: instrument.value };
}

function withChange(rows) {
  return rows.map((row) => ({ ...row, change: variation(row.open, row.close) }));
}

function describeDay(row) {
  return (
    fmtDate(row.date) + ": fecho " + fmtCoins(row.close) + ", variação " + fmtPct(row.change) + " (abertura " +
    fmtCoins(row.open) + ", máximo " + fmtCoins(row.high) + ", mínimo " + fmtCoins(row.low) + ", " + fmtInt(row.ticks) + " ticks)"
  );
}

function eventItem(event) {
  return h(
    "li",
    null,
    h("a", { href: dayHref(event.date) }, fmtDate(event.date)),
    ": " + describeEvent(event),
    event.sharesBefore !== null && event.sharesAfter !== null
      ? " (shares de " + fmtInt(event.sharesBefore) + " para " + fmtInt(event.sharesAfter) + ")"
      : "",
    event.documentId === null ? "" : ". Despacho n.º " + event.documentId,
    event.notes ? ". " + event.notes : "",
  );
}

function dividendSection(ctx, instrument) {
  const host = h("div");
  fill(host, {
    signal: ctx.signal,
    load: () => loadDividends(ctx.signal),
    loading: "A carregar a política de dividendos...",
    render: (dividends) => {
      const policy = dividends.policies.find((item) => item.code === instrument.code && item.asset_type === instrument.assetType);
      if (!policy) return h("p", { class: "muted" }, "Sem política de dividendos registada.");
      return kvList([
        ["Percentagem do saldo da tesouraria", fmtNumber(policy.percentage, 0, 2) + " %"],
        ["Intervalo entre pagamentos", fmtInt(policy.distribution_days) + (policy.distribution_days === 1 ? " dia" : " dias")],
        ["Último pagamento", fmtInstant(policy.last_distribution)],
        ["Próximo pagamento", fmtInstant(policy.next_distribution)],
      ]);
    },
  });
  return [h("h2", null, "Dividendos"), host];
}

function capitalSection(core, ctx, instrument) {
  const lastDaily = [...core.days].reverse().find((day) => day.source === "daily");
  const host = h("div");
  if (!lastDaily) {
    host.append(
      h("p", { class: "muted" }, "Ainda não há dias arquivados com snapshot, por isso não há capitalização para mostrar."),
    );
    return [h("h2", null, "Capitalização"), host];
  }
  fill(host, {
    signal: ctx.signal,
    load: () => loadSnapshot(lastDaily.date, ctx.signal),
    loading: "A carregar a capitalização...",
    render: (snapshot) => {
      const entry = snapshot.instruments.find((item) => item.code === instrument.code && item.asset_type === instrument.assetType);
      if (!entry) return h("p", { class: "muted" }, "Este instrumento não consta do snapshot de " + fmtDate(lastDaily.date) + ".");
      return [
        h("p", { class: "muted" }, "No fecho de " + fmtDate(lastDaily.date) + ". " + CAP_NOTE),
        kvList([
          ["Preço", fmtCoins(entry.price)],
          ["Shares autorizadas", fmtInt(entry.shares_total)],
          ["Shares em circulação", fmtInt(entry.shares_in_circulation)],
          ["Capitalização", fmtCoins(entry.market_cap)],
        ]),
        h("p", null, h("a", { href: toHash(["pesquisa", "capitalizacao"], { q: instrument.code }) }, "Ver a história da capitalização")),
      ];
    },
  });
  return [h("h2", null, "Capitalização"), host];
}

function view({ core, data }, ctx, heading) {
  if (!data) {
    return [
      h("p", { class: "note note-warn", role: "alert" }, "Não existe nenhum instrumento com o identificador «" + ctx.params.slug + "»."),
      h("p", null, h("a", { class: "button", href: "#/instrumentos" }, "Ver todos os instrumentos")),
    ];
  }
  const instrument = makeInstrument(data.code, data.asset_type, data.slug, data.name, core.catalog.indexCodes, data.is_index);
  const title = instrument.name ? instrument.name + " (" + instrument.code + ")" : instrument.code;
  heading.textContent = title;
  ctx.setTitle(title);

  const raw = withChange(data.daily);
  const adjusted = withChange(data.daily_adjusted);
  const differs = adjusted.some((row, index) => !raw[index] || row.close !== raw[index].close || row.open !== raw[index].open);
  const events = data.events.map((event) => eventFromJson(event, data.code, data.asset_type));
  let mode = differs ? "adjusted" : "raw";
  const rowsFor = () => (mode === "adjusted" ? adjusted : raw);

  const last = raw.length > 0 ? raw[raw.length - 1] : null;
  const first = raw.length > 0 ? raw[0] : null;
  const owner = data.owner_company_code ? lookup(core.catalog, data.owner_company_code, "company") : null;
  const facts = [["Tipo", typeChip(instrument)]];
  if (owner) {
    facts.push(["Empresa a que pertence", owner.slug ? h("a", { href: toHash(["instrumento", owner.slug]) }, owner.title) : owner.code]);
  }
  if (last) {
    facts.push(
      ["Último fecho", fmtCoins(last.close) + " em " + fmtDate(last.date)],
      ["Variação no último dia", delta(last.change)],
      ["Período no arquivo", fmtDate(first.date) + " a " + fmtDate(last.date) + " (" + fmtInt(raw.length) + (raw.length === 1 ? " dia)" : " dias)")],
    );
  }

  const chartHost = h("div");
  let chart = null;
  ctx.onCleanup(() => {
    if (chart) chart.destroy();
  });

  const table = createTable({
    caption: "Dias de " + instrument.title + ": abertura, máximo, mínimo, fecho, variação e ticks",
    sort: { key: "data", dir: "desc" },
    columns: [
      { key: "data", label: "Data", header: true, value: (row) => row.date, render: (row) => h("a", { href: dayHref(row.date) }, fmtDate(row.date)) },
      { key: "abertura", label: "Abertura", num: true, value: (row) => row.open, render: (row) => fmtCoins(row.open) },
      { key: "maximo", label: "Máximo", num: true, value: (row) => row.high, render: (row) => fmtCoins(row.high) },
      { key: "minimo", label: "Mínimo", num: true, value: (row) => row.low, render: (row) => fmtCoins(row.low) },
      { key: "fecho", label: "Fecho", num: true, value: (row) => row.close, render: (row) => fmtCoins(row.close) },
      { key: "variacao", label: "Variação", num: true, value: (row) => row.change, render: (row) => delta(row.change) },
      {
        key: "ticks", label: "Ticks", num: true, value: (row) => row.ticks,
        render: (row) => h("a", { href: ticksHref(row.date, instrument.slug) }, fmtInt(row.ticks)),
      },
    ],
  });

  function refresh() {
    const rows = rowsFor();
    if (chart) chart.destroy();
    chartHost.replaceChildren();
    chart = createLineChart({
      points: rows.map((row) => ({ x: dayMs(row.date), y: row.close, row })),
      kind: "day",
      height: 300,
      markers: events.map((event) => ({ x: dayMs(event.date), kind: event.event, title: fmtDate(event.date) + ": " + describeEvent(event) })),
      ariaLabel:
        "Gráfico do fecho diário de " + instrument.title + (rows.length > 0 ? " de " + fmtDate(rows[0].date) + " a " + fmtDate(rows[rows.length - 1].date) : "") +
        ". A tabela mais abaixo tem os mesmos valores.",
      describePoint: (point) => describeDay(point.row),
      emptyText: "Este instrumento não tem dias arquivados.",
    });
    chartHost.append(chart.el);
    table.update(rows);
  }

  const toggleName = uniqueId("serie");
  const option = (value, label) =>
    h(
      "label",
      null,
      h("input", { type: "radio", name: toggleName, value, checked: mode === value, on: { change: () => { mode = value; refresh(); } } }),
      label,
    );
  const series = differs
    ? [
        h("fieldset", { class: "segmented" }, h("legend", null, "Série"), option("adjusted", "Ajustada aos splits"), option("raw", "Bruta, como arquivada")),
        h("p", { class: "muted" }, "A série ajustada divide os preços anteriores a cada split pelo seu factor, para o gráfico não mostrar quedas que não existiram."),
      ]
    : [h("p", { class: "muted" }, "Sem splits que afetem os dias arquivados: a série bruta e a ajustada coincidem.")];

  const outside = events.filter((event) => first && (event.date < first.date || event.date > last.date));
  const parts = [
    kvList(facts),
    h("h2", null, "Fecho diário"),
    ...series,
    chartHost,
  ];
  if (outside.length > 0) {
    parts.push(h("p", { class: "muted" }, outside.length + (outside.length === 1 ? " evento fica" : " eventos ficam") + " fora do período do gráfico e só aparece na lista abaixo."));
  }
  parts.push(
    h("h2", null, "Eventos"),
    events.length > 0 ? h("ul", null, events.map(eventItem)) : h("p", { class: "muted" }, "Sem eventos registados para este instrumento."),
    ...dividendSection(ctx, instrument),
    ...capitalSection(core, ctx, instrument),
    h("h2", null, "Dias"),
    table.el,
  );
  if (last) {
    parts.push(
      h(
        "p",
        { class: "actions" },
        h("a", { class: "button", href: ticksHref(last.date, instrument.slug) }, "Ver os ticks de " + fmtDate(last.date)),
        h("a", { class: "button", href: toHash(["pesquisa", "dias"], { q: instrument.code }) }, "Pesquisar os dias deste instrumento"),
      ),
    );
  }
  refresh();
  return parts;
}

export async function render(ctx) {
  const slug = ctx.params.slug;
  ctx.setTitle("Instrumento");
  const heading = h("h1", null, "Instrumento");
  const host = h("div");
  ctx.main.append(heading, host);
  if (!SLUG.test(slug)) {
    host.append(h("p", { class: "note note-warn", role: "alert" }, "O identificador do instrumento não é válido."));
    return;
  }
  await fill(host, {
    signal: ctx.signal,
    load: () => loadAll(slug, ctx.signal),
    render: (loaded) => view(loaded, ctx, heading),
    loading: "A carregar o instrumento...",
  });
}
