# Scraper Spot Gifts (Playwright)
Scraper em Python para catálogo dinâmico da Spot Gifts, renderizando JavaScript antes da extração.
URL de entrada fixa:
- `https://www.spotgifts.com.br/pt/catalogo/?catalogo=1`

## O que extrai
- nome
- url
- descrição (quando disponível — site pode exigir login para exibir)
- imagens
- categorias (derivadas da URL e/ou breadcrumb)
- referência/código (do último segmento da URL ou elemento na página)

## Regras
- ignora páginas institucionais e de autenticação (area-reservada, equipe, contatos, stricker, história, declaração de acessibilidade etc.)
- produtos têm URL no padrão `/pt/catalogo/<familia>/<referencia>/`
- salva todos os itens com nome válido; descrição e imagens ficam vazias se não disponíveis

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
- `--max-scrolls`: máximo de ciclos de scroll/paginação (default: `60`)
- `--headed`: abre o navegador visível (debug)

## Saída JSON
```json
{
  "nome": "GOA. Sacola em non-woven (80 g/m²) termo-selado",
  "url": "https://www.spotgifts.com.br/pt/catalogo/sacos-de-compras-non-woven/22904",
  "descricao": "Descrição do produto ou null",
  "imagens": ["https://..."],
  "categorias": ["Sacos De Compras Non Woven"],
  "referencia": "22904"
}
```
