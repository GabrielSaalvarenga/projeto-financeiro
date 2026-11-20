# Diagnóstico da interface — Painel Financeiro 0.8.0

Data: 14/11/2026 · Fonte: instância de demonstração (`financas-demo`, :8503, dados fictícios) e leitura de `financas/ui/app.py` e `theme.py`.
Capturas do "antes": pasta `antes-2026-11-14/` (12 telas no computador + 1 no celular).
Dados da demo regerados em 14/11/2026 (com autorização) e congelados em `data-demo/base-2026-11-14/financas.db`; o banco anterior está em `data-demo/anterior-2026-10-24/`. As capturas e os números abaixo são dessa base. Nenhum código foi alterado.

## 1. Inventário de telas

| # | Tela (menu) | Título na página | Número que domina hoje | Filtro |
|---|---|---|---|---|
| 1 | Visão geral | Visão geral | nenhum: 4 cartões iguais | nenhum |
| 2 | Gastos | Para onde vai o dinheiro | nenhum: não há total do período | Período (topo) |
| 3 | Entradas | De onde vem o dinheiro | Total no período, igual aos vizinhos | Período (topo) |
| 4 | Cartão | Cartão de crédito | nenhum: 4 cartões iguais | nenhum |
| 5 | Previsão | Estimativa dos próximos meses | nenhum: só gráfico e tabela | Meses (topo) |
| 6 | Contas de consumo | Contas de consumo | nenhum: 5 cartões iguais | abas Energia / Água |
| 7 | Empréstimos e vendas | Empréstimos e vendas | nenhum: 3 cartões iguais | abas + "Posição em" |
| 8 | Carro | Quanto me custa o carro | nenhum: 8 cartões iguais | nenhum |
| 9 | Investimentos | Investimentos | nenhum: total só por instituição | nenhum |
| 10 | Sincronizar | Coleta de dados | — | — |
| 11 | Configurações | Configurações | — | — |
| 12 | Começar | Começar | — | — |

O nome no menu e o título da página são diferentes em 6 das 12 telas.
Na barra lateral ficam ainda dois filtros globais: "Ver dados de" (backup) e "Pessoa / conta".

## 2. As 3 tarefas, medidas com os dados da demo

### Tarefa 1 — "Quanto gastei neste mês e por quê?"

- Começa na Visão geral, no cartão "Gasto no mês". O cartão não é clicável.
- Caminho: menu Gastos (1) → arrastar o Período até o mês (2) → ler o Ranking → clicar na cor da categoria no gráfico (3) para ver os lançamentos.
- **3 ações e 3 ligações à mão:**
  - A tela Gastos não mostra o total do período, então o número da Visão geral não reaparece em lugar nenhum.
  - A Visão geral conta do dia 1 até hoje; o gráfico de Gastos conta o mês inteiro. São dois "gastos do mês" diferentes sem aviso.
  - O Ranking corta o valor ("R$ 16", "R$ 4") e não leva aos lançamentos; só o gráfico leva.

### Tarefa 2 — "O que vence ou atrasou, e resolver"

- Não existe uma tela para isso. A informação está em 4 lugares:
  - Cartão: "Fatura aberta (estimada)", sem data de vencimento à vista.
  - Contas de consumo: vencimento só na tabela "Mês a mês" (coluna fora da tela) ou no "Detalhe de uma fatura"; não diz se está paga.
  - Empréstimos e vendas → aba "Que eu devo (banco)": parcelas da dívida.
  - Previsão: soma por mês, sem datas.
- **Pelo menos 6 cliques** (3 telas, 1 aba, 2 expansões) e a soma é de cabeça.
- Registrar o pagamento de uma parcela do banco é um formulário separado no fim da aba, onde é preciso escolher de novo a dívida.

### Tarefa 3 — "Quanto me devem, quem paga quando, e dar baixa"

- Começa na Visão geral: "A receber R$ 4.480,32". O cartão não é clicável e não diz que há atraso.
- Menu Empréstimos e vendas (1): aparece "Total a receber R$ 3.280,32". A diferença de R$ 1.200,00 são as vendas, que estão em outra aba (2). Nada na tela explica isso.
- O atraso (R$ 1.093,44) aparece só como cartão de soma. Em "Quando vou receber", a parcela de 10/11 (vencida) é igual às de 10/12 e 10/01 (a vencer).
- Dar baixa: rolar além do gráfico, de 3 tabelas e do formulário "Novo empréstimo" até "Lançar recebimento"; escolher a pessoa (3), a data (4), digitar o valor de memória (5), confirmar (6).
- **6 ações, 1 rolagem longa e 3 ligações à mão** (somar as abas, achar a parcela vencida, redigitar o valor da parcela).

## 3. Desconexões entre módulos

| Métrica | Onde aparece | Problema |
|---|---|---|
| A receber | Visão geral (4.480,32) · Empréstimos (3.280,32) · Vendas e Entradas (1.200,00) | Mesma origem, mas três rótulos e nenhuma indicação de que um é a soma dos outros |
| Gasto do mês | Visão geral (4.259,78, dia 1 até hoje) · Gastos (mês cheio, só no gráfico) | Duas definições; a tela de detalhe não mostra o total |
| Investimentos | Visão geral (60.523,19) · Investimentos (3 subtotais) | O total não aparece na tela de detalhe |
| Cartão | Cartão ("Fatura aberta", "parcelas futuras") · Previsão ("Parcelas cartão") | Sem ligação entre as duas |
| Em atraso | Só dentro das abas de Empréstimos e Vendas | Não sobe para a Visão geral |

