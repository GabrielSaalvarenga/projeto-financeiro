# Sistema de design e incremento 1 — Painel Financeiro

Data: 14/11/2026 · Ramo git: `ui-evolucao` (sem commit) · Só a demo foi usada; prod e dev não foram tocados.

## 1. O que a pesquisa diz e como foi aplicado

| Princípio | Fonte | Aplicação no painel |
|---|---|---|
| Um ou dois números no topo; o resto é detalhe sob demanda | guias de dashboards financeiros (Lollypop, UX Studio, DesignRush) | Um número dominante por tela (`hero`); tabela completa fica num expansor "para conferir" |
| Comprimento e posição são lidos mais rápido que área e cor | resumos das diretrizes da NN/g sobre atributos pré-atentivos | Composição e ranking viram barras horizontais ordenadas, não pizza nem treemap |
| Texto à esquerda, número à direita com algarismos tabulares | idem; guias de tabelas | Colunas de valor alinhadas à direita com `tabular-nums` |
| Cor nunca é o único sinal de estado | WCAG 1.4.1 (uso da cor) | Etiqueta de estado sempre com ícone de forma diferente e texto ("Atrasada há 4 dias") |
| Paleta categórica em ordem fixa, validada para daltonismo | método da skill de visualização usada nesta sessão | 8 matizes fixos, um passo para o claro e outro para o escuro; a 9ª série vira "Outros" |
| Filtro dentro do bloco que controla; aviso e ação no item | vídeo de referência (seção 3 do pedido) | Seletor de período dentro do bloco de gasto; "Dar baixa" na própria parcela |

As fontes da web são blogs de estúdios e resumos de segunda mão; as regras de contraste e de uso da cor vêm do WCAG.

## 2. Tokens (`financas/ui/theme.py`)

| Papel | Claro | Escuro |
|---|---|---|
| Fundo da página | `#F6F6F4` | `#0D0D0D` |
| Painel | `#FFFFFF` | `#1A1A19` |
| Fio / borda | `#E1E0D9` | `#2C2C2A` |
| Texto | `#0B0B0B` | `#F0EFEC` |
| Texto secundário / apagado | `#52514E` / `#6F6D68` | `#C3C2B7` / `#989690` |
| Acento (só o que é clicável) | `#1F65BD` | `#5B9DEB` |
| Entrada | `#1BAF7A` | `#199E70` |
| Saída | `#EB6834` | `#D95926` |
| Atenção | `#FAB219` | `#FAB219` |
| Atraso | `#D03B3B` | `#D03B3B` |

- Tipografia: fonte do sistema. Título de tela 1,45 rem; número dominante 2,2 a 3,1 rem; corpo 0,9 rem.
- Raio: 10 px em painéis, 8 px em controles, pílula só em etiqueta de estado.
- Ícones: Material Symbols, que já vem dentro do Streamlit. Nada é baixado de fora.

## 3. Componentes e a função de cada um

| Componente | Função | Como se distingue |
|---|---|---|
| `hero` | Número dominante da tela | O maior texto da página; um por tela |
| `st.metric` (reestilizado) | Indicador secundário | Valor médio, rótulo pequeno, sem seta nem cor |
| `segmented_control` | Filtro de período | Fica dentro do bloco que controla, com frase de escopo (`scope`) |
| `badge` / `due_badge` | Estado (atrasada, vence em N dias, paga) | Pílula pequena com ícone; não reage ao mouse |
| Botão | Ação ("Dar baixa", "Registrar") | Retângulo com borda e peso; primário preenchido |
| Botão terciário | Ir ao detalhe | Texto no acento, com seta |
| `row_html` / `rows` | Linha de item: marca, título, detalhe, estado, valor | Mesma forma na lista e no detalhe |
| `mark` | Reconhecer antes de ler | Monograma da instituição ou ícone da categoria |
| `bars` | Composição e comparação | Barras ordenadas com valor e percentual |
| `table` | Auditoria | Cabeçalhos em português, números à direita |

Os monogramas (In, XP, Bn) não são os logotipos oficiais das instituições.

## 4. O que mudou neste incremento

