# -*- coding: utf-8 -*-
"""
terra_pacote.py — Pacote do Imóvel (Terra Geotecnologia) · esquema v1.0

Biblioteca central da integração. Python puro (só biblioteca padrão), então roda
igual no QGIS, no TopoPro e em qualquer script.

Formatos:
  .gpkg        → arquivo mestre (QGIS, TopoPro, arquivo do processo)
  .terra.json  → mesmo conteúdo em JSON (app de campo e portal web)

Uso rápido:
  import terra_pacote as tp
  pac = tp.abrir("fazenda.terra.json")   # ou .gpkg
  pac = tp.normalizar(pac)               # completa UTM/lat-long, sigma, lados, área
  for nivel, msg in tp.validar(pac): print(nivel, msg)
  tp.salvar(pac, "fazenda.gpkg")
"""
import json, math, os, sqlite3, struct, datetime

VERSAO = "1.0"
FORMATO = "terra-pacote"

# ---------------------------------------------------------------- esquema
CAMPOS = {
    "imovel": [
        ("imovel_id", "TEXT"), ("denominacao", "TEXT"), ("municipio", "TEXT"), ("uf", "TEXT"),
        ("comarca", "TEXT"), ("matricula", "TEXT"), ("cns_cartorio", "TEXT"), ("livro", "TEXT"),
        ("ccir", "TEXT"), ("nirf", "TEXT"), ("car", "TEXT"), ("codigo_sigef", "TEXT"),
        ("servico", "TEXT"), ("area_matricula_ha", "REAL"), ("area_utm_ha", "REAL"),
        ("area_sgl_ha", "REAL"), ("perimetro_utm_m", "REAL"), ("datum", "TEXT"), ("fuso", "TEXT"),
        ("resp_tecnico", "TEXT"), ("registro_prof", "TEXT"), ("cod_credenciado", "TEXT"),
        ("etapa_atual", "TEXT"), ("criado_em", "TEXT"), ("atualizado_em", "TEXT")],
    "vertices": [
        ("imovel_id", "TEXT"), ("ordem", "INTEGER"), ("codigo", "TEXT"), ("tipo", "TEXT"),
        ("este", "REAL"), ("norte", "REAL"), ("latitude", "REAL"), ("longitude", "REAL"),
        ("alt_elipsoidal", "REAL"), ("sigma_n", "REAL"), ("sigma_e", "REAL"), ("sigma_u", "REAL"),
        ("sigma_h", "REAL"), ("tolerancia_h", "REAL"), ("dentro_tolerancia", "INTEGER"),
        ("metodo", "TEXT"), ("equipamento", "TEXT"), ("altura_antena", "REAL"),
        ("data_levantamento", "TEXT"), ("foto_marco", "TEXT"), ("obs", "TEXT")],
    "limites": [
        ("imovel_id", "TEXT"), ("ordem", "INTEGER"), ("vertice_ini", "TEXT"), ("vertice_fim", "TEXT"),
        ("tipo_limite", "TEXT"), ("descricao_limite", "TEXT"), ("confrontante_id", "TEXT"),
        ("azimute_dec", "REAL"), ("azimute_dms", "TEXT"), ("distancia_m", "REAL")],
    "proprietarios": [
        ("imovel_id", "TEXT"), ("nome", "TEXT"), ("cpf_cnpj", "TEXT"), ("estado_civil", "TEXT"),
        ("regime_bens", "TEXT"), ("conjuge", "TEXT"), ("conjuge_cpf", "TEXT"), ("fracao_ideal", "TEXT"),
        ("endereco", "TEXT"), ("telefone", "TEXT"), ("email", "TEXT")],
    "confrontantes": [
        ("id", "TEXT"), ("imovel_id", "TEXT"), ("nome", "TEXT"), ("cpf_cnpj", "TEXT"),
        ("denominacao", "TEXT"), ("matricula", "TEXT"), ("cns_cartorio", "TEXT"),
        ("codigo_sigef", "TEXT"), ("tipo", "TEXT"), ("anuencia_status", "TEXT"), ("anuencia_data", "TEXT")],
    "processo": [
        ("imovel_id", "TEXT"), ("etapa", "TEXT"), ("data", "TEXT"), ("responsavel", "TEXT"),
        ("origem", "TEXT"), ("obs", "TEXT")],
    "documentos": [
        ("imovel_id", "TEXT"), ("tipo", "TEXT"), ("arquivo", "TEXT"), ("data", "TEXT"), ("gerado_por", "TEXT")],
}
GEOM = {"imovel": "POLYGON", "vertices": "POINT", "limites": "LINESTRING"}
LISTAS = ["vertices", "limites", "proprietarios", "confrontantes", "processo", "documentos"]

