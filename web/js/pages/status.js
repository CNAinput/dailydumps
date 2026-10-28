// Estado do arquivo: dia mais recente, atualização, dias em falta e a lista dos dias arquivados.
import { githubUrl, loadStatus } from "../api.js";
import { REPO_URL } from "../config.js";
import { loadCore } from "../core.js";
import { externalLink, h } from "../dom.js";
import { daysBetween, fmtDate, fmtInstant, fmtInt, lastClosedDay } from "../format.js";
import { missingDays } from "../model.js";
import { chip, dayChips, dayLink, kvList } from "../ui/blocks.js";
import { mountExplorer } from "../ui/explorer.js";
import { fill, settle } from "../ui/states.js";

async function loadAll(signal) {
  const [core, status] = await Promise.all([loadCore(signal), settle(loadStatus(signal))]);
  return { core, status: status.value || null };
}

function freshness(lastDate) {
  const gap = daysBetween(lastDate, lastClosedDay());
  if (gap <= 0) return [chip("Em dia", "ok"), " O último dia arquivado é o último fecho."];
  if (gap === 1) {
    return [
      chip("À espera da atualização", "info"),
      " O último fecho ainda não foi arquivado. O arquivo atualiza-se todas as noites, por volta das 23:17 de Lisboa.",
    ];
  }
  return [chip("Em atraso", "warn"), " O último dia arquivado tem " + gap + " dias de atraso face ao último fecho."];
}

function overview({ core, status }) {
  const last = core.latest.date;
  const day = core.dayMap.get(last);
  const missing = missingDays(core.dates);
  const facts = [
    ["Último dia arquivado", dayLink(last)],
    ["Estado do último dia", h("span", { class: "chips-inline" }, dayChips(day, core.baseline).flatMap((item) => [item, " "]))],
    ["Ficheiro gerado a", day.generatedAt ? fmtInstant(day.generatedAt, true) + " (hora de Lisboa)" : "n/d"],
    ["Atualização", h("span", null, freshness(last))],
    ["Dias arquivados", fmtInt(core.dates.length) + ", de " + fmtDate(core.dates[0]) + " a " + fmtDate(last)],
    ["Dias em falta no intervalo", missing.length === 0 ? "Nenhum" : missing.map(fmtDate).join(", ")],
    ["Ticks no último dia", fmtInt(day.rows)],
    ["Instrumentos no último dia", fmtInt((core.ohlc.byDate.get(last) || []).length)],
  ];
  if (status) {
    facts.push(["Última execução", status.ok ? "O último dia arquivado é o último fecho." : "O último dia arquivado não é o último fecho."]);
  }
  return kvList(facts);
}

export async function render(ctx) {
  ctx.setTitle("Estado do arquivo");
  const overviewHost = h("div");
  const explorerHost = h("div");
  ctx.main.append(
    h("h1", null, "Estado do arquivo"),
    h("p", { class: "lead" }, "O que está arquivado, quando foi gerado e o que merece cuidado ao ler os dados."),
    overviewHost,
    h("h2", null, "Como ler os dados"),
    h(
      "ul",
      null,
      h("li", null, "Um dia é o dia civil de Lisboa. Há dias de 23 e de 25 horas, mas o mercado abre sempre das 11:00 às 23:00."),
      h("li", null, "«Arquivado no fecho» tem snapshot, por isso tem capitalização. «Arquivado depois do fecho» (backfill) não tem, porque as shares detidas no passado não se reconstituem."),
      h("li", null, "«Poucos ticks» marca os dias com menos de 80 % da mediana dos ticks diários. Os ficheiros refletem o que a base de dados tinha."),
      h("li", null, "Os ficheiros de dias passados não mudam. Os splits ajustam-se na série ajustada, a partir dos eventos registados."),
      h(
        "li",
        null,
        "Mais pormenores: ",
        externalLink(REPO_URL + "#readme", "README"),
        ", ",
        externalLink(githubUrl("docs/SCHEMA.md"), "esquema dos dados"),
        ", ",
        externalLink(githubUrl("docs/OPERATIONS.md"), "operação"),
        " e a ",
        h("a", { href: "api.html" }, "API estática"),
        ".",
      ),
    ),
    h("h2", null, "Dias arquivados"),
    explorerHost,
  );
  fill(overviewHost, {
    signal: ctx.signal,
    load: () => loadAll(ctx.signal),
    render: overview,
    loading: "A carregar o estado do arquivo...",
  });
  const module = await import("../datasets/archive.js");
  if (ctx.signal.aborted) return;
  await mountExplorer(explorerHost, ctx, module.dataset);
}
