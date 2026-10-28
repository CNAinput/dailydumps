// Peças partilhadas pelas páginas: ligações, etiquetas, variações, resumo do fecho e descarga de ticks.
import { DataError, describeError, githubUrl, pricesPath, rawUrl } from "../api.js";
import { TICKS_BASE } from "../config.js";
import { externalLink, h } from "../dom.js";
import {
  ARROWS, DIRECTION_WORDS, NA, direction, fmtCoins, fmtDate, fmtInstant, fmtInt, fmtPct,
} from "../format.js";
import { isLowDay, lookup } from "../model.js";
import { toHash } from "../router.js";

export const CAP_NOTE =
  "A capitalização é o preço vezes as shares em circulação (as detidas), nunca as autorizadas. " +
  "Nos índices é o valor das unidades detidas por investidores e não entra nos totais do mercado.";

export function dayHref(date) {
  return toHash(["dia", date]);
}

export function instrumentHref(slug) {
  return toHash(["instrumento", slug]);
}

export function ticksHref(date, slug) {
  return toHash(["pesquisa", "ticks"], { de: date, ate: date, i: slug || "" });
}

export function dayLink(date) {
  return h("a", { href: dayHref(date) }, fmtDate(date));
}

export function instrumentLink(instrument) {
  const content = [h("strong", { class: "code" }, instrument.code)];
  if (instrument.name) content.push(" ", h("span", { class: "instrument-name" }, instrument.name));
  const label = h("span", { class: "instrument" }, content);
  return instrument.slug ? h("a", { href: instrumentHref(instrument.slug) }, label) : label;
}

export function typeChip(instrument) {
  return h("span", { class: ["chip", "chip-" + instrument.type] }, instrument.label);
}

export function chip(text, kind, title) {
  return h("span", { class: ["chip", "chip-" + kind], title }, text);
}

// Variação com sinal, seta e palavra para leitores de ecrã: nunca só a cor.
export function delta(change) {
  const way = direction(change);
  if (way === "none") return h("span", { class: "delta delta-none" }, NA);
  return h(
    "span",
    { class: "delta delta-" + way },
    h("span", { class: "delta-arrow", "aria-hidden": "true" }, ARROWS[way]),
    " ",
    fmtPct(change),
    h("span", { class: "sr-only" }, " (" + DIRECTION_WORDS[way] + ")"),
  );
}

export function kvList(pairs) {
  return h("dl", { class: "kv" }, pairs.map(([term, value]) => [h("dt", null, term), h("dd", null, value)]));
}

export function dayChips(day, baseline) {
  const chips = [
    day.source === "daily"
      ? chip("Arquivado no fecho", "ok", "Gerado logo a seguir ao fecho, com snapshot da capitalização.")
      : chip("Arquivado depois do fecho", "info", "Gerado depois de o mercado reabrir: não tem snapshot nem capitalização."),
  ];
  if (day.partial) chips.push(chip("Parcial", "warn", "A retenção do bot pode ter apagado os primeiros ticks deste dia."));
  if (isLowDay(day, baseline)) chips.push(chip("Poucos ticks", "warn", "Tem menos ticks do que o habitual."));
  if (day.regenerations.length > 0) chips.push(chip("Regenerado", "info", "O ficheiro deste dia foi substituído por um pedido explícito."));
  return chips;
}

// Explicações dos avisos de um dia, para quem não vê o texto das etiquetas.
export function dayNotes(day, baseline) {
  const notes = [];
  if (isLowDay(day, baseline)) {
    notes.push(
      h(
        "p",
        { class: "note note-warn" },
        "Este dia tem menos ticks do que o habitual (" + fmtInt(day.rows) + " contra uma mediana de " +
          fmtInt(baseline.median) + "). Pode haver um período sem dados: os ficheiros refletem o que a base de dados tinha.",
      ),
    );
  }
  if (day.partial) {
    notes.push(h("p", { class: "note note-warn" }, "Dia parcial: a retenção de 40 dias do bot pode ter apagado os primeiros ticks."));
  }
  if (day.source !== "daily") {
    notes.push(
      h(
        "p",
        { class: "note" },
        "Dia arquivado depois do fecho (backfill): não tem snapshot e a capitalização não está disponível, " +
          "porque a história das shares detidas não se reconstitui.",
      ),
    );
  }
  for (const entry of day.regenerations) {
    notes.push(
      h(
        "p",
        { class: "note" },
        "Regenerado em " + fmtInstant(entry.at, true) + ". Antes tinha " + fmtInt(entry.previous_rows) + " ticks.",
      ),
    );
  }
  return notes;
}