- **Todas as telas:** sem emojis; ícones no menu; faixa de ambiente fina; cartões secundários menores; cabeçalhos de tabela em português; meses abreviados em português nos gráficos; "R$ 4.000" no padrão brasileiro; eixo de km/L sem "R$"; texto cru corrigido no Carro; primeira coluna das tabelas não corta mais o valor.
- **Visão geral:** gasto do período como número dominante, com o seletor dentro do bloco; "Para onde foi" em barras; bloco "Hoje" com saldo, investimentos, a receber (com o atraso), fatura e dívida, cada um abrindo o seu detalhe; agenda única de recebimentos e vencimentos com estado e ação na linha.
- **Investimentos:** total como número dominante, alocação por classe, participação por instituição e por ativo; tipos em português.
- **Empréstimos e vendas:** "Quando vou receber" com a etiqueta de estado em cada parcela.

## 5. Verificação

- `docs/ui-evolucao/valores.py` rodado antes e depois sobre a base: saída idêntica.
- Números da Visão geral iguais aos de antes: gasto 4.259,78 · saldo 7.162,30 · investimentos 60.523,19 · a receber 4.480,32.
- 53 testes automáticos passando.
- Conferido na demo: tema claro, tema escuro e largura de 390 px.
- O pop-up "Dar baixa" foi aberto e fechado sem registrar nada.

Não verificado: clique em "Registrar recebimento" até o fim; telas Gastos, Entradas, Cartão, Previsão, Contas de consumo e Carro depois da limpeza global (só a Visão geral, Investimentos e o topo de Empréstimos foram vistos).

## 6. As 3 tarefas, antes e depois

| Tarefa | Antes | Depois |
|---|---|---|
| Quanto gastei no mês e por quê | 3 ações, 3 ligações à mão | 0 ações para o total e as categorias; 1 clique para os lançamentos |
| O que vence ou atrasou | pelo menos 6 cliques em 4 lugares | 0 cliques: agenda na Visão geral; 2 para registrar |
| Quanto me devem e dar baixa | 6 ações e rolagem longa | 0 ações para ver; 2 para dar baixa, com o valor já preenchido |

## 7. Próximos incrementos (ordem sugerida)

1. **Gastos:** total do período como número dominante, ranking em barras clicáveis, período dentro do bloco, formulários de correção num expansor.
2. **Empréstimos e vendas:** separar consulta de cadastro; uma linha por pessoa com saldo, atraso e "Dar baixa".
3. **Cartão e Previsão:** fatura com data de vencimento; previsão com saldo projetado por mês.
4. **Contas de consumo e Carro:** conta do mês e custo mensal como números dominantes; gráficos de apoio abaixo.
5. **Navegação:** agrupar o menu pelas 6 perguntas e dar endereço próprio a cada tela (decisão sua).

Limites que continuam: fatura do cartão na agenda (a data de vencimento guardada é a da última fatura); custo médio e rentabilidade não existem nos dados.

## 8. Incremento 2 — Gastos (14/11/2026)

- Título igual ao do menu ("Gastos"). Total do período como número dominante, com o seletor dentro do bloco (os mesmos períodos da Visão geral mais "Outro período").
- `spend_window` em `app.py`: uma definição só de período para a Visão geral e para Gastos. O botão "Ver os lançamentos em Gastos" leva o período junto, então o total reaparece igual.
- "Mês a mês": barras do total por mês, com o período em destaque (substitui o gráfico empilhado de 8 cores, que ficou num expansor para períodos de mais de um mês; o clique nas cores foi trocado pelo clique no ranking).
- "Para onde foi": ranking em linhas com barra; a seta de cada linha filtra os Lançamentos por aquela categoria (clicar de novo desfaz). Tabela antiga do ranking, com produtos e média por mês, num expansor "para conferir".
- Filtros de Lançamentos dentro do bloco, com contagem, total e escopo. Recorrentes e subdivisões dizem que não mudam com o período.
- Correções (categoria, produto, vínculos, regras) em expansores sob "Corrigir e organizar".

Verificado na demo: 4.259,78 (Este mês) e 75.089,09 (12 meses) iguais na Visão geral e em Gastos; Saúde 322,65 na barra e nos lançamentos; expansor de correção continua aberto ao trocar o lançamento; larguras de 1024 px e 390 px; 53 testes; `valores.py` idêntico à base (em cópia).
Conferidos depois: "Outro período" e o expansor de composição. Não verificado: tema escuro em Gastos; gravação de uma correção ou vínculo.

## 9. Incremento 3 — Empréstimos e vendas (14/11/2026)

