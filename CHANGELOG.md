# Novidades

Versões no formato **grande.melhoria.correção** (ex.: 1.2.3): correção de erro sobe o último número,
funcionalidade nova sobe o do meio, mudança grande sobe o primeiro.

## 0.10.0 — app para Mac e Windows
- O painel agora tem **app de verdade**: `.dmg` para Mac (Apple Silicon) e instalador `.exe` para Windows, na página de Releases. Não precisa de Python, Docker nem navegador: abre numa janela própria e fecha junto com ela.
- No app, os dados ficam na pasta do usuário (Mac: `~/Library/Application Support/Painel Financeiro`; Windows: `%APPDATA%\Painel Financeiro`), então atualizar ou desinstalar não apaga nada. Quem já usava pelo Python ou Docker copia a pasta de dados e o `.env` para lá (ver README).
- O app não é assinado pela Apple nem pela Microsoft: na primeira abertura o sistema avisa (o README explica como liberar).
- Os jeitos antigos (duplo clique, Python, Docker) continuam funcionando como antes.
- Novo **registro de erros** (`erros.log` na pasta de dados), em qualquer jeito de rodar: guarda com data e detalhe técnico os erros das telas e das sincronizações (Pluggy, Binance, OFX, backup), para investigar falhas que acontecem de vez em quando. Tem tamanho limitado e não sai do computador.
- Windows: arquivos com acento (tema, avisos das contas para revisar) passam a ser lidos e gravados em UTF-8.

## 0.9.0 — visual novo e telas reorganizadas
- **Menu agrupado** (Dia a dia, Compromissos, Patrimônio, Painel) e **um endereço por tela** (`?tela=gastos`): recarregar mantém a tela e dá para favoritar.
- **Um número em destaque por tela**, com o seletor de período dentro do bloco: gasto do mês (Visão geral, Gastos), entradas, fatura aberta, sobra prevista, conta do mês e custo por mês do carro (soma de fixos, depreciação e média de combustível; não inclui manutenção).
- **Visão geral:** bloco "Hoje" (saldo, investimentos, a receber com atraso, fatura, dívida), agenda única de recebimentos e vencimentos e **Pendências** (Pix a conferir, gastos sem categoria, contas vencidas sem pagamento, PDFs para revisar, dados desatualizados).
- **Extrato por dia** em Gastos e Entradas, com a seta que abre o lançamento e a correção ali mesmo; mostra por onde passou (cartão ou conta, com o **final do cartão**, só os 4 últimos dígitos).
- **Listas no lugar das tabelas**, botão **Colunas** para escolher os campos e fichas no celular, sem rolagem lateral.
- **Empréstimos e vendas:** "Quem me deve" com **Dar baixa** na linha, **Ficha por pessoa**, fila de **Pix a conferir** (confirmar ou ignorar), simulador, resultado por empréstimo (juros recebidos, pontualidade) e cadastros em passos com resumo ao lado.
- Sem emojis, ícones no menu, datas em dia/mês/ano, números no padrão brasileiro e tema claro/escuro revisados. Nenhuma tabela nova no banco.

## 0.8.0 — gráfico clicável e Pix no crédito
- No gráfico **Gasto mensal por categoria** (Gastos), clicar numa cor mostra logo abaixo os lançamentos daquela categoria (do mês clicado ou do período todo), com total.
- O texto ao passar o mouse nas barras agora mostra o **nome da categoria** na caixa lateral, com o mês e o valor.
- **Pix pago no crédito não conta mais em dobro**: a linha da fatura ("PIX CRED A VISTA…") vira a categoria *Pix no crédito (duplicado)*, que fica fora dos gastos, e vale só o Pix que saiu na conta. Os juros do Pix no crédito continuam contando como gasto. Depois de atualizar, use **Recategorizar** para aplicar nos lançamentos antigos.

## 0.7.0 — entradas
- Nova seção **Entradas**: tudo que entrou na conta (salário, mesada, vendas, outras), com gráfico por mês, total por tipo e lista de lançamentos com filtro e busca. Não conta transferência entre contas suas, resgates nem reembolsos.
- Em **Entradas**, *Transformar entrada em venda*: escolha um Pix recorrente, diga o produto e o nº de parcelas; a venda é criada em **Empréstimos e vendas**, os Pix já recebidos são baixados e as parcelas que faltam ficam a receber, com data e mês de término.
- Em **Entradas**, *Vendas a receber*: parcelas recebidas/faltando, próxima data e quando termina cada venda.

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
