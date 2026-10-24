# Projeto Financeiro — Painel

Um painel pessoal, **somente leitura**, que junta num só lugar seus gastos, cartão, previsão do mês,
empréstimos, carro, investimentos e contas de luz e água. Roda no seu computador, com os seus dados.

## Sobre este projeto

Este programa foi **escrito inteiramente pelo [Claude](https://claude.com/claude-code)** (a IA da Anthropic), a
pedido de uma **pessoa que não sabe programar**. Ele nasceu para resolver uma necessidade pessoal: enxergar o
dinheiro de contas diferentes (Inter, XP, Binance, contas de consumo) sem planilha e sem entregar a senha do banco
para ninguém.

Estou disponibilizando porque pode ser útil para mais gente. Algumas coisas para você saber antes:

- **Foi feito para o meu uso.** Categorias, regras e leitores de conta refletem a minha realidade (por exemplo, os
  PDFs de fatura da Cemig, da Cesama e da EDP Espírito Santo). No seu caso, talvez precise ajustar.
- **Sem garantia.** Use por sua conta e risco (veja a licença). Confira os números: o painel ajuda a enxergar, não
  substitui conferir o extrato do banco.
- **Não é aconselhamento financeiro.** Ele mostra dados e faz contas simples; não recomenda investimentos.
- **O código foi escrito por IA e quem mantém não é programadora(o).** Sugestões e correções são bem-vindas
  (aba *Issues* aqui no GitHub), mas a resposta pode demorar.

## Segurança: o que ele faz e não faz

- 🔒 **Somente leitura.** O painel só consulta. Ele **nunca** paga, transfere, faz Pix ou negocia nada. Só usa
  consultas (GET) nas APIs, e a Binance recusa chave que possa negociar ou sacar.
- 💻 **Seus dados ficam no seu computador.** Não existe servidor do projeto no meio: o painel fala direto com a
  Pluggy e a Binance usando **as suas chaves**, guardadas só na sua instalação (arquivo `.env`, nunca no banco nem
  nos backups).
- 🧠 **Funciona sem IA.** A IA escreveu o programa, mas ele não chama nenhuma IA ao rodar: categorias, leitura de
  PDF e cálculos são regras fixas.
- ⚠️ **O painel não tem senha.** Use no seu computador. Não o exponha na internet, porque quem abrir poderia trocar
  as chaves.

## O que ele mostra

| Aba | Para que serve |
|---|---|
| **Começar** | Visão geral e passo a passo para conectar bancos e Binance |
| **Visão geral** | Investimentos, saldo, gasto do mês, o que tem a receber, entradas x saídas e patrimônio |
| **Gastos** | Para onde vai o dinheiro, por categoria, com ranking e gastos recorrentes |
| **Cartão** | Faturas, parcelas futuras e quanto falta pagar |
| **Previsão** | Estimativa dos próximos meses (salário, recorrentes, parcelas, contas) |
| **Contas de consumo** | Luz (Cemig/EDP) e água (Cesama): histórico, consumo, preço do kWh |
| **Empréstimos** | O que você emprestou (com juros e parcelas) e o que você deve ao banco |
| **Carro** | Km, combustível, revisão e custo por km |
| **Investimentos** | Posições da XP e da Binance |
| **Sincronizar** | Busca os dados novos nos bancos e importa PDFs/OFX |
| **Configurações** | Tema claro/escuro, conexões (chaves), backup |

## Como instalar

Escolha **um** dos dois caminhos. Em ambos você começa baixando o projeto.

### Passo 0 — Baixar o projeto

**Jeito mais fácil (sem Git):** nesta página do GitHub, clique no botão verde **Code → Download ZIP**, descompacte
e lembre onde ficou a pasta `projeto-financeiro-main`.

**Com Git** (se você já usa):
```bash
git clone https://github.com/GabrielSaalvarenga/projeto-financeiro.git
cd projeto-financeiro
```

Para abrir um terminal dentro da pasta: no **Mac**, clique com o botão direito na pasta e escolha *Serviços →
Novo Terminal na Pasta*; no **Windows**, abra a pasta, clique na barra de endereço, digite `cmd` e aperte Enter.

---

### Caminho A — Rodar direto no computador (precisa do Python)

**Pré-requisito: Python 3.12.** O programa foi desenvolvido e testado com ele. Para ver se você já tem, no terminal:

```bash
python3 --version      # Mac/Linux
py --version           # Windows
```

Se não aparecer `3.12` (ou parecido), instale em **[python.org/downloads](https://www.python.org/downloads/)**.
No Windows, na primeira tela do instalador, **marque "Add python.exe to PATH"**.

Dentro da pasta do projeto, rode (uma vez só):

**Mac / Linux**
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
**Windows**
```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Para abrir o painel (toda vez que quiser usar):

**Mac / Linux**
```bash
.venv/bin/streamlit run financas/ui/app.py
```
**Windows**
```bat
.venv\Scripts\streamlit run financas\ui\app.py
```

O navegador abre sozinho em **http://localhost:8501**. Para fechar, volte ao terminal e aperte `Ctrl + C`.

> O Windows ainda não foi testado; os comandos acima seguem o padrão do Python. Se algo falhar, abra uma
> *Issue* com a mensagem de erro.

---

### Caminho B — Rodar em container (não precisa instalar Python)

Aqui o Python já vem dentro do container. O **único pré-requisito é o Docker**: instale o
**[Docker Desktop](https://www.docker.com/products/docker-desktop/)** (Mac, Windows ou Linux) e deixe-o aberto.

Dentro da pasta do projeto:

```bash
docker compose -f docker-compose.simples.yml up -d --build
```

A primeira vez demora alguns minutos (baixa e monta a imagem). Depois, abra **http://localhost:8501**.

| Para… | Comando |
|---|---|
| Parar | `docker compose -f docker-compose.simples.yml down` |
| Subir de novo | `docker compose -f docker-compose.simples.yml up -d` |
| Usar outra porta (ex.: 8600) | `PORTA=8600 docker compose -f docker-compose.simples.yml up -d` |

Os seus dados (banco, chaves, backups, PDFs) ficam na pasta **`dados/`**, dentro do projeto, fora do container.
Apagar ou recriar o container **não apaga** seus dados.

> Os arquivos `docker-compose.yml` e `ambientes` são do ambiente de desenvolvimento do autor (produção + testes).
> Para só usar o painel, ignore-os e use o `docker-compose.simples.yml`.

---

## Primeiro uso

1. Abra o painel. Numa instalação nova ele já abre na aba **Começar**, que explica tudo com o passo a passo.
2. Conecte as fontes em **Configurações → Conexões** (cole as chaves e clique em *Testar e salvar*):
   - **Pluggy** (Open Finance: Inter, XP e outros): crie as chaves em [dashboard.pluggy.ai](https://dashboard.pluggy.ai).
     O teste gratuito dura cerca de 15 dias: conecte todos os seus bancos dentro desse prazo (o passo a passo
     completo está na aba *Começar*).
   - **Binance**: crie uma chave com **apenas "Enable Reading"** marcado, sem trade e sem saque.
3. Vá em **Sincronizar** e clique em **Sincronizar tudo**. As outras abas se enchem de dados.

**Quer só ver como funciona, sem conectar nada?** Gere dados fictícios (Caminho A):

```bash
# Mac / Linux
FIN_DATA_DIR=data/demo .venv/bin/python -m financas.cli demo
FIN_DATA_DIR=data/demo .venv/bin/streamlit run financas/ui/app.py
```
```powershell
# Windows (PowerShell)
$env:FIN_DATA_DIR="data/demo"; .venv\Scripts\python -m financas.cli demo
$env:FIN_DATA_DIR="data/demo"; .venv\Scripts\streamlit run financas\ui\app.py
```

## Como atualizar para uma versão nova

- **Baixou o ZIP:** baixe o ZIP novo e copie para a pasta nova os seus dados (`data/` no Caminho A, `dados/` no
  Caminho B) e o arquivo `.env`.
- **Usou Git:** `git pull`. No Caminho B, rode também `docker compose -f docker-compose.simples.yml up -d --build`.

O painel avisa na barra lateral quando sai versão nova (dá para desligar em Configurações › Atualizações).
As novidades de cada versão estão no [CHANGELOG](CHANGELOG.md).

## Guia de uso

**Contas de consumo (Cemig, Cesama, EDP).** Coloque o PDF da fatura em `<pasta de contas>/entrada/` (por padrão
`data/contas/`, ou a pasta definida em `FIN_BILLS_DIR`, que pode ser uma pasta sincronizada como OneDrive). No
próximo sincronizar, o fornecedor é reconhecido pelo texto da fatura e a conta é lançada por regras fixas, **sem
IA**. Deu certo → `importadas/`; não reconheceu → `revisar/`, com um `.txt` explicando o motivo (aí é só lançar
pelo formulário do painel). O leitor da EDP é para o modelo da EDP Espírito Santo.

**Backup.** Na aba Configurações: recorrência do backup automático (padrão 1x ao dia) e botão de backup manual.
Cada backup é um `.zip` com o banco e os PDFs importados, em `<pasta de dados>/backups/`. O automático é feito
quando o painel abre ou a sincronização roda; ficam os 30 mais recentes e os manuais nunca são apagados sozinhos.
O menu lateral **"Ver dados de"** abre o painel inteiro com os dados de um backup, em modo só leitura.

**Categorias.** As regras ficam em `rules.yaml` (expressões regulares, a primeira que casar vence). Edite à
vontade e clique em *Recategorizar*. Correções manuais pela tela sempre vencem as regras.

**Empréstimos.** Juros sobre o valor **total** pelo prazo todo, com parcela = total ÷ nº de parcelas (regra do
autor; a tabela Price só entra se pedida). Há juros simples e compostos, baixa dos recebimentos e cálculo da taxa
efetiva na quitação.

## Módulos do programa

Tudo está na pasta `financas/`. Cada arquivo faz uma coisa:

| Módulo | O que faz |
|---|---|
| `ui/app.py` | O painel (Streamlit): todas as abas e gráficos |
| `ui/guide.py` | A aba **Começar**: textos e passo a passo (não guarda nem pede chaves) |
| `ui/theme.py` | O visual: cores claro/escuro, cartões, tabelas e textos |
| `cli.py` | Comandos de terminal: `sync`, `contas`, `backup`, `recategorize`, `export`, `demo` |
| `sync.py` | Orquestra as coletas; cada fonte falha sozinha sem derrubar as outras |
| `connectors/pluggy.py` | Open Finance via Pluggy (contas, transações, faturas, investimentos): só consultas |
| `connectors/binance.py` | Saldos da Binance: só consultas, recusa chave com permissão de negociar/sacar |
| `importers/bills_folder.py` | Vigia a pasta de contas e lança os PDFs que chegam |
| `importers/cemig_pdf.py`, `cesama_pdf.py`, `edp_pdf.py` | Leitores de PDF de cada fornecedor, com regras fixas |
| `importers/utilities.py` | Grava as contas de consumo, mesclando fontes |
| `importers/ofx.py` | Plano B ao Open Finance: importa extratos OFX do banco |
| `importers/wise.py` | Importação única de um extrato CSV da Wise (uso pessoal do autor) |
| `categorize.py` + `rules.yaml` | Dá categoria a cada transação (prioridade: correção manual → regras → padrão) |
| `analytics.py` | Cálculos: gastos, recorrentes, previsão, empréstimos, carro, patrimônio |
| `loans.py` | Empréstimos: juros, parcelas, baixa dos recebimentos e taxa efetiva (funções puras) |
| `db.py` | Banco SQLite local, fonte única dos dados |
| `config.py` | Caminhos e variáveis de ambiente (nada fixo da máquina do autor) |
| `connections.py` | Conexões configuráveis pela tela: campos, teste de leitura e gravação no `.env` |
| `settings.py` | Preferências (tema, recorrência do backup), guardadas no banco |
| `backup.py` | Backup `.zip` manual/automático e visualização só leitura |
| `obsidian.py` | Opcional: exporta um resumo para uma nota do Obsidian (só com `--write`) |
| `demo.py` | Gera os dados fictícios para experimentar |

## Variáveis de ambiente

Tudo é configurável sem editar código. O arquivo `.env.example` lista as variáveis (chaves da Pluggy e da
Binance, pasta de dados `FIN_DATA_DIR`, pasta de contas `FIN_BILLS_DIR`, etc.). Normalmente você não precisa
mexer: a aba **Configurações → Conexões** grava o `.env` por você.

## Testes

```bash
.venv/bin/python -m pytest -q        # Mac / Linux
.venv\Scripts\python -m pytest -q    # Windows
```

## Para quem quer mexer no código

- `docker-compose.yml` + `./ambientes status | clonar | promover | parar` reproduzem o fluxo do autor: **prod**
  (código de uma tag do Git, dados reais), **dev** (código da pasta, clone dos dados de prod) e **novo**
  (instalação vazia, para testar o primeiro uso).
- Fonte nova de dados = mais um item em `financas/connections.py` e um conector em `financas/connectors/`.
- Regra de ouro do projeto: **nenhum código pode pagar, transferir ou movimentar dinheiro.** Só consultas.

## Licença

[MIT](LICENSE): você pode usar, copiar e modificar, mantendo o aviso de copyright. O software é fornecido "como
está", sem garantia de nenhum tipo.
