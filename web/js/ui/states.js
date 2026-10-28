// Estados de carregamento, vazio e erro, e o preenchimento assíncrono de uma secção.
import { describeError, isAbort } from "../api.js";
import { clear, fragment, h } from "../dom.js";

export function loadingBox(message = "A carregar...") {
  return h(
    "div",
    { class: "state state-loading", role: "status" },
    h("span", { class: "spinner", "aria-hidden": "true" }),
    h("span", null, message),
  );
}

export function emptyBox(message, extra) {
  return h("div", { class: "state state-empty" }, h("p", null, message), extra);
}

export function errorBox(error, retry) {
  return h(
    "div",
    { class: "state state-error", role: "alert" },
    h("p", { class: "state-title" }, "Não foi possível mostrar estes dados"),
    h("p", null, describeError(error)),
    retry ? h("button", { type: "button", class: "button", on: { click: retry } }, "Tentar de novo") : null,
  );
}

// Resolve sempre: { value } se correu bem, { error } se falhou. Os cancelamentos continuam a propagar-se.
export async function settle(promise) {
  try {
    return { value: await promise };
  } catch (error) {
    if (isAbort(error)) throw error;
    return { error };
  }
}

// Mostra "a carregar", depois o resultado de `render(valor)`, ou o erro com "Tentar de novo".
export async function fill(container, { signal, load, render, loading }) {
  async function run() {
    clear(container);
    container.setAttribute("aria-busy", "true");
    container.append(loadingBox(loading));
    try {
      const value = await load();
      if (signal.aborted) return;
      const content = render(value);
      clear(container);
      container.append(fragment(content));
    } catch (error) {
      if (signal.aborted || isAbort(error)) return;
      clear(container);
      container.append(errorBox(error, run));
    } finally {
      container.removeAttribute("aria-busy");
    }
  }
  await run();
}