ETAPAS = ["ORCAMENTO", "DOCUMENTACAO", "CAMPO", "PROCESSAMENTO", "PECAS_TECNICAS", "SIGEF_ENVIO",
          "SIGEF_CERTIFICADO", "CARTORIO_PROTOCOLO", "CARTORIO_AVERBADO", "CONCLUIDO"]
TOLERANCIA = {"LA": 0.50, "LN": 3.00, "LI": 7.50}   # NTGIR 3ª ed. — precisão horizontal máxima (m)
TIPOS_VERTICE = {"M", "P", "V"}

RESP_PADRAO = {"resp_tecnico": "André Ricardo Nascimento Costa",
               "registro_prof": "CRT/MG 94464634672", "cod_credenciado": "DCCM",
               "datum": "SIRGAS2000", "fuso": "23S"}

# ---------------------------------------------------------------- geodésia (SIRGAS2000 / GRS80)
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9996


def fuso_num(fuso):
    return int(str(fuso or "23").upper().replace("S", "").strip())


def epsg_do_fuso(fuso):
    return 31960 + fuso_num(fuso)          # 22→31982, 23→31983, 24→31984


def ll2utm(lat, lon, fuso=23):
    z = fuso_num(fuso)
    phi, l0, l = math.radians(lat), math.radians((z - 1) * 6 - 180 + 3), math.radians(lon)
    s, c, t = math.sin(phi), math.cos(phi), math.tan(phi)
    N = _A / math.sqrt(1 - _E2 * s * s)
    T, C, A = t * t, _EP2 * c * c, c * (l - l0)
    e4, e6 = _E2 ** 2, _E2 ** 3
    M = _A * ((1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
              - (3 * _E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
              + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
              - (35 * e6 / 3072) * math.sin(6 * phi))
    E = _K0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * _EP2) * A ** 5 / 120) + 500000
    Nn = _K0 * (M + N * t * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
                             + (61 - 58 * T + T * T + 600 * C - 330 * _EP2) * A ** 6 / 720))
    if lat < 0:
        Nn += 10000000
    return E, Nn


