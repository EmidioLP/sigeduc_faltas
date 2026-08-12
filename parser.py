"""Extração e parsing dos PDFs 'Mapa de Frequência Sintético' do Portal SIGEduc.

O parsing é feito pelas coordenadas das colunas, e não pela ordem dos valores no
texto: quando um mês não tem lançamento, a célula sai vazia e os valores
seguintes escorregariam para o mês errado se fossem lidos apenas em sequência.
Cada valor é atribuído à coluna cujo centro está mais próximo do seu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


class LayoutInesperadoError(Exception):
    """PDF que não segue o layout esperado do Mapa de Frequência Sintético."""


MESES = ["FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
COLUNAS_TOTAIS = ["Abonadas", "Faltas", "Aulas", "Freq."]


@dataclass(frozen=True)
class MesFreq:
    """Faltas e frequência de um aluno em um mês."""

    faltas: int
    frequencia: float | None = None

    @property
    def frequencia_fmt(self) -> str:
        if self.frequencia is None:
            return "—"
        return f"{self.frequencia:.1f}".replace(".", ",") + "%"


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
    meses: dict[str, MesFreq] = field(default_factory=dict)
    arquivo: str = ""

    @property
    def frequencia_fmt(self) -> str:
        return f"{self.frequencia:.1f}".replace(".", ",") + "%"

    def mes(self, nome: str) -> MesFreq | None:
        return self.meses.get(nome)


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
VAZIOS = {"*", "-", "--", ""}


def _e_valor(token: str) -> bool:
    if token in VAZIOS:
        return True
    return bool(RE_VALOR.match(token)) and any(c.isdigit() for c in token)


def _para_numero(token: str) -> float:
    """Converte '71,3%' -> 71.3, '1.234' -> 1234.0, '*' -> 0.0."""
    if token in VAZIOS:
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


# --- Geometria da tabela ---------------------------------------------------


@dataclass
class Grade:
    """Posição horizontal (centro em pontos) de cada coluna da tabela."""

    meses: list[tuple[str, float, float]]  # (mês, centro de "F.", centro de "Freq.")
    totais: dict[str, float]               # Abonadas / Faltas / Aulas / Freq.
    inicio_valores: float                  # à esquerda disso está o nome do aluno
    tolerancia: float                      # distância máxima valor <-> coluna

    def centros(self) -> list[tuple[str, float]]:
        saida: list[tuple[str, float]] = []
        for mes, cx_f, cx_freq in self.meses:
            saida.append((f"{mes}:F", cx_f))
            saida.append((f"{mes}:Q", cx_freq))
        for nome, cx in self.totais.items():
            saida.append((f"T:{nome}", cx))
        return saida


def _centro(palavra: dict) -> float:
    return (palavra["x0"] + palavra["x1"]) / 2


def _agrupar_linhas(palavras: list[dict], tolerancia: float = 3.0) -> list[list[dict]]:
    """Agrupa palavras em linhas visuais pela coordenada vertical."""
    linhas: list[list[dict]] = []
    atual: list[dict] = []
    referencia: float | None = None

    for palavra in sorted(palavras, key=lambda w: (w["top"], w["x0"])):
        if referencia is None or abs(palavra["top"] - referencia) <= tolerancia:
            if referencia is None:
                referencia = palavra["top"]
            atual.append(palavra)
        else:
            linhas.append(sorted(atual, key=lambda w: w["x0"]))
            atual = [palavra]
            referencia = palavra["top"]

    if atual:
        linhas.append(sorted(atual, key=lambda w: w["x0"]))
    return linhas


def _extrair_grade(linhas: list[list[dict]]) -> Grade | None:
    """Descobre a posição das colunas a partir das linhas de cabeçalho da tabela."""
    meses_pos: list[tuple[str, float]] = []
    pares: list[tuple[float, float]] = []
    totais: dict[str, float] = {}

    for linha in linhas:
        textos = [w["text"] for w in linha]

        # Linha dos nomes dos meses ("FEV MAR ABR ...").
        achados = [(t, _centro(w)) for t, w in zip(textos, linha) if t in MESES]
        if len(achados) >= 2 and len(achados) > len(meses_pos):
            meses_pos = achados

        # Linha dos sub-cabeçalhos ("F. Freq. F. Freq. ...").
        if len(linha) >= 4 and all(t in {"F.", "Freq."} for t in textos):
            atual: list[tuple[float, float]] = []
            i = 0
            while i < len(linha) - 1:
                if textos[i] == "F." and textos[i + 1] == "Freq.":
                    atual.append((_centro(linha[i]), _centro(linha[i + 1])))
                    i += 2
                else:
                    i += 1
            if len(atual) > len(pares):
                pares = atual

        # Linha dos totais ("Nº Estudante Abonadas Faltas Aulas Freq.").
        if "Abonadas" in textos and "Aulas" in textos:
            for nome in COLUNAS_TOTAIS:
                if nome in textos:
                    totais[nome] = _centro(linha[textos.index(nome)])

    if not meses_pos or not pares or len(totais) < len(COLUNAS_TOTAIS):
        return None

    # Cada par (F., Freq.) pertence ao mês cujo rótulo está mais próximo.
    colunas_meses: list[tuple[str, float, float]] = []
    for cx_f, cx_freq in pares:
        meio = (cx_f + cx_freq) / 2
        mes = min(meses_pos, key=lambda mp: abs(mp[1] - meio))[0]
        colunas_meses.append((mes, cx_f, cx_freq))

    # Sem meses repetidos: se o pareamento ficou ambíguo, a grade não é confiável.
    nomes = [m for m, _, _ in colunas_meses]
    if len(set(nomes)) != len(nomes):
        return None

    todos = sorted(
        [cx for _, cx_f, cx_q in colunas_meses for cx in (cx_f, cx_q)]
        + list(totais.values())
    )
    menor_espaco = min(
        (b - a for a, b in zip(todos, todos[1:])), default=20.0
    )
    return Grade(
        meses=colunas_meses,
        totais=totais,
        inicio_valores=todos[0] - menor_espaco / 2,
        tolerancia=max(menor_espaco / 2, 4.0),
    )


# --- Linhas de aluno -------------------------------------------------------


def parse_linha_aluno(linha: str) -> dict | None:
    """Interpreta uma linha da tabela pelo texto (usado quando não há grade).

    O nome vai do Nº até o primeiro token numérico; os 4 últimos valores da
    linha são sempre Abonadas, Faltas, Aulas e Freq. geral.
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
        "meses": {},
    }


