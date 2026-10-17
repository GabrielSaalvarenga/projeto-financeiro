# Projeto Financeiro — Painel

Visão unificada **somente leitura**: Inter (conta, cartão, Pix, salário) e XP via Open Finance (Pluggy),
Binance via API, Cemig/Cesama via PDF, empréstimos a receber e custo do carro. Nenhuma ação de pagamento.

## Rodar
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # ou preencher pela aba Configurações → Conexões
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

## Backup e Configurações
Aba **Configurações** do painel: tema (claro, escuro ou seguir o sistema) e recorrência do backup automático
(padrão 1x ao dia; desligado, 6 h, 12 h ou semanal). Cada backup é um `.zip` com o banco e os PDFs de contas
importadas, em `<pasta de dados>/backups/`. O automático é feito quando o painel abre ou o `sync` roda, se já
passou o intervalo (o programa não fica rodando escondido); ficam os 30 mais recentes, e os manuais nunca são
apagados sozinhos. Backup manual: botão na aba ou `python -m financas.cli backup`; dá para baixar o `.zip` e
**ver os dados de um backup** no painel inteiro (menu lateral "Ver dados de", somente leitura).
O tema é gravado em `.streamlit/config.toml` na pasta onde o painel roda (fora do git).

**Conexões** (Pluggy, Binance) também se configuram na aba: cada fonte tem os campos, onde conseguir as chaves e
"Testar conexão" (só consultas de leitura). Só é salvo o que passa no teste; a Binance recusa chave que possa
negociar ou sacar. As chaves vão para o `.env` (ou `FIN_ENV_FILE`), nunca para o banco ou o backup, e não são
exibidas de novo. Fonte nova = mais um item em `financas/connections.py`. Antes de expor o painel num servidor
compartilhado, ele precisa de senha (quem abre o painel pode trocar as chaves).

## Servidor (futuro)
`docker compose up -d` — painel na porta 8501 + coleta a cada 6 h (inclui a pasta de contas, em `/data/contas`
dentro do volume). Para usar outra pasta, monte-a no serviço `sync` e defina `FIN_BILLS_DIR`. Ver `docker-compose.yml`.
