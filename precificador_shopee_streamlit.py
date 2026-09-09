"""
==================================================================================
 SISTEMA DE PRECIFICAÇÃO AUTOMATIZADA PARA VENDEDORES SHOPEE — VERSÃO WEB
==================================================================================

Versão em Streamlit da calculadora de precificação Shopee. A camada de regras
de negócio (classe RegrasShopee) é EXATAMENTE a mesma da versão desktop feita
com CustomTkinter — só a interface mudou.

Como rodar localmente:
    pip install streamlit matplotlib numpy
    streamlit run precificador_shopee_streamlit.py

Como publicar de graça:
    1. Suba este arquivo em um repositório no GitHub.
    2. Acesse https://share.streamlit.io e conecte o repositório.
    3. Em poucos minutos você terá uma URL pública (ex.: seu-app.streamlit.app).
    4. No celular, abra essa URL no navegador e use "Adicionar à tela inicial"
       (Chrome/Safari) para que ela se comporte como um app instalado (PWA).

Autor: Gerado com apoio do Claude (Anthropic)
==================================================================================
"""

import streamlit as st
import numpy as np
from matplotlib.figure import Figure


# ==================================================================================
# 1. CAMADA DE REGRAS DE NEGÓCIO (idêntica à versão desktop)
# ==================================================================================

class RegrasShopee:
    """
    Concentra todas as constantes e fórmulas de negócio do sistema:
    tributação, taxas/comissões da Shopee e as metas de markup.
    """

    ALIQUOTA_SIMPLES = 0.1070          # 10,70% sobre a venda bruta (Simples Nacional EPP 4ª faixa)
    MARKUP_PISO = 0.2349               # 23,49% -> markup mínimo operacional sobre a venda líquida
    MARKUP_IDEAL_MIN = 0.43            # 43%    -> início da faixa ideal
    MARKUP_IDEAL_MAX = 0.87            # 87%    -> topo da faixa ideal

    DESCONTO_GATILHO_MIN = 0.35        # 35%
    DESCONTO_GATILHO_MAX = 0.55        # 55%
    DESCONTO_GATILHO_REFERENCIA = 0.45  # ponto médio usado para exibir um exemplo de preço promocional

    # Taxa fixa "ajustada" para produtos até R$ 7,99 (ver observação no README /
    # na resposta do chat: a Shopee não publica fórmula fechada para essa faixa).
    _TAXA_FIXA_REFERENCIA = 4.00
    _PRECO_REFERENCIA_FIXA = 8.00

    @classmethod
    def taxa_shopee(cls, preco_bruto: float) -> float:
        if preco_bruto <= 0:
            return 0.0

        if preco_bruto <= 7.99:
            taxa_fixa_proporcional = cls._TAXA_FIXA_REFERENCIA * (
                preco_bruto / cls._PRECO_REFERENCIA_FIXA
            )
            taxa = 0.20 * preco_bruto + taxa_fixa_proporcional
            teto = 0.50 * preco_bruto
            return min(taxa, teto)

        elif preco_bruto <= 79.99:
            return 0.20 * preco_bruto + 4.00

        elif preco_bruto <= 99.99:
            return 0.14 * preco_bruto + 16.00

        elif preco_bruto <= 199.99:
            return 0.14 * preco_bruto + 20.00

        elif preco_bruto <= 499.99:
            return 0.14 * preco_bruto + 26.00

        else:
            return 0.14 * preco_bruto + 28.00

    @classmethod
    def venda_liquida(cls, preco_bruto: float) -> float:
        imposto = preco_bruto * cls.ALIQUOTA_SIMPLES
        taxa_shopee = cls.taxa_shopee(preco_bruto)
        return preco_bruto - imposto - taxa_shopee

    @classmethod
    def markup(cls, preco_bruto: float, preco_custo: float) -> float:
        liquido = cls.venda_liquida(preco_bruto)
        if liquido <= 0:
            return -9.99
        return (liquido - preco_custo) / liquido

    @classmethod
    def preco_para_markup(cls, preco_custo: float, markup_alvo: float) -> float:
        if preco_custo <= 0:
            return 0.0

        limite_inferior = preco_custo * 1.0001
        limite_superior = preco_custo * 50.0

        for _ in range(200):
            meio = (limite_inferior + limite_superior) / 2
            m = cls.markup(meio, preco_custo)
            if m < markup_alvo:
                limite_inferior = meio
            else:
                limite_superior = meio

        return round(limite_superior, 2)

    @classmethod
    def calcular_precificacao(cls, preco_custo: float) -> dict:
        piso = cls.preco_para_markup(preco_custo, cls.MARKUP_PISO)
        ideal_min = cls.preco_para_markup(preco_custo, cls.MARKUP_IDEAL_MIN)
        ideal_max = cls.preco_para_markup(preco_custo, cls.MARKUP_IDEAL_MAX)

        markup_sugerido = (cls.MARKUP_IDEAL_MIN + cls.MARKUP_IDEAL_MAX) / 2
        preco_sugerido = cls.preco_para_markup(preco_custo, markup_sugerido)

        preco_ancoragem = ideal_min / (1 - cls.DESCONTO_GATILHO_MAX)

        preco_promocional = preco_ancoragem * (1 - cls.DESCONTO_GATILHO_REFERENCIA)
        markup_promocional = cls.markup(preco_promocional, preco_custo)

        preco_com_desconto_min = preco_ancoragem * (1 - cls.DESCONTO_GATILHO_MIN)
        preco_com_desconto_max = preco_ancoragem * (1 - cls.DESCONTO_GATILHO_MAX)
        markup_com_desconto_min = cls.markup(preco_com_desconto_min, preco_custo)
        markup_com_desconto_max = cls.markup(preco_com_desconto_max, preco_custo)

        return {
            "preco_custo": preco_custo,
            "piso": piso,
            "markup_piso": cls.markup(piso, preco_custo),
            "ideal_min": ideal_min,
            "ideal_max": ideal_max,
            "preco_sugerido": preco_sugerido,
            "markup_sugerido": cls.markup(preco_sugerido, preco_custo),
            "preco_ancoragem": preco_ancoragem,
            "preco_promocional": preco_promocional,
            "markup_promocional": markup_promocional,
            "preco_com_desconto_min": preco_com_desconto_min,
            "preco_com_desconto_max": preco_com_desconto_max,
            "markup_com_desconto_min": markup_com_desconto_min,
            "markup_com_desconto_max": markup_com_desconto_max,
        }


