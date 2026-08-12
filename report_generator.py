"""Geração do PDF de saída com os alunos acima do limite de faltas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from parser import Aluno

MARGEM = 12 * mm
LARGURAS = [66 * mm, 18 * mm, 38 * mm, 27 * mm, 66 * mm, 58 * mm]  # = 273mm úteis
CABECALHO = [
    "Estudante",
    "Faltas",
    "Turma",
    "Turno",
    "Escola",
    "Professor(a)",
]

AZUL = colors.HexColor("#1F3864")
CINZA = colors.HexColor("#F2F2F2")


def _estilos() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=base["Title"], fontSize=15, spaceAfter=2, textColor=AZUL
        ),
        "subtitulo": ParagraphStyle(
            "subtitulo",
            parent=base["Normal"],
            fontSize=9.5,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#444444"),
        ),
        "info": ParagraphStyle("info", parent=base["Normal"], fontSize=9.5, leading=13),
        "celula": ParagraphStyle(
            "celula", parent=base["Normal"], fontSize=8.5, leading=10.5
        ),
        "cabecalho": ParagraphStyle(
            "cabecalho",
            parent=base["Normal"],
            fontSize=9,
            leading=11,
            textColor=colors.white,
            fontName="Helvetica-Bold",
        ),
    }


def _valor_unico(valores: list[str]) -> str:
    distintos = sorted({v for v in valores if v})
    if not distintos:
        return "—"
    if len(distintos) == 1:
        return distintos[0]
    return f"Vários ({len(distintos)})"


def _ordenar(alunos: list[Aluno]) -> list[Aluno]:
    return sorted(
        alunos,
        key=lambda a: (
            a.turma_info.escola,
            a.turma_info.turma,
            -a.faltas,
            a.nome,
        ),
    )


def _rodape(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(MARGEM, 8 * mm, "Gerado a partir do Mapa de Frequência Sintético — Portal SIGEduc")
    canvas.drawRightString(doc.pagesize[0] - MARGEM, 8 * mm, f"Página {doc.page}")
    canvas.restoreState()


def gerar_relatorio(
    alunos: list[Aluno],
    saida: str | Path,
    limite: float,
    total_analisado: int | None = None,
) -> Path:
    """Escreve o PDF de saída e devolve o caminho gerado."""
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    estilos = _estilos()
    alunos = _ordenar(alunos)
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")

    doc = SimpleDocTemplate(
        str(saida),
        pagesize=landscape(A4),
        leftMargin=MARGEM,
        rightMargin=MARGEM,
        topMargin=MARGEM,
        bottomMargin=16 * mm,
        title="Alunos acima do limite de faltas",
        author="Mapa de Frequência SIGEduc",
    )

    limite_fmt = f"{limite:g}"
    elementos = [
        Paragraph("Relatório de Alunos com Excesso de Faltas", estilos["titulo"]),
        Paragraph(
            f"Alunos com mais de {limite_fmt} faltas no ano letivo", estilos["subtitulo"]
        ),
        Spacer(1, 7 * mm),
    ]

    escola = _valor_unico([a.turma_info.escola for a in alunos])
    turma = _valor_unico([a.turma_info.turma for a in alunos])
    turno = _valor_unico([a.turma_info.turno for a in alunos])
    ano = _valor_unico([a.turma_info.ano for a in alunos])

    info = [
        f"<b>Escola:</b> {escola}",
        f"<b>Turma:</b> {turma} &nbsp;&nbsp;|&nbsp;&nbsp; <b>Turno:</b> {turno}"
        f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>Ano letivo:</b> {ano}",
        f"<b>Limite de faltas:</b> {limite_fmt} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Alunos listados:</b> {len(alunos)}"
        + (
            f" de {total_analisado} analisados"
            if total_analisado is not None
            else ""
        ),
        f"<b>Gerado em:</b> {agora}",
    ]
    elementos += [Paragraph(linha, estilos["info"]) for linha in info]
    elementos.append(Spacer(1, 6 * mm))

    if not alunos:
        elementos.append(
            Paragraph(
                "<b>Nenhum aluno ultrapassou o limite de faltas informado.</b>",
                estilos["info"],
            )
        )
        doc.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
        return saida

    dados = [[Paragraph(c, estilos["cabecalho"]) for c in CABECALHO]]
    for aluno in alunos:
        dados.append(
            [
                Paragraph(aluno.nome, estilos["celula"]),
                Paragraph(f"<b>{aluno.faltas}</b>", estilos["celula"]),
                Paragraph(aluno.turma_info.turma or "—", estilos["celula"]),
                Paragraph(aluno.turma_info.turno or "—", estilos["celula"]),
                Paragraph(aluno.turma_info.escola or "—", estilos["celula"]),
                Paragraph(aluno.turma_info.professor or "—", estilos["celula"]),
            ]
        )

    tabela = Table(dados, colWidths=LARGURAS, repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), AZUL),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CINZA]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    elementos.append(tabela)

    doc.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
    return saida


__all__ = ["gerar_relatorio"]
