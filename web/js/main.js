// Arranque do site: rotas, estado do arquivo no cabeçalho, foco e anúncios entre páginas.
import { loadLatest } from "./api.js";
import { SITE_TITLE } from "./config.js";
import { clear, h } from "./dom.js";
import { fmtDate } from "./format.js";
import { startRouter } from "./router.js";
import { errorBox } from "./ui/states.js";

const main = document.getElementById("conteudo");
const live = document.getElementById("anuncios");
const status = document.getElementById("estado-arquivo");
let firstPage = true;

const routes = [
  { nav: "inicio", match: (s) => (s.length === 0 ? {} : null), load: () => import("./pages/home.js") },
  { nav: "dia", match: (s) => (s[0] === "dia" && s.length <= 2 ? { date: s[1] || null } : null), load: () => import("./pages/day.js") },
  { nav: "instrumentos", match: (s) => (s[0] === "instrumentos" && s.length === 1 ? {} : null), load: () => import("./pages/instruments.js") },
  { nav: "instrumentos", match: (s) => (s[0] === "instrumento" && s.length === 2 ? { slug: s[1] } : null), load: () => import("./pages/instrument.js") },
  { nav: "pesquisa", match: (s) => (s[0] === "pesquisa" && s.length <= 2 ? { dataset: s[1] || "dias" } : null), load: () => import("./pages/search.js") },
  { nav: "estado", match: (s) => (s[0] === "estado" && s.length === 1 ? {} : null), load: () => import("./pages/status.js") },
];

function announce(text) {
  live.textContent = "";
  window.setTimeout(() => {
    live.textContent = text;
  }, 60);
}

async function showArchiveStatus() {
  try {
    const latest = await loadLatest(new AbortController().signal);
    status.textContent = "Último dia arquivado: " + fmtDate(latest.date);
  } catch {
    status.textContent = "Estado do arquivo indisponível";
  }
}

document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  main.focus();
});

startRouter(routes, {
  before(ctx, route) {
    ctx.main = main;
    ctx.setTitle = (title) => {
      document.title = title + " | " + SITE_TITLE;
    };
    ctx.announce = announce;
    clear(main);
    for (const item of document.querySelectorAll(".site-nav a")) {
      if (route && item.dataset.nav === route.nav) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    if (!firstPage) window.scrollTo(0, 0);
  },
  rendered() {
    const heading = main.querySelector("h1");
    if (!firstPage && heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
      announce(document.title);
    }
    firstPage = false;
  },
  failed(ctx, error) {
    clear(main);
    main.append(h("h1", null, "Não foi possível abrir esta página"), errorBox(error, ctx.retry));
    document.title = "Erro | " + SITE_TITLE;
  },
  loadNotFound: () => import("./pages/notfound.js"),
});

showArchiveStatus();
