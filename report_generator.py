"""Geração do PDF de saída com os alunos acima do limite de faltas.

O relatório sai agrupado por turma: os metadados (escola, turno, professor)
ficam no cabeçalho de cada seção, o que libera a largura da tabela para as
colunas de faltas e frequência de cada mês.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from parser import (
    PREFIXO_SAIDA,
    Aluno,
    Turma,
    agrupar_por_escola,
    meses_lancados,
)

MARGEM = 12 * mm

LARG_NOME = 58 * mm
LARG_TOTAIS = [17 * mm, 14 * mm, 14 * mm, 16 * mm]  # Abonadas, Faltas, Aulas, Freq.
LARG_MES_MINIMA = 16 * mm  # abaixo disso "100,0%" não cabe: muda para A3
PROPORCAO_FALTAS = 0.38    # divisão da largura do mês entre "F." e "Freq."

AZUL = colors.HexColor("#1F3864")
AZUL_CLARO = colors.HexColor("#2E5496")
CINZA = colors.HexColor("#F2F2F2")
BORDA = colors.HexColor("#BFBFBF")


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
        "secao": ParagraphStyle(
            "secao",
            parent=base["Normal"],
            fontSize=11,
            leading=14,
            spaceBefore=2,
            textColor=AZUL,
        ),
        "secao_sub": ParagraphStyle(
            "secao_sub",
            parent=base["Normal"],
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#555555"),
        ),
        "nome": ParagraphStyle("nome", parent=base["Normal"], fontSize=7.5, leading=9),
    }


def _agrupar_por_turma(alunos: list[Aluno]) -> list[tuple[Turma, list[Aluno]]]:
    grupos: dict[Turma, list[Aluno]] = {}
    for aluno in alunos:
        grupos.setdefault(aluno.turma_info, []).append(aluno)

    ordenados = sorted(
        grupos.items(), key=lambda item: (item[0].escola, item[0].turma)
    )
    return [
        (turma, sorted(lista, key=lambda a: (-a.faltas, a.nome)))
        for turma, lista in ordenados
    ]


def _escolher_pagina(max_meses: int) -> tuple[float, float]:
    """A4 paisagem; A3 quando há meses demais para caber com legibilidade."""
    for pagina in (landscape(A4), landscape(A3)):
        util = pagina[0] - 2 * MARGEM - LARG_NOME - sum(LARG_TOTAIS)
        if max_meses == 0 or util / max_meses >= LARG_MES_MINIMA:
            return pagina
    return landscape(A3)


def _larguras(pagina: tuple[float, float], n_meses: int) -> list[float]:
    util = pagina[0] - 2 * MARGEM - LARG_NOME - sum(LARG_TOTAIS)
    if not n_meses:
        # PDF lido pelo texto (sem detalhamento mensal): o nome ocupa a sobra.
        return [LARG_NOME + util, *LARG_TOTAIS]

    larguras = [LARG_NOME]
    por_mes = util / n_meses
    for _ in range(n_meses):
        larg_f = por_mes * PROPORCAO_FALTAS
        larguras += [larg_f, por_mes - larg_f]
    return larguras + LARG_TOTAIS


def _tabela(alunos: list[Aluno], meses: list[str], pagina) -> Table:
    estilos = _estilos()

    linha_meses: list[str] = ["Estudante"]
    linha_sub: list[str] = [""]
    for mes in meses:
        linha_meses += [mes, ""]
        linha_sub += ["F.", "Freq."]
    linha_meses += ["Abonadas", "Faltas", "Aulas", "Freq."]
    linha_sub += ["", "", "", ""]

    dados: list[list] = [linha_meses, linha_sub]
    for aluno in alunos:
        linha: list = [Paragraph(aluno.nome, estilos["nome"])]
        for mes in meses:
            registro = aluno.mes(mes)
            if registro is None:
                linha += ["", ""]
            else:
                linha += [str(registro.faltas), registro.frequencia_fmt]
        linha += [
            str(aluno.abonadas),
            str(aluno.faltas),
            str(aluno.aulas),
            aluno.frequencia_fmt,
        ]
        dados.append(linha)

    n_col = len(linha_meses)
    col_totais = n_col - 4
    col_faltas = n_col - 3

    estilo = [
        # Cabeçalho em duas faixas: nome do mês em cima, F./Freq. embaixo.
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("BACKGROUND", (0, 1), (-1, 1), AZUL_CLARO),
        # Células que ocupam as duas faixas ficam de uma cor só.
        ("BACKGROUND", (0, 0), (0, 1), AZUL),
        ("BACKGROUND", (n_col - 4, 0), (-1, 1), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 1), colors.white),
        ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 1), 7),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("SPAN", (0, 0), (0, 1)),  # "Estudante" ocupa as duas faixas
        ("FONTSIZE", (0, 2), (-1, -1), 7),
        ("FONTNAME", (col_faltas, 2), (col_faltas, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDA),
        ("LINEBEFORE", (col_totais, 0), (col_totais, -1), 1.1, AZUL),
        ("ROWBACKGROUNDS", (0, 2), (-1, -1), [colors.white, CINZA]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in range(len(meses)):  # nome do mês sobre o par F./Freq.
        estilo.append(("SPAN", (1 + 2 * i, 0), (2 + 2 * i, 0)))
    for j in range(4):  # colunas de total ocupam as duas faixas
        estilo.append(("SPAN", (col_totais + j, 0), (col_totais + j, 1)))

    tabela = Table(
        dados, colWidths=_larguras(pagina, len(meses)), repeatRows=2, hAlign="LEFT"
    )
    tabela.setStyle(TableStyle(estilo))
    return tabela


def _rodape(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(
        MARGEM,
        8 * mm,
        "Gerado a partir do Mapa de Frequência Sintético — Portal SIGEduc",
    )
    canvas.drawRightString(doc.pagesize[0] - MARGEM, 8 * mm, f"Página {doc.page}")
    canvas.restoreState()


def gerar_relatorio(
    alunos: list[Aluno],
    saida: str | Path,
    limite: float,
    total_analisado: int | None = None,
    escola: str | None = None,
) -> Path:
    """Escreve o PDF de saída e devolve o caminho gerado.

    `escola` nomeia o relatório no cabeçalho; sem isso, um relatório de escola
    sem nenhum aluno acima do limite não diria de que escola se trata.
    """
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    estilos = _estilos()
    grupos = _agrupar_por_turma(alunos)
    # Um só conjunto de meses para o documento inteiro: turmas da mesma escola
    # podem ter começado em meses diferentes, e colunas desalinhadas entre as
    # seções tornariam o relatório difícil de comparar.
    meses = meses_lancados(alunos)
    pagina = _escolher_pagina(len(meses))

    doc = SimpleDocTemplate(
        str(saida),
        pagesize=pagina,
        leftMargin=MARGEM,
        rightMargin=MARGEM,
        topMargin=MARGEM,
        bottomMargin=16 * mm,
        title="Alunos acima do limite de faltas",
        author="Mapa de Frequência SIGEduc",
    )

    limite_fmt = f"{limite:g}"
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    anos = sorted({a.turma_info.ano for a in alunos if a.turma_info.ano})

    if escola is None:
        escolas = sorted({a.turma_info.escola for a in alunos if a.turma_info.escola})
        escola = escolas[0] if len(escolas) == 1 else None

    elementos: list = [
        Paragraph("Relatório de Alunos com Excesso de Faltas", estilos["titulo"]),
        Paragraph(
            f"Alunos com mais de {limite_fmt} faltas no ano letivo"
            + (f" {'/'.join(anos)}" if anos else ""),
            estilos["subtitulo"],
        ),
    ]
    if escola:
        elementos.append(Paragraph(f"<b>{escola}</b>", estilos["subtitulo"]))
    elementos += [
        Spacer(1, 6 * mm),
        Paragraph(
            f"<b>Alunos listados:</b> {len(alunos)}"
            + (f" de {total_analisado} analisados" if total_analisado else "")
            + f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>Turmas:</b> {len(grupos)}"
            f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>Limite:</b> mais de {limite_fmt} faltas"
            f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>Gerado em:</b> {agora}",
            estilos["info"],
        ),
        Spacer(1, 5 * mm),
    ]

    if not alunos:
        elementos.append(
            Paragraph(
                "<b>Nenhum aluno ultrapassou o limite de faltas informado.</b>",
                estilos["info"],
            )
        )
        doc.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
        return saida

    for turma, lista in grupos:
        cabecalho = " — ".join(x for x in (turma.escola, turma.turma) if x) or "Turma"
        detalhes = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(
            f"<b>{rotulo}:</b> {valor}"
            for rotulo, valor in (
                ("Turno", turma.turno),
                ("Professor(a)", turma.professor),
                ("Componente", turma.componente),
            )
            if valor
        )
        elementos.append(
            KeepTogether(
                [
                    Paragraph(f"<b>{cabecalho}</b>", estilos["secao"]),
                    Paragraph(detalhes, estilos["secao_sub"]),
                    Spacer(1, 2.5 * mm),
                    _tabela(lista, meses, pagina),
                ]
            )
        )
        elementos.append(Spacer(1, 7 * mm))

    doc.build(elementos, onFirstPage=_rodape, onLaterPages=_rodape)
    return saida


# --- Um relatório por escola -----------------------------------------------

# Caracteres proibidos em nome de arquivo no Windows.
RE_INVALIDO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def nome_arquivo_escola(escola: str) -> str:
    """'CRECHE ARCO IRIS' -> 'relatorio_faltas_CRECHE_ARCO_IRIS.pdf'."""
    base = RE_INVALIDO.sub("", escola)
    base = re.sub(r"\s+", "_", base.strip())
    base = base.strip("._")[:80].strip("._") or "sem_escola"
    return f"{PREFIXO_SAIDA}_{base}.pdf"


def gerar_relatorios_por_escola(
    alunos: list[Aluno],
    pasta: str | Path,
    limite: float,
    totais_por_escola: dict[str, int] | None = None,
) -> list[Path]:
    """Gera um PDF por escola, com todas as turmas daquela escola.

    Escolas processadas que ficaram sem nenhum aluno acima do limite também
    ganham um relatório, dizendo isso — a ausência de arquivo seria ambígua.
    """
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)

    totais = totais_por_escola or {}
    grupos = agrupar_por_escola(alunos)
    escolas = sorted(set(grupos) | set(totais))

    saidas: list[Path] = []
    usados: dict[str, int] = {}
    for escola in escolas:
        nome = nome_arquivo_escola(escola)
        # Duas escolas diferentes podem gerar o mesmo nome de arquivo.
        if nome in usados:
            usados[nome] += 1
            caminho = pasta / f"{Path(nome).stem}_{usados[nome]}.pdf"
        else:
            usados[nome] = 1
            caminho = pasta / nome
        gerar_relatorio(
            grupos.get(escola, []),
            caminho,
            limite,
            totais.get(escola),
            escola=escola,
        )
        saidas.append(caminho)

    return saidas


__all__ = [
    "gerar_relatorio",
    "gerar_relatorios_por_escola",
    "nome_arquivo_escola",
]
