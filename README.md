# Mapa de Faltas — SIGEduc

Lê relatórios **"Mapa de Frequência Sintético – Número de Faltas"** do Portal SIGEduc
(Secretaria Municipal de Educação) em PDF e gera um novo PDF com os alunos que
ultrapassaram um limite de faltas no ano letivo.

Funciona com um único PDF ou com uma pasta inteira, consolidando várias turmas em um
só relatório e mantendo turma, turno, escola e professor(a) de cada aluno.

## Como usar

### Interface gráfica

```
python gui.py
```

Escolher o PDF (ou a pasta) → conferir o limite → **Gerar relatório**.

### Linha de comando

```bash
python main.py caminho/do/mapa.pdf
```

```bash
python main.py pasta_com_pdfs --limite 30 --saida faltosos.pdf --verboso
```

| Opção | Padrão | Descrição |
|---|---|---|
| `--limite` | `25` | lista alunos com **mais** faltas que este valor |
| `--saida` | `relatorio_faltas.pdf` | caminho do PDF de saída |
| `--recursivo` | desligado | ao receber uma pasta, procura PDFs nas subpastas |
| `--verboso` | desligado | lista os alunos filtrados no console |

## Instalação

```bash
pip install -r requirements.txt
```

Requer Python 3.10+ (usa `X | Y` em anotações de tipo).

## Gerar os executáveis

```bash
pip install pyinstaller
```

Depois execute `build.bat` (Windows). Saem dois arquivos em `dist/`:

- **`Mapa de Faltas.exe`** — interface gráfica, para quem não usa terminal
- **`mapa-faltas-cli.exe`** — mesma ferramenta em linha de comando

Ambos são autocontidos: não exigem Python instalado na máquina de destino. Por não
terem assinatura digital, o SmartScreen pede *Mais informações → Executar assim mesmo*
na primeira execução.

## Estrutura

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | CLI (argparse) |
| `gui.py` | interface tkinter, ponto de entrada do executável |
| `parser.py` | leitura do PDF com pdfplumber, cabeçalho e linhas de aluno |
| `report_generator.py` | geração do PDF de saída com reportlab |
| `build.bat` | compilação dos executáveis via PyInstaller |

## Como o PDF de entrada é interpretado

- **Linha de aluno**: os tokens são separados; o nome vai do `Nº` até o primeiro valor
  numérico, e os **4 últimos valores da linha** são sempre `Abonadas`, `Faltas`, `Aulas`
  e `Freq.` geral. Os pares mensais (`F.` / `Freq.`) do meio são ignorados, então não
  importa quantos meses já foram lançados no sistema. `*` conta como zero.
- **Cabeçalho por página**, não por arquivo: um PDF com várias turmas é tratado
  corretamente, e páginas de continuação (sem cabeçalho) herdam os metadados da
  anterior. A linha `Total de faltas da Turma:` é descartada antes da leitura do
  cabeçalho, porque também contém `Turma:`.
- **Escola e professor(a)** vêm na mesma linha, separados por `:`
  (`Escola: CRECHE ARCO IRIS : TALLYTA EDUARDA DA SILVA`).
- **Linhas espúrias** (rodapé de assinaturas, totais da turma, numeração de página) são
  descartadas por filtros de sanidade: mínimo de tokens, `Nº` inicial, `aulas > 0` e
  `0 ≤ freq ≤ 100`.
- **Erros**: um PDF fora do layout gera aviso no console (ou na janela) e o lote
  continua nos demais arquivos.

## Privacidade

Os relatórios do SIGEduc contêm nomes de alunos. O `.gitignore` bloqueia `*.pdf` para
que nenhum dado pessoal seja versionado por engano.
