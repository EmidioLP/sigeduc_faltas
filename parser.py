"""Extração e parsing dos PDFs 'Mapa de Frequência Sintético' do Portal SIGEduc."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

import pdfplumber


class LayoutInesperadoError(Exception):
    """PDF que não segue o layout esperado do Mapa de Frequência Sintético."""


@dataclass(frozen=True)
class Turma:
    """Metadados do cabeçalho (uma turma por página do relatório)."""

    ano: str = ""
    escola: str = ""
    professor: str = ""
    componente: str = ""
    turma: str = ""
    turno: str = ""


@dataclass(frozen=True)
class Aluno:
    numero: int
    nome: str
    abonadas: int
    faltas: int
    aulas: int
    frequencia: float
    turma_info: Turma
    arquivo: str = ""

    @property
    def frequencia_fmt(self) -> str:
        return f"{self.frequencia:.1f}".replace(".", ",") + "%"


# --- Cabeçalho -------------------------------------------------------------

RE_ANO = re.compile(r"Ano:\s*(\d{4})")
# "Escola: CRECHE ARCO IRIS : TALLYTA EDUARDA DA SILVA"
RE_ESCOLA_PROF = re.compile(r"Escola:\s*([^\n:]+?)\s*:\s*([^\n]+)")
RE_ESCOLA = re.compile(r"Escola:\s*([^\n]+)")
RE_COMPONENTE = re.compile(r"Componente:\s*([^\n]+?)(?=\s+Turma:|\s*$)", re.MULTILINE)
RE_TURMA = re.compile(r"Turma:\s*([^\n]+?)(?=\s+Turno:|\s*$)", re.MULTILINE)
RE_TURNO = re.compile(r"Turno:\s*([^\n]+)")

TITULO_ESPERADO = "mapa de frequência sintético"

# Tokens que ocupam uma célula numérica da tabela ("*" = sem faltas no mês).
RE_VALOR = re.compile(r"^(?:\*|-{1,2}|[\d.,]+%?)$")
RE_TEM_LETRA = re.compile(r"[A-Za-zÀ-ÿ]")


def _e_valor(token: str) -> bool:
    if token in {"*", "-", "--"}:
        return True
    return bool(RE_VALOR.match(token)) and any(c.isdigit() for c in token)


def _para_numero(token: str) -> float:
    """Converte '71,3%' -> 71.3, '1.234' -> 1234.0, '*' -> 0.0."""
    if token in {"*", "-", "--"}:
        return 0.0
    limpo = token.rstrip("%").replace(".", "").replace(",", ".")
    return float(limpo)


def _limpar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip(" :-")


def parse_cabecalho(texto_pagina: str) -> Turma | None:
    """Extrai os metadados da turma do texto de uma página. None se não houver."""
    # A linha "Total de faltas da Turma:" também contém "Turma:" — descartá-la
    # evita que o somatório da turma seja lido como nome de turma.
    texto_pagina = "\n".join(
        linha
        for linha in texto_pagina.splitlines()
        if "total de faltas" not in linha.lower()
    )

    escola = professor = ""
    m = RE_ESCOLA_PROF.search(texto_pagina)
    if m:
        escola, professor = _limpar(m.group(1)), _limpar(m.group(2))
    else:
        m = RE_ESCOLA.search(texto_pagina)
        if m:
            escola = _limpar(m.group(1))

    ano = RE_ANO.search(texto_pagina)
    componente = RE_COMPONENTE.search(texto_pagina)
    turma = RE_TURMA.search(texto_pagina)
    turno = RE_TURNO.search(texto_pagina)

    info = Turma(
        ano=ano.group(1) if ano else "",
        escola=escola,
        professor=professor,
        componente=_limpar(componente.group(1)) if componente else "",
        turma=_limpar(turma.group(1)) if turma else "",
        turno=_limpar(turno.group(1)) if turno else "",
    )
    # Um cabeçalho de verdade sempre traz Escola ou Componente; sem isso é uma
    # página de continuação, que deve herdar os metadados da página anterior.
    return info if (info.escola or info.componente) else None


# --- Linhas de aluno -------------------------------------------------------


def parse_linha_aluno(linha: str) -> dict | None:
    """Interpreta uma linha da tabela de alunos.

    O nome vai do Nº até o primeiro token numérico; os 4 últimos valores da
    linha são sempre Abonadas, Faltas, Aulas e Freq. geral — os pares mensais
    do meio são ignorados.
    """
    tokens = linha.split()
    if len(tokens) < 6 or not tokens[0].isdigit():
        return None

    i = 1
    while i < len(tokens) and not _e_valor(tokens[i]):
        i += 1

    nome = " ".join(tokens[1:i])
    valores = tokens[i:]
    if len(valores) < 4 or not RE_TEM_LETRA.search(nome):
        return None

    # "Total de faltas da Turma:" e afins não são alunos.
    if "total de faltas" in nome.lower():
        return None

    try:
        abonadas, faltas, aulas, freq = (_para_numero(v) for v in valores[-4:])
    except ValueError:
        return None

    if aulas <= 0 or faltas < 0 or freq < 0 or freq > 100:
        return None

    return {
        "numero": int(tokens[0]),
        "nome": nome,
        "abonadas": int(abonadas),
        "faltas": int(faltas),
        "aulas": int(aulas),
        "frequencia": freq,
    }


# --- PDF -------------------------------------------------------------------


def extrair_alunos(caminho: str | Path) -> list[Aluno]:
    """Lê um PDF e devolve todos os alunos encontrados, com os metadados da turma.

    Cada página tem o seu próprio cabeçalho; páginas sem cabeçalho herdam o da
    página anterior (continuação da mesma turma).
    """
    caminho = Path(caminho)
    alunos: list[Aluno] = []
    meta_atual: Turma | None = None
    viu_titulo = False

    try:
        pdf = pdfplumber.open(caminho)
    except Exception as exc:  # PDF corrompido, protegido por senha, etc.
        raise LayoutInesperadoError(f"não foi possível abrir o PDF: {exc}") from exc

    with pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text() or ""
            if TITULO_ESPERADO in texto.lower():
                viu_titulo = True

            meta_pagina = parse_cabecalho(texto)
            if meta_pagina:
                meta_atual = meta_pagina

            for linha in texto.splitlines():
                dados = parse_linha_aluno(linha)
                if dados:
                    alunos.append(
                        Aluno(
                            **dados,
                            turma_info=meta_atual or Turma(),
                            arquivo=caminho.name,
                        )
                    )

    if not alunos:
        motivo = (
            "nenhuma linha de aluno reconhecida"
            if viu_titulo
            else "não parece ser um Mapa de Frequência Sintético do SIGEduc"
        )
        raise LayoutInesperadoError(motivo)

    return alunos


def filtrar_por_faltas(alunos: list[Aluno], limite: float) -> list[Aluno]:
    """Alunos cujo total de faltas no ano ultrapassa o limite."""
    return [a for a in alunos if a.faltas > limite]


@dataclass
class ResultadoLote:
    alunos: list[Aluno]          # já filtrados pelo limite
    total_analisado: int         # todos os alunos lidos, antes do filtro
    falhas: list[tuple[Path, str]]
    processados: int


def processar_lote(
    pdfs: list[Path], limite: float, log=None
) -> ResultadoLote:
    """Processa vários PDFs, sem deixar que um arquivo ruim interrompa o lote.

    `log` é um callable opcional que recebe mensagens de progresso.
    """
    registrar = log or (lambda _msg: None)
    alunos_filtrados: list[Aluno] = []
    falhas: list[tuple[Path, str]] = []
    total_analisado = 0
    processados = 0

    for pdf in pdfs:
        try:
            alunos = extrair_alunos(pdf)
        except LayoutInesperadoError as exc:
            falhas.append((pdf, str(exc)))
            registrar(f"  [FALHA] {pdf.name}: {exc}")
            continue
        except Exception as exc:  # nunca interromper o lote por um arquivo ruim
            falhas.append((pdf, f"erro inesperado: {exc}"))
            registrar(f"  [FALHA] {pdf.name}: erro inesperado: {exc}")
            continue

        acima = filtrar_por_faltas(alunos, limite)
        alunos_filtrados.extend(acima)
        total_analisado += len(alunos)
        processados += 1

        info = alunos[0].turma_info
        contexto = " | ".join(x for x in (info.turma, info.turno) if x)
        registrar(
            f"  [OK] {pdf.name}: {len(alunos)} aluno(s)"
            + (f" ({contexto})" if contexto else "")
            + f" -> {len(acima)} acima do limite"
        )

    return ResultadoLote(alunos_filtrados, total_analisado, falhas, processados)


def listar_pdfs(caminho: str | Path, recursivo: bool = False) -> list[Path]:
    """Resolve o argumento de entrada em uma lista de PDFs."""
    caminho = Path(caminho)
    if caminho.is_file():
        return [caminho]
    if caminho.is_dir():
        padrao = "**/*.pdf" if recursivo else "*.pdf"
        return sorted(p for p in caminho.glob(padrao) if p.is_file())
    raise FileNotFoundError(f"caminho não encontrado: {caminho}")


__all__ = [
    "Aluno",
    "Turma",
    "ResultadoLote",
    "LayoutInesperadoError",
    "extrair_alunos",
    "filtrar_por_faltas",
    "processar_lote",
    "listar_pdfs",
    "parse_cabecalho",
    "parse_linha_aluno",
]
