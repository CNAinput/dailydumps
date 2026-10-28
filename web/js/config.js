// Constantes do site. Os valores que podem mudar estão todos aqui.
export const REPO = "CNAinput/dailydumps";
export const REPO_URL = "https://github.com/" + REPO;
export const RAW_URL = "https://raw.githubusercontent.com/" + REPO + "/main/";
export const LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/deed.pt";
export const ATTRIBUTION = "Arquivo de dados do mercado da CNA, licença CC BY 4.0";
export const SITE_TITLE = "Arquivo de dados do mercado da CNA";

// Origem dos ticks (prices/). Vazia, lê-os do próprio site.
export const TICKS_BASE = RAW_URL;
// Modelo do endereço de um despacho, com {id}. Vazio, mostra só o número.
export const DOCUMENT_URL = "";

export const TIMEZONE = "Europe/Lisbon";
export const OPEN_HOUR = 11;
export const CLOSE_HOUR = 23;

export const PAGE_SIZE = 100;
export const TICKS_MAX_DAYS = 60;
export const SNAPSHOTS_MAX_DAYS = 366;
export const TICKS_CONCURRENCY = 4;
// Dia (ou instrumento) com menos ticks do que esta fração da mediana.
export const LOW_TICKS_RATIO = 0.8;
export const LOW_TICKS_MIN_DAYS = 5;
