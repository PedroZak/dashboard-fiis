# Painel de Renda Imobiliária (FIIs)

App para acompanhar uma carteira de fundos imobiliários, FIAGROs e FI-Infras no celular ou no computador.

**Privacidade:** este repositório não tem nenhum dado pessoal. Cada pessoa importa a própria carteira (ou começa do zero) e ela fica só no armazenamento local do navegador. O app baixa apenas dados públicos de mercado, e só dos fundos que estão na carteira.

## Como funciona

| Parte | O que faz |
|---|---|
| `index.html` | O app. Lê a carteira do aparelho, baixa os dados de mercado dos fundos dela e faz todos os cálculos no navegador. |
| `coletor/coletar_mercado.py` | Busca preço, DY, P/VP, faixa de 52 semanas, DY CAGR, vacância e proventos dos ~180 fundos mais negociados + extras de `tickers.json`. |
| `.github/workflows/mercado.yml` | Roda o coletor em dias úteis, publica os dados no ramo `dados` e monta o site (app + dados). |

**Dados (ramo `dados`, substituído a cada coleta, sem histórico acumulado):**
- `indice.json`: data da coleta e lista de fundos disponíveis.
- `ativos/<TICKER>.json`: um arquivo por fundo, com proventos dos últimos 12 meses e uma foto mensal dos indicadores dos últimos 12 meses.
- Fundos que saem da lista somem automaticamente após 30 dias sem atualização.

Fontes: [fiis.com.br](https://fiis.com.br) (principal), Yahoo Finance (preço mais recente) e Fundamentus (ranking de liquidez e vacância).

## Formato da carteira

```json
{
  "versao": 1,
  "ativos": {
    "ABCD11": { "segmento": "Logística", "classe": "tijolo", "cotas": 10, "pm": 100.0, "metaPct": 20 }
  },
  "proventos": { "lancamentos": [], "por_ativo": {}, "mensal": [], "anual": [], "cursores": {} }
}
```

`classe` aceita `tijolo`, `papel`, `terras` ou `infra`.
