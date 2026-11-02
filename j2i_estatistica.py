"""Visão executiva por equipamento, sem misturar unidades ou metas/capacidade."""
import json
import math
from datetime import date,datetime,timedelta
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
import j2i_industrial as m


def iniciar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS mes_capacidade_estatistica (
        equipamento_id INTEGER NOT NULL, vigencia TEXT NOT NULL,
        unidade TEXT NOT NULL, capacidade REAL NOT NULL CHECK(capacidade>0),
        PRIMARY KEY(equipamento_id,vigencia,unidade))''')


def salvar_capacidade(c,eq,vigencia,unidade,valor,usuario):
    date.fromisoformat(vigencia)
    if not math.isfinite(valor) or valor<=0:raise ValueError('Informe capacidade maior que zero.')
    iniciar(c)
    if c.execute('SELECT 1 FROM mes_capacidade_estatistica WHERE equipamento_id=? AND vigencia=? AND unidade=?',(eq,vigencia,unidade)).fetchone():
        raise ValueError('Já existe capacidade nessa vigência e unidade. Use outra vigência para preservar o histórico.')
    c.execute('INSERT INTO mes_capacidade_estatistica VALUES(?,?,?,?)',(eq,vigencia,unidade,valor))
    m.auditoria(c,'capacidade_estatistica',usuario,dict(equipamento=eq,vigencia=vigencia,unidade=unidade,capacidade=valor))


def carregar(c,eq,de,ate,unidade,agora=None):
    iniciar(c)
    limite=datetime.combine(ate+timedelta(days=1),datetime.min.time())
    if agora is not None:limite=min(limite,agora+timedelta(seconds=1))
    rows=[dict(r) for r in c.execute('''SELECT o.fechada_em,o.quantidade_boa,o.refugo,o.retrabalho,
        r.unidade,r.boas,r.sucata,r.regra_json FROM ordens_operacionais o
        LEFT JOIN mes_resultados r ON r.ordem_id=o.id
        WHERE o.equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) AND o.equipamento_id=? AND o.status='FINALIZADA' AND o.fechada_em>=? AND o.fechada_em<?''',
        (eq,de.isoformat(),limite.isoformat(sep=' ')))]
    legados=sum(r['unidade'] is None for r in rows)
    rows=[r for r in rows if r['unidade']==unidade]
    planos={r[0] for r in c.execute('SELECT DISTINCT data_programada FROM mes_programacao WHERE equipamento_id=? AND data_programada BETWEEN ? AND ?',(eq,de.isoformat(),ate.isoformat()))}
    tabelas={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    jornada=None
    if 'mes_jornadas' in tabelas:
        r=c.execute('SELECT dias_json FROM mes_jornadas WHERE equipamento_id=?',(eq,)).fetchone()
        if r:jornada={d['dia']:d for d in json.loads(r[0])}
    feriados={r[0] for r in c.execute('SELECT data FROM mes_feriados')} if 'mes_feriados' in tabelas else set()
    capacidades=[dict(r) for r in c.execute('SELECT * FROM mes_capacidade_estatistica WHERE equipamento_id=? AND unidade=? AND vigencia<=? ORDER BY vigencia',(eq,unidade,ate.isoformat()))]
    registros={}
    for r in rows:registros.setdefault(r['fechada_em'][:10],[]).append(r)
    dias=[];invalidos=0
    for i in range((ate-de).days+1):
        d=de+timedelta(days=i);ds=d.isoformat();rs=registros.get(ds,[])
        trabalho=(jornada.get(d.weekday(),{}).get('ativo',False) if jornada is not None else d.weekday()<5) and ds not in feriados
        if not(trabalho or rs or ds in planos):continue
        invalido=any(r['boas'] is None or r['sucata'] is None or json.loads(r['regra_json'] or '{}').get('permitir_dimensao_zero') for r in rs)
        invalidos+=int(invalido)
        boas=sum(float(r['boas'] or 0) for r in rs);sucata=sum(float(r['sucata'] or 0) for r in rs)
        vigentes=[r for r in capacidades if r['vigencia']<=ds]
        cap=vigentes[-1]['capacidade'] if vigentes else None
        dias.append({'Data':pd.Timestamp(d),'Processado':None if invalido else boas+sucata,'Boas':None if invalido else boas,
                     'Capacidade':cap,'Apontamentos':len(rs),'Peças boas':sum(float(r['quantidade_boa'] or 0) for r in rs),
                     'Peças processadas':sum(float(r['quantidade_boa'] or 0)+float(r['refugo'] or 0) for r in rs)})
    return pd.DataFrame(dias),dict(legados=legados,invalidos=invalidos,jornada=jornada is not None)


def analisar(df,hoje=None):
    serie=df.dropna(subset=['Processado']).copy()
    volume=float(serie['Processado'].sum())
    entrada=float(df['Peças processadas'].sum());boas=float(df['Peças boas'].sum())
    completa=df['Capacidade'].notna().all() and df['Processado'].notna().all()
    capacidade=float(df['Capacidade'].sum()) if completa else None
    ocupacao=100*volume/capacidade if capacidade and capacidade>0 else None
    rendimento=100*boas/entrada if entrada>0 else None
    if hoje is not None:
        serie=serie[serie['Data'].dt.date<hoje].copy()
    tendencia=None;cep=None
    if len(serie)>=7:
        x=(serie['Data']-serie['Data'].min()).dt.days.to_numpy(dtype=float);y=serie['Processado'].to_numpy(dtype=float)
        slope,inter=np.polyfit(x,y,1);prev=slope*x+inter
        ss=float(((y-y.mean())**2).sum());r2=1-float(((y-prev)**2).sum())/ss if ss else 0.0
        serie['Tendência']=prev
        tendencia=dict(inclinacao=float(slope),r2=r2)
    # Série diária: carta individual exploratória, não X-barra/R de subgrupos.
    if len(serie)>=20:
        y=serie['Processado'];mr=float(y.diff().abs().dropna().mean());media=float(y.mean())
        if mr>0:
            lci=media-3*mr/1.128;lcs=media+3*mr/1.128
            cep=dict(media=media,lci=lci,lcs=lcs,sinais=int(((y<lci)|(y>lcs)).sum()))
    return dict(volume=volume,ocupacao=ocupacao,rendimento=rendimento,tendencia=tendencia,cep=cep,serie=serie)


def numero(v):
    return f'{v:,.2f}'.replace(',','@').replace('.',',').replace('@','.')


def renderizar(a):
    st.title('Estatística por equipamento')
    st.caption('Visão executiva • produção encerrada no período • uma unidade por análise')
    with a.conectar_banco_operacional() as c:
        eqs=[dict(r) for r in c.execute('SELECT id,maquina,ativo FROM equipamentos WHERE ativo=1 ORDER BY maquina')]
    if not eqs:st.info('Cadastre os equipamentos para iniciar.');return
    cols=st.columns([2,1,1])
    eq=cols[0].selectbox('Equipamento',eqs,format_func=lambda e:e['maquina']+(' (inativo)' if not e['ativo'] else ''),key='estat_eq')
    agora=datetime.fromisoformat(a.agora_iso())
    hoje=agora.date()
    de=cols[1].date_input('De',hoje-timedelta(days=29),key='estat_de')
    ate=cols[2].date_input('Até',hoje,key='estat_ate')
    if de>ate or ate>hoje:st.info('Selecione um período válido, até hoje.');return
    st.button('Atualizar dados',key='estat_atualizar')
    st.caption(f'Dados encerrados até {agora:%d/%m/%Y %H:%M:%S} • Horário do servidor')
    if ate==hoje:
        st.info('Hoje é parcial: volume e rendimento incluem somente OPs finalizadas até esta consulta. A ocupação usa a capacidade do dia inteiro, sem projeção. CEP, tendência, histograma e padrão semanal consideram apenas dias anteriores a hoje.')
    if (ate-de).days>1826:st.info('Selecione um período de até cinco anos.');return
    with a.conectar_banco_operacional() as c:
        unidades={r[0] for r in c.execute('SELECT DISTINCT r.unidade FROM mes_resultados r JOIN ordens_operacionais o ON o.id=r.ordem_id WHERE o.equipamento_id=?',(eq['id'],))}
        regra=c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=?',(eq['id'],)).fetchone()
        atual=m.validar_regra(json.loads(regra[0]))['unidade'] if regra else None
        if atual:unidades.add(atual)
    if not unidades:st.info('Cadastre a métrica do equipamento.');return
    unidades=sorted(unidades)
    unidade=st.selectbox('Unidade de análise',unidades,index=unidades.index(atual) if atual in unidades else 0)
    with st.expander('Configurar capacidade máxima diária'):
        st.caption('Informe a capacidade máxima validada de um dia completo de operação nesta unidade. É independente da meta. A vigência preserva alterações históricas. A mesma capacidade diária será usada nos dias considerados; avalie turnos/jornadas diferentes antes de interpretar.')
        with st.form('estat_capacidade'):
            vigencia=st.date_input('Válida a partir de',de)
            valor=st.number_input(f'Capacidade máxima por dia ({unidade})',min_value=0.0,value=0.0)
            salvar=st.form_submit_button('Salvar capacidade')
        if salvar:
            try:
                with a.conectar_banco_operacional() as c:
                    c.execute('BEGIN IMMEDIATE')
                    salvar_capacidade(c,eq['id'],vigencia.isoformat(),unidade,float(valor),a.LOGIN_APONTAMENTO)
                st.success('Capacidade salva.')
            except ValueError as exc:st.error(str(exc))
    with a.conectar_banco_operacional() as c:df,avisos=carregar(c,eq['id'],de,ate,unidade,agora)
    if df.empty:st.info('Não há dias de operação, programação ou apontamentos neste período.');return
    if avisos['legados'] or avisos['invalidos']:
        st.warning(f"Dados incompletos: {avisos['legados']} apontamento(s) sem métrica e {avisos['invalidos']} dia(s) com dimensão/resultado pendente. Totais são parciais; ocupação e CEP ficam indisponíveis.")
    r=analisar(df,hoje)
    if avisos['legados'] or avisos['invalidos']:r['ocupacao']=None;r['cep']=None
    cards=st.columns(3)
    cards[0].metric('Volume processado'+(' (parcial)' if avisos['legados'] or avisos['invalidos'] else ''),numero(r['volume'])+' '+unidade)
    cards[1].metric('Ocupação da capacidade','—' if r['ocupacao'] is None else numero(r['ocupacao'])+'%')
    cards[2].metric('Rendimento em peças','—' if r['rendimento'] is None else numero(r['rendimento'])+'%')
    st.caption('Volume = boas + sucata de cada passagem concluída; passagens repetidas contam novamente. Rendimento = peças boas ÷ (boas + sucata), incluindo peças recuperadas por retrabalho. Não é rendimento de matéria-prima nem qualidade na primeira passagem.')
    zeros=int((df['Apontamentos']==0).sum())
    st.info(f"{len(df)} dias considerados • {zeros} sem encerramentos registrados. Dias sem registro entram como volume apontado zero; isso não comprova ausência de produção física.")
    abas=st.tabs(['Evolução','Estabilidade (CEP)','Distribuição','Padrão semanal'])
    with abas[0]:
        cols=['Processado','Boas','Capacidade']+(['Tendência'] if r['tendencia'] else [])
        dados=df.merge(r['serie'][['Data','Tendência']],on='Data',how='left') if r['tendencia'] else df
        graf=dados.melt('Data',value_vars=cols,var_name='Indicador',value_name='Volume')
        st.altair_chart(alt.Chart(graf).mark_line(point=True).encode(x='Data:T',y=alt.Y('Volume:Q',title=unidade),color='Indicador:N',tooltip=['Data:T','Indicador:N','Volume:Q']).properties(height=300),use_container_width=True)
        if r['tendencia']:
            t=r['tendencia'];st.caption(f"Tendência linear: {numero(t['inclinacao'])} {unidade} por dia corrido • R² {numero(t['r2'])}. Descreve o histórico; não é previsão.")
        else:st.caption('Tendência disponível a partir de sete dias válidos.')
        if r['ocupacao'] is None:st.caption('Para ocupação, cadastre capacidade vigente para todos os dias e resolva pendências de dados.')
    with abas[1]:
        cep=r['cep']
        if cep:
            st.metric('Dias fora dos limites',cep['sinais'])
            dados=r['serie'].copy();dados['Sinal']=np.where((dados['Processado']<cep['lci'])|(dados['Processado']>cep['lcs']),'Fora dos limites','Dentro dos limites')
            base=alt.Chart(dados).encode(x='Data:T',y=alt.Y('Processado:Q',title=unidade))
            limites=pd.DataFrame({'Limite':['LCI','Média','LCS'],'Volume':[cep['lci'],cep['media'],cep['lcs']]})
            regras=alt.Chart(limites).mark_rule(strokeDash=[5,4]).encode(y='Volume:Q',color='Limite:N',tooltip=['Limite','Volume'])
            st.altair_chart((base.mark_line(color='#6488a8')+base.mark_circle(size=65).encode(color=alt.Color('Sinal:N',scale=alt.Scale(domain=['Dentro dos limites','Fora dos limites'],range=['#27806b','#d94c4c'])),tooltip=['Data:T','Processado:Q','Sinal:N'])+regras).resolve_scale(color='independent').properties(height=300),use_container_width=True)
            st.caption('Carta I exploratória: média ± 3 × amplitude móvel média / 1,128. Limites estimados no próprio período, não são metas. Sinais pedem investigação; ausência de sinais não comprova estabilidade. Mudanças de mix, jornada e registros podem afetar os limites.')
        else:st.info('CEP requer pelo menos 20 dias válidos, variação entre dias e dados completos. Não há evidência suficiente para exibir limites neste filtro.')
    with abas[2]:
        if r['serie'].empty:st.info('Selecione também dias anteriores a hoje para analisar a distribuição de dias completos.')
        st.altair_chart(alt.Chart(r['serie']).mark_bar(color='#27806b').encode(x=alt.X('Processado:Q',bin=alt.Bin(maxbins=12),title=f'Volume diário ({unidade})'),y=alt.Y('count():Q',title='Quantidade de dias'),tooltip=['count():Q']).properties(height=280),use_container_width=True)
        st.caption('Mostra a frequência dos volumes diários registrados. A forma do histograma, isoladamente, não confirma distribuição normal.')
    with abas[3]:
        serie=r['serie'].copy();serie['dia']=serie['Data'].dt.dayofweek
        semana=serie.groupby('dia')['Processado'].agg(['mean','count']).reset_index()
        if len(serie)<28 or (semana['count']<4).any():st.info('Amplie o período: o padrão semanal requer pelo menos 28 dias válidos e quatro observações de cada dia da semana presente.')
        else:
            nomes=['Seg','Ter','Qua','Qui','Sex','Sáb','Dom'];semana['Dia']=semana['dia'].map(dict(enumerate(nomes)))
            st.altair_chart(alt.Chart(semana).mark_bar(color='#6488a8').encode(x=alt.X('Dia:N',sort=nomes),y=alt.Y('mean:Q',title=f'Média ({unidade})'),tooltip=['Dia','mean','count']).properties(height=280),use_container_width=True)
            st.caption('Padrão descritivo por dia da semana. Não comprova sazonalidade; feriados e mudanças de demanda podem explicar diferenças. Sazonalidade anual exige vários ciclos históricos comparáveis.')
    with st.expander('Dados e critérios de cálculo'):
        st.caption('Dias: jornada atualmente cadastrada, descontando feriados; inclui também datas com programação ou encerramentos. Sem jornada cadastrada, considera segunda a sexta. Alterar a jornada/feriados pode modificar os dias históricos considerados. Capacidade diária não é automaticamente proporcional à duração da jornada.')
        st.caption('Rendimento de matéria-prima não disponível: exige entradas e saídas comparáveis e conversões técnicas por produto. Baixas de insumos não equivalem automaticamente a perdas físicas medidas.')
        st.markdown('[Referência metodológica: cartas individuais — NIST](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc322.htm)')
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('Baixar dados CSV',df.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'estatistica_equipamento.csv','text/csv')
