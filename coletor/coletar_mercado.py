"""
Coletor de dados de MERCADO dos FIIs (roda no GitHub Actions).

Gera dois arquivos públicos, sem nenhum dado pessoal:
    mercado.json           -> preço, indicadores e proventos dos últimos 12 meses de cada ticker
    historico_mercado.json -> uma foto por mês dos indicadores (faixa 52 sem., DY CAGR, vacância, P/VP)

Fontes (todas acessíveis a partir do GitHub; o StatusInvest bloqueia com HTTP 403):
    fiis.com.br  -> principal: preço, faixa 52 sem., DY 12m, P/VP, VP/cota, DY CAGR 3/5a e
                    tabela de proventos (valor, data-com, pagamento)
    Yahoo        -> preço mais recente (atualiza durante o pregão)
    Fundamentus  -> vacância média (só FIIs com imóveis)

Uso:
    python coletor/coletar_mercado.py
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
TICKERS_FILE = RAIZ / "tickers.json"
MERCADO_FILE = RAIZ / "mercado.json"
HISTORICO_FILE = RAIZ / "historico_mercado.json"

BRT = timezone(timedelta(hours=-3))
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "pt-BR,pt;q=0.9"}


def num(v):
    """Número ou None. Trata '', 0 'de mentira' (campo sem dado) e strings BR."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace("%", "").replace(" ", "")
    if s in ("", "-", "—"):
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def positivo(v):
    """Campos em que 0 significa 'sem dado' (ex.: P/VP 0 no CPTI11)."""
    v = num(v)
    return v if v and v > 0 else None


# ---------------------------------------------------------------- fiis.com.br
def fiis_com_br(ticker):
    r = requests.get(f"https://fiis.com.br/{ticker.lower()}/", headers=H, timeout=30)
    r.raise_for_status()
    html = r.text

    marca = "var dataLayer_content = "
    i = html.find(marca)
    if i < 0:
        raise RuntimeError("bloco de dados não encontrado (layout mudou?)")
    obj, _ = json.JSONDecoder().raw_decode(html, i + len(marca))
    meta = obj.get("pagePostTerms", {}).get("meta", {})
    if not meta:
        raise RuntimeError("bloco de dados vazio")

    proventos = []
    tabela = re.search(r'<table class="dividendsTable__table">(.*?)</table>', html, re.S)
    if tabela:
        for linha in re.findall(r"<tr>(.*?)</tr>", tabela.group(1), re.S):
            comp = re.search(r'data-label="Compet[^"]*">\s*([\d/]+)', linha)
            valor = re.search(r'data-label="Rendimento">.*?R\$\s*([\d.,]+)', linha, re.S)
            dcom = re.search(r'data-label="Data-com">\s*<time datetime="(\d{4}-\d\d-\d\d)"', linha)
            pag = re.search(r'data-label="Pagamento">\s*<time datetime="(\d{4}-\d\d-\d\d)"', linha)
            if valor and dcom and pag:
                proventos.append({
                    "comp": comp.group(1) if comp else None,
                    "valor": num(valor.group(1)),
                    "dataCom": dcom.group(1),
                    "pagamento": pag.group(1),
                })

    return {
        "nome": meta.get("nome_pregao") or meta.get("name"),
        "preco": positivo(meta.get("valor")),
        "precoData": (meta.get("datacotacao") or "")[:10] or None,
        "min52": positivo(meta.get("min_52_semanas")),
        "max52": positivo(meta.get("max_52_semanas")),
        "dy12m": positivo(meta.get("dy")),
        "pvp": positivo(meta.get("pvp")),
        "vpa": positivo(meta.get("valorpatrimonialcota")),
        "dyCagr3": num(meta.get("dividend_cagr3")),
        "dyCagr5": num(meta.get("dividend_cagr5")),
        "proventos": proventos,
    }


# ---------------------------------------------------------------- Yahoo
def yahoo_preco(ticker):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.SA",
                     params={"range": "5d", "interval": "1d"}, headers=H, timeout=30)
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    preco = positivo(meta.get("regularMarketPrice"))
    quando = meta.get("regularMarketTime")
    data = datetime.fromtimestamp(quando, BRT).strftime("%Y-%m-%d") if quando else None
    return preco, data


