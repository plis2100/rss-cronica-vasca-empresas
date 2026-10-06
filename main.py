import re
import html
import hashlib
import datetime as dt
import xml.etree.ElementTree as ET

from email.utils import format_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURACIÓN
# ============================================================

BASE_URL = "https://cronicavasca.elespanol.com"

SECTION_URL = (
    "https://cronicavasca.elespanol.com/empresas/"
)

OUTPUT_FILE = "feed.xml"

# Revisamos varias páginas para mantener histórico
MAX_PAGES = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


# ============================================================
# LIMPIEZA
# ============================================================

def clean_text(value):

    if not value:
        return ""

    value = html.unescape(str(value))

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def clean_url(url):

    if not url:
        return ""

    parts = urlsplit(url)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            "",
            "",
        )
    )


# ============================================================
# DESCARGAR
# ============================================================

def download(url):

    print(
        f"Descargando: {url}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=45
    )

    response.raise_for_status()

    return response.text


# ============================================================
# VALIDAR ARTÍCULO
# ============================================================

def valid_article_url(url):

    if not url:
        return False

    url = clean_url(url)

    if not url.startswith(BASE_URL):
        return False

    # No queremos la propia portada Empresas
    if url.rstrip("/") == SECTION_URL.rstrip("/"):
        return False

    # Excluir paginación
    if re.fullmatch(
        r"https://cronicavasca\.elespanol\.com/"
        r"empresas/\d+/?",
        url
    ):
        return False

    # Excluir recursos
    extensions = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".css",
        ".js",
        ".xml",
    )

    if url.lower().endswith(
        extensions
    ):
        return False

    return True


# ============================================================
# FECHA
# ============================================================

def parse_date(value):

    if not value:
        return None

    value = clean_text(value)

    # ISO 8601
    try:

        iso = value.replace(
            "Z",
            "+00:00"
        )

        result = dt.datetime.fromisoformat(
            iso
        )

        if result.tzinfo is None:

            result = result.replace(
                tzinfo=dt.timezone.utc
            )

        return result

    except Exception:
        pass

    # Formato:
    # 06/10/2026 16:05h

    match = re.search(
        r"(\d{1,2})/"
        r"(\d{1,2})/"
        r"(\d{4})"
        r"(?:\s+"
        r"(\d{1,2}):"
        r"(\d{2}))?",
        value
    )

    if match:

        try:

            day = int(
                match.group(1)
            )

            month = int(
                match.group(2)
            )

            year = int(
                match.group(3)
            )

            hour = int(
                match.group(4) or 0
            )

            minute = int(
                match.group(5) or 0
            )

            return dt.datetime(
                year,
                month,
                day,
                hour,
                minute,
                tzinfo=dt.timezone.utc
            )

        except Exception:
            pass

    return None


def extract_date(soup):

    # META
    selectors = [
        {
            "property":
            "article:published_time"
        },
        {
            "name":
            "article:published_time"
        },
        {
            "property":
            "og:published_time"
        },
        {
            "name":
            "date"
        },
        {
            "name":
            "pubdate"
        },
    ]

    for attrs in selectors:

        tag = soup.find(
            "meta",
            attrs=attrs
        )

        if (
            tag
            and tag.get("content")
        ):

            result = parse_date(
                tag["content"]
            )

            if result:
                return result

    # TIME
    for tag in soup.find_all(
        "time"
    ):

        value = (
            tag.get("datetime")
            or tag.get_text(
                " ",
                strip=True
            )
        )

        result = parse_date(
            value
        )

        if result:
            return result

    # JSON-LD
    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        text = script.string

        if not text:
            continue

        match = re.search(
            r'"datePublished"\s*:\s*"([^"]+)"',
            text
        )

        if match:

            result = parse_date(
                match.group(1)
            )

            if result:
                return result

    return None


# ============================================================
# TITULAR
# ============================================================

def extract_title(
    soup,
    fallback=""
):

    h1 = soup.find("h1")

    if h1:

        title = clean_text(
            h1.get_text(
                " ",
                strip=True
            )
        )

        if title:
            return title

    tag = soup.find(
        "meta",
        attrs={
            "property": "og:title"
        }
    )

    if (
        tag
        and tag.get("content")
    ):

        title = clean_text(
            tag["content"]
        )

        if title:
            return title

    return clean_text(
        fallback
    )


# ============================================================
# DESCRIPCIÓN
# ============================================================

def extract_description(soup):

    for attrs in [
        {
            "name":
            "description"
        },
        {
            "property":
            "og:description"
        },
    ]:

        tag = soup.find(
            "meta",
            attrs=attrs
        )

        if (
            tag
            and tag.get("content")
        ):

            return clean_text(
                tag["content"]
            )

    return ""


