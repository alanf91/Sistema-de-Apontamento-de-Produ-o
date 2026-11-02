"""Resumo executivo somente leitura. Não soma unidades de produção diferentes."""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
import j2i_desempenho_periodo as desempenho
from j2i_jornadas import validar


def segundos(dias, inicio, fim):
    if dias is None:return None
    total=0;dia=inicio.date();mapa={d['dia']:d for d in dias}
    while dia<=fim.date():
        d=mapa[dia.weekday()]
        if d['ativo']:
            pares=[(d['inicio'],d['pausa']),(d['retorno'],d['fim'])] if d['intervalo'] else [(d['inicio'],d['fim'])]
            for a,b in pares:
                ini=max(inicio,datetime.fromisoformat(f'{dia} {a}'));final=min(fim,datetime.fromisoformat(f'{dia} {b}'))
                total+=max(0,int((final-ini).total_seconds()))
        dia+=timedelta(days=1)
    return total


def jornada(c):
    result={}
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_jornadas'").fetchone():
        for r in c.execute('SELECT equipamento_id,dias_json FROM mes_jornadas'):
            try:result[r[0]]=validar(json.loads(r[1]))
            except (ValueError,TypeError,KeyError):result[r[0]]=None
    return result


def consolidar(c,de,ate,agora,ids,limites):
    resumo,planos,resultados,avisos=desempenho.consultar(c,de,ate,ids)
    dias=jornada(c);inicio=datetime.combine(de,datetime.min.time());fim=min(agora,datetime.combine(ate+timedelta(days=1),datetime.min.time()))
    paradas=defaultdict(float);motivos=defaultdict(lambda:dict(segundos=0,equipamentos=set()));faltas=set()
    for r in c.execute('SELECT equipamento_id,maquina,motivo,iniciada_em,encerrada_em FROM paradas_operacionais WHERE iniciada_em<? AND COALESCE(encerrada_em,?)>?',(fim.isoformat(sep=' '),agora.isoformat(sep=' '),inicio.isoformat(sep=' '))):
        if r['equipamento_id'] not in ids:continue
        ini=max(inicio,datetime.fromisoformat(r['iniciada_em']));final=min(fim,datetime.fromisoformat(r['encerrada_em']) if r['encerrada_em'] else agora)
        valor=segundos(dias.get(r['equipamento_id']),ini,final)
        if valor is None:faltas.add(r['equipamento_id']);continue
        paradas[r['equipamento_id']]+=valor
        m=motivos[r['motivo']];m['segundos']+=valor;m['equipamentos'].add(r['maquina'])
    qualidade={r['equipamento_id']:dict(r) for r in c.execute("SELECT equipamento_id,SUM(COALESCE(quantidade_boa,0)) boas,SUM(COALESCE(refugo,0)) sucata,SUM(COALESCE(retrabalho,0)) retrabalho FROM ordens_operacionais WHERE status='FINALIZADA' AND fechada_em>=? AND fechada_em<? GROUP BY equipamento_id",(inicio.isoformat(sep=' '),fim.isoformat(sep=' ')))}
    linhas=[]
    for r in resumo:
        eq=r['equipamento_id'];q=qualidade.get(eq,{});total=(q.get('boas') or 0)+(q.get('sucata') or 0)
        sucata=100*(q.get('sucata') or 0)/total if total else None
        retrabalho=100*(q.get('retrabalho') or 0)/(q.get('boas') or 1) if q.get('boas') else None
        disp=segundos(dias.get(eq),inicio,fim);taxa=100*paradas[eq]/disp if disp else None
        andamento=ate>=agora.date()
        if ate==agora.date() and dias.get(eq):
            hoje=dias[eq][agora.weekday()]
            andamento=bool(hoje['ativo'] and agora.time()<datetime.strptime(hoje['fim'],'%H:%M').time())
        prog=r['Programado'];ating=100*r['Realizado bom']/prog if prog else None
        situacao='⚪ Sem programação';causas=[];peso=4
        incompleto=prog is None or 'pendente' in r['Unidade'].lower() or 'configurada' in r['Unidade'].lower() or eq in faltas or dias.get(eq) is None
        if incompleto:situacao='⚪ Dados incompletos';peso=0;causas.append('Conferir medidas, métrica ou jornada')
        elif andamento:situacao='🔵 Em andamento';peso=3;causas.append('Avaliação do plano após encerrar a jornada')
        elif prog and ating<limites['amarelo']:situacao='🔴 Abaixo do esperado';peso=1;causas.append('Produção abaixo do programado')
        elif prog and ating<limites['verde']:situacao='🟡 Atenção';peso=2;causas.append('Programação parcialmente cumprida')
        elif prog:situacao='🟢 Dentro do esperado';peso=5
        if taxa is not None and taxa>limites['paradas']:causas.append('Paradas acima do limite')
        if sucata is not None and sucata>limites['sucata']:causas.append('Sucata acima do limite')
        if retrabalho is not None and retrabalho>limites['retrabalho']:causas.append('Retrabalho acima do limite')
        if len(causas)>0 and peso>=4:situacao='🟡 Atenção';peso=2
        linhas.append({'_id':eq,'_peso':peso,'Equipamento':r['Equipamento'],'Setor':r['Setor'],'Situação':situacao,'Principal desvio':'; '.join(causas) or 'Sem desvio nos limites avaliados',
            'Unidade':r['Unidade'],'Programado':prog,'Realizado bom':r['Realizado bom'],'Cumprimento (%)':round(ating,2) if ating is not None else None,
            'Paradas (h)':round(paradas[eq]/3600,2) if eq not in faltas else None,'Paradas (%)':round(taxa,2) if taxa is not None else None,
            'Sucata (%)':round(sucata,2) if sucata is not None else None,'Retrabalho (%)':round(retrabalho,2) if retrabalho is not None else None})
    grupos=defaultdict(list)
    for r in linhas:grupos[r['_id']].append(r)
    elegiveis=[g for g in grupos.values() if any(r['Programado'] and r['Programado']>0 for r in g) and all(r['Programado'] is not None and 'pendente' not in r['Unidade'].lower() for r in g)]
    cumpriram=sum(all(r['Cumprimento (%)'] is None or r['Cumprimento (%)']>=100 for r in g) for g in elegiveis)
    return dict(linhas=sorted(linhas,key=lambda r:(r['_peso'],r['Equipamento'])),cumpriram=cumpriram,elegiveis=len(elegiveis),
        atencao=len({r['_id'] for r in linhas if r['_peso'] in (1,2)}),incompletos=len({r['_id'] for r in linhas if r['_peso']==0}),
        horas=sum(paradas.values())/3600,pendencias_paradas=len(faltas),motivos=[{'Motivo':k,'Horas':round(v['segundos']/3600,2),'Equipamentos':', '.join(sorted(v['equipamentos']))} for k,v in sorted(motivos.items(),key=lambda x:-x[1]['segundos']) if v['segundos']],avisos=avisos,planos=planos,resultados=resultados)