def utm2ll(E, N, fuso=23, sul=True):
    z = fuso_num(fuso)
    x, y = E - 500000, (N - 10000000 if sul else N)
    e4, e6 = _E2 ** 2, _E2 ** 3
    M = y / _K0
    mu = M / (_A * (1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
          + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
          + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(p1), math.cos(p1), math.tan(p1)
    N1 = _A / math.sqrt(1 - _E2 * s * s)
    T1, C1 = t * t, _EP2 * c * c
    R1 = _A * (1 - _E2) / (1 - _E2 * s * s) ** 1.5
    D = x / (N1 * _K0)
    lat = p1 - (N1 * t / R1) * (D * D / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1 * C1 - 9 * _EP2) * D ** 4 / 24
                                + (61 + 90 * T1 + 298 * C1 + 45 * T1 * T1 - 252 * _EP2 - 3 * C1 * C1) * D ** 6 / 720)
    lon = (D - (1 + 2 * T1 + C1) * D ** 3 / 6
           + (5 - 2 * C1 + 28 * T1 - 3 * C1 * C1 + 8 * _EP2 + 24 * T1 * T1) * D ** 5 / 120) / c
    return math.degrees(lat), (z - 1) * 6 - 180 + 3 + math.degrees(lon)


def azimute(E1, N1, E2, N2):
    return (math.degrees(math.atan2(E2 - E1, N2 - N1)) + 360) % 360


def dms(az):
    d = int(az); m = int((az - d) * 60); s = ((az - d) * 60 - m) * 60
    if s >= 59.995:
        s = 0; m += 1
    if m == 60:
        m = 0; d += 1
    return f"{d:03d}°{m:02d}'{s:05.2f}\"".replace(".", ",")


def area_perimetro(coords):
    n = len(coords)
    a = sum(coords[i][0] * coords[(i + 1) % n][1] - coords[(i + 1) % n][0] * coords[i][1] for i in range(n)) / 2
    p = sum(math.dist(coords[i], coords[(i + 1) % n]) for i in range(n))
    return a, p        # a < 0 → sentido horário


def familia(cod):
    return (cod or "")[:2].upper()


# ---------------------------------------------------------------- pacote em memória
def novo(imovel_id=None, **imovel):
    hoje = datetime.date.today().isoformat()
    im = {k: None for k, _ in CAMPOS["imovel"]}
    im.update(RESP_PADRAO)
    im.update(imovel_id=imovel_id or "IMV-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
              etapa_atual="DOCUMENTACAO", criado_em=hoje, atualizado_em=hoje)
    im.update(imovel)
    return {"formato": FORMATO, "versao": VERSAO, "imovel": im, **{k: [] for k in LISTAS}}


def normalizar(pac, recalcular_lados=True):
    """Completa o que dá para calcular: UTM↔lat/long, σH, tolerância, lados, área, perímetro."""
    im = pac["imovel"]
    for k, v in RESP_PADRAO.items():
        im.setdefault(k, v) if im.get(k) else im.__setitem__(k, v)
    fuso = im.get("fuso") or "23S"
    iid = im["imovel_id"]
    vs = sorted(pac.get("vertices", []), key=lambda v: v.get("ordem") or 0)
    for i, v in enumerate(vs, 1):
        v["imovel_id"] = iid
        v["ordem"] = i
        if v.get("este") is None and v.get("latitude") is not None:
            v["este"], v["norte"] = ll2utm(v["latitude"], v["longitude"], fuso)
        if v.get("latitude") is None and v.get("este") is not None:
            v["latitude"], v["longitude"] = utm2ll(v["este"], v["norte"], fuso)
        for c in ("este", "norte"):
            v[c] = round(v[c], 3)
        v["latitude"], v["longitude"] = round(v["latitude"], 9), round(v["longitude"], 9)
        if v.get("sigma_n") is not None and v.get("sigma_e") is not None:
            v["sigma_h"] = round(math.hypot(v["sigma_n"], v["sigma_e"]), 3)
        if not v.get("tipo") and v.get("codigo"):
            partes = v["codigo"].split("-")
            v["tipo"] = partes[1] if len(partes) >= 3 else "M"
    pac["vertices"] = vs

    # lados
    antigos = {(l.get("vertice_ini"), l.get("vertice_fim")): l for l in pac.get("limites", [])}
    if recalcular_lados and len(vs) >= 3:
        lados = []
        for i, a in enumerate(vs):
            b = vs[(i + 1) % len(vs)]
            old = antigos.get((a["codigo"], b["codigo"]), {})
            az = azimute(a["este"], a["norte"], b["este"], b["norte"])
            lados.append({"imovel_id": iid, "ordem": i + 1, "vertice_ini": a["codigo"], "vertice_fim": b["codigo"],
                          "tipo_limite": old.get("tipo_limite") or a.get("_limite"),
                          "descricao_limite": old.get("descricao_limite") or a.get("_descricao_limite"),
                          "confrontante_id": old.get("confrontante_id") or a.get("_confrontante_id"),
                          "azimute_dec": round(az, 6), "azimute_dms": dms(az),
                          "distancia_m": round(math.dist((a["este"], a["norte"]), (b["este"], b["norte"])), 2)})
        pac["limites"] = lados
        for v in vs:
            for k in ("_limite", "_descricao_limite", "_confrontante_id"):
                v.pop(k, None)

    # tolerância pelo lado mais restritivo que toca o vértice
    lados = pac.get("limites", [])
    for v in vs:
        tl = [familia(l.get("tipo_limite")) for l in lados if v["codigo"] in (l["vertice_ini"], l["vertice_fim"])]
        tols = [TOLERANCIA[t] for t in tl if t in TOLERANCIA]
        v["tolerancia_h"] = min(tols) if tols else None
        if v.get("sigma_h") is not None and v["tolerancia_h"] is not None:
            v["dentro_tolerancia"] = int(v["sigma_h"] <= v["tolerancia_h"])

    if len(vs) >= 3:
        a, p = area_perimetro([(v["este"], v["norte"]) for v in vs])
        im["area_utm_ha"], im["perimetro_utm_m"] = round(abs(a) / 10000, 4), round(p, 2)
    for k in LISTAS:
        for r in pac.get(k, []):
            if "imovel_id" in dict(CAMPOS[k]):
                r["imovel_id"] = iid
    im["atualizado_em"] = datetime.date.today().isoformat()
    pac["formato"], pac["versao"] = FORMATO, VERSAO
    return pac


def registrar_etapa(pac, etapa, origem, obs=None, responsavel="André"):
    if etapa not in ETAPAS:
        raise ValueError(f"Etapa inválida: {etapa}")
    pac["imovel"]["etapa_atual"] = etapa
    pac.setdefault("processo", []).append({"imovel_id": pac["imovel"]["imovel_id"], "etapa": etapa,
        "data": datetime.date.today().isoformat(), "responsavel": responsavel, "origem": origem, "obs": obs})
    return pac


# ---------------------------------------------------------------- validação
def validar(pac):
    """Retorna lista de (nivel, mensagem); nivel = 'ERRO' | 'AVISO' | 'OK'."""
    out = []
    im, vs, ls = pac["imovel"], pac.get("vertices", []), pac.get("limites", [])
    conf_ids = {c.get("id") for c in pac.get("confrontantes", [])}
    if len(vs) < 3:
        return [("ERRO", "Menos de 3 vértices.")]
    cods = [v.get("codigo") for v in vs]
    dup = {c for c in cods if cods.count(c) > 1}
    if dup:
        out.append(("ERRO", f"Códigos de vértice repetidos: {', '.join(sorted(dup))}"))
    cred = im.get("cod_credenciado") or "DCCM"
    for v in vs:
        c = v.get("codigo") or ""
        p = c.split("-")
        if len(p) != 3 or p[0] != cred or p[1] not in TIPOS_VERTICE or not p[2].isdigit():
            out.append(("ERRO", f"Código fora do padrão {cred}-TIPO-NNNN: '{c}'"))
        if not v.get("metodo"):
            out.append(("ERRO", f"{c}: método de posicionamento vazio"))
        if v.get("sigma_h") is None:
            out.append(("AVISO", f"{c}: sem sigma (σN/σE)"))
        elif v.get("dentro_tolerancia") == 0:
            out.append(("ERRO", f"{c}: σH {v['sigma_h']:.3f} m acima da tolerância {v['tolerancia_h']:.2f} m"))
    # pontos coincidentes
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            if math.dist((vs[i]["este"], vs[i]["norte"]), (vs[j]["este"], vs[j]["norte"])) < 0.01:
                out.append(("ERRO", f"Vértices coincidentes: {vs[i]['codigo']} e {vs[j]['codigo']}"))
    for l in ls:
        tag = f"Lado {l['vertice_ini']}→{l['vertice_fim']}"
        if familia(l.get("tipo_limite")) not in TOLERANCIA:
            out.append(("ERRO", f"{tag}: tipo de limite vazio ou inválido"))
        if not l.get("confrontante_id"):
            out.append(("ERRO", f"{tag}: sem confrontante"))
        elif conf_ids and l["confrontante_id"] not in conf_ids:
            out.append(("ERRO", f"{tag}: confrontante '{l['confrontante_id']}' não cadastrado"))
    for c in pac.get("confrontantes", []):
        if c.get("tipo") == "PARTICULAR" and not (c.get("codigo_sigef") or (c.get("matricula") and c.get("cns_cartorio"))):
            out.append(("ERRO", f"Confrontante {c.get('nome')}: falta matrícula + CNS ou código SIGEF"))
        if c.get("tipo") == "PARTICULAR" and c.get("anuencia_status") not in ("ASSINADA", "NAO_APLICA"):
            out.append(("AVISO", f"Confrontante {c.get('nome')}: anuência {c.get('anuencia_status') or 'PENDENTE'}"))
    a, _ = area_perimetro([(v["este"], v["norte"]) for v in vs])
    if a > 0:
        out.append(("AVISO", "Perímetro no sentido anti-horário (conferir sentido exigido na planilha SIGEF)"))
    if not pac.get("proprietarios"):
        out.append(("AVISO", "Nenhum proprietário cadastrado"))
    for k in ("matricula", "cns_cartorio", "municipio"):
        if not im.get(k):
            out.append(("AVISO", f"Imóvel sem {k}"))
    am, au = im.get("area_matricula_ha"), im.get("area_utm_ha")
    if am and au:
        dif = (au - am) / am * 100
        out.append(("AVISO" if abs(dif) > 5 else "OK",
                    f"Área UTM {au:.4f} ha × matrícula {am:.4f} ha ({dif:+.2f}%). Área oficial é a SGL do SIGEF."))
    if not any(n == "ERRO" for n, _ in out):
        out.append(("OK", "Nenhum erro impeditivo encontrado."))
    return out


# ---------------------------------------------------------------- JSON
def ler_json(caminho):
    with open(caminho, encoding="utf-8") as f:
        pac = json.load(f)
    if pac.get("formato") != FORMATO:
        raise ValueError("Arquivo não é um Pacote do Imóvel (formato 'terra-pacote').")
    for k in LISTAS:
        pac.setdefault(k, [])
    return pac


def gravar_json(pac, caminho):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(pac, f, ensure_ascii=False, indent=1)
    return caminho


# ---------------------------------------------------------------- GeoPackage (sem GDAL)
def _wkt_utm(fuso):
    z = fuso_num(fuso)
    return ('PROJCS["SIRGAS 2000 / UTM zone %dS",GEOGCS["SIRGAS 2000",DATUM["Sistema_de_Referencia_Geocentrico_para_las_AmericaS_2000",'
            'SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6674"]],'
            'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
            'AUTHORITY["EPSG","4674"]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",%d],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
            'PARAMETER["false_northing",10000000],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],'
            'AXIS["Northing",NORTH],AUTHORITY["EPSG","%d"]]') % (z, (z - 1) * 6 - 180 + 3, epsg_do_fuso(z))


def _gp(srs, wkb, env):
    minx, maxx, miny, maxy = env
    return b"GP" + bytes([0, 0b00000011]) + struct.pack("<i4d", srs, minx, maxx, miny, maxy) + wkb


def _wkb_point(x, y):
    return struct.pack("<BIdd", 1, 1, x, y)


def _wkb_line(pts):
    return struct.pack("<BII", 1, 2, len(pts)) + b"".join(struct.pack("<dd", *p) for p in pts)


def _wkb_poly(pts):
    ring = list(pts) + [pts[0]]
    return struct.pack("<BIII", 1, 3, 1, len(ring)) + b"".join(struct.pack("<dd", *p) for p in ring)


def _env(pts):
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _ler_geom(blob):
    """Decodifica geometria GPKG (ponto, linha ou polígono 2D) → lista de (x, y)."""
    if not blob:
        return None
    flags = blob[3]
    env_len = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 0b111]
    w = blob[8 + env_len:]
    bo = "<" if w[0] == 1 else ">"
    gtype = struct.unpack(bo + "I", w[1:5])[0] % 1000
    if gtype == 1:
        return [struct.unpack(bo + "dd", w[5:21])]
    if gtype == 2:
        n = struct.unpack(bo + "I", w[5:9])[0]
        return [struct.unpack(bo + "dd", w[9 + 16 * i:25 + 16 * i]) for i in range(n)]
    if gtype == 3:
        n = struct.unpack(bo + "I", w[9:13])[0]
        return [struct.unpack(bo + "dd", w[13 + 16 * i:29 + 16 * i]) for i in range(n)][:-1]
    return None