- Topo: "A receber" como número dominante, igual ao da Visão geral (empréstimos + vendas, com o atraso), e a data "Posição em" dentro do bloco, valendo para as abas de empréstimos e de vendas.
- Empréstimos: "Quem me deve", uma linha por pessoa com saldo, próximo vencimento, atraso e "Dar baixa" (abate dos mais antigos, valor da próxima parcela já preenchido). Tabela completa e recebimentos em expansores.
- Vendas: uma linha por venda em aberto com "Dar baixa"; parcelas com etiqueta de estado.
- Que eu devo (banco): próximas 6 parcelas com etiqueta de estado e "Registrar"; contratos em tabela.
- Cadastro separado da consulta: novo empréstimo, nova venda, novo empréstimo no banco, lançamentos com mais opções, quitação e memória de cálculo ficam em expansores sob "Cadastrar e ajustar". O código dos formulários não mudou.
- Os pop-ups de baixa passaram a ser os mesmos na Visão geral e nesta tela.

Verificado na demo: 4.480,32 no topo, igual à Visão geral; as três abas e todos os expansores abrem sem erro; pop-up "Dar baixa" aberto e fechado sem registrar; larguras de 1024 px e 390 px; 53 testes; `valores.py` idêntico à base (em cópia). A baixa por pessoa foi exercitada fora da tela, numa cópia descartável da base: a receber de 3.280,32 para 2.186,88 e atraso de 1.093,44 para 0.
Não verificado: gravação pelo botão na tela; tema escuro; "Quitar" e "Memória de cálculo" (a demo não tem empréstimo sem data combinada); simulação com data futura.

## 10. Incremento 4 — Entradas, Cartão, Previsão, Contas de consumo e Carro (14/11/2026)

- **Entradas:** total do período em destaque com o seletor no bloco; "De onde veio" em barras; tabela por tipo num expansor; filtros de lançamentos lado a lado; botão que leva de "Vendas a receber" para Empréstimos e vendas; "Transformar entrada em venda" num expansor.
- **Cartão:** fatura aberta (estimativa) em destaque, barra do limite e as quatro medidas em linhas; a tela diz que a data da próxima fatura não vem do banco.
- **Previsão:** "Sobra prevista" do próximo mês em destaque (coluna "Saldo previsto" que a previsão já calculava), com entradas e saídas previstas; meses por extenso na tabela; cadastro de renda num expansor; cores das saídas sem verde, que fica só para as entradas.
- **Contas de consumo:** conta mais recente em destaque em cada aba, com vencimento e estado (paga, vence em N dias ou "pagamento não registrado" quando o vencimento passou e não há data de pagamento); números no padrão brasileiro; a frase fixa sobre a água foi trocada por uma calculada dos dados.
- **Carro:** "Custo por mês (estimativa)" em destaque. **É uma soma nova**, de três partes que o painel já calculava ou mostrava: fixos por mês + depreciação por mês + média de 3 meses do gasto em posto. Manutenção e revisão não entram, e a tela diz isso. Tabela de eventos com tipo, tanque e odômetro legíveis; cadastros num expansor.
- Títulos das telas iguais aos nomes do menu (inclusive "Sincronizar").

Verificado na demo: as 12 telas abrem sem erro; tema claro e tema escuro nas telas redesenhadas; 390 px sem rolagem lateral em nenhuma tela; 53 testes; `valores.py` idêntico à base (em cópia). Números em destaque: Entradas 63.945,09 (6 meses) · Cartão 2.040,85 · Previsão 5.914,87 · Cemig 235,50 · Cesama 95,98 · Carro 1.223,08.
Não verificado: gravação pelos formulários que foram para expansores (o código deles não mudou, só a posição); instalação com mais de um cartão ou mais de uma distribuidora; telas Sincronizar, Configurações e Começar além da abertura.

## 11. Incremento 5 — extrato por dia e tabelas ajustáveis (14/11/2026)

Motivo: a tabela de lançamentos cortava colunas à direita (Instituição, Parcela) e pedia rolagem lateral.

