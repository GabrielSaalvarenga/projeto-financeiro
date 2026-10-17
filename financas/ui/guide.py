"""Aba "Começar": visão geral do painel e passo a passo das conexões (Pluggy, Binance, contas de consumo).

Só texto e atalhos para outras abas — nenhuma chave é pedida ou gravada aqui (isso é na aba Configurações).
"""
from __future__ import annotations

from typing import Callable

import streamlit as st

from financas import __version__, config, connections

SOURCES = {s.id: s for s in connections.SOURCES}


def _status(source_id: str) -> str:
    return "✅ conectado" if connections.is_configured(SOURCES[source_id]) else "⚪ ainda não conectado"


def _overview() -> None:
    st.markdown(f"""
O **Painel Financeiro** junta num só lugar seus gastos, cartão, previsão do mês, empréstimos, carro,
investimentos e contas de luz e água. Versão **{__version__}**.

- 🔒 **Somente leitura.** O painel só consulta. Ele **nunca** paga, transfere, faz Pix ou negocia nada.
- 💻 **Seus dados ficam no seu computador.** Não há servidor nosso no meio: o painel fala direto com a
  Pluggy e a Binance usando as **suas** chaves, que ficam guardadas só nesta instalação.
- 🧠 **Funciona sem IA.** Categorias, leitores de conta e cálculos são regras fixas.

**Como começar, em 3 passos:**
1. Marque abaixo o que você usa e siga o passo a passo de cada um.
2. Cole as chaves em **Configurações → Conexões** e clique em **Testar e salvar**.
3. Vá em **Sincronizar** e clique em **Sincronizar tudo**. Pronto: as outras abas se enchem de dados.
""")


def _pluggy() -> None:
    st.markdown(f"""
**Status:** {_status("pluggy")}

A **Pluggy** é uma empresa regulada de Open Finance. Ela busca, com a sua autorização, os dados dos seus bancos
e corretoras (Inter, XP, Nubank, Itaú…). O uso pessoal pelo **Meu Pluggy** é grátis.

> ⏰ **Importante — prazo de 15 dias:** ao criar a conta de desenvolvedor (passo B) começa um teste de ~15 dias.
> **Faça todas as conexões dos bancos dentro desse prazo.** Depois do prazo, o que já foi conectado continua
> funcionando, mas não dá mais para adicionar banco novo. Por isso, conecte tudo de uma vez.

#### A. Conectar seus bancos no Meu Pluggy
1. Acesse **[meu.pluggy.ai](https://meu.pluggy.ai)** e crie sua conta (e-mail e senha).
2. Clique em **Conectar Minha Conta**, escolha o banco e autorize no site/app do banco (é o Open Finance oficial).
3. Confira: o banco precisa aparecer no Meu Pluggy **com saldo e extrato**. Se não aparecer, conecte de novo.
4. Repita para cada banco ou corretora (até **5 conexões**, todas no seu CPF).

#### B. Criar sua aplicação (as chaves do painel)
1. Acesse **[dashboard.pluggy.ai](https://dashboard.pluggy.ai)** e crie a conta — de preferência **com o mesmo
   e-mail** do Meu Pluggy. Se pedir, crie um time (*team*) com qualquer nome.
2. No menu **Applications**, crie **uma** aplicação (qualquer nome, ex.: "Meu painel").
3. Abra a aplicação e copie o **Client ID** e o **Client Secret**. Guarde-os: são a "senha" do painel na Pluggy.

#### C. Ligar o Meu Pluggy à sua aplicação
1. Dentro da aplicação, clique em **Ir para Demo**.
2. Crie uma conexão escolhendo o conector **MeuPluggy** — *não* escolha o banco direto, nem Sandbox, nem Pluggy Bank.
   (Se o MeuPluggy não aparecer, ative-o nas configurações de conectores da aplicação.)
3. Entre com a sua conta do Meu Pluggy e autorize.
4. No menu de três pontinhos (canto superior direito) clique em **Copiar Item ID**. Esse é o "ID da conexão".

#### D. Colar no painel
1. Abra **Configurações → Conexões → Pluggy**.
2. Cole **Client ID**, **Client Secret** e o **ID da conexão** (se tiver mais de um, separe por vírgula).
3. Clique em **Testar e salvar**. O teste mostra os bancos encontrados; se algo estiver errado, nada é salvo.

**Bom saber**
- Os dados atualizam **1 vez por dia** na Pluggy.
- A autorização do Open Finance vence (em geral em 12 meses) e é renovada **de graça** no app do banco.
- O plano grátis é só para os **seus** dados: cada pessoa usa a própria conta da Pluggy.
""")