def gravar_gpkg(pac, caminho):
    if os.path.exists(caminho):
        os.remove(caminho)
    im = pac["imovel"]
    srs = epsg_do_fuso(im.get("fuso") or "23S")
    agora = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    db = sqlite3.connect(caminho)
    cur = db.cursor()
    cur.execute("PRAGMA application_id = 1196444487")   # 'GPKG'
    cur.execute("PRAGMA user_version = 10300")
    cur.executescript("""
    CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY, organization TEXT NOT NULL,
      organization_coordsys_id INTEGER NOT NULL, definition TEXT NOT NULL, description TEXT);
    CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
      description TEXT DEFAULT '', last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
      min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
    CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
      srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL, CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
    """)
    cur.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", [
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None),
        ("WGS 84 geodetic", 4326, "EPSG", 4326,
         'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]', None),
        (f"SIRGAS 2000 / UTM zone {fuso_num(im.get('fuso'))}S", srs, "EPSG", srs, _wkt_utm(im.get("fuso")), None)])

    vs = pac.get("vertices", [])
    xy = {v["codigo"]: (v["este"], v["norte"]) for v in vs}
    for tab, cols in CAMPOS.items():
        geom = GEOM.get(tab)
        defs = ", ".join(f'"{c}" {t}' for c, t in cols)
        cur.execute(f'CREATE TABLE "{tab}" (fid INTEGER PRIMARY KEY AUTOINCREMENT{", geom " + geom if geom else ""}, {defs})')
        linhas = [pac["imovel"]] if tab == "imovel" else pac.get(tab, [])
        env_tab = None
        for r in linhas:
            vals = [r.get(c) for c, _ in cols]
            if geom:
                if tab == "imovel":
                    pts = [(v["este"], v["norte"]) for v in vs]
                    g = _gp(srs, _wkb_poly(pts), _env(pts)) if len(pts) >= 3 else None
                elif tab == "vertices":
                    pts = [(r["este"], r["norte"])]
                    g = _gp(srs, _wkb_point(*pts[0]), _env(pts))
                else:
                    pts = [xy.get(r["vertice_ini"]), xy.get(r["vertice_fim"])]
                    g = _gp(srs, _wkb_line(pts), _env(pts)) if None not in pts else None
                if g:
                    e = _env(pts)
                    env_tab = e if env_tab is None else (min(env_tab[0], e[0]), max(env_tab[1], e[1]),
                                                         min(env_tab[2], e[2]), max(env_tab[3], e[3]))
                vals = [g] + vals
            ph = ",".join("?" * len(vals))
            names = (["geom"] if geom else []) + [c for c, _ in cols]
            cur.execute(f'INSERT INTO "{tab}" ({",".join(chr(34)+n+chr(34) for n in names)}) VALUES ({ph})', vals)
        if geom:
            e = env_tab or (0, 0, 0, 0)
            cur.execute("INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (tab, "features", tab, "", agora, e[0], e[2], e[1], e[3], srs))
            cur.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,0,0)", (tab, "geom", geom, srs))
        else:
            cur.execute("INSERT INTO gpkg_contents (table_name,data_type,identifier,last_change) VALUES (?,?,?,?)",
                        (tab, "attributes", tab, agora))
    cur.execute('CREATE TABLE "metadados" (fid INTEGER PRIMARY KEY AUTOINCREMENT, chave TEXT, valor TEXT)')
    cur.executemany('INSERT INTO metadados (chave, valor) VALUES (?,?)',
                    [("formato", FORMATO), ("versao_esquema", VERSAO), ("norma", "NTGIR 3ª edição"),
                     ("crs", f"EPSG:{srs}"), ("gravado_em", agora)])
    cur.execute("INSERT INTO gpkg_contents (table_name,data_type,identifier,last_change) VALUES ('metadados','attributes','metadados',?)", (agora,))
    db.commit()
    db.close()
    return caminho