- **Extrato (`visual.ledger`)** em Gastos e Entradas: lançamentos agrupados por dia, com o total do dia. Cada linha traz ícone da categoria, quem/o quê, e embaixo categoria › produto, subdivisão, parcela "N de M" e banco. Todos os campos aparecem sem rolagem. Mostra até 300 linhas e avisa quando há mais. A tabela antiga continua num expansor "Ver como tabela".
- **Botão "Colunas"** em toda tabela com 3 ou mais colunas: escolhe quais campos aparecem e a ordem (tirar e escolher de novo manda o campo para o fim). A escolha vale até fechar o painel; não é gravada.
- **Tabelas no celular** (até 640 px): cada registro vira uma ficha com rótulo e valor; campos vazios somem.
- **Por onde passou** (`paid_with`): cada lançamento diz o cartão pelo nome ("Cartão Mastercard Inter") ou a conta, com o meio quando o banco informa ("Pix · Conta Corrente Inter"). Sem meio informado, aparece só a conta. Sequências de 4 ou mais dígitos no nome são retiradas: número de conta ou cartão nunca aparece. Para isso a consulta de lançamentos passou a trazer o nome da conta (coluna a mais, nenhum cálculo muda).
- Texto com mais de 22 caracteres quebra linha em vez de alargar a tabela. Parcela aparece como "4" e não "4,00".

Verificado na demo: 12 telas sem erro; extrato de Gastos no tema escuro; Colunas testado em Gastos (tirar dois campos e recolocar um no fim); 390 px sem rolagem lateral nem tabela cortada em Gastos, Entradas, Empréstimos e vendas, Investimentos e Previsão; 53 testes; `valores.py` idêntico à base (em cópia).
Não verificado: extrato no tema claro e com mais de 300 lançamentos; Colunas nas demais tabelas além da abertura.

## 12. Incremento 6 — final do cartão e listas no lugar das tabelas (14/11/2026)

- **Final do cartão:** o lançamento de cartão mostra "Cartão Mastercard Inter · final 4321". Os 4 dígitos são lidos, na hora da consulta, do registro bruto que a coleta já guardava (`creditCardMetadata.cardNumber`); só os 4 últimos são usados e nada novo é gravado. Pedido do dono em 14/11/2026: é uma exceção à regra "nunca exibir número de cartão", restrita ao final. Se a origem não informar, não aparece nada. Na demo o final é fictício.
- **Lista de registros (`visual.listing`)** em 16 tabelas: recorrentes, subdivisões, produtos vinculados e regras (Gastos); vendas e próximas parcelas (Entradas); compras parceladas (Cartão); previsão mês a mês e rendas fora do banco (Previsão); energia e água mês a mês (Contas de consumo); recebimentos de empréstimos e de vendas e contratos de banco (Empréstimos e vendas); eventos do carro; histórico de sincronização. Cada registro é uma linha com ícone, título, campos embaixo e valor à direita. Fora de expansores, a mesma informação continua disponível em "Ver … em tabela", com o botão Colunas.
- **Ficaram como tabela:** as tabelas "para conferir" que já têm linhas acima (ranking, empréstimos, vendas, parcelas do banco, carteira), memória de cálculo, prévia de recebimento e lista de backups.

Verificado na demo: 12 telas e todas as abas sem erro e sem rolagem lateral em 1024 px, com todos os expansores abertos; textos das listas lidos em Gastos, Entradas, Cartão, Previsão, Carro e Sincronizar; energia mês a mês vista no tema claro; 53 testes; `valores.py` idêntico à base (em cópia).
Não verificado: final do cartão com dados reais (o campo da origem pode vir vazio ou em outro formato); listas em 390 px e no tema escuro; listas dentro de expansores além da abertura sem erro.

## 13. Incremento 7 — Empréstimos e vendas: ficha, fila de Pix, simulador e resultado (14/11/2026)

- **Ficha por pessoa:** botão "Ficha" em cada linha de "Quem me deve" e de "Vendas em aberto". Abre saldo, empréstimos e vendas, parcelas em aberto e linha do tempo (emprestou, vendeu, recebeu). Só consulta.
- **Pix a conferir:** bloco acima das abas, só quando há algo. Lista Pix recebidos que podem ser pagamento e não foram baixados sozinhos: (a) têm o nome de Pix cadastrado mas o valor não bateu com uma parcela de venda; (b) o remetente tem todas as palavras do nome cadastrado, para quem não tem nome de Pix. "Confirmar" faz a mesma baixa interna do casamento automático (inclusive mudar a categoria do lançamento para "Venda recebida" ou "Empréstimo recebido"); "Ignorar" guarda só o id do lançamento na preferência `loan_pix_ignored`. Nenhuma tabela nova.
- **Simulador:** expansor "Simular antes de emprestar (nada é gravado)". Mostra total, parcela, juros e cronograma pela regra do painel (`make_schedule`, a mesma do cadastro) e o efeito mês a mês na sobra da Previsão.
- **Resultado por empréstimo:** juros recebidos contra previstos e pontualidade das parcelas vencidas. **São números novos**, só de leitura:
  - juros previstos = recebido + falta − emprestado (o "juros" que a tabela já mostrava);
  - juros recebidos, parcelado = recebido × juros totais ÷ total (parcela = total ÷ n, juro na mesma proporção); sem data combinada = recebido − principal devolvido (o recebimento paga juros primeiro);
  - atraso = dias entre o vencimento e o dia em que a parcela ficou coberta, com os recebimentos cobrindo as mais antigas primeiro; 1 dia já conta;
  - taxa realizada ao mês: só para empréstimo quitado, pelas datas reais dos recebimentos.
