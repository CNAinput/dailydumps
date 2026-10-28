// Pesquisa nos dados: um separador por conjunto de dados, todos com o mesmo explorador.
import { h } from "../dom.js";
import { TABS, findTab } from "../datasets/index.js";
import { toHash } from "../router.js";
import { mountExplorer } from "../ui/explorer.js";

function tabs(current) {
  return h(
    "nav",
    { "aria-label": "Conjuntos de dados" },
    h(
      "ul",
      { class: "tabs" },
      TABS.map((tab) =>
        h("li", null, h("a", { href: toHash(["pesquisa", tab.id]), "aria-current": tab.id === current ? "page" : null }, tab.label)),
      ),
    ),
  );
}

export async function render(ctx) {
  const tab = findTab(ctx.params.dataset);
  ctx.setTitle(tab ? "Pesquisa: " + tab.label : "Pesquisa");
  ctx.main.append(h("h1", null, "Pesquisa nos dados"), tabs(tab ? tab.id : null));
  if (!tab) {
    ctx.main.append(
      h("p", { class: "note note-warn", role: "alert" }, "Não existe o conjunto de dados «" + ctx.params.dataset + "». Escolhe um dos separadores."),
    );
    return;
  }
  const host = h("div");
  ctx.main.append(h("h2", null, tab.label), h("p", { class: "muted" }, tab.description), host);
  const module = await tab.load();
  if (ctx.signal.aborted) return;
  await mountExplorer(host, ctx, module.dataset);
}