def publico(rows):return [{k:v for k,v in r.items() if not k.startswith('_')} for r in rows]


def renderizar(a):
    import streamlit as st
    import pandas as pd
    from j2i_atrasos_equipamento import consultar as atrasos
    from j2i_industrial_ui import csv_bytes
    st.title('Resumo Executivo')
    st.caption('Execução do plano, perdas e prioridades para decisão. Somente equipamentos ativos.')
    agora=datetime.fromisoformat(a.agora_iso());ontem=agora.date()-timedelta(days=1)
    cols=st.columns(3);de=cols[0].date_input('De',ontem,key='dir_de');ate=cols[1].date_input('Até',ontem,key='dir_ate')
    if de>ate or ate>agora.date():st.info('Selecione um período válido até hoje.');return
    if (ate-de).days>366:st.info('Selecione até 367 dias por consulta.');return
    with a.conectar_banco_operacional() as c:
        eqs=[dict(r) for r in c.execute('SELECT id,maquina,setor FROM equipamentos WHERE ativo=1 ORDER BY maquina')]
    setor=cols[2].selectbox('Setor',['Todos']+sorted({e['setor'] or 'Sem setor' for e in eqs}),key='dir_setor')
    ids={e['id'] for e in eqs if setor=='Todos' or (e['setor'] or 'Sem setor')==setor}
    if not ids:st.info('Nenhum equipamento ativo neste filtro.');return
    with st.expander('Limites de avaliação'):
        st.caption('Valores iniciais para avaliação, não metas oficiais. Ajustes valem nesta sessão. Cumpriu o plano significa atingir 100%.')
        x=st.columns(5)
        verde=x[0].number_input('Verde a partir de (%)',min_value=1.,max_value=200.,value=100.,key='dir_verde')
        amarelo=x[1].number_input('Amarelo a partir de (%)',min_value=0.,max_value=200.,value=90.,key='dir_amarelo')
        p=x[2].number_input('Limite paradas (%)',min_value=0.,max_value=100.,value=15.,key='dir_paradas')
        s=x[3].number_input('Limite sucata (%)',min_value=0.,max_value=100.,value=3.,key='dir_sucata')
        rt=x[4].number_input('Limite retrabalho (%)',min_value=0.,max_value=100.,value=5.,key='dir_rt')
    if amarelo>verde:st.error('O limite amarelo deve ser menor ou igual ao verde.');return
    limites=dict(verde=verde,amarelo=amarelo,paradas=p,sucata=s,retrabalho=rt)
    st.button('Atualizar resumo',key='dir_atualizar')
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        atual=consolidar(c,de,ate,agora,ids,limites)
        tamanho=(ate-de).days+1;anterior=consolidar(c,de-timedelta(days=tamanho),de-timedelta(days=1),agora,ids,limites)
        saldo,detalhes,avisos_atraso=atrasos(c,agora.date())
        saldo=[r for r in saldo if r['equipamento_id'] in ids and r['Passagens pendentes']]
        detalhes=[r for r in detalhes if r['equipamento_id'] in ids]
        trend=[]
        for i in range(3,-1,-1):
            final=ontem-timedelta(days=7*i);inicial=final-timedelta(days=6)
            t=consolidar(c,inicial,final,agora,ids,limites)
            trend.append({'Semana encerrada em':final.isoformat(),'Equipamentos que cumpriram (%)':round(100*t['cumpriram']/t['elegiveis'],1) if t['elegiveis'] else None,'Avaliáveis':t['elegiveis']})
    if ate==agora.date():st.info('Dia em andamento: valores até esta consulta. A situação do plano permanece provisória enquanto a jornada estiver aberta.')
    from j2i_oee import renderizar as painel_oee
    painel_oee(a,de,ate,agora,setor)
    col=st.columns(4)
    col[0].metric('Cumpriram o programado',f"{atual['cumpriram']} de {atual['elegiveis']}")
    col[1].metric('Equipamentos em atraso',len({r['equipamento_id'] for r in saldo}))
    col[2].metric('Horas de parada',f"{atual['horas']:.2f}",f"{atual['horas']-anterior['horas']:+.2f} h vs. período anterior",delta_color='inverse')
    col[3].metric('Precisam de atenção',atual['atencao'])
    st.caption(f"Período anterior: {de-timedelta(days=tamanho):%d/%m/%Y} a {de-timedelta(days=1):%d/%m/%Y}: {anterior['cumpriram']} de {anterior['elegiveis']} equipamentos cumpriram. Atualizado em {agora:%d/%m/%Y %H:%M}.")
    if atual['incompletos']:st.warning(f"{atual['incompletos']} equipamento(s) com dados incompletos. Cinza não significa bom desempenho; confira os detalhes.")
    if atual['pendencias_paradas']:st.warning('O total de horas é parcial: há paradas sem jornada cadastrada.')
    st.subheader('Onde precisamos agir')
    foco=[r for r in atual['linhas'] if r['_peso'] in (0,1,2)]
    if not foco:st.info('Nenhum desvio identificado nos critérios avaliáveis. Consulte abaixo os equipamentos sem programação ou ainda em andamento.')
    else:
        st.dataframe([{k:r[k] for k in ('Equipamento','Situação','Principal desvio','Cumprimento (%)')} for r in foco[:10]],hide_index=True,use_container_width=True)
        if len(foco)>10:st.caption('Exibindo as 10 primeiras prioridades; lista completa em Ver detalhes.')
    st.caption('Cumprimento = boas/programado, por equipamento e unidade. Produção de lotes fora do plano do período também entra no realizado: este indicador não comprova entrega do lote. Sucata = sucata/(boas+sucata); retrabalho = retrabalho/boas, em peças/passagens do equipamento. Paradas usam a jornada semanal atual, sem almoço e horas sem expediente.')
    st.download_button('Baixar resumo executivo',csv_bytes(publico(atual['linhas'])),'resumo_executivo.csv','text/csv')
    esq,dir=st.columns(2)
    with esq:
        st.subheader('Principais motivos de parada')
        if atual['motivos']:st.dataframe(atual['motivos'][:3],hide_index=True,use_container_width=True)
        else:st.info('Nenhuma hora de parada calculável no período.')
    with dir:
        st.subheader('Evolução nas últimas quatro semanas')
        st.line_chart(pd.DataFrame(trend).set_index('Semana encerrada em')[['Equipamentos que cumpriram (%)']])
        st.caption('Janelas de 7 dias encerradas até ontem, independentes do filtro de datas. Sem programação calculável, não há percentual.')
    st.subheader('Atrasos que exigem acompanhamento')
    st.caption(f'Saldo atual da carteira vencida até {ontem:%d/%m/%Y}; não é uma fotografia histórica do período selecionado.')
    tabela=[]
    for r in sorted(saldo,key=lambda r:-r['Maior atraso (dias)']):
        ds=[d for d in detalhes if d['equipamento_id']==r['equipamento_id'] and d['Unidade']==r['Unidade']]
        pendentes=r['Pendências de cálculo']+r['Passagens ignoradas (zero)']
        tabela.append({'Equipamento':r['Equipamento'],'Lotes':', '.join(sorted({d['Lote'] for d in ds})), 'Maior atraso (dias)':r['Maior atraso (dias)'],'Data prevista mais antiga':min(d['Data prevista'] for d in ds),'Saldo calculável':r['Saldo calculado'],'Unidade':r['Unidade'],'Passagens pendentes':r['Passagens pendentes'],'Dados':f'Parcial: {pendentes} pendência(s)' if pendentes else 'Calculado'})
    if tabela:st.dataframe(tabela,hide_index=True,use_container_width=True)
    else:st.success('Nenhum saldo vencido identificado na programação dos equipamentos selecionados.')
    with st.expander('Ver detalhes e pendências'):
        st.write('Todos os equipamentos e indicadores');st.dataframe(publico(atual['linhas']),hide_index=True,use_container_width=True)
        st.write('Avisos de cálculo');st.write(atual['avisos']);st.write(avisos_atraso)
        st.write('Todos os motivos de parada');st.dataframe(atual['motivos'],hide_index=True,use_container_width=True)
