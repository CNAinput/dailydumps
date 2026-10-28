// Leitor de CSV (RFC 4180) para os ficheiros do arquivo.
function parseSimple(text) {
  const lines = text.split("\n");
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines.map((line) => (line.endsWith("\r") ? line.slice(0, -1) : line).split(","));
}

function parseQuoted(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char !== '"') {
        field += char;
      } else if (text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else {
        quoted = false;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }
  if (quoted) throw new Error("aspas por fechar");
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

// Devolve o cabeçalho e as linhas (listas de texto).
export function parseCsv(text) {
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const rows = clean.includes('"') ? parseQuoted(clean) : parseSimple(clean);
  return { header: rows.length > 0 ? rows[0] : [], rows: rows.slice(1) };
}

// Confirma o cabeçalho e o número de colunas. Falha com a linha em causa.
export function checkCsv(parsed, expectedHeader) {
  if (parsed.header.join(",") !== expectedHeader.join(",")) {
    throw new Error("cabeçalho inesperado, esperava " + expectedHeader.join(","));
  }
  parsed.rows.forEach((row, index) => {
    if (row.length !== expectedHeader.length) {
      throw new Error("a linha " + (index + 2) + " tem " + row.length + " colunas em vez de " + expectedHeader.length);
    }
  });
  return parsed.rows;
}
