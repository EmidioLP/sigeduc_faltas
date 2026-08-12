# Mapa de Faltas — SIGEduc

Lê relatórios **"Mapa de Frequência Sintético – Número de Faltas"** do Portal SIGEduc
(Secretaria Municipal de Educação) em PDF e gera um novo PDF com os alunos que
ultrapassaram um limite de faltas no ano letivo.

O relatório de saída traz **faltas e frequência mês a mês** (apenas os meses já
lançados no sistema) ao lado dos totais do ano — Abonadas, Faltas, Aulas e Frequência
geral — agrupados por turma.

Funciona com um único PDF ou com uma pasta inteira. **É gerado um PDF por escola**,
`relatorio_faltas_NOME_DA_ESCOLA.pdf`, reunindo todas as turmas daquela escola em
seções — cada uma com seu turno, professor(a) e componente.

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
| `--saida` | pasta de entrada | pasta onde salvar os relatórios |
| `--consolidado` | desligado | gera um único PDF com todas as escolas |
| `--recursivo` | desligado | ao receber uma pasta, procura PDFs nas subpastas |
| `--verboso` | desligado | lista os alunos filtrados, mês a mês, no console |

`--saida` também aceita um caminho `.pdf`, respeitado quando há uma escola só ou junto
de `--consolidado`; com várias escolas, a pasta desse caminho é usada e os nomes saem
por escola.

Escolas processadas em que ninguém passou do limite também ganham um relatório, dizendo
isso — arquivo nenhum seria ambíguo. E PDFs já gerados pelo app (`relatorio_faltas*.pdf`)
são ignorados na leitura, então salvar a saída na mesma pasta dos mapas não quebra a
execução seguinte.

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

- **Leitura por coordenadas, não por ordem**: cada valor é atribuído à coluna cujo
  centro (em pontos) está mais próximo do seu, usando as posições dos cabeçalhos
  `FEV MAR ABR ...` e `F. Freq.`. Isso é essencial porque células vazias não ocupam
  espaço no texto extraído: um aluno sem lançamento em um mês do meio faria todos os
  pares seguintes escorregarem para o mês errado se fossem lidos em sequência. `*`
  conta como zero falta.
- **Conferência automática**: a soma das faltas mensais é comparada com a coluna
  `Faltas`; qualquer divergência vira aviso no console, já que o relatório do SIGEduc
  é internamente consistente e diferença ali indica leitura errada.
- **Reserva**: se a grade de colunas não for reconhecida, o parser cai para leitura
  textual — pega o `Nº`, o nome e os **4 últimos valores da linha** (`Abonadas`,
  `Faltas`, `Aulas`, `Freq.`), sem o detalhamento mensal.
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
