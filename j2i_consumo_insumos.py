"""Consulta somente leitura de baixas, com filtros SQL e paginação."""
from datetime import date, timedelta
import math
import pandas as pd
import streamlit as st
import j2i_industrial as m

MODOS={'equipamento':'Por equipamento / etapa','inicio_op':'Única ao iniciar a OP','fim_op':'Única ao finalizar a primeira etapa'}
BASE=''' FROM mes_movimentos v
JOIN mes_insumos i ON i.codigo=v.insumo
LEFT JOIN ordens_operacionais o ON o.id=v.ordem_id
LEFT JOIN equipamentos e ON e.id=o.equipamento_id
LEFT JOIN mes_politica_op p ON p.op=v.origem '''
COLUNAS='''v.id AS movimento, v.instante AS data_hora, v.origem AS op,
COALESCE(o.lote_identificado,'') AS lote, o.rota_ordem AS etapa,
v.insumo AS codigo_insumo,i.descricao AS insumo,i.unidade,
-v.quantidade AS consumo,v.antes AS saldo_antes,v.depois AS saldo_depois,
COALESCE(o.maquina,e.maquina,'') AS equipamento,v.usuario AS operador,
COALESCE(p.modo,'equipamento') AS modo_baixa'''


def clausula(f):
    de=date.fromisoformat(f['de']);ate=date.fromisoformat(f['ate'])
    if de>ate:raise ValueError('A data inicial deve ser anterior ou igual à final.')
    w=["v.tipo='CONSUMO'", "(o.equipamento_id IS NULL OR e.ativo=1)",'v.instante>=?','v.instante<?'];args=[de.isoformat(),(ate+timedelta(days=1)).isoformat()]
    for campo,coluna in [('op','v.origem'),('lote','o.lote_identificado'),('busca','i.descricao')]:
        valor=f.get(campo,'').strip()
        if valor:
            w.append(coluna+" LIKE ? ESCAPE '\\'")
            args.append('%'+valor.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    for campo,coluna in [('insumos','v.insumo'),('equipamentos','o.equipamento_id'),('operadores','v.usuario'),('unidades','i.unidade'),('modos',"COALESCE(p.modo,'equipamento')")]:
        valores=f.get(campo,[])
        if valores:
            w.append(coluna+' IN ('+','.join('?' for _ in valores)+')');args.extend(valores)
    saldo=f.get('saldo','Todos')
    if saldo=='Negativo':w.append('v.depois<0')
    elif saldo=='Zerado':w.append('v.depois=0')
    elif saldo=='Positivo':w.append('v.depois>0')
    elif saldo!='Todos':raise ValueError('Filtro de saldo inválido.')
    return ' WHERE '+' AND '.join(w),args


def consultar(c,f,pagina=1,tamanho=50):
    where,args=clausula(f)
    totais=dict(c.execute('SELECT COUNT(*) AS baixas,COUNT(DISTINCT v.origem) AS ops,COUNT(DISTINCT v.insumo) AS insumos'+BASE+where,args).fetchone())
    paginas=max(1,math.ceil(totais['baixas']/tamanho));pagina=max(1,min(int(pagina),paginas))
    resumo=[dict(r) for r in c.execute('SELECT v.insumo AS codigo_insumo,i.descricao AS insumo,i.unidade,ROUND(SUM(-v.quantidade),6) AS consumo,COUNT(*) AS baixas'+BASE+where+' GROUP BY v.insumo,i.descricao,i.unidade ORDER BY i.descricao',args)]
    linhas=[dict(r) for r in c.execute('SELECT '+COLUNAS+BASE+where+' ORDER BY v.instante DESC,v.id DESC LIMIT ? OFFSET ?',[*args,tamanho,(pagina-1)*tamanho])]
    return totais,resumo,linhas,pagina,paginas


def exportar(c,f):
    where,args=clausula(f)
    return [dict(r) for r in c.execute('SELECT '+COLUNAS+BASE+where+' ORDER BY v.instante DESC,v.id DESC',args)]


def csv_dados(rows):
    df=pd.DataFrame(rows)
    if 'modo_baixa' in df:df['modo_baixa']=df['modo_baixa'].map(lambda x:MODOS.get(x,x))
    for col in df.select_dtypes(include=['object']).columns:
        df[col]=df[col].map(lambda v:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
    return df.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig')


def renderizar(a):
    st.title('Consumo de Insumos')
    st.caption('Baixas efetivamente registradas. Importações de saldo não entram no consumo. Na baixa única por OP, o equipamento exibido é o que registrou a baixa total.')
    with a.conectar_banco_operacional() as c:
        insumos={r['codigo']:f"{r['codigo']} — {r['descricao']}" for r in c.execute('SELECT codigo,descricao FROM mes_insumos ORDER BY descricao')}
        eqs={r['id']:r['maquina'] for r in c.execute('SELECT id,maquina FROM equipamentos WHERE ativo=1 ORDER BY maquina')}
        usuarios=[r[0] for r in c.execute("SELECT DISTINCT v.usuario FROM mes_movimentos v LEFT JOIN ordens_operacionais o ON o.id=v.ordem_id LEFT JOIN equipamentos e ON e.id=o.equipamento_id WHERE v.tipo='CONSUMO' AND (o.equipamento_id IS NULL OR e.ativo=1) ORDER BY v.usuario")]
        unidades=[r[0] for r in c.execute('SELECT DISTINCT unidade FROM mes_insumos ORDER BY unidade')]
    with st.form('filtros_consumo_insumos'):
        c1,c2=st.columns(2)
        de=c1.date_input('Data inicial',date.today().replace(day=1))
        ate=c2.date_input('Data final',date.today())
        c1,c2=st.columns(2)
        op=c1.text_input('OP (parte ou número completo)')
        lote=c2.text_input('Lote (parte ou número completo)')
        busca=st.text_input('Buscar na descrição do insumo')
        materiais=st.multiselect('Insumos',list(insumos),format_func=insumos.get)
        maquinas=st.multiselect('Equipamentos que registraram a baixa',list(eqs),format_func=eqs.get)
        operadores=st.multiselect('Operadores',usuarios)
        unidades_escolhidas=st.multiselect('Unidades',unidades)
        modos=st.multiselect('Modos de baixa',list(MODOS),format_func=MODOS.get)
        saldo=st.selectbox('Saldo após a baixa',['Todos','Negativo','Zerado','Positivo'])
        aplicar=st.form_submit_button('Aplicar filtros',type='primary')
    filtro=dict(de=de.isoformat(),ate=ate.isoformat(),op=op,lote=lote,busca=busca,insumos=materiais,equipamentos=maquinas,operadores=operadores,unidades=unidades_escolhidas,modos=modos,saldo=saldo)
    if aplicar or 'consumo_filtros_aplicados' not in st.session_state:
        try:clausula(filtro)
        except ValueError as exc:st.error(str(exc));return
        st.session_state['consumo_filtros_aplicados']=filtro
        st.session_state['consumo_pagina']=1
    filtro=st.session_state['consumo_filtros_aplicados']
    st.caption(f"Consulta aplicada: {filtro['de']} a {filtro['ate']}. Use Aplicar filtros para atualizar a consulta.")
    pagina=int(st.session_state.get('consumo_pagina',1))
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        totais,resumo,linhas,pagina,paginas=consultar(c,filtro,pagina)
    st.session_state['consumo_pagina']=pagina
    c1,c2,c3=st.columns(3)
    c1.metric('Baixas registradas',totais['baixas']);c2.metric('OPs',totais['ops']);c3.metric('Insumos',totais['insumos'])
    if not linhas:st.info('Nenhuma baixa encontrada com os filtros aplicados.');return
    st.subheader('Consumo por insumo')
    st.dataframe(resumo,use_container_width=True,hide_index=True)
    st.caption('Totais separados por material e unidade. A unidade exibida vem do cadastro atual do insumo.')
    st.download_button('Baixar resumo CSV',csv_dados(resumo),'resumo_consumo_insumos.csv','text/csv')
    st.subheader('Histórico das baixas')
    df=pd.DataFrame(linhas);df['modo_baixa']=df['modo_baixa'].map(lambda x:MODOS.get(x,x))
    st.dataframe(df,use_container_width=True,hide_index=True)
    anterior,centro,proxima=st.columns(3)
    if anterior.button('Página anterior',disabled=pagina<=1):
        st.session_state['consumo_pagina']=pagina-1;st.rerun()
    centro.write(f'Página {pagina} de {paginas} — até 50 registros por página')
    if proxima.button('Próxima página',disabled=pagina>=paginas):
        st.session_state['consumo_pagina']=pagina+1;st.rerun()
    if st.button('Preparar CSV de todas as baixas filtradas'):
        with a.conectar_banco_operacional() as c:todos=exportar(c,filtro)
        st.download_button('Baixar histórico CSV completo',csv_dados(todos),'consumo_insumos.csv','text/csv')