# ============================================================
# ENCONTRAR ARTÍCULOS EN EMPRESAS
# ============================================================

def get_article_links():

    links = {}

    for page in range(
        1,
        MAX_PAGES + 1
    ):

        if page == 1:

            page_url = SECTION_URL

        else:

            page_url = (
                f"{SECTION_URL}{page}/"
            )

        try:

            source = download(
                page_url
            )

        except Exception as exc:

            print(
                f"ERROR descargando "
                f"{page_url}: {exc}"
            )

            continue

        soup = BeautifulSoup(
            source,
            "lxml"
        )

        # Los titulares de la sección aparecen
        # principalmente dentro de H2.
        for heading in soup.find_all(
            ["h2", "h3"]
        ):

            link_tag = heading.find(
                "a",
                href=True
            )

            if not link_tag:
                continue

            url = urljoin(
                BASE_URL,
                link_tag["href"]
            )

            url = clean_url(
                url
            )

            if not valid_article_url(
                url
            ):
                continue

            title = clean_text(
                link_tag.get_text(
                    " ",
                    strip=True
                )
            )

            if not title:
                continue

            links[url] = title

    print(
        f"Artículos encontrados: "
        f"{len(links)}"
    )

    return links


# ============================================================
# LEER ARTÍCULO
# ============================================================

def get_article(
    url,
    fallback_title
):

    try:

        source = download(
            url
        )

    except Exception as exc:

        print(
            f"ERROR artículo "
            f"{url}: {exc}"
        )

        return None

    soup = BeautifulSoup(
        source,
        "lxml"
    )

    title = extract_title(
        soup,
        fallback_title
    )

    if not title:
        return None

    published = extract_date(
        soup
    )

    description = extract_description(
        soup
    )

    return {
        "title": title,
        "url": url,
        "date": published,
        "description": description,
    }


# ============================================================
# RECOPILAR
# ============================================================

def collect_articles():

    links = get_article_links()

    articles = []

    seen = set()

    for (
        url,
        fallback_title
    ) in links.items():

        article = get_article(
            url,
            fallback_title
        )

        if not article:
            continue

        guid = hashlib.sha256(
            url.encode(
                "utf-8"
            )
        ).hexdigest()

        if guid in seen:
            continue

        seen.add(
            guid
        )

        article["guid"] = guid

        articles.append(
            article
        )

    articles.sort(
        key=lambda x: (
            x["date"]
            or dt.datetime(
                1970,
                1,
                1,
                tzinfo=dt.timezone.utc
            )
        ),
        reverse=True
    )

    return articles


# ============================================================
# CREAR RSS
# ============================================================

def create_rss(articles):

    rss = ET.Element(
        "rss",
        {
            "version": "2.0"
        }
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = (
        "Crónica Vasca - Empresas"
    )

    ET.SubElement(
        channel,
        "link"
    ).text = SECTION_URL

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "Noticias de la sección "
        "Empresas de Crónica Vasca"
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "es"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        dt.datetime.now(
            dt.timezone.utc
        )
    )

    for article in articles:

        item = ET.SubElement(
            channel,
            "item"
        )

        # ====================================================
        # SOLO EL TITULAR ORIGINAL
        # ====================================================

        ET.SubElement(
            item,
            "title"
        ).text = article["title"]

        # ENLACE ORIGINAL
        ET.SubElement(
            item,
            "link"
        ).text = article["url"]

        # GUID
        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink":
                "false"
            }
        )

        guid.text = article["guid"]

        # FECHA INTERNA PARA FEEDLY
        if article["date"]:

            date_value = article["date"]

            if (
                date_value.tzinfo
                is None
            ):

                date_value = (
                    date_value.replace(
                        tzinfo=dt.timezone.utc
                    )
                )

            ET.SubElement(
                item,
                "pubDate"
            ).text = format_datetime(
                date_value
            )

        # DESCRIPCIÓN
        if article["description"]:

            ET.SubElement(
                item,
                "description"
            ).text = html.escape(
                article["description"]
            )

    tree = ET.ElementTree(
        rss
    )

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 60
    )

    print(
        "CRÓNICA VASCA - EMPRESAS"
    )

    print(
        "=" * 60
    )

    articles = collect_articles()

    print(
        f"\nArtículos obtenidos: "
        f"{len(articles)}"
    )

    print(
        "\nÚltimos titulares:"
    )

    for article in articles[:20]:

        print(
            "- "
            + article["title"]
        )

    if not articles:

        raise RuntimeError(
            "No se encontraron artículos."
        )

    create_rss(
        articles
    )

    print(
        "\nRSS creada correctamente:"
    )

    print(
        OUTPUT_FILE
    )


if __name__ == "__main__":
    main()
