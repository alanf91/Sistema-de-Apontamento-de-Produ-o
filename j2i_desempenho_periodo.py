"""Comparação por data: programação prevista e produção efetivamente apontada."""
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
import j2i_industrial as m


def consultar(c, de, ate, equipamento_ids=None):
    if de>ate:raise ValueError('A data final deve ser igual ou posterior à inicial.')
    eqs={r['id']:dict(r) for r in c.execute('SELECT id,codigo,maquina,setor,ativo FROM equipamentos WHERE ativo=1 ORDER BY maquina,id')}
    ids=set(eqs) if equipamento_ids is None else set(equipamento_ids)&set(eqs)
    if not ids:return [],[],[],[]
    marcas=','.join('?' for _ in ids);params=sorted(ids)
    planos=[dict(r) for r in c.execute(f'SELECT * FROM mes_programacao WHERE equipamento_id IN ({marcas}) AND data_programada BETWEEN ? AND ? ORDER BY data_programada,op,etapa',(*params,de.isoformat(),ate.isoformat()))]
    rows=[dict(r) for r in c.execute(f'''SELECT o.*,r.unidade AS unidade_snapshot,r.fator AS fator_snapshot,
        r.boas AS boas_metrica,r.sucata AS sucata_metrica,r.retrabalho AS retrabalho_metrica,
        p.regra_json AS regra_plano,p.data_programada,p.medida AS medida_plano,
        cfg.regra_json AS regra_atual
        FROM ordens_operacionais o LEFT JOIN mes_resultados r ON r.ordem_id=o.id
        LEFT JOIN mes_programacao p ON p.op=o.ficha_op AND p.etapa=o.rota_ordem
            AND p.equipamento_id=o.equipamento_id AND p.lote=o.lote_identificado
        LEFT JOIN mes_metricas cfg ON cfg.equipamento_id=o.equipamento_id
        WHERE o.equipamento_id IN ({marcas}) AND o.status='FINALIZADA'
        AND o.fechada_em>=? AND o.fechada_em<? ORDER BY o.fechada_em,o.id''',
        (*params,de.isoformat(),(ate+timedelta(days=1)).isoformat()))]
    grupos={};avisos=[];detalhes=[];programacao=[]
    def grupo(eqid,un):
        eq=eqs[eqid];chave=(eqid,un)
        return grupos.setdefault(chave,{'equipamento_id':eqid,'Código':eq['codigo'],'Equipamento':eq['maquina'],
            'Setor':eq['setor'] or 'Sem setor','Lote':set(),'Unidade':un,
            'Programado':Decimal(0),'Realizado total':Decimal(0),'Realizado bom':Decimal(0),
            'Sucata':Decimal(0),'Retrabalho':Decimal(0),'Apontamentos':0,'programado_invalido':False})
    for p in planos:
        un='Métrica pendente';valor=None
        try:
            regra=m.validar_regra(json.loads(p['regra_json']));un=regra['unidade']
            fator=m.fator(regra,p['medida'])
            if fator<=0:raise ValueError('Fator da programação zerado.')
            valor=m.calcular(p['quantidade'],fator)
            grupo(p['equipamento_id'],un)['Programado']+=Decimal(str(valor))
        except (ValueError,TypeError,KeyError) as exc:
            grupo(p['equipamento_id'],un)['programado_invalido']=True
            avisos.append(f"OP {p['op']}, etapa {p['etapa']}: programação sem conversão válida ({exc}).")
        lote=str(p['lote']).strip() if p['lote'] is not None else ''
        if lote:grupo(p['equipamento_id'],un)['Lote'].add(lote)
        programacao.append({'Equipamento':eqs[p['equipamento_id']]['maquina'],'OP':p['op'],'Etapa':p['etapa'],
            'Data prevista':p['data_programada'],'Unidade':un,'Programado':valor})
    for r in rows:
        origem='Métrica preservada no apontamento'
        try:
            if r['unidade_snapshot'] and all(r[k] is not None for k in ('boas_metrica','sucata_metrica','retrabalho_metrica')):
                un=r['unidade_snapshot']
                b,s,rt=[float(m.numero(r[k])) for k in ('boas_metrica','sucata_metrica','retrabalho_metrica')]
                if r['fator_snapshot'] is None or float(m.numero(r['fator_snapshot']))<=0:
                    raise ValueError('Fator preservado ausente ou zerado.')
            else:
                regra=m.validar_regra(json.loads(r['regra_plano'] or r['regra_atual'] or '{}'))
                un=regra['unidade'];fator=m.fator(regra,r['medida_ficha'] or r['medida_plano'] or '')
                if fator<=0:raise ValueError('Fator de conversão zerado.')
                b,s,rt=[m.calcular(r[k] or 0,fator) for k in ('quantidade_boa','refugo','retrabalho')]
                origem='Legado convertido pela programação' if r['regra_plano'] else 'Legado convertido pelo cadastro atual'
                avisos.append(f"Apontamento {r['id']}, OP {r['ficha_op']}: {origem.lower()}; não possui resultado métrico preservado.")
        except (ValueError,TypeError,KeyError) as exc:
            un='peças (conversão pendente)';origem='Quantidade original em peças'
            b,s,rt=[float(m.numero(r[k] or 0)) for k in ('quantidade_boa','refugo','retrabalho')]
            avisos.append(f"Apontamento {r['id']}, OP {r['ficha_op']}: exibido em peças, sem misturar com a métrica do equipamento ({exc}).")
        g=grupo(r['equipamento_id'],un)
        for k,v in [('Realizado bom',b),('Sucata',s),('Retrabalho',rt),('Realizado total',b+s)]:g[k]+=Decimal(str(v))
        g['Apontamentos']+=1
        detalhes.append({'Registro':r['id'],'Equipamento':eqs[r['equipamento_id']]['maquina'],'OP':r['ficha_op'],
            'Lote':r['lote_identificado'],'Etapa':r['rota_ordem'],'Fechamento':r['fechada_em'],
            'Encerramento':'Parcial' if r['encerramento_parcial'] else 'Total','Data prevista':r['data_programada'],
            'Unidade':un,'Realizado total':b+s,'Realizado bom':b,'Sucata':s,'Retrabalho':rt,'Origem da métrica':origem})
    # Equipamentos sem qualquer movimento também integram o relatório.
    presentes={eqid for eqid,un in grupos}
    metricas={r['equipamento_id']:r['regra_json'] for r in c.execute('SELECT equipamento_id,regra_json FROM mes_metricas')}
    for eqid in sorted(ids-presentes):
        try:un=m.validar_regra(json.loads(metricas.get(eqid,'{}')))['unidade']
        except (ValueError,TypeError,KeyError):un='Métrica não configurada'
        grupo(eqid,un)
    resumo=[]
    for g in grupos.values():
        invalido=g.pop('programado_invalido')
        g['Lote']=', '.join(sorted(g['Lote'],key=lambda v:(0,int(v),v) if v.isdecimal() else (1,0,v))) or '—'
        for k,v in list(g.items()):
            if isinstance(v,Decimal):g[k]=float(v)
        if invalido:g['Programado']=None
        g['Atingimento bom/programado (%)']=round(100*g['Realizado bom']/g['Programado'],2) if g['Programado'] else None
        resumo.append(g)
    return sorted(resumo,key=lambda r:(r['Equipamento'],r['equipamento_id'],r['Unidade'])),programacao,detalhes,avisos


