// Criação de elementos sem HTML em texto: os dados do arquivo só entram como texto.
const SVG_NS = "http://www.w3.org/2000/svg";
const PROPERTIES = new Set(["value", "checked", "selected", "disabled", "hidden", "open", "indeterminate"]);

function addChild(parent, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) {
    for (const item of child) addChild(parent, item);
  } else if (child instanceof Node) {
    parent.appendChild(child);
  } else {
    parent.appendChild(document.createTextNode(String(child)));
  }
}

function applyProps(element, props, svg) {
  if (!props) return;
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") {
      element.setAttribute("class", Array.isArray(value) ? value.filter(Boolean).join(" ") : value);
    } else if (key === "text") {
      element.textContent = value;
    } else if (key === "on") {
      for (const [type, handler] of Object.entries(value)) element.addEventListener(type, handler);
    } else if (key === "dataset") {
      Object.assign(element.dataset, value);
    } else if (!svg && PROPERTIES.has(key) && key in element) {
      element[key] = value;
    } else {
      element.setAttribute(key, value === true ? "" : String(value));
    }
  }
}

export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  applyProps(element, props, false);
  addChild(element, children);
  return element;
}

export function s(tag, props, ...children) {
  const element = document.createElementNS(SVG_NS, tag);
  applyProps(element, props, true);
  addChild(element, children);
  return element;
}

export function clear(element) {
  element.replaceChildren();
  return element;
}

export function fragment(...children) {
  const node = document.createDocumentFragment();
  addChild(node, children);
  return node;
}

// Ligação interna (rota por hash) ou externa (abre noutro separador).
export function link(href, label, props) {
  return h("a", { href, ...props }, label);
}

export function externalLink(href, label, props) {
  return h("a", { href, target: "_blank", rel: "noopener noreferrer", ...props }, label, h("span", { class: "sr-only" }, " (abre noutro separador)"));
}

let uid = 0;
export function uniqueId(prefix) {
  uid += 1;
  return prefix + "-" + uid;
}