function indexCard(entry, catalog) {
  const instrument = lookup(catalog, entry.code, "asset");
  return h(
    "li",
    { class: "card" },
    h("h3", { class: "card-title" }, instrumentLink({ ...instrument, name: entry.name || instrument.name })),
    h("p", { class: "card-value" }, fmtCoins(entry.close)),
    h("p", { class: "card-meta" }, delta(entry.change_pct), " ", h("span", { class: "muted" }, "abertura " + fmtCoins(entry.open))),
  );
}

function moverCard(title, entry, catalog) {
  if (!entry) return null;
  const instrument = lookup(catalog, entry.code, entry.asset_type);
  return h(
    "li",
    { class: "card" },
    h("h3", { class: "card-title" }, title),
    h("p", { class: "card-name" }, instrumentLink({ ...instrument, name: entry.name || instrument.name })),
    h("p", { class: "card-value" }, fmtCoins(entry.close)),
    h("p", { class: "card-meta" }, delta(entry.change_pct), " ", h("span", { class: "muted" }, "abertura " + fmtCoins(entry.open))),
  );
}

// Resumo do fecho de um dia (o mesmo conteúdo do «Fecho do Mercado» do Discord).
export function summaryBlock(summary, catalog) {
  const cards = [];
  for (const entry of summary.indices || []) cards.push(indexCard(entry, catalog));
  cards.push(moverCard("Maior subida", summary.biggest_riser, catalog));
  cards.push(moverCard("Maior descida", summary.biggest_faller, catalog));
  const block = h("div", { class: "summary" }, h("ul", { class: "cards" }, cards));
  if (summary.calm_day) {
    block.append(h("p", { class: "note" }, "Dia calmo: nenhum instrumento subiu nem desceu mais de 0,05 %."));
  }
  if (summary.top_market_cap) {
    block.append(
      h("h3", { class: "block-title" }, "Maiores empresas por capitalização"),
      h(
        "ol",
        { class: "rank" },
        summary.top_market_cap.map((entry) =>
          h("li", null, instrumentLink({ ...lookup(catalog, entry.code, "company"), name: entry.name }), " ", h("span", { class: "muted" }, fmtCoins(entry.market_cap))),
        ),
      ),
      h(
        "p",
        { class: "muted" },
        "Capitalização total do mercado: " + fmtCoins(summary.total_market_cap) + ", em " + fmtInt(summary.companies_count) + " empresas.",
      ),
    );
  } else {
    block.append(
      h(
        "p",
        { class: "note" },
        "Capitalização indisponível: este dia foi arquivado depois do fecho e não tem snapshot das shares detidas.",
      ),
    );
  }
  return block;
}

// Descarga dos ticks de um dia: vai buscar o ficheiro ao GitHub e grava-o com o nome certo.
export function ticksPanel(date, ticks) {
  const path = pricesPath(date);
  const status = h("p", { class: "download-status", role: "status" });
  const button = h("button", { type: "button", class: "button" }, "Descarregar ticks (CSV)");
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "A descarregar...";
    try {
      const response = await fetch(TICKS_BASE + path, { cache: "no-cache" });
      if (!response.ok) throw new DataError(path, "http", response.status);
      const url = URL.createObjectURL(await response.blob());
      const anchor = h("a", { href: url, download: date + ".csv" });
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      status.textContent = "Descarga iniciada: " + date + ".csv";
    } catch (error) {
      const failure = error instanceof DataError ? error : new DataError(path, "network", "");
      status.textContent = describeError(failure) + " ";
      status.append(externalLink(rawUrl(path), "Abrir o ficheiro no GitHub"));
    } finally {
      button.disabled = false;
    }
  });
  return h(
    "div",
    { class: "ticks-panel" },
    h("p", null, "Este dia tem " + fmtInt(ticks) + " ticks de preço, com o instante em UTC como na base de dados."),
    h(
      "div",
      { class: "actions" },
      h("a", { class: "button", href: ticksHref(date) }, "Explorar os ticks no site"),
      button,
      externalLink(githubUrl(path), "Ver no GitHub"),
    ),
    status,
  );
}
