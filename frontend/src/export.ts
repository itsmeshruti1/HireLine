export function csvCell(value: string) {
  // Spreadsheet applications evaluate formulas even inside quoted CSV cells.
  const safe = /^[\s]*[=+@-]/.test(value) ? "'" + value : value;
  return '"' + safe.replaceAll('"', '""') + '"';
}
