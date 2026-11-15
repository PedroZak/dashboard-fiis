"""
Coletor de dados de MERCADO dos FIIs (roda no GitHub Actions). Nenhum dado pessoal.

Universo: os N fundos mais negociados (liquidez diária no Fundamentus) + extras do tickers.json.

Saída (pasta --saida, publicada no ramo "dados", substituído a cada execução):
    indice.json          -> data da coleta, lista de fundos disponíveis (ticker -> nome), avisos
    ativos/<TICKER>.json -> preço, indicadores, proventos dos últimos 12 meses e
                            foto mensal dos indicadores dos últimos 12 meses

Limpeza automática:
    - foto mensal: só os últimos 12 meses
    - fundo que saiu do universo (ou parou de responder) some depois de 30 dias sem atualização

Fontes (todas acessíveis a partir do GitHub; o StatusInvest bloqueia com HTTP 403):
    fiis.com.br  -> principal: preço, faixa 52 sem., DY 12m, P/VP, VP/cota, DY CAGR 3/5a, proventos
    Yahoo        -> preço mais recente (atualiza durante o pregão)
    Fundamentus  -> ranking de liquidez e vacância média (só FIIs com imóveis)

Uso:
    python coletor/coletar_mercado.py --saida dados
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
TICKERS_FILE = RAIZ / "tickers.json"
BRT = timezone(timedelta(hours=-3))
MESES_HISTORICO = 12
DIAS_PARA_EXPIRAR = 30
PAUSA = 0.5  # segundos entre fundos, para não sobrecarregar os sites

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
     "Accept-Language": "pt-BR,pt;q=0.9"}
TICKER_RE = re.compile(r"^[A-Z0-9]{4}1[1-3]$")


def num(v):
    """Número ou None. Aceita número, string BR ('1.234,56'), '%' e 'R$'."""
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


# ---------------------------------------------------------------- Fundamentus
def fundamentus():
    """{ticker: {'liquidez': R$/dia, 'vacancia': % ou None}} de todos os FIIs/FIAGROs listados."""
    r = requests.get("https://www.fundamentus.com.br/fii_resultado.php", headers=H, timeout=30)
    r.raise_for_status()
    html = r.content.decode("latin-1", errors="replace")
    out = {}
    for t, resto in re.findall(r">([A-Z0-9]{4}1[1-3])</a></span></td>(.*?)</tr>", html, re.S):
        c = [re.sub(r"<[^>]+>", "", x).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", resto, re.S)]
        # colunas: 0 segmento, 1 cotação, 2 FFO yield, 3 DY, 4 P/VP, 5 valor de mercado,
        #          6 liquidez, 7 qtd imóveis, 8 preço m², 9 aluguel m², 10 cap rate, 11 vacância média
        if len(c) < 12:
            continue
        vac = num(c[11]) if (num(c[7]) or 0) > 0 else None
        # Alguns fundos (ex.: shoppings) aparecem com a OCUPAÇÃO no lugar da vacância
        # (XPML11 = 91,8%). Acima de 50% tratamos como dado não confiável.
        out[t] = {"liquidez": num(c[6]) or 0, "vacancia": vac if vac is not None and vac < 50 else None,
                  "cotacao": positivo(c[1]), "dy": positivo(c[3]), "pvp": positivo(c[4]), "segmento": c[0]}
    return out


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
    if not meta or not positivo(meta.get("valor")):
        raise RuntimeError("sem cotação")

    proventos = []
    tabela = re.search(r'<table class="dividendsTable__table">(.*?)</table>', html, re.S)
    if tabela:
        for linha in re.findall(r"<tr>(.*?)</tr>", tabela.group(1), re.S):
            comp = re.search(r'data-label="Compet[^"]*">\s*([\d/]+)', linha)
            valor = re.search(r'data-label="Rendimento">.*?R\$\s*([\d.,]+)', linha, re.S)
            dcom = re.search(r'data-label="Data-com">\s*<time datetime="(\d{4}-\d\d-\d\d)"', linha)
            pag = re.search(r'data-label="Pagamento">\s*<time datetime="(\d{4}-\d\d-\d\d)"', linha)
            if valor and dcom and pag:
                proventos.append({"comp": comp.group(1) if comp else None, "valor": num(valor.group(1)),
                                  "dataCom": dcom.group(1), "pagamento": pag.group(1)})

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
    quando = meta.get("regularMarketTime")
    return positivo(meta.get("regularMarketPrice")), (datetime.fromtimestamp(quando, BRT).strftime("%Y-%m-%d") if quando else None)


# ---------------------------------------------------------------- principal
def ler_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default="dados")
    ap.add_argument("--limite", type=int, default=0, help="só para teste: coleta no máximo N fundos")
    args = ap.parse_args()

    saida = Path(args.saida)
    pasta_ativos = saida / "ativos"
    pasta_ativos.mkdir(parents=True, exist_ok=True)

    config = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
    agora = datetime.now(BRT)
    agora_iso = agora.strftime("%Y-%m-%dT%H:%M:%S-03:00")
    mes = agora.strftime("%Y-%m")
    falhas = []

    # Universo: mais negociados + extras
    try:
        fund = fundamentus()
    except Exception as e:
        fund = {}
        falhas.append(f"Fundamentus: {type(e).__name__}: {e}")
    ranking = sorted((t for t, d in fund.items() if d["liquidez"] > 0), key=lambda t: -fund[t]["liquidez"])
    universo = list(dict.fromkeys(ranking[:config["quantidade"]] + [t.upper() for t in config.get("extras", [])]))
    universo = [t for t in universo if TICKER_RE.match(t)]
    if not ranking:
        # Sem o ranking, coleta pelo menos quem já estava publicado (não derruba o app).
        universo = list(dict.fromkeys(universo + [p.stem for p in pasta_ativos.glob("*.json")]))
    if args.limite:
        universo = universo[:args.limite]
    print(f"Universo: {len(universo)} fundos", flush=True)

    ok = 0
    t0 = time.time()
    for t in universo:
        arq = pasta_ativos / f"{t}.json"
        anterior = ler_json(arq) or {}
        try:
            d = fiis_com_br(t)
        except Exception as e:
            f = fund.get(t)
            if f and f.get("cotacao"):
                # Fundo que o fiis.com.br não cobre: registro parcial com Fundamentus (sem proventos).
                d = {"nome": "", "preco": f["cotacao"], "precoData": None, "min52": None, "max52": None,
                     "dy12m": f["dy"], "pvp": f["pvp"], "vpa": None, "dyCagr3": None, "dyCagr5": None,
                     "proventos": [], "parcial": True}
                falhas.append(f"{t}: sem página no fiis.com.br — dados parciais do Fundamentus")
            else:
                falhas.append(f"{t} fiis.com.br: {type(e).__name__}: {str(e)[:100]}")
                if anterior:  # mantém o último dado bom; a limpeza remove se ficar velho demais
                    anterior["desatualizado"] = True
                    arq.write_text(json.dumps(anterior, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                time.sleep(PAUSA)
                continue

        d["precoFonte"] = "Fundamentus" if d.get("parcial") else "fiis.com.br"
        try:
            py, data_y = yahoo_preco(t)
            if py and (not d["precoData"] or (data_y and data_y >= d["precoData"])):
                d["preco"], d["precoData"], d["precoFonte"] = py, data_y, "Yahoo"
        except Exception:
            pass  # sem Yahoo, fica o preço do fiis.com.br

        f = fund.get(t, {})
        d["vacancia"] = f.get("vacancia")
        d["liquidez"] = f.get("liquidez")

        foto = {"m": mes, "preco": d["preco"], "min52": d["min52"], "max52": d["max52"], "dy12m": d["dy12m"],
                "pvp": d["pvp"], "dyCagr3": d["dyCagr3"], "dyCagr5": d["dyCagr5"], "vacancia": d["vacancia"]}
        hist = [h for h in anterior.get("historico", []) if h.get("m") != mes] + [foto]
        d["historico"] = sorted(hist, key=lambda h: h["m"])[-MESES_HISTORICO:]
        d["ticker"] = t
        d["atualizadoEm"] = agora_iso

        arq.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        ok += 1
        if ok % 25 == 0:
            print(f"  {ok} fundos... ({time.time() - t0:.0f}s)", flush=True)
        time.sleep(PAUSA)

    # Limpeza: remove fundos sem atualização há mais de DIAS_PARA_EXPIRAR dias
    limite = agora - timedelta(days=DIAS_PARA_EXPIRAR)
    removidos = []
    for arq in pasta_ativos.glob("*.json"):
        d = ler_json(arq) or {}
        try:
            quando = datetime.fromisoformat(d.get("atualizadoEm", ""))
        except ValueError:
            quando = None
        if quando is None or quando < limite:
            arq.unlink()
            removidos.append(arq.stem)

    disponiveis = {}
    for arq in sorted(pasta_ativos.glob("*.json")):
        d = ler_json(arq) or {}
        disponiveis[arq.stem] = d.get("nome") or ""

    if ok == 0:
        print("Nenhum fundo coletado — nada será publicado.", file=sys.stderr)
        sys.exit(1)

    indice = {"geradoEm": agora_iso, "fontes": "fiis.com.br, Yahoo Finance, Fundamentus",
              "total": len(disponiveis), "ativos": disponiveis, "removidos": removidos, "falhas": falhas}
    (saida / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")

    for f in falhas:
        print("AVISO", f)
    print(f"\n{ok}/{len(universo)} coletados em {time.time() - t0:.0f}s · {len(disponiveis)} publicados · "
          f"{len(removidos)} removidos pela limpeza")


if __name__ == "__main__":
    main()