def ler_gpkg(caminho):
    db = sqlite3.connect(caminho)
    db.row_factory = sqlite3.Row
    tabelas = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pac = {"formato": FORMATO, "versao": VERSAO}
    fuso = "23S"
    try:
        srs = db.execute("SELECT srs_id FROM gpkg_geometry_columns WHERE table_name='vertices'").fetchone()
        if srs:
            fuso = f"{srs[0] - 31960}S"
    except sqlite3.Error:
        pass
    for tab, cols in CAMPOS.items():
        linhas = []
        if tab in tabelas:
            existentes = {r[1] for r in db.execute(f'PRAGMA table_info("{tab}")')}
            geomcol = next((c for c in ("geom", "geometry") if c in existentes), None)
            for r in db.execute(f'SELECT * FROM "{tab}"'):
                d = {c: (r[c] if c in existentes else None) for c, _ in cols}
                if tab == "vertices" and geomcol:
                    # a geometria manda: se o ponto foi movido no QGIS, E/N e lat/long são refeitos
                    p = _ler_geom(r[geomcol])
                    if p and (d.get("este") is None or math.dist(p[0], (d["este"], d["norte"])) > 0.0005):
                        d["este"], d["norte"] = p[0]
                        d["latitude"] = d["longitude"] = None
                linhas.append(d)
        if tab == "imovel":
            pac["imovel"] = linhas[0] if linhas else novo()["imovel"]
        else:
            pac[tab] = linhas
    db.close()
    pac["imovel"]["fuso"] = pac["imovel"].get("fuso") or fuso
    return pac


