// Rotas por hash (#/dia/2026-10-27, #/pesquisa/ticks?de=2026-10-13). O Pages não tem rewrites.
import { isAbort } from "./api.js";

function safeDecode(part) {
  try {
    return decodeURIComponent(part);
  } catch {
    return part;
  }
}

export function parseHash(hash) {
  const text = hash.startsWith("#") ? hash.slice(1) : hash;
  const cut = text.indexOf("?");
  const path = cut === -1 ? text : text.slice(0, cut);
  const search = cut === -1 ? "" : text.slice(cut + 1);
  const query = {};
  for (const [key, value] of new URLSearchParams(search)) query[key] = value;
  return {
    segments: path.split("/").filter(Boolean).map(safeDecode),
    query,
    valid: text === "" || text.startsWith("/"),
  };
}

export function toHash(segments, query = {}) {
  const path = "#/" + segments.map(encodeURIComponent).join("/");
  const pairs = Object.entries(query)
    .filter(([, value]) => value !== "" && value !== null && value !== undefined)
    .map(([key, value]) => encodeURIComponent(key) + "=" + encodeURIComponent(value));
  return pairs.length > 0 ? path + "?" + pairs.join("&") : path;
}

// `routes`: lista de { nav, match(segments) -> params | null, load() -> módulo com render(ctx) }.
export function startRouter(routes, hooks) {
  let controller = null;
  let cleanups = [];

  async function navigate() {
    if (controller) controller.abort();
    for (const cleanup of cleanups.splice(0)) {
      try {
        cleanup();
      } catch (error) {
        console.error(error);
      }
    }
    controller = new AbortController();
    const { signal } = controller;
    const { segments, query, valid } = parseHash(location.hash);
    let route = null;
    let params = {};
    if (valid) {
      for (const candidate of routes) {
        const found = candidate.match(segments);
        if (found) {
          route = candidate;
          params = found;
          break;
        }
      }
    }
    const ctx = {
      signal,
      segments,
      query,
      params,
      retry: navigate,
      onCleanup: (fn) => cleanups.push(fn),
      replaceQuery: (next) => history.replaceState(null, "", toHash(segments, next)),
      replaceHash: (nextSegments, next = {}) => history.replaceState(null, "", toHash(nextSegments, next)),
    };
    hooks.before(ctx, route);
    try {
      const module = await (route ? route.load() : hooks.loadNotFound());
      if (signal.aborted) return;
      const pending = module.render(ctx);
      hooks.rendered(ctx);
      await pending;
    } catch (error) {
      if (signal.aborted || isAbort(error)) return;
      hooks.failed(ctx, error);
    }
  }

  window.addEventListener("hashchange", navigate);
  navigate();
}
