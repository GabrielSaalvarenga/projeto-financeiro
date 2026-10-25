# Novidades

Versões no formato **grande.melhoria.correção** (ex.: 1.2.3): correção de erro sobe o último número,
funcionalidade nova sobe o do meio, mudança grande sobe o primeiro.

## 0.6.0 — duas contas Pluggy
- Dá para conectar **duas contas da Pluggy ao mesmo tempo** (Configurações → Conexões → *Pluggy — conta 2*): serve para marido e mulher, ou para quem criou uma segunda conta de desenvolvedor depois que o teste de 15 dias da primeira acabou.
- Os dados aparecem juntos; com mais de uma conta, a barra lateral ganha o filtro **Pessoa / conta** (gastos, cartões e saldos).
- Cada conta é coletada separadamente: se uma falhar, a outra continua. Quem usa uma conta só não precisa mudar nada.
- **Não pôde ser testado com duas contas reais da Pluggy** (testes automáticos com a API simulada); relate problemas nas Issues.

## 0.5.0 — abrir com duplo clique
- Novos atalhos `Iniciar.bat` (Windows), `Iniciar.command` (Mac) e `Iniciar.sh` (Linux): preparam o Python e as dependências sozinhos na primeira vez e abrem o painel. Se já estiver aberto, só abrem o navegador.

## 0.4.0 — aviso de versão nova
- O painel avisa na barra lateral quando sai uma versão nova no GitHub, com link para as novidades. Só consulta o GitHub (no máximo a cada 6 horas) e não envia nada seu; dá para desligar em Configurações › Atualizações.

## 0.3.0 — vendas e demonstração
- Tela **Empréstimos e vendas**, com nova aba **Vendas**: venda parcelada de produto ou serviço entra como previsão de entrada (também na Previsão e na Visão geral).
- Baixa automática: Pix da pessoa com o valor de uma parcela em aberto baixa a parcela sozinho (categoria *Venda recebida*, conta como entrada). Pix com outro valor, você lança à mão.
- Dados fictícios de demonstração mais completos (`cli demo`, pasta própria `data-demo`, faixa azul "Demonstração").

## 0.2.0 — produtos nas compras online
- Nova área **Vincular produto** (aba Gastos): diga qual produto foi uma compra; com "loja + valor", toda parcela igual (passada e futura) é marcada sozinha e vai para Compras online.
- O ranking mostra "Compras online › Produto" e a tabela de lançamentos ganhou a coluna Produto.

## 0.1.1 — ajustes em Gastos
- Gráficos mensais mostram o mês por extenso na horizontal (maio/26, junho/26…).
- Corrigido: a tabela "Ranking no período" não mostrava o nome das categorias.

## 0.1.0 — primeira versão
- Aba **Começar**: visão geral do painel e passo a passo para conectar bancos (Pluggy) e Binance.
- Conexões pela tela: Pluggy (Open Finance — Inter, XP e outros) e Binance (chave só de leitura), com teste antes de salvar.
- Gastos por categoria, cartão, previsão, empréstimos (a receber e dívidas com banco), carro e investimentos.
- Contas de consumo por PDF, sem IA: Cemig, Cesama e EDP.
- Backup automático e manual (.zip), tema claro/escuro.
- Visual novo: cartões, tabelas mais legíveis e textos explicativos em listas curtas.
- Somente leitura: o painel nunca paga, transfere nem movimenta dinheiro.
