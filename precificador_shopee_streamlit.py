"""
==================================================================================
 SISTEMA DE PRECIFICAÇÃO AUTOMATIZADA PARA VENDEDORES SHOPEE — VERSÃO WEB
==================================================================================

Versão em Streamlit da calculadora de precificação Shopee.

Novidades desta versão:
    - Seletor da faixa do Simples Nacional (Anexo I) — o imposto sobre a
      venda bruta passa a depender da faixa de faturamento escolhida, em vez
      de ficar fixo em 10,70% (EPP 4ª Faixa).
    - Card "Zero a Zero": preço de venda bruta que cobre exatamente os
      impostos e taxas da Shopee, sem lucro (markup 0% sobre o custo).
    - Markup Piso atualizado para 12,75% (antes 23,49%).
    - Faixa de Trabalho (markup ideal) atualizada para 35% a 75% (antes 43%-87%).
    - Tabela de taxas da Shopee atualizada:
        * R$ 0,01 a R$ 9,00: taxa fixa + comissão = 70% flat da venda bruta.
        * R$ 9,00 a R$ 79,99: taxa fixa atualizada de R$ 4,00 para R$ 4,50.

Como rodar localmente:
    pip install streamlit matplotlib numpy
    streamlit run precificador_shopee_streamlit.py

Autor: Gerado com apoio do Claude (Anthropic)
==================================================================================
"""

import streamlit as st
import numpy as np
from matplotlib.figure import Figure


# ==================================================================================
# 1. TABELA DO SIMPLES NACIONAL — ANEXO I (COMÉRCIO)
# ==================================================================================
#
# Alíquotas NOMINAIS de cada faixa (as mesmas usadas na fórmula do Simples
# Nacional antes de aplicar a "parcela a deduzir", que depende do faturamento
# exato dos últimos 12 meses — RBT12). Essa é a mesma simplificação que a
# versão anterior do app já usava (10,70% = alíquota nominal da 4ª Faixa).
# Se você precisar da alíquota EFETIVA exata, calcule à parte com seu RBT12
# e ajuste o valor aqui.
# ==================================================================================

TABELA_SIMPLES_ANEXO_I = {
    "1ª Faixa — até R$ 180.000,00/ano (4,00%)": 0.0400,
    "2ª Faixa — até R$ 360.000,00/ano (7,30%)": 0.0730,
    "3ª Faixa — até R$ 720.000,00/ano (9,50%)": 0.0950,
    "4ª Faixa — até R$ 1.800.000,00/ano (10,70%)": 0.1070,
    "5ª Faixa — até R$ 3.600.000,00/ano (14,30%)": 0.1430,
    "6ª Faixa — até R$ 4.800.000,00/ano (19,00%)": 0.1900,
}


# ==================================================================================
# 2. CAMADA DE REGRAS DE NEGÓCIO
# ==================================================================================