def parse_linha_grade(linha: list[dict], grade: Grade) -> dict | None:
    """Interpreta uma linha de aluno usando as coordenadas das colunas."""
    if not linha:
        return None

    primeiro = linha[0]
    if not primeiro["text"].isdigit() or _centro(primeiro) >= grade.inicio_valores:
        return None

    nome_partes = [
        w["text"]
        for w in linha[1:]
        if _centro(w) < grade.inicio_valores
    ]
    nome = " ".join(nome_partes)
    if not RE_TEM_LETRA.search(nome) or "total de faltas" in nome.lower():
        return None

    # Atribui cada valor à coluna cujo centro está mais próximo.
    centros = grade.centros()
    celulas: dict[str, str] = {}
    for palavra in linha[1:]:
        cx = _centro(palavra)
        if cx < grade.inicio_valores:
            continue
        chave, distancia = min(
            ((c, abs(cx - x)) for c, x in centros), key=lambda item: item[1]
        )
        if distancia > grade.tolerancia or chave in celulas:
            continue
        celulas[chave] = palavra["text"]

    try:
        abonadas = _para_numero(celulas.get("T:Abonadas", "0"))
        faltas = _para_numero(celulas["T:Faltas"])
        aulas = _para_numero(celulas["T:Aulas"])
        freq = _para_numero(celulas["T:Freq."])
    except (KeyError, ValueError):
        return None

    if aulas <= 0 or faltas < 0 or not 0 <= freq <= 100:
        return None

    meses: dict[str, MesFreq] = {}
    for mes, _, _ in grade.meses:
        bruto_f = celulas.get(f"{mes}:F")
        if bruto_f is None:
            continue
        bruto_q = celulas.get(f"{mes}:Q")
        try:
            faltas_mes = int(_para_numero(bruto_f))
            freq_mes = None if bruto_q is None else _para_numero(bruto_q)
        except ValueError:
            continue
        meses[mes] = MesFreq(faltas_mes, freq_mes)

    return {
        "numero": int(primeiro["text"]),
        "nome": nome,
        "abonadas": int(abonadas),
        "faltas": int(faltas),
        "aulas": int(aulas),
        "frequencia": freq,
        "meses": meses,
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
    grade_atual: Grade | None = None
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

            linhas = _agrupar_linhas(pagina.extract_words())
            grade_pagina = _extrair_grade(linhas)
            if grade_pagina:
                grade_atual = grade_pagina

            da_pagina: list[dict] = []
            if grade_atual:
                da_pagina = [
                    d
                    for d in (parse_linha_grade(linha, grade_atual) for linha in linhas)
                    if d
                ]
            if not da_pagina:
                # Sem grade reconhecível (ou nenhuma linha casou): lê pelo texto,
                # sem o detalhamento mensal.
                da_pagina = [
                    d
                    for d in (
                        parse_linha_aluno(" ".join(w["text"] for w in linha))
                        for linha in linhas
                    )
                    if d
                ]

            alunos.extend(
                Aluno(**dados, turma_info=meta_atual or Turma(), arquivo=caminho.name)
                for dados in da_pagina
            )

    if not alunos:
        motivo = (
            "nenhuma linha de aluno reconhecida"
            if viu_titulo
            else "não parece ser um Mapa de Frequência Sintético do SIGEduc"
        )
        raise LayoutInesperadoError(motivo)

    return alunos


def meses_lancados(alunos: list[Aluno]) -> list[str]:
    """Meses com algum lançamento no grupo, na ordem do ano letivo."""
    presentes = {mes for aluno in alunos for mes in aluno.meses}
    return [mes for mes in MESES if mes in presentes]


def divergencias_de_soma(alunos: list[Aluno]) -> list[tuple[str, int, int]]:
    """Alunos em que a soma dos meses não bate com a coluna 'Faltas'.

    O relatório do SIGEduc é internamente consistente, então divergência aqui
    indica leitura errada das colunas — vale avisar em vez de silenciar.
    """
    fora: list[tuple[str, int, int]] = []
    for aluno in alunos:
        if not aluno.meses:
            continue
        soma = sum(m.faltas for m in aluno.meses.values())
        if soma != aluno.faltas:
            fora.append((aluno.nome, soma, aluno.faltas))
    return fora


def filtrar_por_faltas(alunos: list[Aluno], limite: float) -> list[Aluno]:
    """Alunos cujo total de faltas no ano ultrapassa o limite."""
    return [a for a in alunos if a.faltas > limite]


@dataclass
class ResultadoLote:
    alunos: list[Aluno]          # já filtrados pelo limite
    total_analisado: int         # todos os alunos lidos, antes do filtro
    falhas: list[tuple[Path, str]]
    processados: int


def processar_lote(pdfs: list[Path], limite: float, log=None) -> ResultadoLote:
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
        meses = meses_lancados(alunos)
        contexto = " | ".join(x for x in (info.turma, info.turno) if x)
        registrar(
            f"  [OK] {pdf.name}: {len(alunos)} aluno(s)"
            + (f" ({contexto})" if contexto else "")
            + (f" | meses: {', '.join(meses)}" if meses else "")
            + f" -> {len(acima)} acima do limite"
        )

        for nome, soma, total in divergencias_de_soma(alunos):
            registrar(
                f"     [ATENCAO] {nome}: soma dos meses ({soma}) difere do total"
                f" impresso ({total})"
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
    "MesFreq",
    "Turma",
    "ResultadoLote",
    "LayoutInesperadoError",
    "MESES",
    "divergencias_de_soma",
    "extrair_alunos",
    "filtrar_por_faltas",
    "meses_lancados",
    "processar_lote",
    "listar_pdfs",
    "parse_cabecalho",
    "parse_linha_aluno",
    "parse_linha_grade",
]
