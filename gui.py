"""Interface gráfica (tkinter) do Mapa de Faltas — SIGEduc.

É o ponto de entrada do executável: nenhuma linha de comando é necessária.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    W,
    X,
    StringVar,
    Tk,
    filedialog,
    messagebox,
    scrolledtext,
)
from tkinter import ttk

from parser import listar_pdfs, processar_lote
from report_generator import gerar_relatorio

TITULO = "Mapa de Faltas — SIGEduc"
LIMITE_PADRAO = 25


def _abrir_no_sistema(caminho: Path) -> None:
    """Abre um arquivo ou pasta no aplicativo padrão do sistema."""
    if sys.platform == "win32":
        os.startfile(caminho)  # noqa: S606 - abertura pelo shell do Windows
    elif sys.platform == "darwin":
        subprocess.run(["open", str(caminho)], check=False)
    else:
        subprocess.run(["xdg-open", str(caminho)], check=False)


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.entrada = StringVar()
        self.saida = StringVar()
        self.limite = StringVar(value=str(LIMITE_PADRAO))
        self.mensagens: queue.Queue[tuple[str, object]] = queue.Queue()
        self.ultimo_relatorio: Path | None = None
        self.processando = False

        root.title(TITULO)
        root.minsize(720, 520)
        self._montar()
        self.root.after(100, self._drenar_fila)

    # --- construção da janela ---------------------------------------------

    def _montar(self) -> None:
        quadro = ttk.Frame(self.root, padding=14)
        quadro.pack(fill=BOTH, expand=True)

        ttk.Label(
            quadro,
            text="Relatório de alunos com excesso de faltas",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor=W)
        ttk.Label(
            quadro,
            text=(
                "Escolha o PDF do Mapa de Frequência Sintético (ou uma pasta com "
                "vários) e clique em Gerar relatório."
            ),
            foreground="#555555",
            wraplength=680,
        ).pack(anchor=W, pady=(2, 12))

        # Entrada
        caixa_entrada = ttk.LabelFrame(quadro, text=" 1. Arquivo ou pasta ", padding=10)
        caixa_entrada.pack(fill=X)
        linha = ttk.Frame(caixa_entrada)
        linha.pack(fill=X)
        ttk.Entry(linha, textvariable=self.entrada).pack(
            side=LEFT, fill=X, expand=True, ipady=2
        )
        ttk.Button(linha, text="Escolher PDF...", command=self._escolher_pdf).pack(
            side=LEFT, padx=(8, 0)
        )
        ttk.Button(linha, text="Escolher pasta...", command=self._escolher_pasta).pack(
            side=LEFT, padx=(6, 0)
        )

        # Limite
        caixa_limite = ttk.LabelFrame(quadro, text=" 2. Limite de faltas ", padding=10)
        caixa_limite.pack(fill=X, pady=(10, 0))
        linha_limite = ttk.Frame(caixa_limite)
        linha_limite.pack(fill=X)
        ttk.Label(linha_limite, text="Listar alunos com MAIS de").pack(side=LEFT)
        ttk.Spinbox(
            linha_limite, from_=0, to=999, width=6, textvariable=self.limite
        ).pack(side=LEFT, padx=6)
        ttk.Label(linha_limite, text="faltas no ano").pack(side=LEFT)

        # Saída
        caixa_saida = ttk.LabelFrame(
            quadro, text=" 3. Onde salvar o relatório ", padding=10
        )
        caixa_saida.pack(fill=X, pady=(10, 0))
        linha_saida = ttk.Frame(caixa_saida)
        linha_saida.pack(fill=X)
        ttk.Entry(linha_saida, textvariable=self.saida).pack(
            side=LEFT, fill=X, expand=True, ipady=2
        )
        ttk.Button(linha_saida, text="Alterar...", command=self._escolher_saida).pack(
            side=LEFT, padx=(8, 0)
        )

        # Ações
        acoes = ttk.Frame(quadro)
        acoes.pack(fill=X, pady=12)
        self.btn_gerar = ttk.Button(
            acoes, text="Gerar relatório", command=self._gerar
        )
        self.btn_gerar.pack(side=LEFT)
        self.btn_abrir = ttk.Button(
            acoes, text="Abrir relatório", command=self._abrir, state="disabled"
        )
        self.btn_abrir.pack(side=LEFT, padx=8)
        # Só aparece durante o processamento (parada, uma barra cheia confunde).
        self.progresso = ttk.Progressbar(acoes, mode="indeterminate", length=160)

        # Log
        ttk.Label(quadro, text="Andamento:").pack(anchor=W)
        self.log = scrolledtext.ScrolledText(
            quadro, height=12, font=("Consolas", 9), wrap="word"
        )
        self.log.pack(fill=BOTH, expand=True, pady=(4, 0))
        self.log.configure(state="disabled")
        self._escrever("Escolha um arquivo ou uma pasta acima para começar.")

    # --- seleção de caminhos ----------------------------------------------

    def _sugerir_saida(self, base: Path) -> None:
        pasta = base if base.is_dir() else base.parent
        self.saida.set(str(pasta / "relatorio_faltas.pdf"))

    def _escolher_pdf(self) -> None:
        caminho = filedialog.askopenfilename(
            title="Escolha o PDF do Mapa de Frequência",
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
        if caminho:
            self.entrada.set(caminho)
            self._sugerir_saida(Path(caminho))

    def _escolher_pasta(self) -> None:
        caminho = filedialog.askdirectory(title="Escolha a pasta com os PDFs")
        if caminho:
            self.entrada.set(caminho)
            self._sugerir_saida(Path(caminho))

    def _escolher_saida(self) -> None:
        caminho = filedialog.asksaveasfilename(
            title="Salvar relatório como",
            defaultextension=".pdf",
            initialfile="relatorio_faltas.pdf",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )
        if caminho:
            self.saida.set(caminho)

    # --- log ---------------------------------------------------------------

    def _escrever(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(END, texto + "\n")
        self.log.see(END)
        self.log.configure(state="disabled")

    def _drenar_fila(self) -> None:
        """Traz para a janela as mensagens emitidas pela thread de processamento."""
        try:
            while True:
                tipo, dado = self.mensagens.get_nowait()
                if tipo == "log":
                    self._escrever(str(dado))
                elif tipo == "fim":
                    self._finalizar(dado)
        except queue.Empty:
            pass
        self.root.after(100, self._drenar_fila)

    # --- processamento -----------------------------------------------------

    def _gerar(self) -> None:
        if self.processando:
            return

        entrada = self.entrada.get().strip().strip('"')
        if not entrada:
            messagebox.showwarning(TITULO, "Escolha um arquivo PDF ou uma pasta.")
            return
        if not Path(entrada).exists():
            messagebox.showerror(TITULO, f"Caminho não encontrado:\n{entrada}")
            return

        try:
            limite = float(self.limite.get().replace(",", "."))
            if limite < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(TITULO, "O limite de faltas deve ser um número.")
            return

        if not self.saida.get().strip():
            self._sugerir_saida(Path(entrada))
        saida = Path(self.saida.get().strip().strip('"'))
        if saida.suffix.lower() != ".pdf":
            saida = saida.with_suffix(".pdf")

        self.processando = True
        self.btn_gerar.configure(state="disabled")
        self.btn_abrir.configure(state="disabled")
        self.progresso.pack(side=RIGHT)
        self.progresso.start(12)
        self.log.configure(state="normal")
        self.log.delete("1.0", END)
        self.log.configure(state="disabled")

        threading.Thread(
            target=self._trabalhar, args=(Path(entrada), limite, saida), daemon=True
        ).start()

    def _trabalhar(self, entrada: Path, limite: float, saida: Path) -> None:
        registrar = lambda msg: self.mensagens.put(("log", msg))  # noqa: E731
        try:
            pdfs = listar_pdfs(entrada, recursivo=True)
            if not pdfs:
                self.mensagens.put(
                    ("fim", ValueError(f"Nenhum PDF encontrado em:\n{entrada}"))
                )
                return

            registrar(f"Processando {len(pdfs)} PDF(s)...\n")
            resultado = processar_lote(pdfs, limite, log=registrar)
            gerar_relatorio(
                resultado.alunos, saida, limite, resultado.total_analisado
            )
            self.mensagens.put(("fim", (resultado, saida, limite)))
        except Exception as exc:  # a janela nunca deve morrer em silêncio
            registrar("\n" + traceback.format_exc())
            self.mensagens.put(("fim", exc))

    def _finalizar(self, dado: object) -> None:
        self.processando = False
        self.progresso.stop()
        self.progresso.pack_forget()
        self.btn_gerar.configure(state="normal")

        if isinstance(dado, Exception):
            self._escrever(f"\nERRO: {dado}")
            messagebox.showerror(TITULO, str(dado))
            return

        resultado, saida, limite = dado  # type: ignore[misc]
        self.ultimo_relatorio = saida
        self.btn_abrir.configure(state="normal")

        limite_fmt = f"{limite:g}"
        self._escrever(
            f"\n{len(resultado.alunos)} aluno(s) com mais de {limite_fmt} faltas"
            f" (de {resultado.total_analisado} analisados)."
        )
        self._escrever(f"Relatório salvo em: {saida.resolve()}")

        aviso = ""
        if resultado.falhas:
            self._escrever(f"\n{len(resultado.falhas)} arquivo(s) não processado(s):")
            for pdf, motivo in resultado.falhas:
                self._escrever(f"  - {pdf.name}: {motivo}")
            aviso = (
                f"\n\nAtenção: {len(resultado.falhas)} arquivo(s) não puderam ser "
                "lidos (veja o andamento)."
            )

        if messagebox.askyesno(
            TITULO,
            f"Relatório gerado com {len(resultado.alunos)} aluno(s) acima de "
            f"{limite_fmt} faltas.{aviso}\n\nDeseja abrir o relatório agora?",
        ):
            self._abrir()

    def _abrir(self) -> None:
        if self.ultimo_relatorio and self.ultimo_relatorio.exists():
            _abrir_no_sistema(self.ultimo_relatorio)


def main() -> int:
    root = Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
