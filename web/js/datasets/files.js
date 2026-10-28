// Ficheiros do arquivo: caminho, soma de controlo SHA-256 e ligações para os abrir.
import { githubUrl, loadSums } from "../api.js";
import { externalLink, h } from "../dom.js";
import { fmtInt, normalizeText } from "../format.js";
import { ticksHref } from "../ui/blocks.js";

const KINDS = [
  ["ticks", "Ticks"],
  ["resumo", "Resumos"],
  ["snapshot", "Snapshots"],
  ["ohlc", "OHLC"],
  ["geral", "Outros"],
];
const KIND_LABELS = Object.fromEntries(KINDS);
const SERVED_FILES = new Set(["manifest.json", "status.json", "dividends.json", "taxes.json", "events.csv"]);
const SERVED_FOLDERS = ["daily/", "summary/", "snapshots/"];

export function kindOf(path) {
  if (path.startsWith("prices/")) return "ticks";
  if (path.startsWith("summary/")) return "resumo";
  if (path.startsWith("snapshots/")) return "snapshot";
  if (path.startsWith("daily/")) return "ohlc";
  return "geral";
}

function servedBySite(path) {
  return SERVED_FILES.has(path) || SERVED_FOLDERS.some((folder) => path.startsWith(folder));
}

// Os ficheiros do arquivo que o SHA256SUMS não lista: o events.csv é mantido à mão e o próprio SHA256SUMS.
const UNLISTED = ["events.csv", "SHA256SUMS"];

function actions(file) {
  const items = [];
  const date = /^prices\/\d{4}\/(\d{4}-\d{2}-\d{2})\.csv$/.exec(file.path);
  if (date) items.push(h("a", { href: ticksHref(date[1]) }, "Explorar"));
  else if (servedBySite(file.path)) items.push(h("a", { href: file.path }, file.path.endsWith(".csv") ? "Descarregar" : "Abrir"));
  items.push(externalLink(githubUrl(file.path), "GitHub"));
  return h("span", { class: "actions-inline" }, items.flatMap((item, index) => (index === 0 ? [item] : [" ", item])));
}

export const dataset = {
  id: "ficheiros",
  title: "Ficheiros do arquivo",
  caption: "Ficheiros do arquivo com a soma de controlo SHA-256",
  emptyText: "Nenhum ficheiro corresponde a estes filtros.",
  defaultSort: { key: "caminho", dir: "asc" },

  async init(ctx) {
    const sums = await loadSums(ctx.signal);
    const files = sums.map((entry) => ({ path: entry.path, sha256: entry.sha256, kind: kindOf(entry.path) }));
    for (const path of UNLISTED) {
      if (!files.some((file) => file.path === path)) files.push({ path, sha256: null, kind: kindOf(path) });
    }
    return { files };
  },

  fields: () => [
    { name: "q", label: "Caminho ou soma", type: "text", placeholder: "ex.: 2026-10-13", hint: "Procura no caminho e na soma SHA-256." },
    { name: "tipo", label: "Tipo", type: "select", options: [["", "Todos"], ...KINDS] },
  ],

  load: async (state, ctx, init) => init,

  columns: () => [
    {
      key: "caminho", label: "Caminho", header: true, value: (file) => file.path,
      render: (file) => h("code", { class: "mono" }, file.path),
    },
    { key: "tipo", label: "Tipo", value: (file) => KIND_LABELS[file.kind], render: (file) => KIND_LABELS[file.kind] },
    {
      key: "sha256", label: "SHA-256", value: (file) => file.sha256,
      render: (file) => (file.sha256 ? h("code", { class: "mono hash" }, file.sha256) : "n/d (mantido à mão)"),
    },
    { key: "abrir", label: "Ligações", sortable: false, value: (file) => file.path, render: actions },
  ],

  rows(data, state) {
    const query = normalizeText(state.q.trim());
    return data.files.filter((file) => {
      if (query && !(normalizeText(file.path).includes(query) || (file.sha256 || "").includes(query))) return false;
      if (state.tipo && file.kind !== state.tipo) return false;
      return true;
    });
  },

  summary: (data, rows) =>
    fmtInt(rows.length) + " de " + fmtInt(data.files.length) +
    " ficheiros. Para conferir tudo num clone do repositório: sha256sum -c SHA256SUMS.",
};
