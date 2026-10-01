# -*- coding: utf-8 -*-
"""
topopro_pacote.py — ponte TopoPro ↔ Pacote do Imóvel

Preenche os modelos .docx da Terra Geotecnologia com os dados do pacote.
Nos modelos, use marcadores Jinja (docxtpl), por exemplo:
  {{ imovel.denominacao }}  {{ prop.nome }}  {{ area_ha }}  {{ descricao_perimetral }}
  Tabela de vértices: numa linha da tabela, {%tr for v in vertices %} … {%tr endfor %}

Uso pela linha de comando (serve para o TopoPro chamar mesmo que não seja Python):
  python topopro_pacote.py pacote.gpkg modelo.docx saida.docx
  python topopro_pacote.py pacote.gpkg modelo_declaracao.docx pasta_saida --por-confrontante
  python topopro_pacote.py pacote.gpkg --campos      (lista os marcadores disponíveis)
Requer: pip install docxtpl
"""
import os, sys, json, datetime
import terra_pacote as tp

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


def br(x, casas=2):
    if x is None:
        return ""
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _limpo(x):
    if isinstance(x, dict):
        return {k: _limpo(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_limpo(v) for v in x]
    return "" if x is None else x


def contexto(pac):
    pac = tp.normalizar(pac)
    im = pac["imovel"]
    hoje = datetime.date.today()
    props = pac.get("proprietarios", [])
    confs = pac.get("confrontantes", [])
    vs = [dict(v, este_br=br(v["este"], 3), norte_br=br(v["norte"], 3),
               sigma_h_br=br(v.get("sigma_h"), 3), alt_br=br(v.get("alt_elipsoidal"), 3)) for v in pac["vertices"]]
    ls = [dict(l, distancia_br=br(l["distancia_m"]), confrontante=tp.confrontante(pac, l.get("confrontante_id")))
          for l in pac["limites"]]
    return _limpo({
        "imovel": im, "proprietarios": props, "prop": props[0] if props else {},
        "proprietarios_nomes": ", ".join(p["nome"] for p in props if p.get("nome")),
        "confrontantes": confs, "confrontantes_particulares": [c for c in confs if c.get("tipo") == "PARTICULAR"],
        "vertices": vs, "limites": ls,
        "area_ha": br(im.get("area_sgl_ha") or im.get("area_utm_ha"), 4),
        "area_origem": "SGL (SIGEF)" if im.get("area_sgl_ha") else "plano UTM",
        "area_matricula_ha": br(im.get("area_matricula_ha"), 4),
        "perimetro_m": br(im.get("perimetro_utm_m")),
        "descricao_perimetral": tp.descricao_perimetral(pac),
        "data": hoje.strftime("%d/%m/%Y"),
        "data_extenso": f"{hoje.day} de {MESES[hoje.month - 1]} de {hoje.year}",
        "cidade_data": f"Paracatu/MG, {hoje.day} de {MESES[hoje.month - 1]} de {hoje.year}",
        "resp": {"nome": im.get("resp_tecnico"), "registro": im.get("registro_prof"),
                 "credenciado": im.get("cod_credenciado"), "empresa": "Terra Geotecnologia"},
    })


def preencher(pac, modelo, saida, extra=None):
    from docxtpl import DocxTemplate
    doc = DocxTemplate(modelo)
    ctx = contexto(pac)
    ctx.update(extra or {})
    doc.render(ctx, autoescape=True)
    doc.save(saida)
    return saida


def por_confrontante(pac, modelo, pasta):
    """Uma declaração de confrontação por confrontante particular ({{ conf.nome }} no modelo)."""
    os.makedirs(pasta, exist_ok=True)
    saidas = []
    ctx = contexto(pac)
    for c in ctx["confrontantes_particulares"]:
        nome = "".join(ch if ch.isalnum() else "_" for ch in (c.get("nome") or c.get("id")))[:50]
        lados = [l for l in ctx["limites"] if l.get("confrontante_id") == c.get("id")]
        saidas.append(preencher(pac, modelo, os.path.join(pasta, f"declaracao_{nome}.docx"),
                                {"conf": c, "lados_conf": lados}))
    return saidas


def registrar_documento(caminho_pacote, tipo, arquivo):
    """Anota no pacote (.gpkg) que o TopoPro gerou a peça."""
    import sqlite3
    db = sqlite3.connect(caminho_pacote)
    iid = db.execute("SELECT imovel_id FROM imovel LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO documentos (imovel_id,tipo,arquivo,data,gerado_por) VALUES (?,?,?,?,?)",
               (iid, tipo, os.path.basename(arquivo), datetime.date.today().isoformat(), "TOPOPRO"))
    db.commit()
    db.close()


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 2 and a[1] == "--campos":
        ctx = contexto(tp.abrir(a[0]))
        print(json.dumps({k: (v if not isinstance(v, list) else f"[lista de {len(v)}]") for k, v in ctx.items()},
                         ensure_ascii=False, indent=1, default=str))
    elif len(a) >= 3:
        pac = tp.abrir(a[0])
        if "--por-confrontante" in a:
            for s in por_confrontante(pac, a[1], a[2]):
                print("gerado:", s)
        else:
            print("gerado:", preencher(pac, a[1], a[2]))
            if a[0].lower().endswith(".gpkg"):
                registrar_documento(a[0], os.path.splitext(os.path.basename(a[1]))[0].upper(), a[2])
    else:
        print(__doc__)
