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

## Servidor (futuro)
`docker compose up -d` — painel na porta 8501 + coleta a cada 6 h. Ver `docker-compose.yml`.
