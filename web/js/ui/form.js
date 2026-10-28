// Campos de filtro com etiqueta, dica e leitura/escrita do valor.
import { h, uniqueId } from "../dom.js";

// def: { name, label, type: text | select | date | number | time, options, hint, min, max, step, placeholder }
export function createField(def) {
  const id = uniqueId("campo");
  const hintId = def.hint ? id + "-dica" : null;
  let input;
  if (def.type === "select") {
    input = h("select", { id, name: def.name }, def.options.map(([value, label]) => h("option", { value }, label)));
  } else {
    input = h("input", {
      id,
      name: def.name,
      type: def.type === "text" ? "search" : def.type,
      placeholder: def.placeholder,
      min: def.min,
      max: def.max,
      step: def.step,
      inputmode: def.type === "number" ? "decimal" : null,
      autocomplete: "off",
      spellcheck: def.type === "text" ? "false" : null,
    });
  }
  if (hintId) input.setAttribute("aria-describedby", hintId);
  const element = h(
    "div",
    { class: "field" },
    h("label", { for: id }, def.label),
    input,
    def.hint ? h("p", { id: hintId, class: "hint" }, def.hint) : null,
  );
  return {
    el: element,
    input,
    def,
    read: () => input.value,
    write: (value) => {
      input.value = value === null || value === undefined ? "" : value;
    },
  };
}
