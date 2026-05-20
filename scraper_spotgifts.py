#!/usr/bin/env python3
"""Scraper Playwright para catálogo Spot Gifts."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

CATALOGO_URL = "https://www.spotgifts.com.br/pt/catalogo/?catalogo=1"
BASE_URL = "https://www.spotgifts.com.br"

# Tokens que indicam páginas NÃO-produto
BLOCKED_TOKENS = {
    "/area-reservada",   # ← NOVO: login, cadastro, senha
    "/clientes",
    "/valores",
    "/contact",
    "/contato",
    "/contatos",         # ← NOVO
    "/sobre",
    "/blog",
    "/institucional",
    "/politica",
    "/termos",
    "/privacidade",
    "/faq",
    "/ferramentas-de-marketing",
    "/historia",         # ← NOVO
    "/noticias",
    "/perguntas-frequentes",
    "/personalizacao",
    "/sticker",
    "/stricker",         # ← NOVO (estava como /sticker antes, site usa /stricker)
    "/suco-brazil",
    "/equipe",           # ← NOVO
    "/declaracao-de-acessibilidade",  # ← NOVO
    "/flipbook",
    "/idyourself",
}


@dataclass
class Produto:
    nome: str
    url: str
    descricao: str | None
    imagens: list[str]
    categorias: list[str]
    referencia: str | None


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _url_bloqueada(url: str) -> bool:
    u = url.lower()
    return any(t in u for t in BLOCKED_TOKENS)


def _parece_produto(url: str) -> bool:
    """
    Produtos da Spot Gifts têm o padrão:
      /pt/catalogo/<familia>/<referencia>/
    São exatamente 4 segmentos após o domínio: pt, catalogo, <familia>, <referencia>
    """
    u = url.lower().split("?", 1)[0].rstrip("/")
    if not u.startswith("https://www.spotgifts.com.br/pt/catalogo/"):
        return False
    if _url_bloqueada(u):
        return False
    # Remove o prefixo e conta os segmentos restantes
    # /pt/catalogo/<familia>/<referencia>  → ["", "pt", "catalogo", "familia", "referencia"]
    parts = [p for p in u.replace("https://www.spotgifts.com.br", "").split("/") if p]
    # Deve ter exatamente 4 partes: pt, catalogo, familia, referencia
    return len(parts) == 4


async def run_scraper(output: str, delay_ms: int, max_scrolls: int, headless: bool) -> None:
    try:
        from playwright.async_api import async_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Playwright não está instalado. Rode:\n"
            "  pip install -r requirements.txt\n"
            "  python -m playwright install chromium\n"
            f"Erro original: {exc}"
        ) from exc

    start = time.perf_counter()
    produtos_urls: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()

        t0 = time.perf_counter()
        await page.goto(CATALOGO_URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(2500)
        print(f"[tempo] abertura inicial: {time.perf_counter() - t0:.2f}s")

        last_count = 0
        stable_rounds = 0

        for i in range(1, max_scrolls + 1):
            links = await page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href).filter(Boolean)",
            )
            before_filter = len(set(links))
            produtos_candidatos = {
                url.rstrip("/")
                for url in links
                if url.startswith("http") and _parece_produto(url)
            }
            produtos_urls.update(produtos_candidatos)

            print(
                f"[catalogo] scroll={i} links_brutos={before_filter} "
                f"produtos_pagina={len(produtos_candidatos)} total_acumulado={len(produtos_urls)}"
            )

            await page.mouse.wheel(0, 12000)
            await page.wait_for_timeout(delay_ms)

            if len(produtos_urls) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
            last_count = len(produtos_urls)

            if stable_rounds >= 3:
                print("[info] Catálogo estabilizou (sem novos produtos em 3 ciclos).")
                break

        if not produtos_urls:
            html = await page.content()
            with open("debug_catalogo.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("[aviso] Nenhum produto detectado. debug_catalogo.html salvo.")

        produtos: list[Produto] = []
        for idx, url in enumerate(sorted(produtos_urls), start=1):
            print(f"[produto] {idx}/{len(produtos_urls)} -> {url}")
            t_prod = time.perf_counter()
            p2 = await browser.new_page()
            try:
                await p2.goto(url, wait_until="domcontentloaded", timeout=60000)
                await p2.wait_for_timeout(1200)  # ← aumentado: JS do produto precisa de mais tempo

                # --- Nome ---
                # O site usa .product-name, h1.page-header, ou h1 genérico
                nome = ""
                for sel in [".product-name", "h1.page-header", ".product_title", "h1", "[itemprop='name']"]:
                    try:
                        nome = _clean(await p2.eval_on_selector(sel, "el => el ? el.textContent : ''"))
                        if nome:
                            break
                    except Exception:
                        continue

                # --- Descrição ---
                # O site renderiza a descrição em .product-description ou similar
                descricao = ""
                for sel in [
                    ".product-description",
                    ".product-short-description",
                    "[itemprop='description']",
                    ".woocommerce-product-details__short-description",
                    "meta[name='description']",
                    "meta[property='og:description']",
                ]:
                    try:
                        descricao = _clean(
                            await p2.eval_on_selector(
                                sel, "el => el ? (el.content || el.textContent || '') : ''"
                            )
                        )
                        if descricao:
                            break
                    except Exception:
                        continue

                # --- Referência (código do produto, ex: 22904) ---
                # Vem do último segmento da URL ou de .product-reference
                referencia = url.rstrip("/").split("/")[-1]  # fallback confiável
                for sel in [".product-reference", ".sku", "[itemprop='sku']", ".product_ref"]:
                    try:
                        ref_text = _clean(await p2.eval_on_selector(sel, "el => el ? el.textContent : ''"))
                        if ref_text:
                            referencia = ref_text
                            break
                    except Exception:
                        continue

                # --- Categoria (segundo-último segmento da URL é a família) ---
                # Ex: /pt/catalogo/sacos-de-compras-non-woven/22904/ → "sacos-de-compras-non-woven"
                url_parts = url.rstrip("/").split("/")
                categoria_url = url_parts[-2].replace("-", " ").title() if len(url_parts) >= 2 else ""
                categorias = [categoria_url] if categoria_url else []
                # Tenta enriquecer com breadcrumb se disponível
                try:
                    cats_breadcrumb = await p2.eval_on_selector_all(
                        "nav.breadcrumb a, .breadcrumb a, ol.breadcrumb li a",
                        "els => els.map(el => (el.textContent || '').trim()).filter(Boolean)",
                    )
                    cats_extra = sorted({
                        _clean(c) for c in cats_breadcrumb
                        if _clean(c).lower() not in {"home", "início", "catálogo", "catalogo", "spot"}
                    })
                    if cats_extra:
                        categorias = cats_extra
                except Exception:
                    pass

                # --- Imagens ---
                imagens = await p2.eval_on_selector_all(
                    "img[src], img[data-src], meta[property='og:image']",
                    """els => els
                        .map(el => el.content || el.dataset.largeSrc || el.dataset.src || el.src)
                        .filter(src => src && src.startsWith('http') && !src.includes('loading.gif') && !src.includes('favicon'))
                    """,
                )
                imagens = sorted({urljoin(url, i.strip()) for i in imagens if i and i.strip()})

                # Valida: nome é obrigatório; descrição e imagem são desejáveis mas não bloqueiam
                # (site pode exigir login para mostrar tudo — não descartamos por isso)
                if nome:
                    produtos.append(
                        Produto(
                            nome=nome,
                            url=url,
                            descricao=descricao or None,
                            imagens=imagens,
                            categorias=categorias,
                            referencia=referencia or None,
                        )
                    )
                    print(f"[ok] {time.perf_counter() - t_prod:.2f}s: {nome}")
                else:
                    print(f"[skip] sem nome após JS render: {url}")
            except Exception as exc:
                print(f"[erro] falha em {url}: {exc}")
            finally:
                await p2.close()

        with open(output, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in produtos], f, ensure_ascii=False, indent=2)

        print(f"\n[ok] produtos salvos: {len(produtos)} -> {output}")
        print(f"[tempo] execução total: {time.perf_counter() - start:.2f}s")
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper dinâmico Spot Gifts com Playwright")
    parser.add_argument("--output", default="produtos_spotgifts.json")
    parser.add_argument("--delay-ms", type=int, default=1500)
    parser.add_argument("--max-scrolls", type=int, default=60, help="988 produtos — aumente se necessário")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    import asyncio
    asyncio.run(run_scraper(
        output=args.output,
        delay_ms=args.delay_ms,
        max_scrolls=args.max_scrolls,
        headless=not args.headed,
    ))


if __name__ == "__main__":
    main()