# ==================================================================================
# 2. FUNÇÕES AUXILIARES DE FORMATAÇÃO
# ==================================================================================

def formatar_moeda(valor: float) -> str:
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {texto}"


def formatar_percentual(valor: float) -> str:
    return f"{valor * 100:.2f}%".replace(".", ",")


# ==================================================================================
# 3. GRÁFICO (Matplotlib, com tema escuro combinando com a página)
# ==================================================================================

def montar_grafico(resultado: dict) -> Figure:
    preco_custo = resultado["preco_custo"]

    markups = np.linspace(
        RegrasShopee.MARKUP_PISO, RegrasShopee.MARKUP_IDEAL_MAX, 200
    )
    valores_liquidos = preco_custo / (1 - markups)

    cor_fundo = "#0e1117"   # combina com o tema escuro padrão do Streamlit
    cor_texto = "#e0e0e0"
    cor_grade = "#3a3a3a"

    fig = Figure(figsize=(8, 5), dpi=110, facecolor=cor_fundo)
    ax = fig.add_subplot(111, facecolor=cor_fundo)

    for spine in ax.spines.values():
        spine.set_color(cor_grade)
    ax.tick_params(colors=cor_texto)
    ax.grid(True, color=cor_grade, linewidth=0.6, linestyle="--", alpha=0.6)

    ax.plot(
        markups * 100, valores_liquidos,
        color="#2ecc71", linewidth=2.5, label="Venda Líquida necessária",
    )

    ax.axvspan(
        RegrasShopee.MARKUP_IDEAL_MIN * 100,
        RegrasShopee.MARKUP_IDEAL_MAX * 100,
        color="#3498db", alpha=0.12, label="Faixa ideal (43% – 87%)",
    )

    ax.axvline(
        RegrasShopee.MARKUP_PISO * 100,
        color="#e67e22", linestyle="--", linewidth=1.5,
        label=f"Piso operacional ({formatar_percentual(RegrasShopee.MARKUP_PISO)})",
    )

    liquido_sugerido = RegrasShopee.venda_liquida(resultado["preco_sugerido"])
    ax.scatter(
        [resultado["markup_sugerido"] * 100], [liquido_sugerido],
        color="#f1c40f", s=90, zorder=5, edgecolor="black",
        label="Preço sugerido",
    )

    ax.set_xlabel("Markup sobre a Venda Líquida (%)", color=cor_texto)
    ax.set_ylabel("Valor Líquido da Venda (R$)", color=cor_texto)
    ax.set_title(f"Custo: {formatar_moeda(preco_custo)}", fontsize=12, color=cor_texto, pad=12)
    ax.legend(
        loc="upper left", fontsize=8.5, facecolor=cor_fundo,
        edgecolor=cor_grade, labelcolor=cor_texto,
    )

    fig.tight_layout()
    return fig