# ---------------------------------------------------------------- atalhos
def abrir(caminho):
    return ler_gpkg(caminho) if caminho.lower().endswith(".gpkg") else ler_json(caminho)


def salvar(pac, caminho):
    return gravar_gpkg(pac, caminho) if caminho.lower().endswith(".gpkg") else gravar_json(pac, caminho)


def confrontante(pac, cid):
    return next((c for c in pac.get("confrontantes", []) if c.get("id") == cid), {})


def descricao_perimetral(pac):
    """Texto corrido do perímetro para memorial/requerimento (coordenadas UTM, SIRGAS2000)."""
    vs, ls = pac["vertices"], pac["limites"]
    im = pac["imovel"]
    if not vs:
        return ""
    f = lambda x: f"{x:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    v0 = vs[0]
    txt = [f"Inicia-se a descrição deste perímetro no vértice {v0['codigo']}, de coordenadas "
           f"N {f(v0['norte'])} m e E {f(v0['este'])} m"]
    por_cod = {v["codigo"]: v for v in vs}
    for l in ls:
        b = por_cod[l["vertice_fim"]]
        c = confrontante(pac, l.get("confrontante_id"))
        nome = c.get("nome") or l.get("confrontante_id") or "confrontante não informado"
        extra = f", {c['denominacao']}" if c.get("denominacao") else ""
        mat = f", matrícula {c['matricula']}" if c.get("matricula") else ""
        sig = f", código SIGEF {c['codigo_sigef']}" if c.get("codigo_sigef") else ""
        lim = f" ({l['descricao_limite'].lower()})" if l.get("descricao_limite") else ""
        txt.append(f"; deste, segue confrontando com {nome}{extra}{mat}{sig}{lim}, com azimute de "
                   f"{l['azimute_dms']} e distância de {f(l['distancia_m'])[:-1]} m, até o vértice {b['codigo']}"
                   + ("" if b is not vs[0] else ", ponto inicial da descrição deste perímetro"))
    txt.append(f". Todas as coordenadas aqui descritas estão georreferenciadas ao Sistema Geodésico Brasileiro, "
               f"referenciadas ao Meridiano Central {-(fuso_num(im.get('fuso')) - 1) * 6 + 180 - 3}° WGr, "
               f"tendo como datum o SIRGAS2000, e encontram-se representadas no Sistema UTM. "
               f"Todos os azimutes e distâncias, área e perímetro foram calculados no plano de projeção UTM.")
    return "".join(txt)
