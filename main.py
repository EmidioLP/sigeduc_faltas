"""CLI: filtra alunos com excesso de faltas nos Mapas de Frequência do SIGEduc.

Uso:
    python main.py relatorio.pdf
    python main.py pasta_com_pdfs --limite 30 --saida faltosos.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from parser import listar_pdfs, processar_lote
from report_generator import gerar_relatorio, gerar_relatorios_por_escola

LIMITE_PADRAO = 25.0
SAIDA_PADRAO = "relatorio_faltas.pdf"


def _console_utf8() -> None:
    """Evita acentos quebrados no console do Windows (cp850/cp1252)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sigeduc-faltas",
        description=(
            "Processa relatórios 'Mapa de Frequência Sintético' (Portal SIGEduc) e "
            "gera um PDF com os alunos que ultrapassaram o limite de faltas no ano."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("caminho", help="arquivo PDF ou pasta contendo vários PDFs")
    p.add_argument(
        "--limite",
        type=float,
        default=LIMITE_PADRAO,
        help="número de faltas acima do qual o aluno é listado",
    )
    p.add_argument(
        "--saida",
        default=None,
        help=(
            "pasta onde salvar os relatórios (padrão: a pasta de entrada). "
            "Aceita também um caminho .pdf, respeitado quando há uma escola só "
            "ou junto de --consolidado"
        ),
    )
    p.add_argument(
        "--consolidado",
        action="store_true",
        help="gera um único PDF com todas as escolas, em vez de um por escola",
    )
    p.add_argument(
        "--recursivo",
        action="store_true",
        help="ao receber uma pasta, procurar PDFs também nas subpastas",
    )
    p.add_argument(
        "--verboso",
        action="store_true",
        help="listar no console todos os alunos filtrados",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    _console_utf8()
    args = montar_parser().parse_args(argv)

    try:
        pdfs = listar_pdfs(args.caminho, args.recursivo)
    except FileNotFoundError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    if not pdfs:
        print(f"Erro: nenhum PDF encontrado em {args.caminho}", file=sys.stderr)
        return 2

    print(f"Processando {len(pdfs)} PDF(s)...\n")
    resultado = processar_lote(pdfs, args.limite, log=print)
    todos, falhas = resultado.alunos, resultado.falhas
    total_analisado = resultado.total_analisado

    if args.verboso and todos:
        print("\nAlunos acima do limite:")
        for aluno in sorted(todos, key=lambda a: (-a.faltas, a.nome)):
            print(
                f"  {aluno.faltas:>4} faltas ({aluno.frequencia_fmt:>6})  {aluno.nome}"
                f"  [{aluno.turma_info.turma or '—'}]"
            )
            detalhe = "  ".join(
                f"{mes} {registro.faltas}/{registro.frequencia_fmt}"
                for mes, registro in aluno.meses.items()
            )
            if detalhe:
                print(f"        {detalhe}")

    entrada = Path(args.caminho)
    destino = Path(args.saida) if args.saida else (
        entrada if entrada.is_dir() else entrada.parent
    )
    e_arquivo = destino.suffix.lower() == ".pdf"

    print(f"\n{len(todos)} aluno(s) com mais de {args.limite:g} faltas.")

    if args.consolidado:
        arquivo = destino if e_arquivo else destino / SAIDA_PADRAO
        saidas = [gerar_relatorio(todos, arquivo, args.limite, total_analisado)]
    elif e_arquivo and len(resultado.total_por_escola) <= 1:
        saidas = [gerar_relatorio(todos, destino, args.limite, total_analisado)]
    else:
        if e_arquivo:
            print(
                f"Aviso: {len(resultado.total_por_escola)} escolas encontradas;"
                f" gerando um PDF por escola em {destino.parent.resolve()}"
                " (use --consolidado para um arquivo único).",
                file=sys.stderr,
            )
            destino = destino.parent
        saidas = gerar_relatorios_por_escola(
            todos, destino, args.limite, resultado.total_por_escola
        )

    print(f"{len(saidas)} relatório(s) gerado(s):")
    for arquivo in saidas:
        print(f"  - {arquivo.resolve()}")
    if falhas:
        print(f"\n{len(falhas)} arquivo(s) não processado(s):", file=sys.stderr)
        for pdf, motivo in falhas:
            print(f"  - {pdf.name}: {motivo}", file=sys.stderr)

    if falhas and not todos:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