# ==================================================================================
# 4. INTERFACE STREAMLIT
# ==================================================================================

st.set_page_config(
    page_title="Precificador Shopee",
    page_icon="🛒",
    layout="wide",
)

# -- Pequeno ajuste visual via CSS para os cards de resultado -- #
st.markdown(
    """
    <style>
    .card {
        background-color: #1c1f26;
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
    }
    .card-titulo {
        font-size: 13px;
        font-weight: 600;
        color: #9aa0a6;
        margin-bottom: 4px;
    }
    .card-valor {
        font-size: 26px;
        font-weight: 800;
        margin-bottom: 4px;
    }
    .card-sub {
        font-size: 12px;
        color: #7d8590;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def card(titulo: str, valor: str, subtitulo: str, cor: str):
    st.markdown(
        f"""
        <div class="card">
            <div class="card-titulo">{titulo}</div>
            <div class="card-valor" style="color:{cor};">{valor}</div>
            <div class="card-sub">{subtitulo}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.title("🛒 Precificador Shopee")
st.caption("Simples Nacional • EPP 4ª Faixa (10,70%) — Markup mínimo 23,49% • Faixa ideal 43% a 87%")

col_entrada, col_espaco = st.columns([1, 2])
with col_entrada:
    preco_custo = st.number_input(
        "Preço de Custo (PC) em R$",
        min_value=0.0,
        value=0.0,
        step=1.0,
        format="%.2f",
        help="Informe apenas o custo do produto — o restante é calculado automaticamente.",
    )
    calcular = st.button("Calcular Precificação", type="primary", use_container_width=True)

# Mantém o último resultado calculado entre interações (session_state)
if calcular and preco_custo > 0:
    st.session_state["resultado"] = RegrasShopee.calcular_precificacao(preco_custo)
elif calcular and preco_custo <= 0:
    st.error("Digite um Preço de Custo maior que zero.")

if "resultado" in st.session_state:
    r = st.session_state["resultado"]

    col_cards, col_grafico = st.columns([1, 1.4])

    with col_cards:
        card(
            "🛡️ Piso de Segurança (mín. 23,49%)",
            formatar_moeda(r["piso"]),
            f"Markup real: {formatar_percentual(r['markup_piso'])} • cobre impostos e custos operacionais",
            "#e67e22",
        )
        card(
            "✅ Preço Sugerido (faixa ideal)",
            formatar_moeda(r["preco_sugerido"]),
            f"Markup: {formatar_percentual(r['markup_sugerido'])} (ponto médio da faixa ideal)",
            "#2ecc71",
        )
        card(
            "📊 Faixa Ideal de Venda (43% a 87%)",
            f"{formatar_moeda(r['ideal_min'])} → {formatar_moeda(r['ideal_max'])}",
            "De 43% (entrada) até 87% (topo) de markup sobre a venda líquida",
            "#3498db",
        )
        card(
            "🏷️ Preço Teto / Ancoragem (\"De:\")",
            formatar_moeda(r["preco_ancoragem"]),
            "Suporta desconto de até 55% sem furar o markup ideal",
            "#9b59b6",
        )
        card(
            "🔥 Preço Promocional com Gatilho (\"Por:\")",
            formatar_moeda(r["preco_promocional"]),
            f"Com 45% off • Markup resultante: {formatar_percentual(r['markup_promocional'])}",
            "#e74c3c",
        )

        st.info(
            f"Com desconto de 35%: **{formatar_moeda(r['preco_com_desconto_min'])}** "
            f"(markup {formatar_percentual(r['markup_com_desconto_min'])})  \n"
            f"Com desconto de 55%: **{formatar_moeda(r['preco_com_desconto_max'])}** "
            f"(markup {formatar_percentual(r['markup_com_desconto_max'])})"
        )

    with col_grafico:
        st.pyplot(montar_grafico(r), use_container_width=True)
else:
    st.info("Informe o preço de custo ao lado e clique em **Calcular Precificação** para ver os resultados.")