def _binance() -> None:
    st.markdown(f"""
**Status:** {_status("binance")}

O painel lê os saldos de cripto da Binance com uma **chave de API só de leitura**.

1. No site ou app da Binance, vá em **Perfil → Gerenciamento de API** (*API Management*).
2. Clique em **Criar API**, escolha **Gerada pelo sistema** (*System generated*) e dê um nome (ex.: "Painel").
3. Confirme com a verificação de segurança da Binance (2FA, e-mail ou SMS).
4. Copie a **API Key** e a **Secret Key**. ⚠️ A Secret Key só aparece **uma vez** — copie antes de sair da tela.
5. Clique em **Editar restrições** e deixe marcado **apenas "Enable Reading"** (Permitir leitura).
   **Não** marque negociar (*Spot & Margin Trading*), saque (*Withdrawals*), transferência, margem nem futuros.
6. Recomendado: em **Restringir acesso a IPs confiáveis**, informe o IP da sua internet (pesquise "qual é meu IP").
   Se a sua operadora trocar o IP, a conexão para de funcionar — é só atualizar o IP lá na Binance.
7. Salve e cole as duas chaves em **Configurações → Conexões → Binance → Testar e salvar**.

🔒 O painel **recusa** qualquer chave que consiga negociar, sacar ou transferir — mesmo que você cole uma assim.
""")


def _bills() -> None:
    st.markdown(f"""
Contas de **luz e água** entram pelo PDF da fatura, lido por regras fixas (sem IA).
Suportadas hoje: **Cemig**, **EDP** e **Cesama**.

1. Baixe o PDF da fatura no site/app da concessionária.
2. Envie pela aba **Contas de consumo → Adicionar conta → Enviar PDF da fatura**, ou salve o PDF na pasta
   `{config.BILLS_DIR / 'entrada'}` — ele é lançado na próxima sincronização.
3. Se o painel não reconhecer a fatura, ela vai para a pasta `revisar` com o motivo. Também dá para lançar os
   valores à mão no formulário da mesma aba.
""")


def render(go_to: Callable[[str], None]) -> None:
    """Desenha a aba. `go_to(nome_da_aba)` troca a aba do menu lateral (usado nos botões de atalho)."""
    st.title("Começar")
    _overview()

    st.subheader("O que você usa?")
    c1, c2, c3 = st.columns(3)
    use_pluggy = c1.checkbox("🏦 Bancos", value=True, key="guide_pluggy",
                             help="Bancos e corretoras (Inter, XP, Nubank, Itaú…) via Open Finance (Pluggy)")
    use_binance = c2.checkbox("🪙 Binance", value=connections.is_configured(SOURCES["binance"]), key="guide_binance")
    use_bills = c3.checkbox("💡 Contas de luz e água", value=False, key="guide_bills")

    if use_pluggy:
        with st.expander("🏦 Passo a passo — conectar bancos pela Pluggy", expanded=True):
            _pluggy()
    if use_binance:
        with st.expander("🪙 Passo a passo — gerar a chave da Binance", expanded=True):
            _binance()
    if use_bills:
        with st.expander("💡 Passo a passo — contas de luz e água", expanded=True):
            _bills()
    if not (use_pluggy or use_binance or use_bills):
        st.info("Marque acima o que você usa para ver o passo a passo.")

    st.subheader("Depois de colar as chaves")
    a, b = st.columns(2)
    a.button("⚙️ Ir para Configurações", on_click=go_to, args=("Configurações",), use_container_width=True)
    b.button("🔄 Ir para Sincronizar", on_click=go_to, args=("Sincronizar",), use_container_width=True)
