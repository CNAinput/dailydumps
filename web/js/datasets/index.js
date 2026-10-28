// Os conjuntos de dados da pesquisa. Cada um carrega-se só quando é aberto.
export const TABS = [
  { id: "dias", label: "Dias", description: "Preços de abertura, máximo, mínimo e fecho por dia e instrumento, com a variação do dia.", load: () => import("./days.js") },
  { id: "ticks", label: "Ticks", description: "Todos os preços registados num ou mais dias, com gráfico, lidos do GitHub só quando pedidos.", load: () => import("./ticks.js") },
  { id: "eventos", label: "Eventos", description: "IPO, splits, emissões e retiradas de cotação registados no arquivo.", load: () => import("./events.js") },
  { id: "capitalizacao", label: "Capitalização", description: "Shares e capitalização no fecho, dia a dia, nos dias arquivados com snapshot.", load: () => import("./snapshots.js") },
  { id: "politicas", label: "Dividendos e impostos", description: "A política de dividendos de cada instrumento e os impostos em vigor.", load: () => import("./policies.js") },
  { id: "ficheiros", label: "Ficheiros", description: "Todos os ficheiros do arquivo, com a soma de controlo SHA-256 e ligações para os abrir.", load: () => import("./files.js") },
];

export function findTab(id) {
  return TABS.find((tab) => tab.id === id) || null;
}
