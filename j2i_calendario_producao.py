"""Lead time de cinco dias úteis e calendário compartilhado da fábrica."""
from datetime import date,timedelta
import streamlit as st
import pandas as pd
import j2i_industrial as m


def iniciar(c):
    c.execute('CREATE TABLE IF NOT EXISTS mes_feriados (data TEXT PRIMARY KEY, descricao TEXT NOT NULL)')
    c.execute('''CREATE TABLE IF NOT EXISTS mes_dias_equipamento (
        equipamento_id INTEGER PRIMARY KEY REFERENCES equipamentos(id), dia INTEGER NOT NULL CHECK(dia BETWEEN 1 AND 5))''')


def dias_uteis(inicio,feriados):
    bloqueados={date.fromisoformat(str(d)) for d in feriados}
    d=date.fromisoformat(str(inicio));resultado=[]
    while len(resultado)<5:
        if d.weekday()<5 and d not in bloqueados:resultado.append(d)
        d+=timedelta(days=1)
    return resultado


def validar_datas(c,datas):
    feriados={r[0] for r in c.execute('SELECT data FROM mes_feriados')}
    for codigo,valor in datas.items():
        d=date.fromisoformat(valor)
        if d.weekday()>=5 or valor in feriados:
            raise ValueError(f'Equipamento {codigo}: {d:%d/%m/%Y} não é dia útil. Atualize a programação.')


def feriados(a):
    with a.conectar_banco_operacional() as c:
        iniciar(c)
        rows=[dict(r) for r in c.execute('SELECT data,descricao FROM mes_feriados ORDER BY data')]
    with st.expander('Feriados e dias sem expediente da fábrica'):
        st.caption('Cadastro compartilhado entre equipamentos e lotes. Informe a data completa de cada feriado; não há inclusão automática nem repetição anual. Sábados e domingos já são excluídos.')
        with st.form('novo_feriado_producao'):
            dia=st.date_input('Data do feriado',date.today())
            descricao=st.text_input('Nome do feriado ou motivo')
            adicionar=st.form_submit_button('Adicionar feriado')
        if adicionar:
            if not descricao.strip():st.error('Informe o nome ou motivo.')
            else:
                with a.conectar_banco_operacional() as c:
                    c.execute('BEGIN IMMEDIATE')
                    c.execute('INSERT INTO mes_feriados VALUES(?,?) ON CONFLICT(data) DO UPDATE SET descricao=excluded.descricao',(dia.isoformat(),descricao.strip()))
                    m.auditoria(c,'feriado_salvo',a.LOGIN_APONTAMENTO,dict(data=dia.isoformat(),descricao=descricao.strip()))
                st.rerun()
        if rows:
            st.dataframe([{'Data':date.fromisoformat(r['data']),'Feriado':r['descricao']} for r in rows],hide_index=True)
            alvo=st.selectbox('Feriado para remover',[None]+[r['data'] for r in rows],format_func=lambda x:'Selecione' if x is None else date.fromisoformat(x).strftime('%d/%m/%Y'))
            if st.button('Remover feriado selecionado',disabled=alvo is None):
                with a.conectar_banco_operacional() as c:
                    c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM mes_feriados WHERE data=?',(alvo,))
                    m.auditoria(c,'feriado_removido',a.LOGIN_APONTAMENTO,dict(data=alvo))
                st.rerun()
        else:st.info('Nenhum feriado cadastrado.')
        st.caption('O calendário é aplicado às novas programações. Lotes já programados não são reagendados automaticamente.')


def programacao(a,eqs,digest):
    st.subheader('Programação em cinco dias úteis')
    inicio=st.date_input('Data de início (Dia 1)',date.today(),key='inicio_lote_'+digest)
    with a.conectar_banco_operacional() as c:
        fer={r[0] for r in c.execute('SELECT data FROM mes_feriados')}
        padroes={r['equipamento_id']:r['dia'] for r in c.execute('SELECT * FROM mes_dias_equipamento')}
    dias=dias_uteis(inicio,fer)
    if dias[0]!=inicio:st.info(f'A data inicial não é útil. O Dia 1 será {dias[0]:%d/%m/%Y}.')
    st.dataframe([{'Dia do processo':f'Dia {i+1}','Data':d,'Dia da semana':['Segunda','Terça','Quarta','Quinta','Sexta'][d.weekday()]} for i,d in enumerate(dias)],hide_index=True,use_container_width=True)
    base=pd.DataFrame([{'codigo':str(e['codigo']).lstrip('0'),'equipamento':e['maquina'],
                        'dia':f"Dia {padroes[e['id']]}" if e['id'] in padroes else 'Selecionar'} for e in eqs])
    editado=st.data_editor(base,disabled=['codigo','equipamento'],hide_index=True,key='dias_lote_'+digest,
        column_config={'codigo':'Código','equipamento':'Equipamento','dia':st.column_config.SelectboxColumn('Dia do processo',options=['Selecionar']+[f'Dia {i}' for i in range(1,6)],required=True)})
    rows=editado.to_dict('records')
    completos=all(r['dia'] in [f'Dia {i}' for i in range(1,6)] for r in rows)
    if not completos:
        st.warning('Selecione o Dia 1 a Dia 5 para todos os equipamentos antes de importar.')
        return None
    atribuicoes={str(r['codigo']):int(r['dia'][-1]) for r in rows}
    datas={cod:dias[n-1].isoformat() for cod,n in atribuicoes.items()}
    if st.button('Salvar dias dos equipamentos como padrão'):
        with a.conectar_banco_operacional() as c:
            c.execute('BEGIN IMMEDIATE')
            atual={r['equipamento_id']:r['dia'] for r in c.execute('SELECT * FROM mes_dias_equipamento')}
            if any(atual.get(e['id'])!=padroes.get(e['id']) for e in eqs):
                st.error('O padrão foi alterado por outro usuário. Atualize a tela.');return None
            for e in eqs:
                c.execute('INSERT INTO mes_dias_equipamento VALUES(?,?) ON CONFLICT(equipamento_id) DO UPDATE SET dia=excluded.dia',(e['id'],atribuicoes[str(e['codigo']).lstrip('0')]))
            m.auditoria(c,'dias_padrao_equipamentos',a.LOGIN_APONTAMENTO,atribuicoes)
        st.success('Padrão salvo para as próximas importações.')
    st.caption('Cada equipamento recebe uma data; todas as suas passagens neste lote usam essa data. O sequenciamento das OPs continua obrigatório.')
    st.dataframe([{'Equipamento':r['equipamento'],'Dia':r['dia'],'Data calculada':date.fromisoformat(datas[str(r['codigo'])])} for r in rows],hide_index=True,use_container_width=True)
    return datas
