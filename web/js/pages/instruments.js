// Lista de instrumentos.
import { h } from "../dom.js";
import { mountExplorer } from "../ui/explorer.js";

export async function render(ctx) {
  ctx.setTitle("Instrumentos");
  const host = h("div");
  ctx.main.append(
    h("h1", null, "Instrumentos"),
    h("p", { class: "lead" }, "Todos os instrumentos que alguma vez tiveram preços no arquivo: empresas, ativos e índices."),
    host,
  );
  const module = await import("../datasets/instruments.js");
  if (ctx.signal.aborted) return;
  await mountExplorer(host, ctx, module.dataset);
}
