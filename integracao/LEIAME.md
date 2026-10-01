# Integração Terra Geotecnologia — Pacote do Imóvel v1.0

Um arquivo por imóvel, lido e gravado por todos os programas:
**.gpkg** no computador (QGIS, TopoPro) e **.terra.json** no celular e no portal. Os dois têm o mesmo conteúdo e se convertem sem perda.

Fluxo: Terra Geo Campo → QGIS (Terra Geo Tools) → TopoPro → Portal (e volta).

## Pastas
| Arquivo | O que é | Como usar |
|---|---|---|
| `terra_pacote.py` | Biblioteca central (Python puro, sem dependências) | Fica ao lado do `topopro_pacote.py`; já vem dentro do complemento QGIS |
| `terra_pacote.js` | Mesma biblioteca em JavaScript | Já embutida no portal e no app de campo |
| `../terra_geo_campo_coleta.html` | App de campo: GPS do celular, pontos do receptor GNSS, envio pelo WhatsApp | Abrir pelo link do GitHub Pages e "Adicionar à tela inicial" |
| `terra_pacote_qgis.zip` | Complemento QGIS: Vetor → Terra Geo → Abrir, Validar, Recalcular, Descrição perimetral, Exportar | QGIS → Complementos → Instalar a partir do ZIP |
| `topopro_pacote.py` + modelos `.docx` | Ponte TopoPro: requerimento de averbação e declaração de confrontação | `python topopro_pacote.py pacote.gpkg requerimento_averbacao_georref.docx saida.docx` |
| `../index.html` | Portal com **Importar Pacote** e **Exportar Pacote** (aba Mapa) | Já publicado |
| `pacote_imovel_modelo.*` | Pacote de exemplo (.gpkg e .terra.json) | Testar o fluxo |

Para baixar tudo: botão verde **Code → Download ZIP** no GitHub.

## Seus modelos no TopoPro
Abra seus .docx e troque os campos por marcadores, por exemplo `{{ imovel.matricula }}`, `{{ prop.nome }}`, `{{ area_ha }}` e `{{ descricao_perimetral }}`. Para ver todos: `python topopro_pacote.py pacote.gpkg --campos`. Se o TopoPro não for em Python, ele chama o mesmo comando pela linha de comando. Requer `pip install docxtpl`.

## Regras embutidas (NTGIR 3ª ed.)
- Código `DCCM-M/P/V-NNNN`, único; σH = √(σN² + σE²); tolerância pelo lado mais restritivo (LA 0,50 · LN 3,00 · LI 7,50 m).
- Todo lado precisa de tipo de limite e confrontante; confrontante particular precisa de matrícula + CNS ou código SIGEF.
- Área UTM é só de conferência. A oficial é a SGL do SIGEF (`area_sgl_ha`), que nunca é ajustada para bater com a matrícula.
- Os códigos completos de método/limite (ex.: PG6, LA1) devem ser conferidos no Manual Técnico antes de gerar a ODS.
- Sigma padrão do portal (0,02) **não** é exportado como real: vértice sem sigma medido sai como "sem sigma".
