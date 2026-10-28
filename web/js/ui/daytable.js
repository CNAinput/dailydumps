// Tabela dos instrumentos de um dia, usada no início e na página de cada dia.
import { h } from "../dom.js";
import { fmtCoins, fmtInt } from "../format.js";
import { isLowRow } from "../model.js";
import { chip, delta, instrumentLink, ticksHref, typeChip } from "./blocks.js";
import { createTable } from "./table.js";

function priceColumn(key, label, field) {
  return { key, label, num: true, value: (row) => row[field], render: (row) => fmtCoins(row[field]) };
}

export function dayColumns(core, full) {
  const columns = [
    {
      key: "instrumento", label: "Instrumento", header: true,
      value: (row) => row.instrument.code, render: (row) => instrumentLink(row.instrument),
    },
    { key: "tipo", label: "Tipo", value: (row) => row.instrument.label, render: (row) => typeChip(row.instrument) },
  ];
  if (full) {
    columns.push(priceColumn("abertura", "Abertura", "open"), priceColumn("maximo", "Máximo", "high"), priceColumn("minimo", "Mínimo", "low"));
  }
  columns.push(
    priceColumn("fecho", "Fecho", "close"),
    { key: "variacao", label: "Variação", num: true, value: (row) => row.change, render: (row) => delta(row.change) },
    {
      key: "ticks", label: "Ticks", num: true, value: (row) => row.ticks,
      render: (row) => [
        isLowRow(row, core.baselines) ? chip("poucos", "warn", "Menos ticks do que o habitual neste instrumento") : null,
        isLowRow(row, core.baselines) ? " " : null,
        h("a", { href: ticksHref(row.date, row.instrument.slug) }, fmtInt(row.ticks)),
      ],
    },
  );
  return columns;
}

export function dayTable(rows, core, { full, caption }) {
  const table = createTable({
    caption,
    columns: dayColumns(core, full),
    sort: { key: "instrumento", dir: "asc" },
    emptyText: "Este dia não tem instrumentos.",
  });
  table.update(rows);
  return table.el;
}