- Demo: um Pix fictício de R$ 150,00 (id `demo-fila1`) para a fila ter exemplo; a semente da demo (`demo.py`) também o cria. As entradas de novembro na demo sobem R$ 150,00.

Verificado na demo: fila, ficha, pop-up de confirmação (aberto e fechado sem confirmar), resultado e simulador (R$ 1.000 a 1% a.m. composto em 6x → total 1.061,52, parcela 176,92); três abas sem erro em 1024 px e 390 px; 57 testes (4 novos); `valores.py` idêntico à base (em cópia). Confirmar e ignorar exercitados numa cópia descartável: a receber da venda de 1.200,00 para 1.050,00, lançamento recategorizado, fila vazia.
Não verificado: confirmar e ignorar pelos botões da tela; casamento por nome parecido (caso b) com dados; taxa realizada (a demo não tem empréstimo quitado); ficha de pessoa com venda; tema escuro.

## 14. Incremento 8 — cadastros de Empréstimos e vendas em passos, ficha fácil de achar (15/11/2026)

Motivo: o dono não achou a ficha por pessoa (era um botão discreto na linha) e pediu cadastros melhores.

- **Ficha por pessoa:** bloco "Ficha por pessoa" logo abaixo do topo, com seletor e botão "Abrir ficha" (inclui quem já quitou). Nas linhas, o botão virou "Ver ficha", com ícone e contorno.
- **Cadastros em passos com resumo ao lado** (novo empréstimo, nova venda, novo empréstimo no banco): passos numerados à esquerda e, à direita, um cartão que mostra total, parcela, juros e primeira e última data enquanto se preenche. O botão de registrar fica desligado até o mínimo estar preenchido, e uma linha diz o que falta. Depois de registrar aparece uma confirmação no alto da tela.
- "Não combinei data de retorno" (caixa de marcar negativa) virou a escolha "Em parcelas com data / Sem data combinada".
- **Simulador → cadastro:** botão "Usar estes valores no cadastro" copia a simulação para o novo empréstimo. Nada é gravado.
- **Prévia do recebimento** em linhas (falta hoje → depois do recebimento), no lugar da tabela.
- **Rever Pix ignorados:** botão que devolve os ignorados à fila.
- Datas no padrão dia/mês/ano em todos os campos de data do painel (6 ainda estavam em ano/mês/dia).
- Os comandos de gravação (SQL) dos três cadastros não mudaram.

Verificado na demo: três abas com todos os expansores abertos, sem erro, em 1024 px e 390 px; bloco da ficha; cópia do simulador para o cadastro (resumo 6x de R$ 166,67, botão desligado com "falta: escolher a pessoa"); 57 testes. `valores.py`: só mudam a data e a média do mesmo período, porque o retrato de base é de 14/11 e hoje é 15/11; os demais valores são idênticos.
Não verificado: registrar um empréstimo, uma venda ou um contrato de banco pelos novos formulários; "Rever Pix ignorados" pelo botão; tema escuro.

## 15. Incremento 9 — menu agrupado com endereço por tela, pendências e detalhe do lançamento (15/11/2026)

Aprovado pelo dono em 15/11/2026 ("faça suas sugestões"), inclusive a mudança de navegação, que era decisão estrutural pendente.

