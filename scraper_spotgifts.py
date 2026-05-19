#!/usr/bin/env python3
"""Scraper de produtos da Spot Gifts (https://www.spotgifts.com.br/pt/).

Coleta:
- nome
- descrição
- imagens
- categorias

Uso:
    python scraper_spotgifts.py --output produtos_spotgifts.json
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.spotgifts.com.br/pt/"
CATALOGO_URL = "https://www.spotgifts.com.br/pt/catalogo/?catalogo=1"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}


@dataclass
class Produto:
    url: str
    nome: str | None
    descricao: str | None
    imagens: list[str]
    categorias: list[str]
    referencia: str | None


class SpotGiftsScraper:
    def __init__(self, delay: float = 0.2, timeout: int = 25) -> None:
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, url: str) -> requests.Response:
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp

    def listar_urls_produtos(self) -> list[str]:
        """Descobre URLs reais de produtos começando exclusivamente pelo catálogo."""
        print(f"[info] Iniciando descoberta a partir do catálogo: {CATALOGO_URL}")
        urls = self._listar_urls_catalogo()
        print(f"[info] URLs de produto encontradas no catálogo: {len(urls)}")
        return urls

    def _parece_url_produto(self, url: str) -> bool:
        u = url.lower()
        if self._url_bloqueada(u):
            return False
        if any(
            token in u
            for token in ["/pt/produto", "/pt/product", "/produto/", "/product/", "?product="]
        ):
            return True
        path = u.split("?", 1)[0].rstrip("/")
        if not path.startswith("https://www.spotgifts.com.br/pt/"):
            return False
        # Muitos catálogos usam slug direto no /pt/<slug>, sem /product/.
        blocked = ("/pt/", "/pt/categoria", "/pt/category", "/pt/contact", "/pt/sobre", "/pt/home", "/pt/catalogo")
        if path in blocked:
            return False
        pieces = [p for p in path.replace("https://www.spotgifts.com.br", "").split("/") if p]
        return len(pieces) >= 2 and pieces[0] == "pt" and pieces[1] not in {
            "categoria",
            "category",
            "catalogo",
            "catalog",
            "contactos",
            "contatos",
            "institucional",
        }

    def _url_bloqueada(self, lower_url: str) -> bool:
        blocked_tokens = [
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
        ]
        return any(token in lower_url for token in blocked_tokens)

    def _listar_urls_catalogo(self) -> list[str]:
        """Navega catálogo e paginação, coletando apenas produtos reais."""
        to_visit = deque([CATALOGO_URL])
        seen_pages: set[str] = set()
        product_urls: set[str] = set()
        filtered_urls = 0
        total_raw_links = 0

        while to_visit:
            page_url = to_visit.popleft()
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            print(f"[crawl] Processando página de catálogo/listagem: {page_url}")

            try:
                resp = self._get(page_url)
            except Exception:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            links = self._coletar_links_relevantes_da_pagina(soup, page_url)
            print(f"[debug] Links encontrados na página antes do filtro: {len(links)}")
            total_raw_links += len(links)

            for url in links:
                url_lower = url.lower()
                if self._url_bloqueada(url_lower):
                    filtered_urls += 1
                    continue
                if self._parece_url_produto(url):
                    product_urls.add(url.rstrip("/"))
                elif any(k in url_lower for k in ("?paged=", "&paged=", "/page/")):
                    if url not in seen_pages and url not in to_visit:
                        to_visit.append(url)

            ajax_urls = self._detectar_endpoints_ajax(soup, page_url)
            if ajax_urls:
                print(f"[debug] Possíveis endpoints AJAX/API detectados: {len(ajax_urls)}")
                for endpoint in ajax_urls:
                    print(f"[debug] Endpoint: {endpoint}")

            time.sleep(self.delay)

        if not product_urls:
            with open("debug_catalogo.html", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("[aviso] Nenhum produto encontrado no HTML. Arquivo debug_catalogo.html salvo.")

        print(f"[info] Total de links brutos encontrados no catálogo: {total_raw_links}")
        print(f"[info] URLs ignoradas por filtro institucional: {filtered_urls}")
        return sorted(product_urls)

    def _coletar_links_relevantes_da_pagina(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()

        # foco na grade/listagem de catálogo
        selectors = [
            ".products a[href]",
            ".product a[href]",
            ".catalogo a[href]",
            ".grid a[href]",
            "main a[href]",
        ]
        for sel in selectors:
            for a in soup.select(sel):
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                url = urljoin(BASE_URL, href).rstrip("/")
                if "/pt/" not in url.lower():
                    continue
                if url not in seen:
                    seen.add(url)
                    links.append(url)

        # inclui links vindos de scripts (quando catálogo é renderizado por JS)
        script_text = " ".join(s.get_text(" ", strip=False) for s in soup.select("script"))
        script_text = html.unescape(script_text)
        for match in re.findall(r"https://www\.spotgifts\.com\.br/pt/[a-zA-Z0-9\-_/?.=&]+", script_text):
            url = match.rstrip("/")
            if url not in seen:
                seen.add(url)
                links.append(url)
        for match in re.findall(r"\"(/pt/[a-zA-Z0-9\-_/?.=&]+)\"", script_text):
            url = urljoin(BASE_URL, match).rstrip("/")
            if url not in seen:
                seen.add(url)
                links.append(url)
        return links

    def _detectar_endpoints_ajax(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        candidates: set[str] = set()
        for script in soup.select("script"):
            raw = script.get_text(" ", strip=False) or ""
            for m in re.findall(r"https?://[^\s\"']+", raw):
                ml = m.lower()
                if any(k in ml for k in ("admin-ajax", "/wp-json/", "/api/", "graphql")):
                    candidates.add(m.strip().rstrip(",;"))
            for m in re.findall(r"['\"](/[^'\"]*(?:admin-ajax|wp-json|api)[^'\"]*)['\"]", raw):
                candidates.add(urljoin(page_url, m))
        return sorted(candidates)

    def extrair_produto(self, url: str) -> Produto:
        resp = self._get(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        nome = self._extrair_nome(soup)
        descricao = self._extrair_descricao(soup)
        imagens = self._extrair_imagens(soup, url)
        categorias = self._extrair_categorias(soup)
        referencia = self._extrair_referencia(soup)

        return Produto(
            url=url,
            nome=nome,
            descricao=descricao,
            imagens=imagens,
            categorias=categorias,
            referencia=referencia,
        )

    def _extrair_nome(self, soup: BeautifulSoup) -> str | None:
        candidates = [
            "h1.product_title",
            "h1.entry-title",
            "h1",
            '[itemprop="name"]',
            "meta[property='og:title']",
        ]
        for sel in candidates:
            node = soup.select_one(sel)
            if not node:
                continue
            if node.name == "meta":
                content = node.get("content")
                if content:
                    return self._clean(content)
            text = node.get_text(" ", strip=True)
            if text:
                return self._clean(text)
        return None

    def _extrair_descricao(self, soup: BeautifulSoup) -> str | None:
        selectors = [
            "div.product-description",
            "div.woocommerce-product-details__short-description",
            "div#tab-description",
            '[itemprop="description"]',
            "meta[name='description']",
            "meta[property='og:description']",
        ]
        for sel in selectors:
            node = soup.select_one(sel)
            if not node:
                continue
            if node.name == "meta":
                content = node.get("content")
                if content:
                    return self._clean(content)
            text = node.get_text(" ", strip=True)
            if text:
                return self._clean(text)
        return None

    def _extrair_imagens(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        selectors = [
            "figure.woocommerce-product-gallery__wrapper img",
            "div.product-gallery img",
            '[itemprop="image"]',
            "meta[property='og:image']",
        ]

        for sel in selectors:
            for node in soup.select(sel):
                if node.name == "meta":
                    src = node.get("content", "")
                else:
                    src = node.get("data-large_image") or node.get("data-src") or node.get("src") or ""
                if not src:
                    continue
                src = urljoin(page_url, src.strip())
                if src and src not in seen:
                    seen.add(src)
                    found.append(src)

        return found

    def _extrair_categorias(self, soup: BeautifulSoup) -> list[str]:
        categorias: list[str] = []
        seen: set[str] = set()

        for node in soup.select(".posted_in a, .product_meta .sku_wrapper + span a, nav.woocommerce-breadcrumb a"):
            text = self._clean(node.get_text(" ", strip=True))
            if text and text.lower() not in {"início", "home"} and text not in seen:
                seen.add(text)
                categorias.append(text)

        ldjson_nodes = soup.select("script[type='application/ld+json']")
        for node in ldjson_nodes:
            raw = (node.string or "").strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            for cat in self._coletar_categorias_jsonld(data):
                if cat not in seen:
                    seen.add(cat)
                    categorias.append(cat)

        return categorias

    def _coletar_categorias_jsonld(self, data: object) -> Iterable[str]:
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() in {"category", "categories"} and isinstance(value, str):
                    clean = self._clean(value)
                    if clean:
                        yield clean
                else:
                    yield from self._coletar_categorias_jsonld(value)
        elif isinstance(data, list):
            for item in data:
                yield from self._coletar_categorias_jsonld(item)

    def _extrair_referencia(self, soup: BeautifulSoup) -> str | None:
        selectors = [
            ".sku",
            "[itemprop='sku']",
            ".product-reference",
            ".product_ref",
        ]
        for sel in selectors:
            node = soup.select_one(sel)
            if node:
                text = self._clean(node.get_text(" ", strip=True))
                if text:
                    return text

        text_full = self._clean(soup.get_text(" ", strip=True))
        m = re.search(r"(?:refer[eê]ncia|ref\\.?|c[oó]digo|sku)\\s*[:#-]\\s*([A-Z0-9\\-_.]+)", text_full, re.I)
        if m:
            return m.group(1).strip()
        return None

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper de produtos da Spot Gifts")
    parser.add_argument("--output", default="produtos_spotgifts.json", help="Arquivo JSON de saída")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay entre requests")
    parser.add_argument("--limit", type=int, default=0, help="Limita quantidade de produtos (0 = sem limite)")
    parser.add_argument("--resume", action="store_true", help="Reaproveita URLs já processadas do arquivo de saída")
    args = parser.parse_args()

    scraper = SpotGiftsScraper(delay=args.delay)
    urls = scraper.listar_urls_produtos()
    print(f"[info] URLs de produtos encontradas: {len(urls)}")

    produtos: list[Produto] = []
    processadas: set[str] = set()
    if args.resume:
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                existentes = json.load(f)
            for item in existentes:
                if isinstance(item, dict) and item.get("url"):
                    processadas.add(item["url"])
                    produtos.append(
                        Produto(
                            url=item.get("url"),
                            nome=item.get("nome"),
                            descricao=item.get("descricao"),
                            imagens=item.get("imagens") or [],
                            categorias=item.get("categorias") or [],
                            referencia=item.get("referencia"),
                        )
                    )
            print(f"[info] Modo resume: {len(processadas)} produtos já existentes em {args.output}")
        except FileNotFoundError:
            pass
    if args.limit > 0:
        urls = urls[: args.limit]

    for i, url in enumerate(urls, start=1):
        if url in processadas:
            print(f"[{i}/{len(urls)}] SKIP (resume): {url}")
            continue
        try:
            print(f"[produto] Extraindo: {url}")
            produto = scraper.extrair_produto(url)
            if not produto.descricao:
                print(f"[{i}/{len(urls)}] SKIP sem descrição: {url}")
                continue
            produtos.append(produto)
            print(f"[{i}/{len(urls)}] OK: {produto.nome or url}")
        except Exception as exc:
            print(f"[{i}/{len(urls)}] ERRO {url}: {exc}")
        time.sleep(args.delay)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in produtos], f, ensure_ascii=False, indent=2)

    print(f"[ok] Produtos extraídos: {len(produtos)}")
    print(f"[ok] {len(produtos)} produtos salvos em {args.output}")


if __name__ == "__main__":
    main()