def renderizar(a):
    import streamlit as st
    from j2i_industrial_ui import csv_bytes
    st.title('Programado × realizado por equipamento')
    st.caption('Programado: etapas previstas nas datas selecionadas. Realizado: todos os apontamentos encerrados nessas datas, inclusive parciais e OPs sem programação no período.')
    st.button('Atualizar consulta',key='desempenho_atualizar')
    hoje=datetime.fromisoformat(a.agora_iso()).date()
    de=st.date_input('De',hoje,key='desempenho_de')
    ate=st.date_input('Até',hoje,key='desempenho_ate')
    if de>ate:st.error('Período inválido.');return
    with a.conectar_banco_operacional() as c:
        eqs=[dict(r) for r in c.execute('SELECT id,codigo,maquina,setor,ativo FROM equipamentos WHERE ativo=1 ORDER BY maquina,id')]
    setor=st.selectbox('Setor',['Todos']+sorted({e['setor'] or 'Sem setor' for e in eqs}),key='desempenho_setor')
    eqs=[e for e in eqs if setor=='Todos' or (e['setor'] or 'Sem setor')==setor]
    mapa={e['id']:e for e in eqs}
    eq=st.selectbox('Equipamento',[None]+list(mapa),format_func=lambda i:'Todos do setor' if i is None else f"{mapa[i]['codigo']} — {mapa[i]['maquina']}"+(' (inativo)' if not mapa[i]['ativo'] else ''),key='desempenho_eq')
    ids=[eq] if eq is not None else list(mapa)
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        resumo,planos,resultados,avisos=consultar(c,de,ate,ids)
        from j2i_atraso_programado import incluir
        resumo,detalhes_atraso,avisos_atraso=incluir(c,resumo,de,ids)
        meta=c.execute('SELECT * FROM mes_metas WHERE equipamento_id=? AND vigencia<=? ORDER BY vigencia DESC LIMIT 1',(eq,de.isoformat())).fetchone() if eq is not None else None
    st.caption('Realizado total = boas + sucata. Retrabalho já está incluído nas boas e não é somado novamente. Somente os equipamentos marcados em Métricas e Metas → Equipamentos ativos aparecem, inclusive sem programação ou apontamentos, com valores zero. Unidades diferentes permanecem separadas.')
    if not resumo:st.info('Nenhuma programação ou apontamento encontrado no período e nos filtros selecionados.');return
    if any(r['Programado']==0 and r['Apontamentos'] for r in resumo):
        st.info('Equipamentos sem programação no período aparecem com Programado = 0 e todo o volume apontado em Realizado. O atingimento fica sem percentual quando o programado é zero.')
    st.caption(f'Atraso: saldo atual ainda pendente de etapas previstas até {(de-timedelta(days=1)):%d/%m/%Y}. Programação da data De em diante não entra no atraso. Não é uma fotografia histórica do saldo naquela data.')
    if avisos_atraso:st.warning('Há pendências na apuração do atraso. Consulte o detalhamento abaixo; valor vazio não significa saldo zero.')
    export=[{k:v for k,v in r.items() if k!='equipamento_id'} for r in resumo]
    st.dataframe(export,use_container_width=True,hide_index=True)
    st.download_button('Baixar resumo Programado × realizado',csv_bytes(export),'programado_realizado_resumo.csv','text/csv')
    agregado={}
    for r in resumo:
        chave=(r['Setor'],r['Unidade'])
        g=agregado.setdefault(chave,{'Setor':r['Setor'],'Unidade':r['Unidade'],**{k:0. for k in ['Programado','Atraso','Realizado total','Realizado bom','Sucata','Retrabalho']}})
        for k in ['Programado','Atraso','Realizado total','Realizado bom','Sucata','Retrabalho']:
            g[k]=None if g[k] is None or r[k] is None else g[k]+r[k]
    st.subheader('Produção por setor e unidade')
    st.dataframe(list(agregado.values()),use_container_width=True,hide_index=True)
    if meta and de==ate:
        regra=m.validar_regra(json.loads(meta['regra_json']))
        multiplicador=st.number_input('Horas previstas no dia' if meta['periodo']=='Hora' else 'Turnos previstos no dia',min_value=0.,value=8. if meta['periodo']=='Hora' else 1.) if meta['periodo']!='Dia' else 1.
        alvo=meta['valor']*multiplicador
        real=sum(r['Realizado bom'] for r in resumo if r['equipamento_id']==eq and r['Unidade']==regra['unidade'])
        st.metric('Meta do dia',f"{alvo:g} {regra['unidade']}")
        st.metric('Atingimento da meta',f'{real/alvo*100:.1f}%' if alvo else 'Sem meta numérica')
    elif de!=ate:st.caption('Selecione um único dia e equipamento para comparar com a meta vigente.')
    with st.expander('Conferir composição do Atraso'):
        st.dataframe(detalhes_atraso,use_container_width=True,hide_index=True)
        if detalhes_atraso:st.download_button('Baixar composição do Atraso',csv_bytes(detalhes_atraso),'composicao_atraso.csv','text/csv')
        if avisos_atraso:st.dataframe(avisos_atraso,use_container_width=True,hide_index=True)
    with st.expander('Conferir origem do Programado e datas'):
        st.dataframe(planos,use_container_width=True,hide_index=True)
        if planos:st.download_button('Baixar composição do Programado',csv_bytes(planos),'composicao_programado.csv','text/csv')
    st.subheader('Apontamentos do período')
    st.dataframe(resultados,use_container_width=True,hide_index=True)
    if resultados:st.download_button('Baixar apontamentos do período',csv_bytes(resultados),'apontamentos_metricas.csv','text/csv')
    if avisos:
        st.warning('Alguns registros exigem conferência da métrica. Conversões de legados estão identificadas abaixo e no detalhamento.')
        with st.expander('Avisos de cálculo',expanded=True):st.dataframe({'Aviso':avisos},hide_index=True,use_container_width=True)
