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

/* Statement layout: financial measures down rows, filings across columns. */
(() => {
  const {get, flatten} = AccountData;
  const result = 'resultatregnskapResultat.';
  const sections = [
    ['Resultat', [
      ['Driftsinntekter', result+'driftsresultat.driftsinntekter.sumDriftsinntekter'],
      ['Driftskostnader', result+'driftsresultat.driftskostnad.sumDriftskostnad'],
      ['Driftsresultat', result+'driftsresultat.driftsresultat'],
      ['Netto finans', result+'finansresultat.nettoFinans'],
      ['Resultat før skatt', result+'ordinaertResultatFoerSkattekostnad'],
      ['Årsresultat', result+'aarsresultat'], ['Totalresultat', result+'totalresultat']]],
    ['Balanse', [
      ['Eiendeler', 'eiendeler.sumEiendeler'], ['Anleggsmidler', 'eiendeler.anleggsmidler.sumAnleggsmidler'],
      ['Omløpsmidler', 'eiendeler.omloepsmidler.sumOmloepsmidler'],
      ['Egenkapital', 'egenkapitalGjeld.egenkapital.sumEgenkapital'],
      ['Gjeld', 'egenkapitalGjeld.gjeldOversikt.sumGjeld'],
      ['Kortsiktig gjeld', 'egenkapitalGjeld.gjeldOversikt.kortsiktigGjeld.sumKortsiktigGjeld'],
      ['Langsiktig gjeld', 'egenkapitalGjeld.gjeldOversikt.langsiktigGjeld.sumLangsiktigGjeld']]],
    ['Regnskapsinformasjon', [
      ['Periode', null], ['Valuta', 'valuta'], ['Journalnr.', 'journalnr'], ['Regnskaps-id', 'id'],
      ['Oppstillingsplan', 'oppstillingsplan'], ['Regnskapsregler', 'regnkapsprinsipper.regnskapsregler'],
      ['Små foretak', 'regnkapsprinsipper.smaaForetak'], ['Ikke revidert', 'revisjon.ikkeRevidertAarsregnskap'],
      ['Fravalg revisjon', 'revisjon.fravalgRevisjon'], ['Avviklingsregnskap', 'avviklingsregnskap'],
      ['Morselskap', 'virksomhet.morselskap']]],
  ];
  const numeric = new Intl.NumberFormat('nb-NO', {maximumFractionDigits: 20});
  function text(value, money=false) {
    if (value == null || value === '' || typeof value === 'object') return '—';
    if (value === true || value === 'true') return 'Ja';
    if (value === false || value === 'false') return 'Nei';
    if (money && /^-?\d+(?:\.\d+)?$/.test(String(value)) && Number.isFinite(Number(value)) && Math.abs(Number(value)) <= Number.MAX_SAFE_INTEGER) return numeric.format(Number(value));
    return String(value);
  }
  function node(tag, content, cls) {
    const el=document.createElement(tag);
    if (content != null) el.textContent=content;
    if (cls) el.className=cls;
    return el;
  }
  function tableHeader(table, entries, label='') {
    const head=node('thead'), tr=node('tr'); tr.append(node('th',label));
    for(const f of entries) {
      const th=node('th', `${String(get(f,'regnskapsperiode.tilDato')||'').slice(0,4)} · ${get(f,'valuta')||'—'}`);
      th.scope='col';tr.append(th);
    }
    head.append(tr);table.append(head);
  }
  function render(container, filings) {
    container.replaceChildren();
    for (const type of [...new Set(filings.map(f=>get(f,'regnskapstype')))].sort((a,b)=>a==='SELSKAP'?-1:b==='SELSKAP'?1:String(a).localeCompare(String(b)))) {
      const entries=filings.filter(f=>get(f,'regnskapstype')===type).sort((a,b)=>String(get(b,'regnskapsperiode.tilDato')).localeCompare(String(get(a,'regnskapsperiode.tilDato'))));
      const section=node('section',null,'statement');
      const label=type==='SELSKAP'?'Selskapsregnskap':type==='KONSERN'?'Konsernregnskap':type||'Regnskap';
      section.append(node('h3',`${label} · ${entries.length} regnskap`));
      const scroll=node('div',null,'table-scroll'),table=node('table',null,'statement-table');
      tableHeader(table,entries);
      const body=node('tbody');
      for(const [title,fields] of sections){
        const heading=node('tr',null,'section-row'), th=node('th',title);th.colSpan=entries.length+1;heading.append(th);body.append(heading);
        for(const [label,path] of fields){
          const tr=node('tr'),th=node('th',label);th.scope='row';tr.append(th);
          for(const f of entries){
            const value=path?get(f,path):`${get(f,'regnskapsperiode.fraDato')||'—'} – ${get(f,'regnskapsperiode.tilDato')||'—'}`;
            tr.append(node('td',text(value,title!=='Regnskapsinformasjon'),title==='Regnskapsinformasjon'?'account-info':''));
          }
          body.append(tr);
        }
      }
      table.append(body);scroll.append(table);section.append(scroll);container.append(section);
    }
    const rows=filings.map(f=>flatten(f)), keys=[...new Set(rows.flatMap(r=>Object.keys(r)))].sort();
    const detail=node('details',null,'all-fields');detail.append(node('summary',`Alle kildefelt · ${keys.length} felt × ${filings.length} regnskap`));
    const scroll=node('div',null,'table-scroll'),table=node('table',null,'source-table');
    const head=node('thead'),tr=node('tr');tr.append(node('th','Kildefelt'));
    for(const f of filings)tr.append(node('th',`${get(f,'regnskapstype')} ${String(get(f,'regnskapsperiode.tilDato')||'').slice(0,4)} · ${get(f,'id')}`));
    head.append(tr);table.append(head);const body=node('tbody');
    for(const key of keys){const tr=node('tr');tr.append(node('th',key));for(const row of rows)tr.append(node('td',text(row[key])));body.append(tr);}
    table.append(body);scroll.append(table);detail.append(scroll);container.append(detail);
  }
  AccountData.render=render;
})();