class RegrasShopee:
    """
    Concentra todas as constantes e fórmulas de negócio do sistema:
    tributação, taxas/comissões da Shopee e as metas de markup.

    A alíquota do Simples Nacional NÃO é mais uma constante fixa — ela é
    passada como parâmetro em cada cálculo, de acordo com a faixa que o
    usuário seleciona na interface.
    """

    MARKUP_ZERO_A_ZERO = 0.00           # 0%     -> cobre impostos/taxas, sem lucro
    MARKUP_PISO = 0.1275                # 12,75% -> markup mínimo operacional sobre o CUSTO
    MARKUP_IDEAL_MIN = 0.35             # 35%    -> início da faixa de trabalho (sobre o custo)
    MARKUP_IDEAL_MAX = 0.75             # 75%    -> topo da faixa de trabalho (sobre o custo)

    DESCONTO_GATILHO_MIN = 0.35         # 35%
    DESCONTO_GATILHO_MAX = 0.55         # 55%
    DESCONTO_GATILHO_REFERENCIA = 0.45  # ponto médio usado para exibir um exemplo de preço promocional

    # Taxa fixa da faixa R$ 9,00 a R$ 79,99 (valor publicado pela Shopee) —
    # atualizada de R$ 4,00 para R$ 4,50.
    _TAXA_FIXA_PADRAO = 4.50

    @classmethod
    def taxa_shopee(cls, preco_bruto: float) -> float:
        """
        Calcula o valor (em R$) da taxa + comissão da Shopee para um dado
        preço bruto, de acordo com a tabela progressiva por faixa de preço.
        """
        if preco_bruto <= 0:
            return 0.0

        if preco_bruto <= 9.00:
            # Faixa: R$ 0,01 a R$ 9,00 -> taxa fixa + comissão = 70% flat da venda bruta.
            return 0.70 * preco_bruto

        elif preco_bruto <= 79.99:
            # Faixa: R$ 9,00 a R$ 79,99 -> 20% + taxa fixa de R$ 4,50.
            return 0.20 * preco_bruto + cls._TAXA_FIXA_PADRAO

        elif preco_bruto <= 99.99:
            return 0.14 * preco_bruto + 16.00

        elif preco_bruto <= 199.99:
            return 0.14 * preco_bruto + 20.00

        elif preco_bruto <= 499.99:
            return 0.14 * preco_bruto + 26.00

        else:
            return 0.14 * preco_bruto + 28.00

    @classmethod
    def venda_liquida(cls, preco_bruto: float, aliquota_simples: float) -> float:
        """Venda bruta menos imposto (Simples Nacional) e taxa/comissão Shopee."""
        imposto = preco_bruto * aliquota_simples
        taxa_shopee = cls.taxa_shopee(preco_bruto)
        return preco_bruto - imposto - taxa_shopee

    @classmethod
    def markup(cls, preco_bruto: float, preco_custo: float, aliquota_simples: float) -> float:
        """
        Markup percentual sobre o CUSTO (margem clássica):

            markup = (Venda Líquida - Preço de Custo) / Preço de Custo
        """
        liquido = cls.venda_liquida(preco_bruto, aliquota_simples)
        return (liquido - preco_custo) / preco_custo

    @classmethod
    def preco_para_markup(
        cls, preco_custo: float, markup_alvo: float, aliquota_simples: float
    ) -> float:
        """
        Busca binária (bisseção) do Preço Bruto necessário para atingir o
        markup_alvo desejado, dada a alíquota do Simples Nacional escolhida.
        """
        if preco_custo <= 0:
            return 0.0

        limite_inferior = preco_custo * 1.0001
        limite_superior = preco_custo * 50.0

        for _ in range(200):
            meio = (limite_inferior + limite_superior) / 2
            m = cls.markup(meio, preco_custo, aliquota_simples)
            if m < markup_alvo:
                limite_inferior = meio
            else:
                limite_superior = meio

        return round(limite_superior, 2)

    @classmethod
    def calcular_precificacao(cls, preco_custo: float, aliquota_simples: float) -> dict:
        zero_a_zero = cls.preco_para_markup(preco_custo, cls.MARKUP_ZERO_A_ZERO, aliquota_simples)
        piso = cls.preco_para_markup(preco_custo, cls.MARKUP_PISO, aliquota_simples)
        ideal_min = cls.preco_para_markup(preco_custo, cls.MARKUP_IDEAL_MIN, aliquota_simples)
        ideal_max = cls.preco_para_markup(preco_custo, cls.MARKUP_IDEAL_MAX, aliquota_simples)

        markup_sugerido = (cls.MARKUP_IDEAL_MIN + cls.MARKUP_IDEAL_MAX) / 2
        preco_sugerido = cls.preco_para_markup(preco_custo, markup_sugerido, aliquota_simples)

        preco_ancoragem = ideal_min / (1 - cls.DESCONTO_GATILHO_MAX)

        preco_promocional = preco_ancoragem * (1 - cls.DESCONTO_GATILHO_REFERENCIA)
        markup_promocional = cls.markup(preco_promocional, preco_custo, aliquota_simples)

        preco_com_desconto_min = preco_ancoragem * (1 - cls.DESCONTO_GATILHO_MIN)
        preco_com_desconto_max = preco_ancoragem * (1 - cls.DESCONTO_GATILHO_MAX)
        markup_com_desconto_min = cls.markup(preco_com_desconto_min, preco_custo, aliquota_simples)
        markup_com_desconto_max = cls.markup(preco_com_desconto_max, preco_custo, aliquota_simples)

        return {
            "preco_custo": preco_custo,
            "aliquota_simples": aliquota_simples,
            "zero_a_zero": zero_a_zero,
            "markup_zero_a_zero": cls.markup(zero_a_zero, preco_custo, aliquota_simples),
            "piso": piso,
            "markup_piso": cls.markup(piso, preco_custo, aliquota_simples),
            "ideal_min": ideal_min,
            "ideal_max": ideal_max,
            "preco_sugerido": preco_sugerido,
            "markup_sugerido": cls.markup(preco_sugerido, preco_custo, aliquota_simples),
            "preco_ancoragem": preco_ancoragem,
            "preco_promocional": preco_promocional,
            "markup_promocional": markup_promocional,
            "preco_com_desconto_min": preco_com_desconto_min,
            "preco_com_desconto_max": preco_com_desconto_max,
            "markup_com_desconto_min": markup_com_desconto_min,
            "markup_com_desconto_max": markup_com_desconto_max,
        }


