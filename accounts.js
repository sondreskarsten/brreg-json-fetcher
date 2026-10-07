/* Parse response fields without guessing corrections to source/proxy structure. */
(() => {
  function xmlObject(element) {
    if (!element.children.length) return element.textContent.trim();
    const out = Object.create(null);
    for (const child of element.children) {
      const key = child.localName;
      const value = xmlObject(child);
      if (Object.hasOwn(out, key)) out[key] = Array.isArray(out[key]) ? [...out[key], value] : [out[key], value];
      else out[key] = value;
    }
    return out;
  }
  function get(value, path) {
    for (const part of path.split('.')) {
      if (!value || typeof value !== 'object') return undefined;
      const key = Object.keys(value).find(k => k.toLowerCase() === part.toLowerCase());
      value = value[key];
    }
    return value;
  }
  function flatten(value, prefix = '', out = Object.create(null)) {
    for (const [key, item] of Object.entries(value)) {
      const path = prefix ? prefix + '.' + key : key;
      if (item && typeof item === 'object' && !Array.isArray(item) && Object.keys(item).length) flatten(item, path, out);
      else out[path] = item && typeof item === 'object' ? JSON.stringify(item) : item;
    }
    return out;
  }
  function records(filings, orgnr, route, format, retrievedAt) {
    return filings.map(filing => {
      const row = flatten(filing);
      row['_meta.orgnr'] = orgnr;
      row['_meta.fiscal_year'] = String(get(filing, 'regnskapsperiode.tilDato') || '').slice(0, 4);
      row['_meta.route'] = route;
      row['_meta.response_format'] = format;
      row['_meta.retrieved_at'] = retrievedAt;
      row['_meta.reader_reformatted'] = route === 'Jina Reader';
      return row;
    });
  }
  function cell(value) {
    let text = value == null ? '' : String(value);
    // Escape spreadsheet formulas while retaining negative numeric amounts.
    if (/^[\s]*[=+@-]/.test(text) && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }
  function csv(rows) {
    const first = ['_meta.orgnr', 'id', 'journalnr', 'regnskapstype', '_meta.fiscal_year', 'valuta'];
    const keys = new Set(rows.flatMap(row => Object.keys(row)));
    const columns = [...first.filter(k => keys.has(k)), ...[...keys].filter(k => !first.includes(k)).sort()];
    return '\uFEFF' + [columns.map(cell).join(','), ...rows.map(row => columns.map(k => cell(row[k])).join(','))].join('\r\n') + '\r\n';
  }
  globalThis.AccountData = {xmlObject, get, flatten, records, csv};
})();
