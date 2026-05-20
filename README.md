# Scraper Spot Gifts (Playwright)

Scraper em Python para catálogo dinâmico da Spot Gifts, renderizando JavaScript antes da extração.

URL de entrada fixa:
- `https://www.spotgifts.com.br/pt/catalogo/?catalogo=1`

## O que extrai
- nome
- url
- descrição
- imagens
- categorias
- referência/código (se disponível)

## Regras
- ignora páginas institucionais (clientes, valores, contato, sobre, blog etc.)
- salva apenas itens válidos com:
  - nome
  - URL real de produto
  - descrição
  - ao menos 1 imagem

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

> Se estiver em servidor Linux, pode ser necessário:

```bash
python -m playwright install-deps chromium
```

## Execução

```bash
python scraper_spotgifts.py --output produtos_spotgifts.json
```

Parâmetros:
- `--output`: arquivo de saída JSON (default: `produtos_spotgifts.json`)
- `--delay-ms`: espera entre ciclos de carregamento dinâmico (default: `1500`)
- `--max-scrolls`: máximo de ciclos de scroll/paginação (default: `30`)
- `--headed`: abre o navegador visível (debug)

## Logs esperados
- tempo de abertura da página de catálogo
- quantidade de links brutos por ciclo
- quantidade de produtos detectados por ciclo
- total acumulado de produtos
- tempo por produto extraído
- tempo total da execução

Se nenhum produto for detectado, o scraper salva:
- `debug_catalogo.html`

## Saída JSON

```json
{
  "nome": "Nome do produto",
  "url": "https://www.spotgifts.com.br/pt/...",
  "descricao": "Descrição",
  "imagens": ["https://..."],
  "categorias": ["Categoria"],
  "referencia": "REF-123"
}
```
