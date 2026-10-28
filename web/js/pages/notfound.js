// Endereço que não existe.
import { h } from "../dom.js";

export async function render(ctx) {
  ctx.setTitle("Página não encontrada");
  ctx.main.append(
    h("h1", null, "Página não encontrada"),
    h("p", null, "Este endereço não corresponde a nenhuma página do arquivo."),
    h("p", null, h("a", { class: "button", href: "#/" }, "Voltar ao início")),
  );
}
