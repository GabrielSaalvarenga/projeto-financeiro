# Projeto Financeiro — código

Antes de qualquer trabalho, ler a Nota de Ouro do cofre:
`~/Library/CloudStorage/OneDrive-Pessoal/Obsidian/Obsidian Pessoal - Meu cofre/Projeto Financeiro/00 - Meta/Nota de Ouro Projeto Financeiro.md`
Documentação da automação no cofre: `09 - Automações/Painel Financeiro - App.md`.

## Regras invioláveis
- **Somente leitura.** Nenhum código pode pagar, transferir, iniciar Pix, negociar ou movimentar dinheiro.
  Só chamar endpoints de consulta (GET) — Pluggy: accounts/transactions/bills/investments; Binance: account/earn/ticker.
- Segredos só no `.env` (gitignored). No cofre vai, no máximo, o *nome* da variável.
- Nunca gravar número de conta/cartão em claro (o OFX guarda hash).
- A exportação para o cofre escreve só em `OBSIDIAN_NOTE` e só com `--write`. Toda mudança no cofre feita por
  script entra no Log como `automação … — via Code`.

## Mapa
- `financas/connectors/` — Pluggy (Inter + XP via Open Finance), Binance
- `financas/importers/` — OFX (plano B); contas de consumo: `bills_folder` (pasta FIN_BILLS_DIR → entrada/importadas/revisar,
  fornecedor reconhecido pelo texto, **sem IA**), `cemig_pdf` (leitor da Cemig), `utilities` (gravação com mescla)
- Portável: nenhum caminho da máquina no código — tudo por variável de ambiente (`.env.example`)
- `financas/categorize.py` + `rules.yaml` — categorias; `nao_gasto` = movimentações que não contam como gasto
- `financas/analytics.py` — gastos, recorrentes, previsão, empréstimos (casamento por Pix), carro, patrimônio
- `financas/ui/app.py` — painel Streamlit · `financas/cli.py` — sync | recategorize | export | demo
- Dados: `data/financas.db` (SQLite) · inbox OFX: `data/inbox/ofx` · contas: `data/contas/` (ou FIN_BILLS_DIR)
