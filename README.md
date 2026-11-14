# Painel de Renda Imobiliária (FIIs)

App para acompanhar uma carteira de fundos imobiliários, FIAGROs e FI-Infras no celular ou no computador.

**Privacidade:** este repositório não tem nenhum dado pessoal. A carteira (cotas, preço médio e histórico de proventos) é importada por cada pessoa no próprio aparelho e fica só no armazenamento local do navegador. O app baixa apenas `mercado.json`, que tem dados públicos de mercado.

## Como funciona

| Parte | O que faz |
|---|---|
| `index.html` | O app. Lê a carteira do aparelho, baixa `mercado.json` e faz todos os cálculos no próprio navegador. |
| `coletor/coletar_mercado.py` | Busca preço, DY, P/VP, faixa de 52 semanas, DY CAGR, vacância e proventos dos fundos listados em `tickers.json`. |
| `.github/workflows/mercado.yml` | Roda o coletor em dias úteis e publica `mercado.json` e `historico_mercado.json`. |

Fontes: [fiis.com.br](https://fiis.com.br) (principal), Yahoo Finance (preço mais recente) e Fundamentus (vacância).

## Formato da carteira

```json
{
  "versao": 1,
  "ativos": {
    "ABCD11": { "segmento": "Logística", "classe": "tijolo", "cotas": 10, "pm": 100.0, "metaPct": 20 }
  },
  "proventos": { "por_ativo": {}, "mensal": [], "anual": [], "cursores": {} }
}
```

`classe` aceita `tijolo`, `papel`, `terras` ou `infra`.