- **Menu agrupado:** Visão geral; Dia a dia (Gastos, Entradas, Cartão, Contas de consumo); Compromissos (Empréstimos e vendas, Previsão); Patrimônio (Investimentos, Carro); Painel (Sincronizar, Configurações, Começar). A tela atual fica destacada.
- **Endereço por tela:** `?tela=<slug>` (visao-geral, gastos, entradas, cartao, contas, emprestimos, previsao, investimentos, carro, sincronizar, configuracoes, comecar). Recarregar a página fica na mesma tela; dá para favoritar. Continua Streamlit, um arquivo só: sem migração.
- **Pendências na Visão geral:** só o que pede ação, cada item com seta para o lugar de resolver: Pix a conferir; gastos dos últimos 60 dias em "Outros" ou "Pix enviado"; contas de consumo vencidas nos últimos 60 dias sem data de pagamento (o texto diz que pode já estar paga); PDFs aguardando revisão; dados com 3 dias ou mais desde a última sincronização que deu certo. Só contagens de leitura.
- **Detalhe do lançamento:** em Gastos e Entradas cada linha do extrato tem uma seta que abre o lançamento (categoria e de onde ela veio, descrição, por onde passou, parcela, produto, subdivisão) e a correção ali mesmo, com as mesmas funções da seção "Corrigir e organizar" (`set_manual`, `add_rule`, `set_tag`). O extrato mostra 30 linhas por vez, com "Mostrar mais 30".

Verificado na demo por mim: `?tela=gastos` abre em Gastos com o item destacado no menu; extrato com 16 linhas e setas; pop-up do lançamento com os dados da linha; 57 testes. Verificação por subagente (Sonnet, só leitura, só na demo), em 15/11/2026:
- OK: as 12 telas e todas as abas sem erro e sem rolagem lateral, em largura normal e em 390 px; menu agrupado com a tela atual destacada; clicar no menu troca a tela e o endereço; recarregar fica na mesma tela; "voltar" do navegador volta à tela anterior; `?tela=xyz` cai na Visão geral; gasto de "Este mês" (4.259,78) e de "12 meses" (75.089,09) iguais na Visão geral e em Gastos; extrato por dia com seta que abre o lançamento certo (3 lançamentos conferidos); "Mostrar mais 30" (30 → 60); botão Colunas remove a coluna; seta na mesma linha em 390 px; ficha por pessoa; resultado por empréstimo; simulador (1.061,52 e 176,92); três cadastros em passos com botão desligado e "falta: …"; datas em dia/mês/ano.
- Corrigido depois do relatório: "12.4 km/L" virou "12,4 km/L" no Carro; data do histórico de Sincronizar em dia/mês/ano.
- Não verificado: pendências com itens (a demo está sem nenhuma: o Pix de exemplo foi ignorado e não há gasto sem categoria nos últimos 60 dias; a contagem foi conferida só por cálculo numa cópia); cliques com o mouse no menu (foram por script); gravações.
- Dados da demo corrigidos em 15/11/2026, com aprovação do dono (semente `demo.py` e base atual): km atual do carro passou a 42.724, acima do último abastecimento; o pagamento de banco com data futura (05/12/2026) foi retirado. Com isso, na demo: dívida com o banco de 11.602,50 para 12.376,00, 16 parcelas em aberto, dezembro volta às próximas parcelas e a sobra prevista de dezembro vai de 5.914,87 para 5.141,37. Achados originais: km atual do carro (41.850) menor que o último abastecimento (42.604); 9º pagamento do empréstimo de banco com data futura (05/12/2026), o que tira dezembro das próximas parcelas.
- Tema: com o navegador de teste emulando modo escuro em "Seguir o sistema", a tela ficou metade clara, metade escura. Não confirmado em navegador real.

## 16. O que ficou para decisão

1. **Navegação:** feita no incremento 9 (menu agrupado e `?tela=`), com aprovação do dono em 15/11/2026.
2. **Número dominante da Visão geral:** segue o gasto do mês (decisão de 12/10 de não ter patrimônio total no topo).
3. **Custo por mês do Carro:** confirmar se a soma (sem manutenção) é a que você quer ver.
4. **Gráfico empilhado de Gastos:** ficou num expansor; o clique nas cores foi trocado pelo ranking.
5. **Commit e produção:** nada foi commitado; promover exige sua confirmação, backup e tag.
6. **Ordem das colunas:** hoje vale só até fechar o painel. Gravar a escolha por tabela pede uma chave nova nas configurações.
7. **Extrato:** confirmar se substitui de vez a tabela de lançamentos ou se a tabela volta a ser a visão principal.
8. **Regra do número de cartão:** o `CLAUDE.md` e o briefing dizem "nunca exibir"; o final de 4 dígitos é exceção pedida em 14/11/2026. Decidido em 14/11/2026: a exceção entrou no `CLAUDE.md`.
9. **Atraso de 1 dia:** hoje conta como parcela paga com atraso. Dá para pôr uma tolerância em dias.
