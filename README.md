# Projeto Financeiro — Painel

Visão unificada **somente leitura**: Inter (conta, cartão, Pix, salário) e XP via Open Finance (Pluggy),
Binance via API, Cemig/Cesama via PDF, empréstimos a receber e custo do carro. Nenhuma ação de pagamento.

## Rodar
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # preencher chaves
.venv/bin/python -m financas.cli sync
.venv/bin/streamlit run financas/ui/app.py
```
Demonstração com dados fictícios: `FIN_DATA_DIR=data/demo .venv/bin/python -m financas.cli demo` e depois o
mesmo `streamlit run` com `FIN_DATA_DIR=data/demo`.

## Contas de consumo (Cemig, Cesama)
Coloque o PDF da fatura em `<pasta de contas>/entrada/` — por padrão `data/contas/`, ou a pasta definida em
`FIN_BILLS_DIR` (pode ser uma pasta sincronizada, como OneDrive). No próximo `sync` (ou com
`python -m financas.cli contas`) o fornecedor é reconhecido pelo texto da fatura e a conta é lançada por regras
fixas, **sem IA**. Deu certo → `importadas/`; não reconheceu ou o total não fechou → `revisar/`, com um `.txt`
explicando o motivo (lançar pelo formulário do painel). Hoje só a Cemig tem leitor de PDF.

## Servidor (futuro)
`docker compose up -d` — painel na porta 8501 + coleta a cada 6 h (inclui a pasta de contas, em `/data/contas`
dentro do volume). Para usar outra pasta, monte-a no serviço `sync` e defina `FIN_BILLS_DIR`. Ver `docker-compose.yml`.
