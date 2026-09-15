#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
descargar_examenes_dipujaen.py
--------------------------------
Descarga automáticamente los documentos "Examen y/o plantilla de respuestas"
(y variantes como "Plantilla de respuestas", "Examen") publicados en la
página de Ofertas de Empleo de la Diputación de Jaén:

  https://www.dipujaen.es/conoce-diputacion/areas-organismos-empresas/areaD/
  recursos-humanos/ofertas-de-empleo/

Cómo funciona:
  1. Descarga la página principal de "Ofertas de empleo".
  2. Extrae los enlaces "Ver detalles" de cada convocatoria (abiertas y
     cerradas), junto con el nombre del puesto.
  3. Entra en cada página de detalle y busca los enlaces a PDF cuyo texto
     visible contenga "examen" o "plantilla" (sin distinguir mayúsculas
     ni acentos), que es donde este organismo publica los exámenes y las
     plantillas de respuestas.
  4. Descarga esos PDF a una carpeta local, organizados en una subcarpeta
     por convocatoria.

Es seguro ejecutarlo varias veces: si un archivo ya existe no se vuelve a
descargar (así puedes programarlo, por ejemplo, para que corra cada
semana y solo baje lo nuevo).

Requisitos (una sola vez):
    pip install requests beautifulsoup4

Uso:
    python descargar_examenes_dipujaen.py
    python descargar_examenes_dipujaen.py --output-dir "C:/Users/tu_usuario/Documentos/examenes_dipujaen"
    python descargar_examenes_dipujaen.py --keywords examen,plantilla,resultado
"""

import argparse
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print(
        "Faltan dependencias. Instálalas con:\n"
        "    pip install requests beautifulsoup4\n"
    )
    sys.exit(1)

BASE_URL = "https://www.dipujaen.es"
LISTADO_URL = (
    "https://www.dipujaen.es/conoce-diputacion/areas-organismos-empresas/"
    "areaD/recursos-humanos/ofertas-de-empleo/"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

DEFAULT_KEYWORDS = ["examen", "plantilla"]


def quitar_acentos(texto: str) -> str:
    """Normaliza texto quitando acentos, para comparar sin importar tildes."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def texto_normalizado(texto: str) -> str:
    return quitar_acentos(texto or "").lower().strip()


def sanear_nombre(nombre: str) -> str:
    """Convierte un texto en un nombre de carpeta/archivo válido."""
    nombre = quitar_acentos(nombre)
    nombre = re.sub(r"[^\w\s.-]", "", nombre)
    nombre = re.sub(r"\s+", "_", nombre.strip())
    return nombre[:120] if nombre else "convocatoria"


def obtener_html(session: requests.Session, url: str) -> str | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [!] No se pudo cargar {url}: {e}")
        return None


def obtener_convocatorias(session: requests.Session) -> list[dict]:
    """Devuelve una lista de dicts: {'nombre': ..., 'detalle_url': ...}"""
    html = obtener_html(session, LISTADO_URL)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    convocatorias = []
    vistos = set()

    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        if "_detalles/index.html" not in href or "uid=" not in href:
            continue

        detalle_url = urljoin(BASE_URL, href)
        if detalle_url in vistos:
            continue
        vistos.add(detalle_url)

        # El nombre del puesto suele estar en la misma fila de la tabla:
        # buscamos el texto de la primera celda de la fila (<tr>) que
        # contiene este enlace.
        nombre = None
        fila = enlace.find_parent("tr")
        if fila:
            primera_celda = fila.find("td")
            if primera_celda and primera_celda.get_text(strip=True):
                nombre = primera_celda.get_text(strip=True)

        if not nombre:
            # Alternativa: usar el uid como nombre si no hay tabla legible
            nombre = detalle_url.split("uid=")[-1]

        convocatorias.append({"nombre": nombre, "detalle_url": detalle_url})

    return convocatorias


def buscar_pdfs_examen(
    session: requests.Session, detalle_url: str, keywords: list[str]
) -> list[dict]:
    """Busca en una página de detalle los enlaces a PDF cuyo texto visible
    contenga alguna de las palabras clave (examen, plantilla, ...)."""
    html = obtener_html(session, detalle_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    encontrados = []

    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        texto = texto_normalizado(enlace.get_text())

        if not any(kw in texto for kw in keywords):
            continue
        if not href.lower().endswith(".pdf"):
            continue

        pdf_url = urljoin(BASE_URL, href)
        encontrados.append({"texto": enlace.get_text(strip=True), "url": pdf_url})

    return encontrados


def descargar_pdf(session: requests.Session, url: str, destino: Path) -> bool:
    if destino.exists() and destino.stat().st_size > 0:
        return False  # ya lo teníamos, no hace falta bajarlo otra vez

    try:
        resp = session.get(url, headers=HEADERS, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [!] Error descargando {url}: {e}")
        return False

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(resp.content)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="examenes_dipujaen",
        help="Carpeta donde guardar los PDF descargados (por defecto: ./examenes_dipujaen)",
    )
    parser.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="Palabras clave (separadas por coma, sin acentos) que debe "
        "contener el texto del enlace para descargarlo. Por defecto: "
        f"{','.join(DEFAULT_KEYWORDS)}",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.6,
        help="Segundos de espera entre peticiones, para no saturar el "
        "servidor del organismo (por defecto: 0.6)",
    )
    args = parser.parse_args()

    keywords = [texto_normalizado(k) for k in args.keywords.split(",") if k.strip()]
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    print(f"Cargando listado de convocatorias desde:\n  {LISTADO_URL}\n")
    convocatorias = obtener_convocatorias(session)

    if not convocatorias:
        print(
            "No se encontraron convocatorias. Es posible que la web haya "
            "cambiado de estructura, o que no haya conexión a internet."
        )
        sys.exit(1)

    print(f"Encontradas {len(convocatorias)} convocatorias. Revisando cada una...\n")

    total_nuevos = 0
    total_encontrados = 0
    sin_examen = []

    for i, conv in enumerate(convocatorias, start=1):
        nombre = conv["nombre"]
        print(f"[{i}/{len(convocatorias)}] {nombre}")

        pdfs = buscar_pdfs_examen(session, conv["detalle_url"], keywords)
        time.sleep(args.delay)

        if not pdfs:
            sin_examen.append(nombre)
            continue

        carpeta_conv = output_dir / sanear_nombre(nombre)

        for pdf in pdfs:
            total_encontrados += 1
            nombre_archivo = pdf["url"].rsplit("/", 1)[-1]
            destino = carpeta_conv / nombre_archivo

            es_nuevo = descargar_pdf(session, pdf["url"], destino)
            time.sleep(args.delay)

            if es_nuevo:
                total_nuevos += 1
                print(f"    -> descargado: {destino}")
            else:
                print(f"    -> ya existía: {destino.name}")

    print("\n" + "=" * 60)
    print(f"Convocatorias revisadas: {len(convocatorias)}")
    print(f"Documentos de examen/plantilla encontrados: {total_encontrados}")
    print(f"Descargados ahora (nuevos): {total_nuevos}")
    print(f"Convocatorias sin documento de examen todavía: {len(sin_examen)}")
    print(f"\nArchivos guardados en: {output_dir.resolve()}")

    if sin_examen:
        log_path = output_dir / "convocatorias_sin_examen.txt"
        log_path.write_text("\n".join(sin_examen), encoding="utf-8")
        print(f"(Lista de convocatorias sin examen todavía guardada en {log_path.name})")


if __name__ == "__main__":
    main()
