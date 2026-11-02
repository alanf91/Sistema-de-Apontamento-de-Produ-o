"""Saldo por setor da programação selecionada, apurado até a data final."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from j2i_analises_manuais import validar, texto, ID_COL

COLUNAS = ['Setor', 'Peças programadas', 'Peças apontadas até a data final', 'Peças sem apontar', 'Atraso (%)']


def calcular(a, df, data_inicio, data_fim):
    inicio = pd.Timestamp(data_inicio).normalize()
    fim = pd.Timestamp(data_fim).normalize()
    if pd.isna(inicio) or pd.isna(fim) or inicio > fim:
        raise ValueError('A data inicial deve ser menor ou igual à data final.')
    limite = fim + pd.Timedelta(days=1)
    historico = validar(df)
    # Converte somente as colunas necessárias; não expande toda a planilha.
    base = pd.DataFrame({
        'Setor': df['Setor'].fillna('').astype(str).str.strip().replace('', 'Sem setor'),
        'Programada': pd.to_datetime(df['Data Programada Valor'], errors='coerce'),
        'Realizada': pd.to_datetime(df['Data Realizada Valor'], errors='coerce'),
        'Qtde Programada Num': a.to_num(df['Qtde Programada']).clip(lower=0),
        'Quantidade': a.to_num(df['Qtde Realizada']).clip(lower=0),
        'ID': df[ID_COL].map(texto) if ID_COL in df else '',
    }).reset_index(drop=True)
    selecionadas = base.loc[(base['Programada'] >= inicio) &
        (base['Programada'] < limite) & (base['Qtde Programada Num'] > 0)].copy()
    if selecionadas.empty:
        return pd.DataFrame(columns=COLUNAS)
    realizadas = selecionadas['Quantidade'].where(selecionadas['Realizada'] < limite, 0).copy()
    for indice, chave in selecionadas.loc[selecionadas['ID'].isin(historico), 'ID'].items():
        realizadas.at[indice] = sum(float(e['Quantidade lançada']) for e in historico[chave]
                                   if pd.Timestamp(e['Data produção']) < limite)
    selecionadas['Peças programadas'] = selecionadas['Qtde Programada Num']
    # Excesso em uma peça não quita o saldo de outra peça.
    selecionadas['Peças apontadas até a data final'] = realizadas.clip(upper=selecionadas['Peças programadas'])
    selecionadas['Peças sem apontar'] = selecionadas['Peças programadas'] - selecionadas['Peças apontadas até a data final']
    resumo = selecionadas.groupby('Setor', as_index=False)[COLUNAS[1:4]].sum()
    resumo['Atraso (%)'] = 100 * resumo['Peças sem apontar'] / resumo['Peças programadas']
    return resumo[COLUNAS].sort_values('Setor').reset_index(drop=True)


def estilo_linha(linha):
    cor = '#dc2626' if linha['Peças sem apontar'] > 0 else '#16a34a'
    return [f'color: {cor}; font-weight: bold' if c in ('Peças sem apontar', 'Atraso (%)') else '' for c in linha.index]


def renderizar(a, df):
    st.title('Status de entrega por setor')
    st.caption('Resumo por setor — programação do período, com os apontamentos dessas mesmas peças até a data final.')
    hoje = datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    d1, d2 = st.columns(2)
    inicio = d1.date_input('Data inicial da programação', value=hoje.replace(day=1), key='entrega_inicio')
    fim = d2.date_input('Data final', value=hoje, key='entrega_fim')
    if inicio > fim:
        st.error('A data inicial deve ser menor ou igual à data final.')
        return
    resumo = calcular(a, df, inicio, fim)
    opcoes = sorted(resumo['Setor'].unique())
    if 'entrega_setores' in st.session_state:
        st.session_state['entrega_setores'] = [s for s in st.session_state['entrega_setores'] if s in opcoes]
    setores = st.multiselect('Setores', opcoes, key='entrega_setores')
    if setores:
        resumo = resumo[resumo['Setor'].isin(setores)]
    if resumo.empty:
        st.info('Nenhuma peça programada no período para os setores selecionados.')
        return
    totais = resumo[COLUNAS[1:4]].sum()
    atraso = 100 * totais['Peças sem apontar'] / totais['Peças programadas']
    cols = st.columns(4)
    for c, nome in zip(cols[:3], COLUNAS[1:4]):
        c.metric(nome, a.fmt_num(totais[nome]))
    cols[3].metric('Atraso total (%)', f'{atraso:.2f}%'.replace('.', ','))
    formatos = {c: a.fmt_num for c in COLUNAS[1:4]}
    formatos['Atraso (%)'] = lambda v: f'{v:.2f}%'.replace('.', ',')
    st.dataframe(resumo.style.apply(estilo_linha, axis=1).format(formatos), hide_index=True, use_container_width=True)
    st.caption('Atraso = peças sem apontar ÷ peças programadas × 100. Vermelho: saldo pendente. Verde: saldo zerado. Cada setor aparece uma única vez, somando seus lotes.')
    st.caption('Inclui produção antecipada e parciais das peças programadas no intervalo. Exclui produção após a data final e de peças programadas fora do intervalo. Excesso apontado em uma peça não compensa outra peça pendente.')
    st.download_button('Baixar resumo em CSV', resumo.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig'), file_name=f'status_setores_{inicio:%Y%m%d}_{fim:%Y%m%d}.csv', mime='text/csv')
    st.caption('Fonte: planilha de acompanhamento e histórico manual. Registros antigos sem histórico usam a quantidade e a data realizada registradas; quantidades sem data realizada válida não são consideradas apontadas até a data final.')
