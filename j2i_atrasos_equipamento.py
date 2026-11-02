"""Carteira vencida: saldo atual das passagens programadas até ontem (somente leitura)."""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
import streamlit as st
import j2i_industrial as m
from j2i_sessoes_producao import resumir


def consultar(c, hoje):
    corte = hoje - timedelta(days=1)
    eqs = {r['id']: dict(r) for r in c.execute('SELECT id,codigo,maquina,setor,ativo FROM equipamentos WHERE ativo=1 ORDER BY maquina,id')}
    metricas = {r['equipamento_id']: r['regra_json'] for r in c.execute('SELECT equipamento_id,regra_json FROM mes_metricas')}
    planos = [dict(r) for r in c.execute('SELECT * FROM mes_programacao WHERE equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) ORDER BY equipamento_id,data_programada,op,etapa')]
    from j2i_encerramento_ppcp import fechadas
    manuais=fechadas(c)
    candidatos, avisos = [], []
    for p in planos:
        if (p['op'],p['lote'],p['etapa']) in manuais:continue
        try:
            dia = date.fromisoformat(p['data_programada'] or '')
        except (TypeError, ValueError):
            avisos.append({'OP': p['op'], 'Etapa': p['etapa'], 'Pendência': 'Data programada ausente ou inválida; atraso não classificável.'})
            continue
        if dia <= corte:
            candidatos.append(p)
    # Apenas OPs com etapas vencidas, sem uma consulta SQL por passagem.
    ops = {p['op'] for p in candidatos}
    por_op = defaultdict(list)
    por_etapa = defaultdict(list)
    for row in c.execute('''SELECT o.*,r.fator AS metrica_fator,r.unidade AS metrica_unidade,
        r.regra_json AS metrica_regra FROM ordens_operacionais o
        LEFT JOIN mes_resultados r ON r.ordem_id=o.id
        WHERE o.status IN ('ABERTA','FINALIZADA') AND EXISTS (
          SELECT 1 FROM mes_programacao p WHERE p.op=o.ficha_op AND p.data_programada<=?)
        ORDER BY o.id''',(corte.isoformat(),)):
        r=dict(row)
        if r['ficha_op'] in ops:
            por_op[(r['ficha_op'],r['lote_identificado'])].append(r)
            por_etapa[(r['ficha_op'],r['lote_identificado'],r['rota_ordem'])].append(r)
    detalhes=[]
    for p in candidatos:
        eq=eqs.get(p['equipamento_id'])
        if not eq:
            avisos.append({'OP':p['op'],'Etapa':p['etapa'],'Pendência':'Equipamento ausente no cadastro.'})
            continue
        registros=por_etapa.get((p['op'],p['lote'],p['etapa']),[])
        ignorada=False;erro='';saldo=None;valor=None;unidade='Não identificada';situacao='Não iniciada'
        try:
            if any(r['equipamento_id']!=p['equipamento_id'] for r in registros):
                raise ValueError('Equipamento do apontamento diverge da programação.')
            estado=resumir(registros)
            if estado['concluida']:continue
            if registros:
                saldo=estado['saldo']
                situacao='Em andamento' if estado['aberta'] else 'Parcial — aguardando retomada'
            else:
                # Peças sucateadas nas passagens anteriores não chegam às posteriores.
                perdas=sum(Decimal(str(r['refugo'] or 0)) for r in por_op[(p['op'],p['lote'])]
                           if r['rota_ordem'] is not None and r['rota_ordem']<p['etapa'] and r['status']=='FINALIZADA')
                saldo=float(max(Decimal(0),m.numero(p['quantidade'])-perdas))
            if saldo<=0:continue
            primeiro=registros[0] if registros else None
            regra=m.validar_regra(json.loads(primeiro['metrica_regra'] if primeiro and primeiro['metrica_regra'] else p['regra_json']))
            unidade=regra['unidade']
            fator=float(m.numero(primeiro['metrica_fator'])) if primeiro and primeiro['metrica_fator'] is not None else m.fator(dict(regra,permitir_dimensao_zero=True),p['medida'])
            if fator==0:
                ignorada=True
                raise ValueError('Ignorada temporariamente no total: conversão zerada. Revise as medidas da passagem.')
            if fator<0:raise ValueError('Fator de conversão negativo.')
            valor=m.calcular(saldo,fator)
        except (ValueError,TypeError,KeyError) as exc:
            erro=str(exc)
        detalhes.append({'equipamento_id':eq['id'],'Código':eq['codigo'],'Equipamento':eq['maquina'],
            'Setor':eq['setor'] or 'Sem setor','Cadastro':'Ativo' if eq['ativo'] else 'Inativo',
            'OP':p['op'],'Lote':p['lote'],'Passagem':p['etapa'],'Peça':p['peca'],
            'Data prevista':p['data_programada'],'Dias em atraso':(hoje-date.fromisoformat(p['data_programada'])).days,
            'Situação':situacao,'Saldo em peças':saldo,'Unidade':unidade,'Saldo na métrica':valor,'Pendência':erro,'Ignorada por conversão zerada':ignorada})
    grupos={}
    for d in detalhes:
        chave=(d['equipamento_id'],d['Unidade'])
        g=grupos.setdefault(chave,{'equipamento_id':d['equipamento_id'],'Código':d['Código'],'Equipamento':d['Equipamento'],
            'Setor':d['Setor'],'Cadastro':d['Cadastro'],'Unidade':d['Unidade'],'OPs em atraso':set(),
            'Passagens pendentes':0,'Saldo calculado':Decimal(0),'Pendências de cálculo':0,'Passagens ignoradas (zero)':0,'Maior atraso (dias)':0})
        g['OPs em atraso'].add((d['OP'],d['Lote']))
        g['Passagens pendentes']+=1
        g['Maior atraso (dias)']=max(g['Maior atraso (dias)'],d['Dias em atraso'])
        if d['Ignorada por conversão zerada']:g['Passagens ignoradas (zero)']+=1
        elif d['Pendência']:g['Pendências de cálculo']+=1
        else:g['Saldo calculado']+=Decimal(str(d['Saldo na métrica']))
    com_saldo={k[0] for k in grupos}
    for eq in eqs.values():
        if eq['id'] in com_saldo:continue
        try:unidade=m.validar_regra(json.loads(metricas.get(eq['id'],'{}')))['unidade']
        except (ValueError,TypeError,KeyError):unidade='Não configurada'
        grupos[(eq['id'],unidade)]={'equipamento_id':eq['id'],'Código':eq['codigo'],'Equipamento':eq['maquina'],
            'Setor':eq['setor'] or 'Sem setor','Cadastro':'Ativo' if eq['ativo'] else 'Inativo','Unidade':unidade,
            'OPs em atraso':set(),'Passagens pendentes':0,'Saldo calculado':Decimal(0),'Pendências de cálculo':0,'Passagens ignoradas (zero)':0,'Maior atraso (dias)':0}
    resumo=[]
    for g in grupos.values():
        g['OPs em atraso']=len(g['OPs em atraso'])
        g['Saldo calculado']=float(g['Saldo calculado'])
        g['Total em atraso']=None if g['Pendências de cálculo'] else g['Saldo calculado']
        resumo.append(g)
    sem_plano=c.execute('''SELECT COUNT(*) FROM ordens_operacionais o WHERE
        NOT EXISTS (SELECT 1 FROM mes_encerramentos_ppcp m WHERE m.op=o.ficha_op AND m.lote=o.lote_identificado AND m.etapa=o.rota_ordem) AND o.equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) AND (o.status='ABERTA' OR o.encerramento_parcial=1) AND NOT EXISTS
        (SELECT 1 FROM mes_programacao p WHERE p.op=o.ficha_op AND p.etapa=o.rota_ordem AND p.lote=o.lote_identificado)
        AND NOT EXISTS (SELECT 1 FROM ordens_operacionais f WHERE f.ficha_op=o.ficha_op
        AND f.lote_identificado=o.lote_identificado AND f.rota_ordem=o.rota_ordem
        AND f.status='FINALIZADA' AND f.encerramento_parcial=0)''').fetchone()[0]
    if sem_plano:
        avisos.append({'OP':'','Etapa':'','Pendência':f'{sem_plano} sessão(ões) aberta(s)/parcial(is) sem programação correspondente; não é possível determinar a data de atraso.'})
    return sorted(resumo,key=lambda r:(r['Equipamento'],r['equipamento_id'],r['Unidade'])),detalhes,avisos


