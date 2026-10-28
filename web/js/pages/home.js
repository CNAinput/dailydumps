// Início: o último dia arquivado e a porta de entrada para os restantes dados.
import { SITE_TITLE } from "../config.js";
import { loadCore } from "../core.js";
import { h } from "../dom.js";
import { fmtDate, fmtInstant, fmtLongDate, fmtWeekday } from "../format.js";
import { TABS } from "../datasets/index.js";
import { toHash } from "../router.js";
import { dayChips, dayHref, dayNotes, summaryBlock } from "../ui/blocks.js";
import { dayTable } from "../ui/daytable.js";
import { fill } from "../ui/states.js";

function content(core) {
  const date = core.latest.date;
  const day = core.dayMap.get(date);
  const rows = core.ohlc.byDate.get(date) || [];
  const parts = [
    h("h2", null, "Último dia arquivado: " + fmtWeekday(date) + ", " + fmtLongDate(date)),
  ];
  if (day) {
    parts.push(h("ul", { class: "chips", "aria-label": "Estado do dia" }, dayChips(day, core.baseline).map((item) => h("li", null, item))));
    parts.push(...dayNotes(day, core.baseline));
    if (day.generatedAt) parts.push(h("p", { class: "muted" }, "Ficheiro gerado a " + fmtInstant(day.generatedAt) + " (hora de Lisboa)."));
  }
  parts.push(
    h("h3", { class: "block-title" }, "Resumo do fecho de " + fmtDate(date)),
    summaryBlock(core.latest.summary, core.catalog),
    h("h2", null, "Instrumentos em " + fmtDate(date)),
    dayTable(rows, core, { full: false, caption: "Instrumentos no último dia: fecho e variação da abertura ao fecho" }),
    h("p", null, h("a", { href: dayHref(date) }, "Ver o dia completo, com abertura, máximo, mínimo e ticks")),
    h("h2", null, "Explorar os dados"),
    h(
      "ul",
      { class: "link-grid" },
      TABS.map((tab) =>
        h("li", null, h("a", { href: toHash(["pesquisa", tab.id]) }, h("strong", null, tab.label), tab.description)),
      ),
    ),
  );
  return parts;
}

export async function render(ctx) {
  ctx.setTitle("Início");
  const host = h("div");
  ctx.main.append(
    h("h1", null, SITE_TITLE),
    h(
      "p",
      { class: "lead" },
      "Arquivo público e permanente dos dados diários do mercado de ações da economia virtual da CNA. " +
        "O bot só guarda 40 dias de histórico de preços; aqui ficam todos, abertos à comunidade.",
    ),
    host,
  );
  await fill(host, { signal: ctx.signal, load: () => loadCore(ctx.signal), render: content, loading: "A carregar o último dia..." });
}