Outros pontos:

- Nenhum valor é clicável, exceto as barras do gráfico de Gastos.
- Várias métricas são calculadas dentro do próprio `app.py` (por exemplo, o gasto do dia 1 até hoje), e não em `analytics.py`. É a causa técnica dos números com definições diferentes.
- O Período de Gastos muda o gráfico, o ranking e os lançamentos, mas não os "Recorrentes detectados", que ficam ao lado sem aviso.
- Telas de consulta e formulários de cadastro estão misturados na mesma página (Empréstimos, Carro, Contas, Previsão).

## 4. Visualizações fracas

- **Visão geral:** rótulos do eixo dos meses sobrepostos e ilegíveis; fontes em minúsculas ("binance", "inter", "xp").
- **Gastos:** barras empilhadas com 8 cores; o ranking, que responde à pergunta, é uma tabela cortada.
- **Investimentos:** só tabelas. Sem alocação, custo médio ou rentabilidade, a pergunta 3 fica sem resposta.
- **Empréstimos:** o que é linha do tempo (vencimentos) está em tabela; o gráfico de barras mostra saldo.
- **Cartão:** "Parcelas já contratadas por mês" é uma barra única.
- **Contas de consumo:** 3 gráficos e 5 cartões antes de saber quanto é a conta deste mês e se está paga.
- **Carro:** 8 cartões e nenhum responde direto "quanto custa por mês".
- **Formatos errados:** eixo de km/L com "R$"; faturas em "R$ 4,000" (padrão americano); meses em inglês ("Jan 2026", "Apr 2026") em 3 gráficos; meses como "2026-12" nas tabelas; quantidades "0,02" e "0.38" na mesma coluna.
- **Erro de exibição no Carro:** aparece o texto cru "**R 0,10 / km**" em vez do valor formatado.

## 5. O que está com "cara de IA" (checklist da seção 4 do pedido)

| Item | Situação |
|---|---|
| Emojis como ícone | Sim: faixa da demo, abas (⚡💧💸🛒🏦), expansores (🚗✏️🧮), botões (💾🔄), status (✅⚪), campo de data (📅) |
| Cards todos iguais | Sim: fileiras de 3 a 8 cartões idênticos em 7 telas |
| Paleta arco-íris | Sim: 8 cores em Gastos; Entradas usa outra paleta, com vermelho para "Venda recebida" |
| Cor como decoração | Sim: a etiqueta verde com seta para cima é usada como legenda ("↑ faltam 8.150 km", "↑ tarifa da Cemig") |
| Cantos muito arredondados | Sim: raio de 16 px em tudo, tudo dentro de cartão |
| Filtro longe do que controla | Sim: Período no topo de Gastos e Entradas; dois filtros globais na lateral |
| Avisos em lista separada | Sim: atraso é um cartão de soma, não uma marca na parcela |
| Tabelas padrão sem ajuste | Sim: cabeçalhos em inglês ou internos (DATE, DESCRIPTION, COUNTERPARTY, KIND, ODOMETER, FULL TANK, AT, OK), tipos FIXED_INCOME / CRYPTO / EQUITY, "1" no lugar de "sim" |
| Gradiente, brilho, vidro | Não |
| Linguagem de marketing | Não: os textos são diretos |
| Fonte monoespaçada em tudo | Não: só em trechos de código |

## 6. Leitura pelos 3 princípios

| Tela | Um número domina? | Aviso junto do item? | Reconhecível sem ler? |
|---|---|---|---|
| Visão geral | Não | Não há avisos | Não |
| Gastos | Não | Não se aplica | Só pela cor da categoria |
| Entradas | Parcial | Parcela atrasada vira "sim" numa coluna | Não |
| Cartão | Não | Não | Barra de limite: sim |
| Previsão | Não | Não | Não |
| Contas de consumo | Não | Não (não mostra paga ou em aberto) | Emoji na aba |
| Empréstimos e vendas | Não | Não: atraso é soma; ação fica longe | Não |
| Carro | Não | "faltam 8.150 km" está junto do item: sim | Não |
| Investimentos | Não | Não se aplica | Não |

Nenhuma tela usa ícone de instituição, de categoria ou de ativo.

## 7. Pontos que dependem de decisão sua

1. **Demo: resolvido.** A base foi regerada e congelada em 14/11/2026. O gerador usa datas relativas a hoje e algumas contas do painel também usam a data do dia, então a comparação "antes e depois" de cada incremento deve ser feita no mesmo dia, ou com a data fixada no teste.
2. **Patrimônio total.** Em 12/10 você decidiu não ter o patrimônio total no topo da Visão geral. A pergunta 1 do projeto é "quanto eu tenho hoje". A proposta precisa saber qual número domina a Visão geral.
3. **Streamlit.** Três limites já aparecem e serão testados na Fase 2 antes de qualquer conclusão: a navegação é um seletor na lateral, sem endereço por tela; as tabelas do painel são HTML fixo, sem ação por linha; valor clicável exige botão ou parâmetro na URL.
4. **Tamanho do `app.py`.** São 1.695 linhas num arquivo só. Separar por tela facilita "uma mudança por vez", mas é mudança estrutural.
