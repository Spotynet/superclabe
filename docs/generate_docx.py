#!/usr/bin/env python3
"""Genera DOCUMENTACION-SISTEMA-COMPLETA.docx con logo, TOC y paginación."""
from __future__ import annotations

import os
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn, nsmap
from docx.shared import Cm, Inches, Pt, RGBColor, Twips
from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "frontend" / "assets" / "logo-super-clabe.jpg"
OUT = Path(__file__).resolve().parent / "DOCUMENTACION-SISTEMA-COMPLETA.docx"

BRAND = RGBColor(0x2A, 0x8D, 0x92)
DEEP = RGBColor(0x0E, 0x3B, 0x43)
MUTED = RGBColor(0x5A, 0x6B, 0x6C)
ACCENT = RGBColor(0x64, 0xC4, 0xBC)


def set_run_font(run, size=11, bold=False, color=None, name="Calibri"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def add_page_break(doc):
    doc.add_page_break()


def set_cell_shading(cell, hex_color: str):
    tc = cell._tePr if hasattr(cell, "_tePr") else cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def shade_header_row(row, hex_color="2A8D92"):
    for cell in row.cells:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), hex_color)
        shd.set(qn("w:val"), "clear")
        tcPr.append(shd)
        for p in cell.paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                r.bold = True


def add_heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for r in h.runs:
        if level == 1:
            set_run_font(r, 18, True, DEEP)
        elif level == 2:
            set_run_font(r, 14, True, BRAND)
        else:
            set_run_font(r, 12, True, DEEP)
    return h


def add_p(doc, text, size=11, bold=False, color=None, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=8):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
    r = p.add_run(text)
    set_run_font(r, size, bold, color or DEEP)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.clear()
    r = p.add_run(text)
    set_run_font(r, 11, False, DEEP)
    p.paragraph_format.left_indent = Cm(0.75 + level * 0.5)
    p.paragraph_format.space_after = Pt(4)
    return p


def add_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table.rows[0]
    for i, h in enumerate(headers):
        cell = hdr.cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        r = p.add_run(h)
        set_run_font(r, 10, True, RGBColor(0xFF, 0xFF, 0xFF))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    shade_header_row(hdr)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = table.rows[ri + 1].cells[ci]
            cell.text = ""
            p = cell.paragraphs[0]
            r = p.add_run(str(val))
            set_run_font(r, 9, False, DEEP)
            if ri % 2 == 1:
                tcPr = cell._tc.get_or_add_tcPr()
                shd = OxmlElement("w:shd")
                shd.set(qn("w:fill"), "F0F7F7")
                shd.set(qn("w:val"), "clear")
                tcPr.append(shd)
    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return table


