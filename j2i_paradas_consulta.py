"""Consulta de paradas operacionais; duração recortada ao período escolhido."""
from datetime import date,datetime,timedelta
import math
import pandas as pd
import streamlit as st


def filtros(de,ate,agora,equipamento=None,estado='Todas'):
    inicio=datetime.combine(de,datetime.min.time()).isoformat(sep=' ')
    fim=min(datetime.combine(ate+timedelta(days=1),datetime.min.time()),agora).isoformat(sep=' ')
    sql="p.equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) AND p.iniciada_em < ? AND COALESCE(p.encerrada_em,?) > ?"
    args=[fim,agora.isoformat(sep=' '),inicio]
    if equipamento is not None:sql+=' AND p.equipamento_id=?';args.append(int(equipamento))
    if estado!='Todas':sql+=' AND p.status=?';args.append('ABERTA' if estado=='Em andamento' else 'FINALIZADA')
    return inicio,fim,sql,args


def consultar(c,de,ate,agora,equipamento=None,estado='Todas',pagina=1,tamanho=100,todos=False):
    inicio,fim,where,args=filtros(de,ate,agora,equipamento,estado)
    if fim<=inicio:return [],dict(qtd=0,abertas=0,segundos=0)
    from j2i_paradas_jornada import registrar_sql
    registrar_sql(c)
    # Interseção da parada, filtro e jornada semanal do equipamento.
    duracao="j2i_tempo_jornada(p.equipamento_id,MAX(p.iniciada_em,?),MIN(COALESCE(p.encerrada_em,?),?))"
    params=[inicio,agora.isoformat(sep=' '),fim]+args
    base=f'''WITH dados AS (SELECT p.*, {duracao} AS segundos_periodo FROM paradas_operacionais p WHERE {where}) '''
    total=c.execute(base+"SELECT COUNT(*),COALESCE(SUM(status='ABERTA'),0),COALESCE(SUM(segundos_periodo),0),COALESCE(SUM(segundos_periodo IS NULL),0) FROM dados",params).fetchone()
    resumo=dict(qtd=total[0],abertas=total[1],segundos=total[2],pendentes=total[3])
    query=base+'''SELECT id AS Registro,maquina AS Equipamento,usuario AS Usuário,motivo AS Motivo,
        iniciada_em AS Início,encerrada_em AS Fim,
        CASE status WHEN 'ABERTA' THEN 'Em andamento' ELSE 'Finalizada' END AS Estado,
        segundos_periodo AS 'Segundos no período' FROM dados ORDER BY iniciada_em DESC,id DESC'''
    if not todos:query+=' LIMIT ? OFFSET ?';params=params+[tamanho,(max(1,pagina)-1)*tamanho]
    rows=[dict(r) for r in c.execute(query,params)]
    for r in rows:
        seg=r['Segundos no período'];r['Tempo no período']=f'{seg//3600:02d}:{seg%3600//60:02d}:{seg%60:02d}' if seg is not None else 'Jornada não cadastrada'
    return rows,resumo


def renderizar(a):
    st.title('Paradas registradas')
    st.caption('Paradas lançadas em Operação por Equipamento, incluindo as iniciadas antes do período que continuaram dentro dele.')
    cols=st.columns(2)
    de=cols[0].date_input('Data inicial',date.today().replace(day=1),key='paradas_de')
    ate=cols[1].date_input('Data final',date.today(),key='paradas_ate')
    if de>ate:st.error('A data final deve ser igual ou posterior à inicial.');return
    with a.conectar_banco_operacional() as c:
        eqs=[dict(r) for r in c.execute('SELECT id,maquina,ativo FROM equipamentos WHERE ativo=1 ORDER BY maquina')]
    cols=st.columns(2)
    eq=cols[0].selectbox('Equipamento',[None]+eqs,format_func=lambda e:'Todos os equipamentos' if e is None else e['maquina']+(' (inativo)' if not e['ativo'] else ''),key='paradas_eq')
    estado=cols[1].selectbox('Situação',['Todas','Em andamento','Finalizadas'],index=2,key='paradas_estado')
    st.button('Atualizar paradas')
    agora=datetime.fromisoformat(a.agora_iso());eid=eq['id'] if eq else None
    with a.conectar_banco_operacional() as c:
        _,resumo=consultar(c,de,ate,agora,eid,estado)
    cards=st.columns(3)
    cards[0].metric('Paradas no período',resumo['qtd'])
    cards[1].metric('Tempo de parada',f"{resumo['segundos']//3600} h {resumo['segundos']%3600//60:02d} min")
    cards[2].metric('Ainda em andamento',resumo['abertas'])
    st.caption('Tempo limitado ao período selecionado e ao horário desta consulta. Conta somente a jornada semanal atualmente cadastrada: exclui intervalos e dias/horários sem expediente, inclusive na virada do dia. Com vários equipamentos, soma horas de equipamento; não representa tempo único de fábrica.')
    if resumo.get('pendentes'):st.warning(f"{resumo['pendentes']} parada(s) sem jornada cadastrada: duração pendente, não incluída no total.")
    if not resumo['qtd']:st.info('Nenhuma parada encontrada para estes filtros.');return
    paginas=math.ceil(resumo['qtd']/100)
    pagina=st.selectbox('Página',range(1,paginas+1),key=f'paradas_pagina_{de}_{ate}_{eid}_{estado}_{paginas}')
    with a.conectar_banco_operacional() as c:
        rows,_=consultar(c,de,ate,agora,eid,estado,pagina)
    df=pd.DataFrame(rows)
    st.dataframe(df.drop(columns=['Segundos no período']),hide_index=True,use_container_width=True)
    st.caption(f'Até 100 registros por página • Consulta em {agora:%d/%m/%Y %H:%M:%S}. Paradas antigas da planilha manual não estão nesta consulta.')
    # Gera o CSV apenas sob demanda e não mantém exportações de filtros anteriores.
    if st.button('Preparar exportação de todas as paradas filtradas'):
        with a.conectar_banco_operacional() as c:
            todos,_=consultar(c,de,ate,agora,eid,estado,todos=True)
        from j2i_industrial_ui import csv_bytes
        st.download_button('Baixar CSV',csv_bytes(todos),'paradas_registradas.csv','text/csv')
