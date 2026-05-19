# Scraper Spot Gifts

Scraper em Python para coletar todos os produtos de `https://www.spotgifts.com.br/pt/` com:

- nome
- descrição
- imagens
- categorias

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Execução

```bash
python scraper_spotgifts.py --output produtos_spotgifts.json
```

Parâmetros:
- `--output`: arquivo JSON de saída (default: `produtos_spotgifts.json`)
- `--delay`: delay entre requests em segundos (default: `0.2`)
- `--limit`: limita a quantidade de produtos processados (default: `0`, sem limite)
- `--resume`: continua uma coleta anterior lendo o arquivo de saída e pulando URLs já processadas

## Estrutura do output

Cada item no JSON contém:

```json
{
  "url": "https://...",
  "nome": "Nome do produto",
  "descricao": "Descrição do produto",
  "imagens": ["https://..."],
  "categorias": ["Categoria A", "Categoria B"]
}
```