def renderizar(a):
    st.title('Saldo em atraso por equipamento')
    if st.session_state.get('ppcp_sucesso'):st.success(st.session_state.pop('ppcp_sucesso'))
    instante=datetime.fromisoformat(a.agora_iso())
    corte=instante.date()-timedelta(days=1)
    st.caption(f'Programação com vencimento até {corte:%d/%m/%Y} · saldo atual consultado em {instante:%d/%m/%Y às %H:%M:%S} (servidor).')
    st.info('Inclui OPs não iniciadas, em andamento e parciais. Produção apontada hoje também reduz o saldo. Etapas previstas para hoje ou depois não entram.')
    st.button('Atualizar saldos',key='atrasos_atualizar')
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        resumo,detalhes,avisos=consultar(c,instante.date())
    setores=sorted({r['Setor'] for r in resumo})
    setor=st.selectbox('Setor',['Todos']+setores,key='atrasos_setor')
    base=[r for r in resumo if setor=='Todos' or r['Setor']==setor]
    nomes={r['equipamento_id']:f"{r['Código']} — {r['Equipamento']}" for r in base}
    eq=st.selectbox('Equipamento',[None]+list(nomes),format_func=lambda i:'Todos' if i is None else nomes[i],key='atrasos_eq')
    somente=st.checkbox('Mostrar somente equipamentos com pendências',value=True,key='atrasos_pendentes')
    rows=[r for r in base if (eq is None or r['equipamento_id']==eq) and (not somente or r['Passagens pendentes']>0)]
    ids={r['equipamento_id'] for r in rows}
    ds=[r for r in detalhes if r['equipamento_id'] in ids]
    cols=st.columns(3)
    cols[0].metric('Equipamentos com atraso',len({r['equipamento_id'] for r in rows if r['Passagens pendentes']}))
    cols[1].metric('OPs distintas em atraso',len({(r['OP'],r['Lote']) for r in ds}))
    cols[2].metric('Passagens pendentes',len(ds))
    st.caption('Cada passagem representa trabalho pendente no equipamento. A mesma OP pode ter mais de uma passagem. Unidades diferentes não são somadas; prevalece a métrica preservada na passagem ou na programação.')
    colunas=['Código','Equipamento','Setor','Cadastro','Unidade','Total em atraso','OPs em atraso','Passagens pendentes','Maior atraso (dias)','Passagens ignoradas (zero)','Pendências de cálculo']
    if rows:
        st.dataframe([{k:r[k] for k in colunas} for r in rows],hide_index=True,use_container_width=True,
                     column_config={'Total em atraso':st.column_config.NumberColumn(format='%.3f')})
    elif not avisos:st.success('Nenhum saldo vencido encontrado para os filtros selecionados.')
    else:st.info('Nenhum saldo vencido classificável para os filtros. Confira os avisos abaixo.')
    ignoradas=sum(r['Passagens ignoradas (zero)'] for r in rows)
    if ignoradas:
        st.warning(f'Total parcial: {ignoradas} passagem(ns) com conversão zerada foram ignoradas temporariamente na soma. Continuam nas contagens e no detalhamento; as medidas não foram alteradas.')
    if any(r['Pendências de cálculo'] for r in rows):
        st.warning('Há totais indisponíveis por dados inconsistentes ou métricas sem conversão válida. Confira o detalhamento. Não foram tratados como zero.')
    from j2i_industrial_ui import csv_bytes
    if rows:st.download_button('Baixar resumo de atrasos',csv_bytes([{k:v for k,v in r.items() if k!='equipamento_id'} for r in rows]),f'atrasos_resumo_{corte}.csv','text/csv')
    with st.expander('Conferir OPs e saldos que compõem os totais',expanded=False):
        itens=[{k:v for k,v in r.items() if k!='equipamento_id'} for r in ds]
        st.dataframe(itens,hide_index=True,use_container_width=True)
        if itens:st.download_button('Baixar detalhamento por OP',csv_bytes(itens),f'atrasos_ops_{corte}.csv','text/csv')
    if avisos:
        st.warning('Existem registros sem classificação de atraso. Os avisos abaixo abrangem todos os equipamentos.')
        st.dataframe(avisos,hide_index=True,use_container_width=True)

    from j2i_encerramento_ppcp import renderizar as encerramento_ppcp
    encerramento_ppcp(a,eq)
