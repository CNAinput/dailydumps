// Dividendos e impostos: a política de cada instrumento e os impostos em vigor.
import { loadDividends, loadTaxes } from "../api.js";
import { loadCore } from "../core.js";
import { h } from "../dom.js";
import { fmtInstant, fmtInt, fmtNumber, normalizeText } from "../format.js";
import { TYPE_OPTIONS, lookup } from "../model.js";
import { instrumentLink, kvList, typeChip } from "../ui/blocks.js";

export const dataset = {
  id: "politicas",
  title: "Dividendos e impostos",
  caption: "Política de dividendos: percentagem do saldo da tesouraria, intervalo e datas de pagamento",
  emptyText: "Nenhuma política de dividendos corresponde a estes filtros.",
  defaultSort: { key: "instrumento", dir: "asc" },

  async init(ctx) {
    const [core, dividends, taxes] = await Promise.all([loadCore(ctx.signal), loadDividends(ctx.signal), loadTaxes(ctx.signal)]);
    const policies = dividends.policies.map((policy) => ({
      ...policy,
      key: policy.code + "|" + policy.asset_type,
      instrument: lookup(core.catalog, policy.code, policy.asset_type),
    }));
    return { core, policies, taxes };
  },

  fields: () => [
    { name: "q", label: "Código ou nome", type: "text", placeholder: "ex.: NEWTE" },
    { name: "tipo", label: "Tipo", type: "select", options: [["", "Todos"], ...TYPE_OPTIONS] },
  ],

  load: async (state, ctx, init) => init,

  columns: () => [
    {
      key: "instrumento", label: "Instrumento", header: true,
      value: (policy) => policy.instrument.code, render: (policy) => instrumentLink(policy.instrument),
    },
    { key: "tipo", label: "Tipo", value: (policy) => policy.instrument.label, render: (policy) => typeChip(policy.instrument) },
    {
      key: "percentagem", label: "% do saldo da tesouraria", num: true, value: (policy) => policy.percentage,
      render: (policy) => fmtNumber(policy.percentage, 0, 2) + " %",
    },
    { key: "intervalo", label: "Intervalo (dias)", num: true, value: (policy) => policy.distribution_days, render: (policy) => fmtInt(policy.distribution_days) },
    {
      key: "ultimo", label: "Último pagamento", value: (policy) => policy.last_distribution,
      render: (policy) => fmtInstant(policy.last_distribution),
    },
    {
      key: "proximo", label: "Próximo pagamento", value: (policy) => policy.next_distribution,
      render: (policy) => fmtInstant(policy.next_distribution),
    },
  ],

  rows(data, state) {
    const query = normalizeText(state.q.trim());
    return data.policies.filter((policy) => {
      if (query && !policy.instrument.searchText.includes(query)) return false;
      if (state.tipo && policy.instrument.type !== state.tipo) return false;
      return true;
    });
  },

  summary: (data, rows) =>
    fmtInt(rows.length) + " de " + fmtInt(data.policies.length) +
    (data.policies.length === 1 ? " política em vigor." : " políticas em vigor.") +
    " Cada pagamento distribui aquela percentagem do saldo da tesouraria pelos acionistas, em proporção das shares detidas.",

  extra(data) {
    const taxes = data.taxes;
    return h(
      "section",
      { "aria-labelledby": "impostos-titulo" },
      h("h3", { id: "impostos-titulo", class: "block-title" }, "Impostos em vigor"),
      kvList([
        ["Juro dos empréstimos novos (por dia)", fmtNumber(taxes.loan_interest_pct, 0, 2) + " %"],
        ["Imposto sobre os salários", fmtNumber(taxes.income_tax_pct, 0, 2) + " %"],
        ["IVA nas compras da loja", fmtNumber(taxes.vat_pct, 0, 2) + " %"],
        ["Última alteração", fmtInstant(taxes.last_changed)],
      ]),
    );
  },
};
