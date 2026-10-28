// Gráfico de linha em SVG, feito à mão: eixos, eventos marcados com letra, cursor por rato, toque e teclado.
import { clear, h, s, uniqueId } from "../dom.js";
import {
  DAY_MS, addDays, fmtClock, fmtNumber, fmtShortDate, lisbonDate, lisbonMidnightMs, lisbonOffsetMs,
} from "../format.js";
import { EVENT_LABELS, EVENT_LETTERS } from "../model.js";

const MARGIN = { top: 22, right: 16, bottom: 34, left: 58 };
const MIN_WIDTH = 260;
const MINUTE_MS = 60000;
const HOUR_MS = 3600000;
const SHORT_STEPS = [30 * MINUTE_MS, HOUR_MS, 2 * HOUR_MS, 3 * HOUR_MS, 6 * HOUR_MS, 12 * HOUR_MS];
const DAY_STEPS = [1, 2, 3, 7, 14, 30, 61, 91, 182, 365, 730];

// Valores "redondos" para o eixo vertical, no máximo perto de `target`.
export function niceTicks(min, max, target = 5) {
  const span = max - min;
  if (!(span > 0)) return [min];
  const rough = span / Math.max(1, target);
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const residual = rough / magnitude;
  const step = (residual > 5 ? 10 : residual > 2 ? 5 : residual > 1 ? 2 : 1) * magnitude;
  const ticks = [];
  for (let value = Math.ceil(min / step) * step; value <= max + step * 1e-9; value += step) {
    ticks.push(Number(value.toFixed(10)));
  }
  return ticks;
}

export function tickDecimals(ticks) {
  if (ticks.length < 2) return 2;
  const step = Math.abs(ticks[1] - ticks[0]);
  return Math.min(4, Math.max(0, Math.ceil(-Math.log10(step) - 1e-9)));
}

function lisbonShort(ms) {
  const date = lisbonDate(ms);
  return date.slice(8, 10) + "/" + date.slice(5, 7);
}

// Marcas do eixo horizontal. `kind` "day": x são dias civis (meia-noite UTC). `kind` "time": instantes.
export function timeTicks(min, max, kind, maxCount) {
  const span = max - min;
  const ticks = [];
  const dayStep = DAY_STEPS.find((days) => span / (days * DAY_MS) <= maxCount) || DAY_STEPS[DAY_STEPS.length - 1];
  if (kind === "day") {
    for (let ms = min; ms <= max + 1; ms += dayStep * DAY_MS) ticks.push(ms);
    return { ticks, labels: ticks.map((ms) => fmtShortDate(ms, span > 300 * DAY_MS)) };
  }
  const shortStep = SHORT_STEPS.find((step) => span / step <= maxCount);
  if (shortStep) {
    const offset = lisbonOffsetMs(min);
    for (let ms = Math.ceil((min + offset) / shortStep) * shortStep - offset; ms <= max; ms += shortStep) ticks.push(ms);
    const withDate = span > 36 * HOUR_MS;
    return { ticks, labels: ticks.map((ms) => (withDate ? lisbonShort(ms) + " " : "") + fmtClock(ms)) };
  }
  for (let date = lisbonDate(min); ; date = addDays(date, dayStep)) {
    const ms = lisbonMidnightMs(date);
    if (ms > max) break;
    if (ms >= min) ticks.push(ms);
  }
  return { ticks, labels: ticks.map((ms) => lisbonShort(ms)) };
}