# ==================================================================================
# 3. FUNÇÕES AUXILIARES DE FORMATAÇÃO
# ==================================================================================

def formatar_moeda(valor: float) -> str:
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "@").replace(".", ",").replace("@", ".")
    return f"R$ {texto}"


def formatar_percentual(valor: float) -> str:
    return f"{valor * 100:.2f}%".replace(".", ",")


# ==================================================================================
# 4. GRÁFICO (Matplotlib, com tema escuro combinando com a página)
# ==================================================================================

def montar_grafico(resultado: dict) -> Figure:
    """
    Plota a curva real Venda Bruta (X) x Venda Líquida (Y), usando a função
    RegrasShopee.venda_liquida diretamente — por isso a curva mostra os
    "degraus" causados pelas mudanças de alíquota/taxa fixa entre as faixas
    de preço da Shopee (R$ 9,00 / R$ 79,99 / R$ 99,99 / R$ 199,99 / R$ 499,99).
    """
    preco_custo = resultado["preco_custo"]
    aliquota = resultado["aliquota_simples"]

    x_min = max(resultado["zero_a_zero"] * 0.5, 0.01)
    x_max = resultado["preco_ancoragem"] * 1.15
    vendas_brutas = np.linspace(x_min, x_max, 400)
    vendas_liquidas = np.array(
        [RegrasShopee.venda_liquida(v, aliquota) for v in vendas_brutas]
    )

    cor_fundo = "#0e1117"   # combina com o tema escuro padrão do Streamlit
    cor_texto = "#e0e0e0"
    cor_grade = "#3a3a3a"

    fig = Figure(figsize=(8, 5.2), dpi=110, facecolor=cor_fundo)
    ax = fig.add_subplot(111, facecolor=cor_fundo)

    for spine in ax.spines.values():
        spine.set_color(cor_grade)
    ax.tick_params(colors=cor_texto)
    ax.grid(True, color=cor_grade, linewidth=0.6, linestyle="--", alpha=0.6)

    # -- Curva real Venda Bruta x Venda Líquida -- #
    ax.plot(
        vendas_brutas, vendas_liquidas,
        color="#2ecc71", linewidth=2.2, label="Venda Líquida (real, com taxas da Shopee)",
        zorder=3,
    )

    # -- Linha de referência y = x (sem impostos/taxas) -- #
    ax.plot(
        vendas_brutas, vendas_brutas,
        color="#5a5a5a", linewidth=1.2, linestyle=":", label="Sem impostos/taxas (referência)",
        zorder=1,
    )

    # -- Faixa de trabalho destacada (35% a 75%) -- #
    ax.axvspan(
        resultado["ideal_min"], resultado["ideal_max"],
        color="#3498db", alpha=0.12, label="Faixa de trabalho (35% – 75%)",
    )

    # -- Linha vertical do piso operacional -- #
    ax.axvline(
        resultado["piso"],
        color="#e67e22", linestyle="--", linewidth=1.5,
        label=f"Piso ({formatar_moeda(resultado['piso'])})",
    )

    # -- Linha vertical do zero a zero -- #
    ax.axvline(
        resultado["zero_a_zero"],
        color="#7f8c8d", linestyle="--", linewidth=1.3,
        label=f"Zero a Zero ({formatar_moeda(resultado['zero_a_zero'])})",
    )

    # -- Pontos-chave marcados sobre a curva -- #
    pontos = [
        (resultado["preco_sugerido"], "#f1c40f", "Preço sugerido"),
        (resultado["preco_ancoragem"], "#9b59b6", "Ancoragem (\"De:\")"),
        (resultado["preco_promocional"], "#e74c3c", "Promocional (\"Por:\")"),
    ]
    for preco_bruto, cor, rotulo in pontos:
        liquido = RegrasShopee.venda_liquida(preco_bruto, aliquota)
        ax.scatter(
            [preco_bruto], [liquido],
            color=cor, s=90, zorder=5, edgecolor="black", label=rotulo,
        )

    ax.set_xlabel("Venda Bruta (R$)", color=cor_texto)
    ax.set_ylabel("Venda Líquida (R$)", color=cor_texto)
    ax.set_title(f"Custo: {formatar_moeda(preco_custo)}", fontsize=12, color=cor_texto, pad=12)
    ax.legend(
        loc="upper left", fontsize=7.5, facecolor=cor_fundo,
        edgecolor=cor_grade, labelcolor=cor_texto,
    )

    fig.tight_layout()
    return fig


