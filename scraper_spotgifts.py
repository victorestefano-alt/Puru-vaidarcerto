#!/usr/bin/env python3
"""Scraper Playwright para catálogo Spot Gifts.

Renderiza JavaScript para extrair produtos do catálogo dinâmico.
"""

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
BLOCKED_TOKENS = {
    "/clientes",
    "/valores",
    "/contact",
    "/contato",
    "/sobre",
    "/blog",
    "/institucional",
    "/politica",
    "/termos",
    "/privacidade",
    "/faq",
    "/ferramentas-de-marketing",
    "/historia",
    "/noticias",
    "/perguntas-frequentes",
    "/personalizacao",
    "/sticker",
    "/suco-brazil",
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
    u = url.lower().split("?", 1)[0].rstrip("/")
    if not u.startswith("https://www.spotgifts.com.br/pt/"):
        return False
    if _url_bloqueada(u):
        return False
    if any(k in u for k in ["/produto", "/product"]):
        return True
    parts = [p for p in u.replace("https://www.spotgifts.com.br", "").split("/") if p]
    if len(parts) < 2 or parts[0] != "pt":
        return False
    return parts[1] not in {"catalogo", "categoria", "category", "home"}


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
            if _url_bloqueada(url):
                continue
            print(f"[produto] {idx}/{len(produtos_urls)} -> {url}")
            t_prod = time.perf_counter()
            p2 = await browser.new_page()
            try:
                await p2.goto(url, wait_until="domcontentloaded", timeout=60000)
                await p2.wait_for_timeout(800)

                nome = _clean(
                    await p2.eval_on_selector(
                        "h1, .product_title, [itemprop='name']",
                        "el => el ? el.textContent : ''",
                    )
                )
                descricao = _clean(
                    await p2.eval_on_selector(
                        "[itemprop='description'], .product-description, .woocommerce-product-details__short-description, meta[name='description'], meta[property='og:description']",
                        "el => el ? (el.content || el.textContent || '') : ''",
                    )
                )

                imagens = await p2.eval_on_selector_all(
                    "img, meta[property='og:image']",
                    "els => els.map(el => el.content || el.dataset.large_image || el.dataset.src || el.src).filter(Boolean)",
                )
                imagens = sorted({urljoin(url, i.strip()) for i in imagens if i and i.strip()})

                categorias = await p2.eval_on_selector_all(
                    ".posted_in a, nav.woocommerce-breadcrumb a",
                    "els => els.map(el => (el.textContent || '').trim()).filter(Boolean)",
                )
                categorias = sorted({_clean(c) for c in categorias if _clean(c).lower() not in {"home", "início"}})

                referencia = _clean(
                    await p2.eval_on_selector(
                        ".sku, [itemprop='sku'], .product-reference, .product_ref",
                        "el => el ? el.textContent : ''",
                    )
                ) or None

                if nome and descricao and imagens and _parece_produto(url):
                    produtos.append(
                        Produto(
                            nome=nome,
                            url=url,
                            descricao=descricao,
                            imagens=imagens,
                            categorias=categorias,
                            referencia=referencia,
                        )
                    )
                    print(f"[ok] extraído em {time.perf_counter() - t_prod:.2f}s: {nome}")
                else:
                    print("[skip] produto incompleto (nome/descricao/imagem/url)")
            except Exception as exc:
                print(f"[erro] falha em {url}: {exc}")
            finally:
                await p2.close()

        with open(output, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in produtos], f, ensure_ascii=False, indent=2)

        print(f"[ok] produtos válidos salvos: {len(produtos)} -> {output}")
        print(f"[tempo] execução total: {time.perf_counter() - start:.2f}s")
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper dinâmico Spot Gifts com Playwright")
    parser.add_argument("--output", default="produtos_spotgifts.json")
    parser.add_argument("--delay-ms", type=int, default=1500, help="Aguardar entre ciclos de scroll")
    parser.add_argument("--max-scrolls", type=int, default=30, help="Máximo de ciclos de scroll/paginação")
    parser.add_argument("--headed", action="store_true", help="Executa com browser visível")
    args = parser.parse_args()

    import asyncio

    asyncio.run(
        run_scraper(
            output=args.output,
            delay_ms=args.delay_ms,
            max_scrolls=args.max_scrolls,
            headless=not args.headed,
        )
    )


if __name__ == "__main__":
    main()
