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
import json
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET

BASE_URL = "https://www.spotgifts.com.br/pt/"
CATALOGO_URL = "https://www.spotgifts.com.br/pt/catalogo/?catalogo=1"
SITEMAP_URL = urljoin(BASE_URL, "sitemap.xml")
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
        """Descobre URLs reais de produtos começando pelo catálogo."""
        print(f"[info] Iniciando descoberta a partir do catálogo: {CATALOGO_URL}")
        urls = self._listar_urls_catalogo()
        print(f"[info] URLs de produto encontradas no catálogo: {len(urls)}")
        return urls

    def _listar_urls_produtos_sitemap(self) -> list[str]:
        resp = self._get(SITEMAP_URL)
        root = ET.fromstring(resp.content)

        ns_match = re.match(r"\{(.+)\}", root.tag)
        ns = {"sm": ns_match.group(1)} if ns_match else {}

        sitemap_tags = root.findall("sm:sitemap", ns) if ns else root.findall("sitemap")

        urls: set[str] = set()

        # Se for sitemapindex, varre sitemaps filhos.
        if sitemap_tags:
            loc_tag = "sm:loc" if ns else "loc"
            for sitemap in sitemap_tags:
                loc = sitemap.findtext(loc_tag, default="", namespaces=ns)
                if not loc:
                    continue
                if "product" in loc.lower() or "produto" in loc.lower() or "post" in loc.lower():
                    urls.update(self._extrair_urls_de_sitemap(loc))
            # fallback: se nada encontrado, varrer todos os sitemaps filhos
            if not urls:
                for sitemap in sitemap_tags:
                    loc = sitemap.findtext(loc_tag, default="", namespaces=ns)
                    if loc:
                        urls.update(self._extrair_urls_de_sitemap(loc))
        else:
            urls.update(self._extrair_urls_de_sitemap(SITEMAP_URL))

        return sorted(u for u in urls if self._parece_url_produto(u))

    def _extrair_urls_de_sitemap(self, sitemap_url: str) -> set[str]:
        resp = self._get(sitemap_url)
        root = ET.fromstring(resp.content)
        ns_match = re.match(r"\{(.+)\}", root.tag)
        ns = {"sm": ns_match.group(1)} if ns_match else {}

        locs: set[str] = set()
        if root.tag.endswith("urlset"):
            url_tags = root.findall("sm:url", ns) if ns else root.findall("url")
            loc_tag = "sm:loc" if ns else "loc"
            for url_node in url_tags:
                loc = url_node.findtext(loc_tag, default="", namespaces=ns)
                if loc:
                    locs.add(loc.strip())
        elif root.tag.endswith("sitemapindex"):
            sitemaps = root.findall("sm:sitemap", ns) if ns else root.findall("sitemap")
            loc_tag = "sm:loc" if ns else "loc"
            for sm in sitemaps:
                loc = sm.findtext(loc_tag, default="", namespaces=ns)
                if loc:
                    locs.update(self._extrair_urls_de_sitemap(loc.strip()))

        return locs

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
        ]
        return any(token in lower_url for token in blocked_tokens)

    def _listar_urls_catalogo(self) -> list[str]:
        """Navega catálogo e paginação, coletando apenas produtos reais."""
        to_visit = deque([CATALOGO_URL])
        seen_pages: set[str] = set()
        product_urls: set[str] = set()
        filtered_urls = 0
        category_hints = ("categoria", "category", "colecao", "catalog", "produtos", "loja", "shop", "catalogo")

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
            for a in soup.select("a[href]"):
                href = a.get("href", "").strip()
                if not href:
                    continue
                url = urljoin(BASE_URL, href)
                url_lower = url.lower()
                if self._url_bloqueada(url_lower):
                    filtered_urls += 1
                    continue
                if self._parece_url_produto(url):
                    product_urls.add(url.rstrip("/"))
                elif "/pt/" in url and any(k in url_lower for k in category_hints):
                    if url not in seen_pages and url not in to_visit:
                        to_visit.append(url)
                elif any(k in url_lower for k in ("?paged=", "&paged=", "/page/")):
                    if url not in seen_pages and url not in to_visit:
                        to_visit.append(url)

            # Busca URLs em scripts (sites com carregamento dinâmico/JS).
            for script in soup.select("script"):
                raw = script.string or script.get_text(" ", strip=False)
                if not raw:
                    continue
                for match in re.findall(r'https://www\\.spotgifts\\.com\\.br/pt/[a-zA-Z0-9\\-_/]+', raw):
                    if self._url_bloqueada(match.lower()):
                        filtered_urls += 1
                        continue
                    if self._parece_url_produto(match):
                        product_urls.add(match.rstrip("/"))
                for match in re.findall(r'"/pt/[a-zA-Z0-9\\-_/]+"' , raw):
                    url = urljoin(BASE_URL, match.strip('"'))
                    if self._url_bloqueada(url.lower()):
                        filtered_urls += 1
                        continue
                    if self._parece_url_produto(url):
                        product_urls.add(url.rstrip("/"))

            time.sleep(self.delay)

        print(f"[info] URLs ignoradas por filtro institucional: {filtered_urls}")
        return sorted(product_urls)

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