# ==================================================================================
# 5. INTERFACE STREAMLIT
# ==================================================================================

st.set_page_config(
    page_title="Precificador Shopee",
    page_icon="🛒",
    layout="wide",
)

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
    .card-detalhe {
        font-size: 11.5px;
        color: #aab2bd;
        margin-top: 8px;
        padding-top: 8px;
        border-top: 1px solid #2a2e37;
        display: flex;
        gap: 16px;
    }
    .card-detalhe b {
        color: #d4d8de;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def detalhar_preco(preco_bruto: float, aliquota_simples: float) -> tuple:
    """Retorna (imposto_em_reais, taxa_shopee_em_reais) para um preço bruto."""
    imposto = preco_bruto * aliquota_simples
    taxa = RegrasShopee.taxa_shopee(preco_bruto)
    return imposto, taxa


def card(titulo: str, valor: str, subtitulo: str, cor: str, detalhe: str = None):
    detalhe_html = f'<div class="card-detalhe">{detalhe}</div>' if detalhe else ""
    st.markdown(
        f"""
        <div class="card">
            <div class="card-titulo">{titulo}</div>
            <div class="card-valor" style="color:{cor};">{valor}</div>
            <div class="card-sub">{subtitulo}</div>
            {detalhe_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


st.title("🛒 Precificador Shopee")
st.caption("Markup mínimo 12,75% • Faixa de trabalho 35% a 75% • Imposto conforme a faixa do Simples Nacional selecionada abaixo")

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

    faixa_selecionada = st.selectbox(
        "Faixa do Simples Nacional (Anexo I)",
        options=list(TABELA_SIMPLES_ANEXO_I.keys()),
        index=3,  # default: 4ª Faixa (10,70%)
        help="Alíquota nominal aplicada sobre a venda bruta, conforme sua faixa de faturamento.",
    )
    aliquota_simples = TABELA_SIMPLES_ANEXO_I[faixa_selecionada]

    calcular = st.button("Calcular Precificação", type="primary", use_container_width=True)

if calcular and preco_custo > 0:
    st.session_state["resultado"] = RegrasShopee.calcular_precificacao(preco_custo, aliquota_simples)
elif calcular and preco_custo <= 0:
    st.error("Digite um Preço de Custo maior que zero.")

if "resultado" in st.session_state:
    r = st.session_state["resultado"]

    col_cards, col_grafico = st.columns([1, 1.4])

    aliquota = r["aliquota_simples"]

    with col_cards:
        imposto, taxa = detalhar_preco(r["zero_a_zero"], aliquota)
        card(
            "⚪ Zero a Zero (sem lucro)",
            formatar_moeda(r["zero_a_zero"]),
            f"Cobre impostos ({formatar_percentual(aliquota)}) e taxas da Shopee — markup 0%",
            "#95a5a6",
            detalhe=f"<span>💰 Imposto: <b>{formatar_moeda(imposto)}</b></span><span>🛍️ Taxa Shopee: <b>{formatar_moeda(taxa)}</b></span>",
        )

        imposto, taxa = detalhar_preco(r["piso"], aliquota)
        card(
            "🛡️ Piso de Segurança (mín. 12,75%)",
            formatar_moeda(r["piso"]),
            f"Markup real: {formatar_percentual(r['markup_piso'])} • cobre impostos e custos operacionais",
            "#e67e22",
            detalhe=f"<span>💰 Imposto: <b>{formatar_moeda(imposto)}</b></span><span>🛍️ Taxa Shopee: <b>{formatar_moeda(taxa)}</b></span>",
        )

        imposto, taxa = detalhar_preco(r["preco_sugerido"], aliquota)
        card(
            "✅ Preço Sugerido (faixa de trabalho)",
            formatar_moeda(r["preco_sugerido"]),
            f"Markup: {formatar_percentual(r['markup_sugerido'])} (ponto médio da faixa de trabalho)",
            "#2ecc71",
            detalhe=f"<span>💰 Imposto: <b>{formatar_moeda(imposto)}</b></span><span>🛍️ Taxa Shopee: <b>{formatar_moeda(taxa)}</b></span>",
        )

        imposto_min, taxa_min = detalhar_preco(r["ideal_min"], aliquota)
        imposto_max, taxa_max = detalhar_preco(r["ideal_max"], aliquota)
        card(
            "📊 Faixa de Trabalho (35% a 75%)",
            f"{formatar_moeda(r['ideal_min'])} → {formatar_moeda(r['ideal_max'])}",
            "De 35% (entrada) até 75% (topo) de markup sobre o custo do produto",
            "#3498db",
            detalhe=(
                f"<span>No piso (35%) → 💰 {formatar_moeda(imposto_min)} · 🛍️ {formatar_moeda(taxa_min)}</span><br>"
                f"<span>No topo (75%) → 💰 {formatar_moeda(imposto_max)} · 🛍️ {formatar_moeda(taxa_max)}</span>"
            ),
        )

        imposto, taxa = detalhar_preco(r["preco_ancoragem"], aliquota)
        card(
            "🏷️ Preço Teto / Ancoragem (\"De:\")",
            formatar_moeda(r["preco_ancoragem"]),
            "Suporta desconto de até 55% sem furar a faixa de trabalho",
            "#9b59b6",
            detalhe=f"<span>💰 Imposto: <b>{formatar_moeda(imposto)}</b></span><span>🛍️ Taxa Shopee: <b>{formatar_moeda(taxa)}</b></span>",
        )

        imposto, taxa = detalhar_preco(r["preco_promocional"], aliquota)
        card(
            "🔥 Preço Promocional com Gatilho (\"Por:\")",
            formatar_moeda(r["preco_promocional"]),
            f"Com 45% off • Markup resultante: {formatar_percentual(r['markup_promocional'])}",
            "#e74c3c",
            detalhe=f"<span>💰 Imposto: <b>{formatar_moeda(imposto)}</b></span><span>🛍️ Taxa Shopee: <b>{formatar_moeda(taxa)}</b></span>",
        )

        imposto_35, taxa_35 = detalhar_preco(r["preco_com_desconto_min"], aliquota)
        imposto_55, taxa_55 = detalhar_preco(r["preco_com_desconto_max"], aliquota)
        st.info(
            f"Com desconto de 35%: **{formatar_moeda(r['preco_com_desconto_min'])}** "
            f"(markup {formatar_percentual(r['markup_com_desconto_min'])}) "
            f"— 💰 {formatar_moeda(imposto_35)} · 🛍️ {formatar_moeda(taxa_35)}  \n"
            f"Com desconto de 55%: **{formatar_moeda(r['preco_com_desconto_max'])}** "
            f"(markup {formatar_percentual(r['markup_com_desconto_max'])}) "
            f"— 💰 {formatar_moeda(imposto_55)} · 🛍️ {formatar_moeda(taxa_55)}"
        )

    with col_grafico:
        st.pyplot(montar_grafico(r), use_container_width=True)
else:
    st.info("Informe o preço de custo, selecione sua faixa do Simples Nacional e clique em **Calcular Precificação**.")