// points: [{ x, y }] por ordem de x. markers: [{ x, kind, title }]. describePoint(ponto, índice) -> texto.
export function createLineChart({ points, kind, markers = [], height = 300, ariaLabel, describePoint, emptyText }) {
  const figure = h("figure", { class: "chart" });
  const count = points.length;
  if (count === 0) {
    figure.append(h("p", { class: "state state-empty" }, emptyText || "Sem pontos para desenhar."));
    return { el: figure, destroy() {} };
  }

  let xmin = points[0].x;
  let xmax = points[count - 1].x;
  if (xmin === xmax) {
    const pad = kind === "day" ? DAY_MS : HOUR_MS;
    xmin -= pad;
    xmax += pad;
  }
  let ymin = Infinity;
  let ymax = -Infinity;
  for (const point of points) {
    if (point.y < ymin) ymin = point.y;
    if (point.y > ymax) ymax = point.y;
  }
  const positive = ymin > 0;
  const pad = ymin === ymax ? Math.abs(ymin) * 0.05 || 1 : (ymax - ymin) * 0.08;
  ymin -= pad;
  ymax += pad;
  if (positive && ymin < 0) ymin = 0;

  const box = h("div", { class: "chart-box" });
  const svg = s("svg", { class: "chart-svg", role: "img", "aria-label": ariaLabel, focusable: "false" });
  box.append(svg);
  const readout = h("p", { class: "chart-readout" });
  const sliderId = uniqueId("grafico");
  const slider = h("input", {
    id: sliderId, type: "range", class: "chart-slider", min: 0, max: count - 1, step: 1, value: count - 1, disabled: count < 2,
  });
  figure.append(box, readout, h("div", { class: "chart-slider-row" }, h("label", { for: sliderId }, "Percorrer os pontos do gráfico"), slider));

  const visible = markers.filter((marker) => marker.x >= xmin && marker.x <= xmax);
  const used = [...new Set(visible.map((marker) => marker.kind))];
  if (used.length > 0) {
    figure.append(
      h(
        "ul",
        { class: "chart-legend", "aria-label": "Legenda dos eventos" },
        used.map((item) => h("li", null, h("span", { class: "legend-letter", "aria-hidden": "true" }, EVENT_LETTERS[item] || "?"), " ", EVENT_LABELS[item] || item)),
      ),
    );
  }

  let current = count - 1;
  let lastWidth = 0;
  let scaleX = (x) => x;
  let scaleY = (y) => y;
  let cursorLine = null;
  let cursorDot = null;

  function nearest(x) {
    let low = 0;
    let high = count - 1;
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (points[middle].x <= x) low = middle;
      else high = middle;
    }
    return Math.abs(points[low].x - x) <= Math.abs(points[high].x - x) ? low : high;
  }

  function moveCursor(index) {
    current = index;
    const point = points[index];
    const text = describePoint ? describePoint(point, index) : String(point.y);
    readout.textContent = text;
    slider.value = String(index);
    slider.setAttribute("aria-valuetext", text);
    if (cursorLine && cursorDot) {
      const x = scaleX(point.x);
      cursorLine.setAttribute("x1", x);
      cursorLine.setAttribute("x2", x);
      cursorDot.setAttribute("cx", x);
      cursorDot.setAttribute("cy", scaleY(point.y));
    }
  }

  function draw() {
    const width = Math.max(Math.round(box.clientWidth), MIN_WIDTH);
    lastWidth = width;
    const innerW = width - MARGIN.left - MARGIN.right;
    const innerH = height - MARGIN.top - MARGIN.bottom;
    const bottom = MARGIN.top + innerH;
    scaleX = (x) => MARGIN.left + ((x - xmin) / (xmax - xmin)) * innerW;
    scaleY = (y) => MARGIN.top + (1 - (y - ymin) / (ymax - ymin)) * innerH;
    clear(svg);
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);

    const yTicks = niceTicks(ymin, ymax, Math.max(3, Math.floor(innerH / 42)));
    const decimals = tickDecimals(yTicks);
    const grid = s("g", { class: "chart-grid" });
    for (const value of yTicks) {
      const y = scaleY(value);
      grid.append(
        s("line", { x1: MARGIN.left, x2: width - MARGIN.right, y1: y, y2: y }),
        s("text", { x: MARGIN.left - 8, y: y + 4, "text-anchor": "end", class: "chart-tick" }, fmtNumber(value, decimals)),
      );
    }
    const axis = s("g", { class: "chart-axis" }, s("line", { x1: MARGIN.left, x2: width - MARGIN.right, y1: bottom, y2: bottom }));
    const { ticks, labels } = timeTicks(xmin, xmax, kind, Math.max(2, Math.floor(innerW / 90)));
    ticks.forEach((tick, index) => {
      const x = scaleX(tick);
      const anchor = x < MARGIN.left + 24 ? "start" : x > width - MARGIN.right - 24 ? "end" : "middle";
      axis.append(
        s("line", { x1: x, x2: x, y1: bottom, y2: bottom + 5 }),
        s("text", { x, y: bottom + 20, "text-anchor": anchor, class: "chart-tick" }, labels[index]),
      );
    });
    svg.append(grid, axis);

    const groups = new Map();
    for (const marker of visible) {
      if (!groups.has(marker.x)) groups.set(marker.x, []);
      groups.get(marker.x).push(marker);
    }
    for (const [x, items] of groups) {
      const px = scaleX(x);
      const letters = items.map((item) => EVENT_LETTERS[item.kind] || "?").join("");
      const badge = 10 + letters.length * 9;
      svg.append(
        s(
          "g",
          { class: "chart-marker" },
          s("line", { x1: px, x2: px, y1: MARGIN.top, y2: bottom }),
          s("rect", { x: px - badge / 2, y: MARGIN.top - 19, width: badge, height: 17, rx: 3 }),
          s("text", { x: px, y: MARGIN.top - 6, "text-anchor": "middle" }, letters),
          s("title", null, items.map((item) => item.title).join("; ")),
        ),
      );
    }

    let line = "";
    for (let i = 0; i < count; i += 1) {
      line += (i === 0 ? "M" : "L") + scaleX(points[i].x).toFixed(1) + " " + scaleY(points[i].y).toFixed(1);
    }
    const first = scaleX(points[0].x).toFixed(1);
    const last = scaleX(points[count - 1].x).toFixed(1);
    svg.append(
      s("path", { class: "chart-area", d: line + "L" + last + " " + bottom + "L" + first + " " + bottom + "Z" }),
      s("path", { class: "chart-line", d: line }),
    );
    if (count <= 90) {
      const dots = s("g", { class: "chart-dots" });
      for (const point of points) dots.append(s("circle", { cx: scaleX(point.x), cy: scaleY(point.y), r: 2.5 }));
      svg.append(dots);
    }

    cursorLine = s("line", { class: "chart-cursor-line", y1: MARGIN.top, y2: bottom });
    cursorDot = s("circle", { class: "chart-cursor-dot", r: 5 });
    const overlay = s("rect", { class: "chart-overlay", x: MARGIN.left, y: MARGIN.top, width: innerW, height: innerH });
    const onPointer = (event) => {
      const rect = svg.getBoundingClientRect();
      const x = ((event.clientX - rect.left) / rect.width) * width;
      moveCursor(nearest(xmin + ((x - MARGIN.left) / innerW) * (xmax - xmin)));
    };
    overlay.addEventListener("pointermove", onPointer);
    overlay.addEventListener("pointerdown", onPointer);
    svg.append(cursorLine, cursorDot, overlay);
    moveCursor(current);
  }

  slider.addEventListener("input", () => moveCursor(Number(slider.value)));

  // Redesenha quando a largura real difere da usada (ao inserir na página e ao redimensionar).
  function syncWidth() {
    if (box.isConnected && box.clientWidth > 0 && Math.abs(box.clientWidth - lastWidth) >= 1) draw();
  }

  let frame = 0;
  const observer = new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(syncWidth);
  });
  observer.observe(box);
  draw();
  queueMicrotask(syncWidth);

  return {
    el: figure,
    destroy() {
      observer.disconnect();
      cancelAnimationFrame(frame);
    },
  };
}