# ---------------------------------------------------------------- Fundamentus
def fundamentus_vacancias():
    """{ticker: vacância %} para FIIs com pelo menos 1 imóvel. Uma única página com todos."""
    r = requests.get("https://www.fundamentus.com.br/fii_resultado.php", headers=H, timeout=30)
    r.raise_for_status()
    html = r.content.decode("latin-1", errors="replace")
    out = {}
    for t, resto in re.findall(r">([A-Z0-9]{4}1[1-3])</a></span></td>(.*?)</tr>", html, re.S):
        c = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", resto, re.S)]
        # colunas: 0 segmento, 1 cotação, 2 FFO yield, 3 DY, 4 P/VP, 5 valor de mercado,
        #          6 liquidez, 7 qtd imóveis, 8 preço m², 9 aluguel m², 10 cap rate, 11 vacância média
        if len(c) >= 12 and (num(c[7]) or 0) > 0:
            vac = num(c[11])
            # Alguns fundos (ex.: shoppings) aparecem com a OCUPAÇÃO no lugar da vacância
            # (XPML11 = 91,8%). Acima de 50% tratamos como dado não confiável.
            out[t] = vac if vac is not None and vac < 50 else None
    return out


# ---------------------------------------------------------------- principal
def mes_label(dt):
    return f"{MESES[dt.month - 1]}/{str(dt.year)[2:]}"


def main():
    tickers = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))["tickers"]
    agora = datetime.now(BRT)
    falhas = []

    try:
        vacancias = fundamentus_vacancias()
    except Exception as e:
        vacancias = {}
        falhas.append(f"Fundamentus: {type(e).__name__}: {e}")

    anterior = {}
    if MERCADO_FILE.exists():
        try:
            anterior = json.loads(MERCADO_FILE.read_text(encoding="utf-8")).get("ativos", {})
        except Exception:
            anterior = {}

    ativos = {}
    for t in tickers:
        try:
            d = fiis_com_br(t)
        except Exception as e:
            falhas.append(f"{t} fiis.com.br: {type(e).__name__}: {str(e)[:120]}")
            if t in anterior:  # mantém o último dado bom em vez de sumir com o ativo
                ativos[t] = {**anterior[t], "desatualizado": True}
            continue

        d["precoFonte"] = "fiis.com.br"
        try:
            py, data_y = yahoo_preco(t)
            if py and (not d["precoData"] or (data_y and data_y >= d["precoData"])):
                d["preco"], d["precoData"], d["precoFonte"] = py, data_y, "Yahoo"
        except Exception as e:
            falhas.append(f"{t} Yahoo: {type(e).__name__}")

        d["vacancia"] = vacancias.get(t)
        ativos[t] = d
        print(f"OK  {t:7} R$ {d['preco']}  proventos={len(d['proventos'])}  "
              f"pvp={d['pvp']}  cagr3={d['dyCagr3']}  vac={d['vacancia']}", flush=True)
        time.sleep(1)

    if not ativos:
        print("Nenhum ativo coletado — mantendo mercado.json anterior.", file=sys.stderr)
        sys.exit(1)

    mercado = {
        "geradoEm": agora.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
        "fontes": "fiis.com.br, Yahoo Finance, Fundamentus",
        "ativos": ativos,
        "falhas": falhas,
    }
    MERCADO_FILE.write_text(json.dumps(mercado, ensure_ascii=False, indent=1), encoding="utf-8")

    # Foto mensal dos indicadores (sobrescreve a do mês corrente).
    hist = {}
    if HISTORICO_FILE.exists():
        hist = json.loads(HISTORICO_FILE.read_text(encoding="utf-8"))
    m = mes_label(agora)
    for t, d in ativos.items():
        if d.get("desatualizado"):
            continue
        foto = {"m": m, "preco": d["preco"], "min52": d["min52"], "max52": d["max52"],
                "dy12m": d["dy12m"], "pvp": d["pvp"], "dyCagr3": d["dyCagr3"],
                "dyCagr5": d["dyCagr5"], "vacancia": d["vacancia"]}
        serie = hist.setdefault(t, [])
        serie[:] = [f for f in serie if f["m"] != m] + [foto]
    HISTORICO_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

    for f in falhas:
        print("AVISO", f)
    print(f"\n{len(ativos)}/{len(tickers)} ativos salvos em {MERCADO_FILE.name}")


if __name__ == "__main__":
    main()
