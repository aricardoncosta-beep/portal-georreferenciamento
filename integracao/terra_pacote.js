/* terra_pacote.js — Pacote do Imóvel (Terra Geotecnologia) · esquema v1.0
 * Mesmo esquema do terra_pacote.py. Usado pelo Terra Geo Campo e pelo portal.
 *
 *   const pac = TerraPacote.novo({denominacao:'Fazenda X', municipio:'Paracatu', uf:'MG'});
 *   TerraPacote.addVertice(pac, {codigo:'DCCM-M-0001', latitude:-17.2, longitude:-46.9,
 *                                 alt_elipsoidal:650, sigma_n:0.01, sigma_e:0.01, metodo:'PG6'});
 *   TerraPacote.normalizar(pac);          // UTM, σH, lados, área
 *   TerraPacote.validar(pac);             // [[nivel, msg], ...]
 *   TerraPacote.baixarJSON(pac);          // salva .terra.json
 *   const pac2 = await TerraPacote.lerArquivo(file);   // .terra.json ou .gpkg (usa sql.js)
 */
(function (g) {
  'use strict';
  const VERSAO = '1.0', FORMATO = 'terra-pacote';
  const TOL = { LA: 0.50, LN: 3.00, LI: 7.50 };
  const ETAPAS = ['ORCAMENTO', 'DOCUMENTACAO', 'CAMPO', 'PROCESSAMENTO', 'PECAS_TECNICAS', 'SIGEF_ENVIO',
    'SIGEF_CERTIFICADO', 'CARTORIO_PROTOCOLO', 'CARTORIO_AVERBADO', 'CONCLUIDO'];
  const LISTAS = ['vertices', 'limites', 'proprietarios', 'confrontantes', 'processo', 'documentos'];
  const RESP = { resp_tecnico: 'André Ricardo Nascimento Costa', registro_prof: 'CRT/MG 94464634672',
    cod_credenciado: 'DCCM', datum: 'SIRGAS2000', fuso: '23S' };
  const hoje = () => new Date().toISOString().slice(0, 10);
  const r = (x, n) => x == null ? null : Math.round(x * 10 ** n) / 10 ** n;

  /* ---------- geodésia SIRGAS2000 / GRS80 ---------- */
  const A = 6378137, F = 1 / 298.257222101, E2 = F * (2 - F), EP2 = E2 / (1 - E2), K0 = 0.9996, D2R = Math.PI / 180;
  const fusoNum = f => parseInt(String(f || '23').replace(/\D/g, ''), 10);
  const mc = z => (z - 1) * 6 - 180 + 3;
  function ll2utm(lat, lon, fuso) {
    const z = fusoNum(fuso), phi = lat * D2R, l0 = mc(z) * D2R, l = lon * D2R;
    const s = Math.sin(phi), c = Math.cos(phi), t = Math.tan(phi), N = A / Math.sqrt(1 - E2 * s * s);
    const T = t * t, C = EP2 * c * c, Aa = c * (l - l0), e4 = E2 * E2, e6 = e4 * E2;
    const M = A * ((1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * Math.sin(2 * phi)
      + (15 * e4 / 256 + 45 * e6 / 1024) * Math.sin(4 * phi) - (35 * e6 / 3072) * Math.sin(6 * phi));
    const E = K0 * N * (Aa + (1 - T + C) * Aa ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * EP2) * Aa ** 5 / 120) + 500000;
    let Nn = K0 * (M + N * t * (Aa * Aa / 2 + (5 - T + 9 * C + 4 * C * C) * Aa ** 4 / 24 + (61 - 58 * T + T * T + 600 * C - 330 * EP2) * Aa ** 6 / 720));
    if (lat < 0) Nn += 10000000;
    return [E, Nn];
  }
  function utm2ll(E, N, fuso) {
    const z = fusoNum(fuso), x = E - 500000, y = N - 10000000, e4 = E2 * E2, e6 = e4 * E2;
    const mu = (y / K0) / (A * (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256)), e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2));
    const p1 = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
      + (151 * e1 ** 3 / 96) * Math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
    const s = Math.sin(p1), c = Math.cos(p1), t = Math.tan(p1), N1 = A / Math.sqrt(1 - E2 * s * s);
    const T1 = t * t, C1 = EP2 * c * c, R1 = A * (1 - E2) / (1 - E2 * s * s) ** 1.5, D = x / (N1 * K0);
    const lat = p1 - (N1 * t / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * EP2) * D ** 4 / 24
      + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * EP2 - 3 * C1 * C1) * D ** 6 / 720);
    const lon = (D - (1 + 2 * T1 + C1) * D ** 3 / 6 + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * EP2 + 24 * T1 * T1) * D ** 5 / 120) / c;
    return [lat / D2R, mc(z) + lon / D2R];
  }
  const azimute = (a, b) => (Math.atan2(b.este - a.este, b.norte - a.norte) / D2R + 360) % 360;
  function dms(az) {
    let d = Math.floor(az), m = Math.floor((az - d) * 60), s = ((az - d) * 60 - m) * 60;
    if (s >= 59.995) { s = 0; m++ } if (m === 60) { m = 0; d++ }
    return `${String(d).padStart(3, '0')}°${String(m).padStart(2, '0')}'${s.toFixed(2).padStart(5, '0').replace('.', ',')}"`;
  }
  const fam = c => String(c || '').slice(0, 2).toUpperCase();

  /* ---------- pacote ---------- */
  function novo(imovel = {}) {
    const im = Object.assign({ imovel_id: 'IMV-' + Date.now(), etapa_atual: 'DOCUMENTACAO', criado_em: hoje(), atualizado_em: hoje() }, RESP, imovel);
    const p = { formato: FORMATO, versao: VERSAO, imovel: im };
    LISTAS.forEach(k => p[k] = []);
    return p;
  }
  function addVertice(p, v) { p.vertices.push(Object.assign({ ordem: p.vertices.length + 1 }, v)); return p; }
  function registrarEtapa(p, etapa, origem, obs) {
    if (!ETAPAS.includes(etapa)) throw new Error('Etapa inválida: ' + etapa);
    p.imovel.etapa_atual = etapa;
    p.processo.push({ imovel_id: p.imovel.imovel_id, etapa, data: hoje(), responsavel: 'André', origem, obs: obs || null });
    return p;
  }
  function normalizar(p) {
    const im = p.imovel, fuso = im.fuso || '23S', id = im.imovel_id;
    Object.keys(RESP).forEach(k => { if (!im[k]) im[k] = RESP[k] });
    const vs = p.vertices.sort((a, b) => (a.ordem || 0) - (b.ordem || 0));
    vs.forEach((v, i) => {
      v.imovel_id = id; v.ordem = i + 1;
      if (v.este == null && v.latitude != null) [v.este, v.norte] = ll2utm(v.latitude, v.longitude, fuso);
      if (v.latitude == null && v.este != null) [v.latitude, v.longitude] = utm2ll(v.este, v.norte, fuso);
      v.este = r(v.este, 3); v.norte = r(v.norte, 3); v.latitude = r(v.latitude, 9); v.longitude = r(v.longitude, 9);
      if (v.sigma_n != null && v.sigma_e != null) v.sigma_h = r(Math.hypot(v.sigma_n, v.sigma_e), 3);
      if (!v.tipo && v.codigo) v.tipo = (v.codigo.split('-')[1] || 'M');
    });
    const old = {}; (p.limites || []).forEach(l => old[l.vertice_ini + '|' + l.vertice_fim] = l);
    if (vs.length >= 3) {
      p.limites = vs.map((a, i) => {
        const b = vs[(i + 1) % vs.length], o = old[a.codigo + '|' + b.codigo] || {}, az = azimute(a, b);
        return { imovel_id: id, ordem: i + 1, vertice_ini: a.codigo, vertice_fim: b.codigo,
          tipo_limite: o.tipo_limite || a._limite || null, descricao_limite: o.descricao_limite || a._descricao_limite || null,
          confrontante_id: o.confrontante_id || a._confrontante_id || null,
          azimute_dec: r(az, 6), azimute_dms: dms(az), distancia_m: r(Math.hypot(b.este - a.este, b.norte - a.norte), 2) };
      });
      vs.forEach(v => { delete v._limite; delete v._descricao_limite; delete v._confrontante_id });
      let s = 0, per = 0;
      vs.forEach((a, i) => { const b = vs[(i + 1) % vs.length]; s += a.este * b.norte - b.este * a.norte; per += Math.hypot(b.este - a.este, b.norte - a.norte) });
      im.area_utm_ha = r(Math.abs(s / 2) / 10000, 4); im.perimetro_utm_m = r(per, 2);
    }
    vs.forEach(v => {
      const t = p.limites.filter(l => l.vertice_ini === v.codigo || l.vertice_fim === v.codigo).map(l => TOL[fam(l.tipo_limite)]).filter(Boolean);
      v.tolerancia_h = t.length ? Math.min(...t) : null;
      if (v.sigma_h != null && v.tolerancia_h != null) v.dentro_tolerancia = v.sigma_h <= v.tolerancia_h ? 1 : 0;
    });
    LISTAS.forEach(k => (p[k] || []).forEach(x => { x.imovel_id = id }));
    im.atualizado_em = hoje(); p.formato = FORMATO; p.versao = VERSAO;
    return p;
  }
  function validar(p) {
    const out = [], vs = p.vertices, cred = p.imovel.cod_credenciado || 'DCCM';
    if (vs.length < 3) return [['ERRO', 'Menos de 3 vértices.']];
    const cods = vs.map(v => v.codigo), dup = [...new Set(cods.filter((c, i) => cods.indexOf(c) !== i))];
    if (dup.length) out.push(['ERRO', 'Códigos repetidos: ' + dup.join(', ')]);
    const re = new RegExp('^' + cred + '-[MPV]-\\d+$');
    vs.forEach(v => {
      if (!re.test(v.codigo || '')) out.push(['ERRO', `Código fora do padrão ${cred}-TIPO-NNNN: '${v.codigo}'`]);
      if (!v.metodo) out.push(['ERRO', `${v.codigo}: método vazio`]);
      if (v.sigma_h == null) out.push(['AVISO', `${v.codigo}: sem sigma`]);
      else if (v.dentro_tolerancia === 0) out.push(['ERRO', `${v.codigo}: σH ${v.sigma_h.toFixed(3)} m > tolerância ${v.tolerancia_h.toFixed(2)} m`]);
    });
    const ids = new Set(p.confrontantes.map(c => c.id));
    p.limites.forEach(l => {
      const tag = `Lado ${l.vertice_ini}→${l.vertice_fim}`;
      if (!TOL[fam(l.tipo_limite)]) out.push(['ERRO', tag + ': tipo de limite vazio']);
      if (!l.confrontante_id) out.push(['ERRO', tag + ': sem confrontante']);
      else if (ids.size && !ids.has(l.confrontante_id)) out.push(['ERRO', `${tag}: confrontante '${l.confrontante_id}' não cadastrado`]);
    });
    if (!out.some(x => x[0] === 'ERRO')) out.push(['OK', 'Nenhum erro impeditivo encontrado.']);
    return out;
  }

  /* ---------- arquivos ---------- */
  function baixarJSON(p, nome) {
    const n = nome || (String(p.imovel.denominacao || p.imovel.imovel_id).normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^\w]+/g, '_').toLowerCase() + '.terra.json');
    const b = new Blob([JSON.stringify(p, null, 1)], { type: 'application/json' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = n;
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 500);
    return n;
  }
  let _sql = null;
  async function sqljs() {
    if (_sql) return _sql;
    if (!g.initSqlJs) await new Promise((ok, err) => {
      const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/sql-wasm.js'; s.onload = ok; s.onerror = () => err(new Error('Não foi possível carregar o leitor de GeoPackage'));
      document.head.appendChild(s);
    });
    _sql = await g.initSqlJs({ locateFile: f => 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.8.0/' + f });
    return _sql;
  }
  async function lerGpkg(buf) {
    const SQL = await sqljs(), db = new SQL.Database(new Uint8Array(buf));
    const q = sql => { try { const res = db.exec(sql)[0]; return res ? res.values.map(v => Object.fromEntries(res.columns.map((c, i) => [c, v[i]]))) : [] } catch (e) { return [] } };
    const tira = rows => rows.map(o => { delete o.fid; delete o.geom; delete o.geometry; return o });
    const p = novo();
    const im = tira(q('SELECT * FROM imovel'))[0]; if (im) p.imovel = Object.assign(p.imovel, im);
    LISTAS.forEach(k => p[k] = tira(q(`SELECT * FROM "${k}"`)));
    db.close();
    if (!p.vertices.length) throw new Error('GeoPackage sem a tabela "vertices" do Pacote do Imóvel');
    return p;
  }
  async function lerArquivo(file) {
    if (/\.gpkg$/i.test(file.name)) return lerGpkg(await file.arrayBuffer());
    const p = JSON.parse(await file.text());
    if (p.formato !== FORMATO) throw new Error('Arquivo não é um Pacote do Imóvel');
    LISTAS.forEach(k => p[k] = p[k] || []);
    return p;
  }

  g.TerraPacote = { VERSAO, FORMATO, TOL, ETAPAS, novo, addVertice, registrarEtapa, normalizar, validar,
    baixarJSON, lerArquivo, lerGpkg, ll2utm, utm2ll, dms };
})(typeof window !== 'undefined' ? window : globalThis);