def add_note(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    p.paragraph_format.left_indent = Cm(0.4)
    r = p.add_run("Nota: ")
    set_run_font(r, 10, True, BRAND)
    r2 = p.add_run(text)
    set_run_font(r2, 10, False, MUTED)
    return p


def add_flow_box(doc, title, steps):
    add_p(doc, title, size=11, bold=True, color=BRAND, align=WD_ALIGN_PARAGRAPH.LEFT, space_after=4)
    for i, step in enumerate(steps, 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.left_indent = Cm(0.5)
        r = p.add_run(f"{i}. ")
        set_run_font(r, 10, True, BRAND)
        r2 = p.add_run(step)
        set_run_font(r2, 10, False, DEEP)


def insert_toc(paragraph):
    """Inserta campo TOC actualizable en Word (clic derecho → Actualizar campos)."""
    run = paragraph.add_run()
    fldChar_begin = OxmlElement("w:fldChar")
    fldChar_begin.set(qn("w:fldCharType"), "begin")

    instrText = OxmlElement("w:instrText")
    instrText.set(qn("xml:space"), "preserve")
    instrText.text = ' TOC \\o "1-3" \\h \\z \\u '

    fldChar_separate = OxmlElement("w:fldChar")
    fldChar_separate.set(qn("w:fldCharType"), "separate")

    # Placeholder visible hasta actualizar
    run2 = paragraph.add_run(
        "Haga clic derecho aquí → Actualizar campos → Actualizar toda la tabla"
    )
    set_run_font(run2, 10, False, MUTED)

    fldChar_end = OxmlElement("w:fldChar")
    fldChar_end.set(qn("w:fldCharType"), "end")

    r_element = run._r
    r_element.append(fldChar_begin)
    r = paragraph.add_run()
    r._r.append(instrText)
    r2b = paragraph.add_run()
    r2b._r.append(fldChar_separate)
    # run2 already has placeholder text
    r3 = paragraph.add_run()
    r3._r.append(fldChar_end)


def add_page_number(paragraph):
    """Inserta PAGE / NUMPAGES en el párrafo del pie."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = paragraph.add_run("Página ")
    set_run_font(run, 9, False, MUTED)

    # PAGE
    run2 = paragraph.add_run()
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    run2._r.append(fld1)

    run3 = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    run3._r.append(instr)

    run4 = paragraph.add_run()
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "end")
    run4._r.append(fld2)

    run5 = paragraph.add_run(" de ")
    set_run_font(run5, 9, False, MUTED)

    # NUMPAGES
    run6 = paragraph.add_run()
    fld3 = OxmlElement("w:fldChar")
    fld3.set(qn("w:fldCharType"), "begin")
    run6._r.append(fld3)

    run7 = paragraph.add_run()
    instr2 = OxmlElement("w:instrText")
    instr2.set(qn("xml:space"), "preserve")
    instr2.text = " NUMPAGES "
    run7._r.append(instr2)

    run8 = paragraph.add_run()
    fld4 = OxmlElement("w:fldChar")
    fld4.set(qn("w:fldCharType"), "end")
    run8._r.append(fld4)

    for r in (run2, run3, run4, run6, run7, run8):
        set_run_font(r, 9, False, MUTED)


def setup_header_footer(doc, logo_path: Path):
    section = doc.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.header_distance = Cm(0.8)
    section.footer_distance = Cm(0.8)

    # Diferente primera página (portada sin header denso)
    section.different_first_page_header_footer = True

    # Header normal
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.clear()
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Tabla logo | título
    htable = header.add_table(1, 2, width=Cm(16.5))
    htable.autofit = True
    c0, c1 = htable.rows[0].cells
    c0.width = Cm(3.2)
    c1.width = Cm(13.3)

    p0 = c0.paragraphs[0]
    p0.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if logo_path.exists():
        # Preparar logo más angosto para header
        tmp = Path("/tmp/superclabe-logo-header.png")
        im = PILImage.open(logo_path).convert("RGBA")
        # Fondo blanco si hay transparencia
        bg = PILImage.new("RGBA", im.size, (255, 255, 255, 255))
        bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
        bg.convert("RGB").save(tmp, "PNG")
        run = p0.add_run()
        run.add_picture(str(tmp), width=Cm(2.6))

    p1 = c1.paragraphs[0]
    p1.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p1.add_run("Súper CLABE")
    set_run_font(r, 11, True, BRAND)
    r2 = p1.add_run("\nDocumentación Técnica y Operativa")
    set_run_font(r2, 8, False, MUTED)

    # Línea bajo header
    p_line = header.add_paragraph()
    p_line.paragraph_format.space_before = Pt(2)
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "2A8D92")
    pBdr.append(bottom)
    p_line._p.get_or_add_pPr().append(pBdr)

    # First page header (solo logo centrado pequeño o vacío con marca)
    fheader = section.first_page_header
    fheader.is_linked_to_previous = False
    fp = fheader.paragraphs[0]
    fp.clear()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Footer
    footer = section.footer
    footer.is_linked_to_previous = False
    fp_line = footer.paragraphs[0]
    fp_line.clear()
    # top border
    pBdr2 = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single")
    top.set(qn("w:sz"), "8")
    top.set(qn("w:space"), "4")
    top.set(qn("w:color"), "64C4BC")
    pBdr2.append(top)
    fp_line._p.get_or_add_pPr().append(pBdr2)

    # Fila: confidencial | página
    ft = footer.add_table(1, 2, width=Cm(16.5))
    left, right = ft.rows[0].cells
    lp = left.paragraphs[0]
    lp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    lr = lp.add_run("Confidencial — uso interno · PSPI · sin captación")
    set_run_font(lr, 8, False, MUTED)

    rp = right.paragraphs[0]
    add_page_number(rp)

    # First page footer
    ffooter = section.first_page_footer
    ffooter.is_linked_to_previous = False
    ffp = ffooter.paragraphs[0]
    ffp.clear()
    ffp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr = ffp.add_run("Súper CLABE · Agosto 2026 · v2.0")
    set_run_font(rr, 9, False, MUTED)


def build_cover(doc, logo_path: Path):
    for _ in range(2):
        doc.add_paragraph()

    if logo_path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        run.add_picture(str(logo_path), width=Cm(7.5))

    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.paragraph_format.space_before = Pt(24)
    r = t.add_run("DOCUMENTACIÓN TÉCNICA Y OPERATIVA")
    set_run_font(r, 22, True, DEEP)

    st = doc.add_paragraph()
    st.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = st.add_run("Sistema completo de cobros y pagos SPEI / CoDi")
    set_run_font(r, 14, False, BRAND)

    meta = [
        ("Producto", "Súper CLABE"),
        ("Modelo", "PSPI · capa no-custodia · sin captación"),
        ("Versión del documento", "2.0"),
        ("Fecha", "Agosto 2026"),
        ("Clasificación", "Confidencial — uso interno"),
        ("Código fuente", "webapp-spei-codi/"),
    ]
    doc.add_paragraph()
    table = doc.add_table(rows=len(meta), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (k, v) in enumerate(meta):
        c0, c1 = table.rows[i].cells
        c0.text = ""
        c1.text = ""
        p0 = c0.paragraphs[0]
        r0 = p0.add_run(k)
        set_run_font(r0, 11, True, BRAND)
        p1 = c1.paragraphs[0]
        r1 = p1.add_run(v)
        set_run_font(r1, 11, False, DEEP)
        c0.width = Cm(5.5)
        c1.width = Cm(9)

    doc.add_paragraph()
    note = doc.add_paragraph()
    note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    note.paragraph_format.space_before = Pt(36)
    r = note.add_run(
        "Circular 14/2017 (SPEI)  ·  Circular 12/2019 (CoDi)\n"
        "Reglas 58a · 71a · 72a  ·  Modelo PSPI sin captación"
    )
    set_run_font(r, 10, False, MUTED)

    add_page_break(doc)


def build_toc_page(doc):
    add_heading(doc, "Índice general", 1)
    add_p(
        doc,
        "Este índice se genera automáticamente con campos de Word. Al abrir el archivo, "
        "seleccione el índice, haga clic derecho y elija «Actualizar campos» → "
        "«Actualizar toda la tabla» para refrescar títulos y números de página.",
        size=10,
        color=MUTED,
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )
    p = doc.add_paragraph()
    insert_toc(p)

    # Índice manual de respaldo (por si el campo no se actualiza aún)
    add_heading(doc, "Contenido del documento (guía)", 2)
    sections = [
        "1. Resumen ejecutivo",
        "2. Modelo regulatorio y de negocio",
        "3. Principio de no-custodia (puente CoDi)",
        "4. Arquitectura del sistema",
        "5. Stack tecnológico",
        "6. Módulos funcionales",
        "7. Modelo de datos",
        "8. API REST completa",
        "9. Flujos operativos",
        "10. Tarifas, membresía e IVA",
        "11. Perfil Financiero y límites KYC",
        "12. Seguridad y controles",
        "13. Frontend y experiencia de usuario",
        "14. Notificaciones y favoritos",
        "15. Auditoría y cumplimiento",
        "16. Despliegue y operación",
        "17. Datos demo y pruebas",
        "18. Estado actual vs producción Banxico",
        "19. Glosario",
        "20. Referencias normativas",
        "Anexos",
    ]
    for s in sections:
        add_bullet(doc, s)
    add_page_break(doc)


def build_body(doc):
    # 1
    add_heading(doc, "1. Resumen ejecutivo", 1)
    add_p(
        doc,
        "Súper CLABE es una plataforma web fullstack de cobranza y pagos que opera como "
        "capa de software no-custodia sobre los rieles del Banco de México (SPEI, CoDi y Dimo). "
        "El dinero nunca entra a una cuenta de la plataforma: viaja cuenta bancaria del pagador "
        "→ cuenta bancaria del cobrador. Súper CLABE actúa como puente / iniciador de pagos "
        "(figura PSPI): genera el Mensaje de Cobro, orquesta la UX, aplica controles de perfil "
        "financiero y registra la liquidación.",
    )
    add_p(
        doc,
        "La monetización es una membresía prepago de software: se debita 0.05% + I.V.A. 16% "
        "del saldo de membresía del receptor al liquidar una operación. No hay wallet de fondos "
        "de clientes ni captación (evita clasificación como IFPE).",
    )
    add_heading(doc, "1.1 Capacidades principales", 2)
    add_table(
        doc,
        ["Capacidad", "Descripción"],
        [
            ["Registro / login por alias $@…", "Identidad única en la plataforma"],
            ["Perfil Financiero (KYC 1–4)", "Topes mensuales de abonos recibidos"],
            ["Mis cuentas (bóveda)", "CLABE destino cifrada AES-256"],
            ["Cobrar (CoDi)", "QR / folio con monto fijo o libre, abierto o dirigido"],
            ["Pagar", "Inbox, lector QR, pago directo P2P"],
            ["Favoritos", "Contactos frecuentes para cobrar/pagar"],
            ["Membresía", "Recarga, simulador de tarifa, bloqueo por saldo"],
            ["Notificaciones in-app", "Eventos de cobro, pago, bóveda, KYC"],
            ["Bitácora inmutable", "Hash SHA-256 encadenado"],
        ],
        [5.5, 11],
    )

    # 2
    add_heading(doc, "2. Modelo regulatorio y de negocio", 1)
    add_heading(doc, "2.1 Figura y marco", 2)
    add_table(
        doc,
        ["Aspecto", "Definición"],
        [
            ["Figura", "PSPI / iniciador de pagos, patrocinado por participante SPEI directo"],
            ["Marco", "Circular 14/2017, Circular 12/2019, Ley Fintech, LTOSF, Circular 9/2026"],
            ["Custodia", "Sin captación: no depósitos, no wallets de cliente, no crédito"],
            ["Monetización", "Membresía prepago; tarifa software 0.05% + IVA"],
            ["Bloqueo", "Membresía blocked → no opera hasta recargar"],
        ],
        [4, 12.5],
    )
    add_heading(doc, "2.2 Reglas aplicadas", 2)
    add_table(
        doc,
        ["Regla / circular", "Implementación en Súper CLABE"],
        [
            ["Regla 58a", "Bóveda AES-256, bitácora hash encadenada, retención ≥6 meses / 1 año"],
            ["Regla 71a", "JWT 20 min, TOTP opcional, CLABE/nombre enmascarados"],
            ["Regla 72a", "Niveles KYC 1–4; tope de abonos mensuales del receptor"],
            ["Apéndice AD", "Generación de cobro + qr_payload tipo CODI_CHARGE"],
            ["Apéndice E", "Vínculo a CEP Banxico por folio/clave"],
            ["Manual SPEI §6", "Validación CLABE dígito verificador mod-10"],
        ],
        [4.5, 12],
    )
    add_heading(doc, "2.3 Qué es y qué no es", 2)
    add_table(
        doc,
        ["Es", "No es"],
        [
            ["Orquestador de cobros/pagos CoDi", "Banco ni IFPE"],
            ["Almacén cifrado de CLABE destino", "Wallet con saldo de clientes"],
            ["Capa UX + cumplimiento + auditoría", "Participante SPEI directo (requiere patrocinio)"],
            ["Cobro de licencia de software", "Captador de fondos del público"],
        ],
        [8, 8.5],
    )

    # 3
    add_heading(doc, "3. Principio de no-custodia (puente CoDi)", 1)
    add_p(
        doc,
        "Súper CLABE solo arma el mensaje y la experiencia. La liquidación real (en producción) "
        "la ejecutan los bancos del pagador y del beneficiario a través de Banxico.",
    )
    add_heading(doc, "3.1 Diagrama conceptual del puente", 2)
    add_flow_box(
        doc,
        "Flujo de dinero vs flujo de la app",
        [
            "El cobrador registra su CLABE destino en Mis cuentas (bóveda cifrada).",
            "Súper CLABE genera el Mensaje de Cobro CoDi (folio + QR).",
            "El pagador abre el checkout en la app (inbox, QR o folio).",
            "Al confirmar, la app NO debita un saldo propio: solicita al riel Banxico/banco patrocinador la transferencia cuenta→cuenta.",
            "La liquidación ocurre entre bancos; la app registra resultado, CEP y debita la membresía 0.05% + IVA del receptor.",
        ],
    )
    add_heading(doc, "3.2 Rol de Mis cuentas", 2)
    add_table(
        doc,
        ["Pregunta", "Respuesta"],
        [
            ["¿Para cobrar?", "Sí — CLABE destino del cobro"],
            ["¿Para pagar (cuenta origen)?", "No — el cargo lo autoriza el banco del pagador"],
            ["¿Por qué?", "En CoDi el origen vive en la app bancaria; la PSPI no custodia esa cuenta"],
        ],
        [5, 11.5],
    )
    add_heading(doc, "3.3 Secuencia operativa del puente", 2)
    add_flow_box(
        doc,
        "Secuencia cobrador → pagador → Banxico",
        [
            "Cobrador registra CLABE destino en bóveda.",
            "Cobrador crea cobro (monto, concepto, vigencia, opciones).",
            "Sistema crea folio + Mensaje de Cobro + QR.",
            "Se comparte QR / folio / cobro dirigido al pagador.",
            "Pagador abre checkout y ve monto, beneficiario enmascarado y CEP.",
            "Pagador confirma (+ PIN/2FA si aplica).",
            "Producción: SC envía mensaje CoDi al riel Banxico.",
            "Liquidación cuenta→cuenta (objetivo ≤4s) y clave de rastreo.",
            "Se deduce membresía del receptor; se notifican ambas partes.",
        ],
    )
    add_note(
        doc,
        "Hoy en el código, POST /checkout/{folio}/pay y POST /checkout/direct simulan la "
        "liquidación. La conexión real PSPI ↔ Banxico es el siguiente hito de producción.",
    )

    # 4
    add_heading(doc, "4. Arquitectura del sistema", 1)
    add_heading(doc, "4.1 Componentes", 2)
    add_flow_box(
        doc,
        "Vista de despliegue",
        [
            "Navegador del usuario → Nginx (HTTPS).",
            "Nginx enruta / y assets al frontend estático; /api/* y /docs al backend.",
            "Backend FastAPI (Uvicorn/Gunicorn) persiste en PostgreSQL 16.",
            "Redis está provisionado para rate-limit/sesiones futuras (aún sin uso intensivo en app).",
        ],
    )
    add_heading(doc, "4.2 Estructura del repositorio", 2)
    for line in [
        "backend/ — FastAPI, ORM, routers, migraciones",
        "frontend/ — landing (index.html) + SPA (app.html)",
        "docs/ — documentación técnica y operativa",
        "deploy/ — guía AWS EC2",
        "nginx/ — reverse-proxy producción",
        "docker-compose*.yml · ecosystem.config.js (PM2 puerto 3017)",
    ]:
        add_bullet(doc, line)

    # 5
    add_heading(doc, "5. Stack tecnológico", 1)
    add_heading(doc, "5.1 Backend", 2)
    add_table(
        doc,
        ["Tecnología", "Rol"],
        [
            ["Python 3.12+", "Runtime"],
            ["FastAPI", "API REST + OpenAPI/Swagger"],
            ["Uvicorn / Gunicorn", "ASGI (dev / prod)"],
            ["SQLAlchemy 2", "ORM"],
            ["Pydantic 2", "Validación I/O"],
            ["PostgreSQL 16", "Persistencia (SQLite fallback)"],
            ["python-jose / cryptography", "JWT HS256 · AES-256-CBC"],
        ],
        [5, 11.5],
    )
    add_heading(doc, "5.2 Frontend", 2)
    add_table(
        doc,
        ["Tecnología", "Rol"],
        [
            ["HTML5 / CSS3 / JS ES2020", "SPA sin framework ni build"],
            ["qrcodejs / jsQR", "Generación y lectura de QR"],
            ["localStorage", "Solo token JWT (superclabe_token)"],
        ],
        [5.5, 11],
    )
    add_heading(doc, "5.3 Constantes de negocio", 2)
    add_table(
        doc,
        ["Constante", "Valor"],
        [
            ["MEMBERSHIP_FEE_RATE", "0.0005 (0.05%)"],
            ["IVA_RATE", "0.16 (16%)"],
            ["MAX_WHATSAPP_REMINDERS", "3"],
            ["SESSION / JWT", "20 minutos"],
            ["KYC MXN niveles 1–4", "0 / 25,000 / 68,000 / ilimitado"],
            ["MIN_OPERATING_LEVEL", "2"],
        ],
        [6, 10.5],
    )

    # 6
    add_heading(doc, "6. Módulos funcionales", 1)
    add_p(
        doc,
        "El sistema expone ocho vistas de producto, más autenticación y panel de notificaciones.",
    )
    add_table(
        doc,
        ["#", "Módulo UI", "Backend", "Función", "Norma"],
        [
            ["1", "Inicio", "tx / membership / me", "KPIs y movimientos", "Operativo"],
            ["2", "Mi perfil", "/kyc", "KYC gradual 1–4", "Regla 72a"],
            ["3", "Mis cuentas", "/vault", "CLABE destino cifrada", "Regla 58a"],
            ["4", "Favoritos", "/billing/favorites", "Contactos frecuentes", "UX"],
            ["5", "Cobrar", "/billing/charges", "Mensaje de Cobro + QR", "Apéndice AD"],
            ["6", "Pagar", "/checkout", "Inbox, QR, directo", "Regla 71a"],
            ["7", "Membresía", "/membership", "Saldo prepago y recarga", "No IFPE"],
            ["8", "Bitácoras", "/compliance", "Auditoría hash", "Regla 58a"],
        ],
        [1.2, 3, 3.5, 4.5, 3],
    )

    add_heading(doc, "6.1 Detalle operativo por módulo", 2)
    modules_detail = [
        (
            "Inicio",
            "Resumen de volumen cobrado/enviado; tarjeta de membresía (saldo MXN, % usado, "
            "volumen estimado); listado filtrable de transacciones; accesos rápidos.",
        ),
        (
            "Mi perfil",
            "Persona física o moral; elevación de nivel con CURP/RFC y documentos; "
            "uso mensual de abonos; nivel 1 no opera.",
        ),
        (
            "Mis cuentas",
            "Alta de CLABE con validación mod-10; alias, titular y banco; solo máscara en UI; "
            "obligatoria para crear cobros.",
        ),
        (
            "Favoritos",
            "Búsqueda de usuarios; alta/baja; atajos a cobro dirigido y pago directo.",
        ),
        (
            "Cobrar",
            "Asistente: cuenta → monto → opciones → QR. Tipos OPEN/TARGETED; monto fijo u open; "
            "usos, frecuencia, vigencia, PIN; recordatorios máx. 3.",
        ),
        (
            "Pagar",
            "Inbox de cobros dirigidos; QR (cámara/imagen/pegar); envío directo a alias; "
            "checkout con beneficiario enmascarado y CEP.",
        ),
        (
            "Membresía",
            "Saldo y estatus active/blocked; recarga simulada; simulador tarifa + IVA.",
        ),
        (
            "Bitácoras",
            "Tabla de eventos y verificación de integridad de la cadena hash.",
        ),
    ]
    for title, body in modules_detail:
        add_p(doc, title, size=11, bold=True, color=BRAND, align=WD_ALIGN_PARAGRAPH.LEFT, space_after=2)
        add_p(doc, body, size=10, space_after=8)

    # 7
    add_heading(doc, "7. Modelo de datos", 1)
    add_p(
        doc,
        "El modelo relacional centra la identidad en users (alias $@). La bóveda guarda CLABEs "
        "destino; charges referencia destination_account_id; transactions registran liquidaciones "
        "(charge_id nulo = pago directo). favorites, notifications, audit_logs y memberships "
        "completan el dominio.",
    )
    add_table(
        doc,
        ["Tabla", "Propósito"],
        [
            ["users", "Identidad $@alias, email/tel, KYC, TOTP"],
            ["companies_metadata / individuals_metadata", "Identidad cifrada + documentos"],
            ["vault_accounts", "CLABE destino cifrada / máscara / hash"],
            ["memberships", "Saldo prepago y estatus"],
            ["charges", "Cobros CoDi (OPEN/TARGETED, usos, frecuencia, PIN)"],
            ["favorites", "Relación usuario→usuario favorito"],
            ["transactions", "Liquidaciones; fee calculado; clave de rastreo"],
            ["audit_logs", "Eventos con hash encadenado"],
            ["notifications", "Alertas in-app por origen"],
        ],
        [6, 10.5],
    )

    # 8
    add_heading(doc, "8. API REST completa", 1)
    add_p(doc, "Base: /api/v1 · Auth: Bearer JWT · Swagger: /docs", size=10, color=MUTED)
    add_heading(doc, "8.1 Auth", 2)
    add_table(
        doc,
        ["Método", "Ruta", "Descripción"],
        [
            ["POST", "/auth/register", "Alta usuario + membresía 0 + KYC 1"],
            ["POST", "/auth/login", "Login por alias; TOTP opcional → JWT"],
            ["GET", "/auth/me", "Perfil + uso mensual KYC"],
            ["GET", "/auth/lookup", "Lookup público para UX login"],
            ["GET", "/auth/users", "Directorio (favoritos / dirigidos)"],
        ],
        [2.5, 4.5, 9.5],
    )
    add_heading(doc, "8.2 KYC · Vault · Membership", 2)
    add_table(
        doc,
        ["Método", "Ruta", "Descripción"],
        [
            ["GET", "/kyc/limits", "Límites en UDIS"],
            ["POST", "/kyc/upgrade", "Eleva nivel 2–4"],
            ["POST/GET", "/vault/accounts", "Alta y listado de CLABE"],
            ["GET", "/membership", "Saldo, status, tasas"],
            ["POST", "/membership/recharge", "Recarga (simulada)"],
            ["POST", "/membership/deduct", "Deducción manual/interna"],
        ],
        [2.5, 5, 9],
    )
    add_heading(doc, "8.3 Billing · Checkout", 2)
    add_table(
        doc,
        ["Método", "Ruta", "Descripción"],
        [
            ["POST", "/billing/charges", "Crea cobro + QR"],
            ["GET", "/billing/charges", "Mis cobros"],
            ["GET", "/billing/charges/payable", "Cobros dirigidos a mí"],
            ["POST", "/billing/charges/{id}/remind", "Recordatorio (máx. 3)"],
            ["GET/POST/DELETE", "/billing/favorites", "CRUD favoritos"],
            ["POST", "/checkout/direct", "Pago P2P sin QR"],
            ["POST", "/checkout/scan", "Decodifica QR → checkout"],
            ["GET", "/checkout/{folio}", "Vista pública del cobro"],
            ["POST", "/checkout/{folio}/pay", "Liquidación (simulada)"],
        ],
        [3.2, 5.5, 7.8],
    )
    add_heading(doc, "8.4 Notifications · Compliance", 2)
    add_table(
        doc,
        ["Método", "Ruta", "Descripción"],
        [
            ["GET", "/notifications", "Listado"],
            ["GET", "/notifications/unread-count", "Contador"],
            ["POST", "/notifications/{id}/read", "Marcar leída"],
            ["POST", "/notifications/read-all", "Marcar todas"],
            ["GET", "/compliance/audit-logs", "Bitácora"],
            ["GET", "/compliance/audit-logs/verify", "Verifica cadena"],
            ["GET", "/compliance/transactions", "Tx + CEP"],
            ["GET", "/compliance/reconciliation", "Conciliación receptor"],
        ],
        [2.5, 6.5, 7.5],
    )

    # 9
    add_heading(doc, "9. Flujos operativos", 1)
    add_heading(doc, "9.1 Alta de usuario y primer uso", 2)
    add_flow_box(
        doc,
        "Onboarding",
        [
            "Abrir /app.html",
            "Registro (tipo PF/PM + alias $@ + email/tel) o login por alias",
            "Obtener JWT (20 min)",
            "Completar Perfil Financiero → nivel ≥ 2",
            "Agregar CLABE en Mis cuentas",
            "Recargar membresía",
            "Listo para Cobrar / Pagar",
        ],
    )
    add_heading(doc, "9.2 Crear cobro CoDi", 2)
    add_flow_box(
        doc,
        "Cobrar",
        [
            "Validar membresía activa y KYC ≥ 2",
            "Elegir cuenta de bóveda",
            "Definir monto (fijo u open) y tipo OPEN/TARGETED",
            "Configurar vigencia, usos, frecuencia, PIN",
            "Validar tope de abonos del receptor si aplica",
            "POST /billing/charges → folio + QR",
            "Compartir / notificar al target si es dirigido",
        ],
    )
    add_heading(doc, "9.3 Pagar un cobro (QR / inbox)", 2)
    add_flow_box(
        doc,
        "Liquidación de cobro",
        [
            "Entrar por Inbox o escanear/pegar QR",
            "Ver checkout: monto, beneficiario máscara, CEP",
            "Validar PIN y reglas del cobro",
            "POST /checkout/{folio}/pay",
            "Validar cupo KYC del receptor y membresía para el fee",
            "Tx PROCESSED · clave de rastreo · notificaciones",
        ],
    )
    add_heading(doc, "9.4 Pago directo", 2)
    add_flow_box(
        doc,
        "Envío a alias",
        [
            "Elegir alias / favorito",
            "Capturar monto y concepto",
            "Bloquear autoenvío (SELF_PAYMENT)",
            "Validar nivel mínimo del emisor y tope de abonos del receptor",
            "POST /checkout/direct · fee solo al receptor",
        ],
    )
    add_heading(doc, "9.5 Matriz de roles en una operación", 2)
    add_table(
        doc,
        ["Operación", "Origen bancario", "Destino", "Fee", "Tope KYC"],
        [
            ["Cobro QR OPEN", "Banco del pagador", "Bóveda cobrador", "Receptor", "Abonos cobrador"],
            ["Cobro TARGETED", "Banco del pagador", "Bóveda cobrador", "Receptor", "Abonos cobrador"],
            ["Pago directo", "Banco del pagador*", "CLABE receptor*", "Receptor", "Abonos receptor"],
        ],
        [3.5, 3.5, 3.5, 2.5, 3.5],
    )
    add_note(
        doc,
        "En la simulación actual el pago directo no selecciona CLABE origen/destino en UI; "
        "en producción CoDi/SPEI el destino debe resolverse a la bóveda del receptor.",
    )

    # 10
    add_heading(doc, "10. Tarifas, membresía e IVA", 1)
    add_p(doc, "Fórmula (redondeo a 2 centavos):", bold=True, align=WD_ALIGN_PARAGRAPH.LEFT)
    add_bullet(doc, "base_fee = monto × 0.0005")
    add_bullet(doc, "iva = base_fee × 0.16")
    add_bullet(doc, "total_fee = base_fee + iva")
    add_p(
        doc,
        "Ejemplo: monto $10,000.00 MXN → base $5.00 + IVA $0.80 = $5.80 MXN debitados "
        "de la membresía del receptor.",
    )
    add_heading(doc, "10.1 Quién paga el fee", 2)
    add_table(
        doc,
        ["Flujo", "Pagador del fee"],
        [
            ["Liquidar cobro QR/CoDi", "Dueño del cobro (receptor)"],
            ["Pago directo", "Receptor (cobro no solicitado)"],
            ["Quien envía / paga", "$0 de membresía por la transferencia"],
        ],
        [7, 9.5],
    )
    add_heading(doc, "10.2 Volumen estimado en dashboard", 2)
    add_p(
        doc,
        "Con saldo de membresía S: volumen_operaciones ≈ S / 0.00058. "
        "Se muestra en MXN y nunca en negativo.",
    )

    # 11
    add_heading(doc, "11. Perfil Financiero y límites KYC", 1)
    add_table(
        doc,
        ["Nivel", "Operación", "Tope mensual de abonos recibidos"],
        [
            ["1", "Solo registro", "$0 (bloqueado)"],
            ["2", "Opera", "$25,000 MXN"],
            ["3", "Opera", "$68,000 MXN"],
            ["4", "Opera", "Sin límite mensual"],
        ],
        [3, 4, 9.5],
    )
    add_note(
        doc,
        "El tope no suma envíos/cargos; solo créditos donde el usuario es payee (abonos).",
    )
    add_p(
        doc,
        "Se valida al crear cobros con monto fijo, al pagar cobros y en pago directo. "
        "Códigos: KYC_LEVEL_BLOCKED, KYC_LIMIT_EXCEEDED.",
    )

    # 12
    add_heading(doc, "12. Seguridad y controles", 1)
    add_table(
        doc,
        ["Control", "Detalle"],
        [
            ["JWT", "HS256, expiración 20 min"],
            ["TOTP", "Opcional en login (RFC 6238)"],
            ["AES-256-CBC", "CLABE, CURP, RFC, nombres sensibles"],
            ["CLABE", "Mod-10; máscara últimos 4; hash SHA-256 unicidad"],
            ["PIN de cobro", "PBKDF2-HMAC-SHA256 (200k iteraciones)"],
            ["Checkout", "Titular por iniciales; banco visible; sin CLABE completa"],
            ["Secretos", "AES_SECRET_KEY y JWT_SECRET por entorno"],
        ],
        [4, 12.5],
    )
    add_note(
        doc,
        "El login actual es por alias sin contraseña (modo demo/desarrollo). "
        "En producción debe reforzarse con password y/o 2FA obligatorio.",
    )

    # 13
    add_heading(doc, "13. Frontend y experiencia de usuario", 1)
    add_table(
        doc,
        ["Archivo", "Rol"],
        [
            ["frontend/index.html", "Landing marketing + demo"],
            ["frontend/app.html", "Sistema completo (login + 8 módulos)"],
            ["frontend/config.js", 'API_BASE: "/api/v1", USE_API: true'],
        ],
        [5, 11.5],
    )
    add_p(doc, "Identidad visual: Deep #0E3B43 · Brand #2A8D92 · Accent #64C4BC.", size=10)
    add_p(
        doc,
        "Navegación: sidebar con módulos y bloque de cumplimiento; topbar con alias, nivel KYC, "
        "saldo, favoritos y campana de notificaciones. Lenguaje UX en español amigable.",
    )

    # 14
    add_heading(doc, "14. Notificaciones y favoritos", 1)
    add_p(doc, "Orígenes: auth · billing · checkout · membership · kyc · vault", size=10, color=MUTED)
    add_table(
        doc,
        ["Kind", "Cuándo"],
        [
            ["CHARGE_*", "Cobro nuevo / dirigido / recordatorio"],
            ["PAYMENT_* / DIRECT_PAYMENT_*", "Liquidación QR o pago directo"],
            ["MEMBERSHIP_RECHARGE / BLOCKED", "Saldo de membresía"],
            ["VAULT_ACCOUNT_ADDED", "Alta de CLABE"],
            ["KYC_UPGRADE", "Cambio de nivel"],
        ],
        [6, 10.5],
    )
    add_p(
        doc,
        "Canal actual: solo in-app. Los «recordatorios WhatsApp» incrementan contador y "
        "notifican en app (sin gateway real).",
    )

    # 15
    add_heading(doc, "15. Auditoría y cumplimiento", 1)
    add_p(
        doc,
        "Cadena de integridad: hₙ = SHA256(hₙ₋₁ + timestamp|operator|action|category|ip|payload). "
        "Verificación vía GET /compliance/audit-logs/verify. Retención declarada ≥ 6 meses (SPEI) "
        "y 1 año (Canales Electrónicos).",
    )
    add_p(
        doc,
        "Cada transacción expone vínculo CEP Banxico. Categorías: auth, kyc_change, vault_access, "
        "payment_initiation, membership, general.",
    )

    # 16
    add_heading(doc, "16. Despliegue y operación", 1)
    add_table(
        doc,
        ["Modo", "Cómo", "Puerto"],
        [
            ["PM2 dev", "ecosystem.config.js → uvicorn", "3017"],
            ["Docker dev", "docker-compose.yml", "8000"],
            ["Docker prod", "docker-compose.prod.yml + Nginx", "80/443"],
            ["Host-nginx", "docker-compose.host.yml", "3017→8000"],
        ],
        [3.5, 8, 4.5],
    )
    add_heading(doc, "16.1 Variables críticas", 2)
    for v in [
        "DATABASE_URL — Postgres o SQLite",
        "AES_SECRET_KEY — cifrado bóveda / PII",
        "JWT_SECRET — firma de sesión",
        "JWT_EXPIRE_MIN — default 20",
        "POSTGRES_* / REDIS_URL — compose",
    ]:
        add_bullet(doc, v)
    add_heading(doc, "16.2 Checklist operativo", 2)
    for item in [
        "Health GET /api/health",
        "Logs PM2/Docker",
        "Backup Postgres",
        "Verificar cadena de auditoría periódicamente",
        "Revisar membresías blocked y topes KYC",
    ]:
        add_bullet(doc, item)
    add_p(doc, "Guía EC2: deploy/DEPLOY-AWS-EC2.md", size=10, color=MUTED)

    # 17
    add_heading(doc, "17. Datos demo y pruebas", 1)
    add_table(
        doc,
        ["Alias", "Tipo", "KYC", "Membresía", "Notas"],
        [
            ["$@empresa.demo", "Empresa", "2", "~$50", "CLABE BBVA demo"],
            ["$@juan.perez", "PF", "2", "~$20", "—"],
            ["$@maria.lopez", "PF", "1", "$0", "Sin operar hasta subir nivel"],
        ],
        [4, 2.5, 1.8, 2.5, 5.5],
    )
    add_p(doc, "Login: solo alias. CLABE demo válida mod-10: 012180001234567895.", size=10)

    # 18
    add_heading(doc, "18. Estado actual vs producción Banxico", 1)
    add_table(
        doc,
        ["Componente", "Estado actual", "Producción objetivo"],
        [
            ["Mensaje de Cobro / QR", "Generado en app", "Homologado con banco patrocinador"],
            ["Liquidación SPEI/CoDi", "Simulada en API", "Riel Banxico vía PSPI"],
            ["Clave de rastreo / CEP", "Sintética + URL plantilla", "Confirmación Banxico real"],
            ["Recarga membresía", "Crédito simulado", "SPEI / medio de pago real"],
            ["KYC documental", "PENDING_VALIDATION", "RENAPO / INE / e.firma"],
            ["Validación CLABE", "Mod-10 + alta inmediata", "Titularidad bancaria"],
            ["WhatsApp", "Contador in-app", "BSP / WhatsApp Business API"],
            ["Auth password", "No", "Password + 2FA obligatorio"],
            ["HSM/KMS", "Clave en env", "Custodia de llaves"],
            ["Regla 74a", "Pendiente", "Auditoría externa"],
        ],
        [4.2, 5.5, 6.5],
    )

    # 19
    add_heading(doc, "19. Glosario", 1)
    add_table(
        doc,
        ["Término", "Significado"],
        [
            ["PSPI", "Proveedor de Servicios de Participación Indirecta en SPEI"],
            ["CoDi", "Cobro Digital Banxico"],
            ["SPEI", "Sistema de Pagos Electrónicos Interbancarios"],
            ["Dimo", "Dinero Móvil (asociación celular–cuenta)"],
            ["CEP", "Comprobante Electrónico de Pago Banxico"],
            ["CLABE", "Clave Bancaria Estandarizada (18 dígitos)"],
            ["IFPE", "Institución de Fondos de Pago Electrónico (custodia)"],
            ["Sin captación", "La app no recibe ni guarda dinero del público"],
            ["Bóveda", "Almacén cifrado de cuentas destino"],
            ["Membresía", "Saldo prepago para tarifa de software"],
            ["Abono", "Crédito recibido (usuario como payee)"],
            ["OPEN / TARGETED", "Cobro abierto vs dirigido a un alias"],
        ],
        [4, 12.5],
    )

    # 20
    add_heading(doc, "20. Referencias normativas", 1)
    add_table(
        doc,
        ["Documento", "Uso en el sistema"],
        [
            ["Circular 14/2017 Banxico (SPEI)", "Reglas 58a, 71a, 72a; Apéndices AN, E, O"],
            ["Circular 12/2019 Banxico (CoDi)", "Mensajes de cobro; Apéndice AD"],
            ["Circular 9/2026", "Homologación UX; sesión 20 min"],
            ["Art. 115 LIC (referencia)", "Niveles / topes de abonos"],
            ["Ley Fintech / LTOSF", "Exclusión IFPE por no-custodia"],
            ["Manual de operación SPEI §6", "Dígito verificador CLABE"],
        ],
        [6.5, 10],
    )

    # Anexos
    add_heading(doc, "Anexos", 1)
    add_heading(doc, "Anexo A — Checklist de puesta en marcha", 2)
    for item in [
        "Variables DATABASE_URL, AES_SECRET_KEY, JWT_SECRET definidas",
        "Migraciones aplicadas",
        "Health OK",
        "Usuario demo o primer registro creado",
        "Al menos una CLABE en bóveda",
        "Membresía con saldo > 0",
        "KYC ≥ 2 para operar",
        "Probar: crear cobro → pagar → ver CEP/bitácora",
        "Verificar cadena de auditoría",
        "Backup de base de datos configurado",
    ]:
        add_bullet(doc, item)

    add_heading(doc, "Anexo B — Documentos relacionados", 2)
    add_table(
        doc,
        ["Documento", "Ruta"],
        [
            ["Doc completa (Markdown)", "docs/DOCUMENTACION-SISTEMA-COMPLETA.md"],
            ["Doc técnica v1 (histórica)", "docs/DOCUMENTACION-TECNICA.md"],
            ["Deploy AWS EC2", "deploy/DEPLOY-AWS-EC2.md"],
            ["README proyecto", "README.md"],
            ["OpenAPI vivo", "http(s)://<host>/docs"],
        ],
        [6.5, 10],
    )

    add_p(
        doc,
        "— Fin del documento — Súper CLABE v2.0 · Agosto 2026 —",
        size=10,
        bold=True,
        color=BRAND,
        align=WD_ALIGN_PARAGRAPH.CENTER,
        space_after=0,
    )


def main():
    doc = Document()

    # Estilos base
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")

    setup_header_footer(doc, LOGO)
    build_cover(doc, LOGO)
    build_toc_page(doc)
    build_body(doc)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUT))
    print(f"OK: {OUT}")
    print(f"Size: {OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
