"""OEE por tempo ideal, com referências explícitas e versionadas."""
import json,math
from datetime import datetime,timedelta,date
from collections import defaultdict


def salvar(c,eq,operacao,unidade,minutos,vigencia,usuario,confirmado):
    if not confirmado:raise ValueError('Confirme que o ritmo representa a velocidade ideal, não a meta.')
    if not math.isfinite(minutos) or minutos<=0:raise ValueError('Tempo ideal deve ser positivo.')
    date.fromisoformat(vigencia)
    if not operacao.strip() or not unidade.strip():raise ValueError('Informe operação e unidade.')
    if not c.execute('SELECT 1 FROM equipamentos WHERE id=? AND ativo=1',(eq,)).fetchone():raise ValueError('Equipamento não está ativo.')
    c.execute('''CREATE TABLE IF NOT EXISTS mes_oee_referencias (
       id INTEGER PRIMARY KEY,equipamento_id INTEGER NOT NULL,operacao TEXT NOT NULL,
       unidade TEXT NOT NULL,minutos_unidade REAL NOT NULL CHECK(minutos_unidade>0),
       vigencia TEXT NOT NULL,usuario TEXT NOT NULL,criado_em TEXT NOT NULL)''')
    c.execute('INSERT INTO mes_oee_referencias(equipamento_id,operacao,unidade,minutos_unidade,vigencia,usuario,criado_em) VALUES(?,?,?,?,?,?,?)',
              (eq,operacao.strip(),unidade.strip(),minutos,vigencia,usuario,datetime.now().isoformat(timespec='seconds')))


def uniao(intervalos):
    merged=[]
    for ini,fim in sorted(intervalos):
        if fim<=ini:continue
        if merged and ini<=merged[-1][1]:merged[-1]=(merged[-1][0],max(fim,merged[-1][1]))
        else:merged.append((ini,fim))
    return merged


def consultar(c,de,ate,agora):
    from j2i_diretoria import jornada,segundos
    eqs=[dict(r) for r in c.execute('SELECT id,maquina,setor FROM equipamentos WHERE ativo=1 ORDER BY maquina')]
    jornadas=jornada(c);inicio=datetime.combine(de,datetime.min.time());fim=min(agora,datetime.combine(ate+timedelta(days=1),datetime.min.time()))
    refs=[]
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_oee_referencias'").fetchone():refs=[dict(r) for r in c.execute('SELECT * FROM mes_oee_referencias ORDER BY vigencia,id')]
    paradas=defaultdict(list)
    for r in c.execute('SELECT equipamento_id,iniciada_em,encerrada_em FROM paradas_operacionais WHERE iniciada_em<? AND COALESCE(encerrada_em,?)>?',(fim.isoformat(sep=' '),fim.isoformat(sep=' '),inicio.isoformat(sep=' '))):
        paradas[r[0]].append((max(inicio,datetime.fromisoformat(r[1])),min(fim,datetime.fromisoformat(r[2])) if r[2] else fim))
    rows=defaultdict(list)
    for r in c.execute('''SELECT o.*,m.unidade oee_unidade,m.fator oee_fator FROM ordens_operacionais o
        LEFT JOIN mes_resultados m ON m.ordem_id=o.id
        WHERE o.status='FINALIZADA' AND o.fechada_em>=? AND o.fechada_em<?''',(inicio.isoformat(sep=' '),fim.isoformat(sep=' '))):rows[r['equipamento_id']].append(dict(r))
    saida=[]
    for eq in eqs:
        eid=eq['id'];dias=jornadas.get(eid);prev=segundos(dias,inicio,fim);erros=set();ideal=boas=0.
        if prev is None:erros.add('Jornada não cadastrada')
        par=sum(segundos(dias,a,b) or 0 for a,b in uniao(paradas[eid])) if dias else None
        rodando=max(0,prev-par) if prev is not None else None
        for r in rows[eid]:
            candidatos=[v for v in refs if v['equipamento_id']==eid and v['operacao'] in ('*',r['rota_operacao']) and v['vigencia']<=r['fechada_em'][:10]]
            exatos=[v for v in candidatos if v['operacao']==r['rota_operacao']];ref=(exatos or candidatos)[-1] if candidatos else None
            if ref is None:erros.add('Ritmo ideal ausente para operação/data');continue
            if ref['unidade']=='peças':fator=1.
            elif r['oee_unidade']==ref['unidade'] and r['oee_fator'] is not None and r['oee_fator']>0:fator=float(r['oee_fator'])
            else:erros.add('Unidade/medida do apontamento incompatível');continue
            b=float(r['quantidade_boa'] or 0);s=float(r['refugo'] or 0);rt=float(r['retrabalho'] or 0)
            if min(b,s,rt)<0 or rt>b:erros.add('Quantidades inconsistentes');continue
            ciclo=ref['minutos_unidade']*60*fator
            ideal+=(b+s)*ciclo;boas+=(b-rt)*ciclo
        if not rows[eid] and not any(v['equipamento_id']==eid and v['vigencia']<=de.isoformat() for v in refs):erros.add('Ritmo ideal não cadastrado')
        if prev and (ideal>(rodando or 0)+0.01):erros.add('Performance acima de 100%: revisar ritmo, datas ou paradas')
        if not prev and rows[eid]:erros.add('Produção sem jornada disponível')
        disp=rodando/prev if prev else None;perf=ideal/rodando if rodando else (0. if prev and not ideal else None);qual=boas/ideal if ideal else None
        oee=boas/prev if prev and not erros else None
        estado='; '.join(sorted(erros)) if erros else ('Sem jornada no período' if not prev else ('Provisório — período inclui hoje' if ate==agora.date() else 'Calculado'))
        saida.append(dict(_id=eid,_observ=len(rows[eid]),_prev=prev,_ideal_bom=boas,_valido=not erros and bool(prev),Equipamento=eq['maquina'],Setor=eq['setor'] or 'Sem setor',
          **{'OEE (%)':round(oee*100,2) if oee is not None else None,'Disponibilidade (%)':round(disp*100,2) if disp is not None else None,'Performance (%)':round(perf*100,2) if perf is not None and not erros else None,'Qualidade (%)':round(qual*100,2) if qual is not None and not erros else None,'Jornada (h)':round(prev/3600,2) if prev is not None else None,'Situação':estado}))
    elegiveis=[r for r in saida if r['_prev'] is None or r['_prev']>0 or r['_observ']>0]
    validos=[r for r in elegiveis if r['_valido']];den=sum(r['_prev'] for r in validos)
    parcial=100*sum(r['_ideal_bom'] for r in validos)/den if den else None
    return saida,dict(total=parcial if len(validos)==len(elegiveis) else None,parcial=parcial,validos=len(validos),elegiveis=len(elegiveis))


def renderizar(a,de,ate,agora,setor):
    import streamlit as st
    from html import escape
    from j2i_diretoria import publico
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN');rows,global_=consultar(c,de,ate,agora)
    total=global_['total'];texto=f'{total:.1f}%' if total is not None else 'Pendente'
    st.markdown(f'<div style="padding:20px;border:1px solid #8886;border-radius:12px;margin:12px 0"><div style="font-size:20px">OEE TOTAL DA FÁBRICA</div><div style="font-size:64px;font-weight:700;line-height:1.2">{escape(texto)}</div><div>{global_["validos"]} de {global_["elegiveis"]} equipamentos com jornada avaliável e dados completos</div></div>',unsafe_allow_html=True)
    st.caption('Consolidado de todos os equipamentos ativos, mesmo com setor filtrado. Ponderado pela jornada; não é média simples nem OEE da linha produtiva como um único processo.')
    if total is None and global_['parcial'] is not None:st.info(f"OEE parcial dos equipamentos calculáveis: {global_['parcial']:.1f}%. Não representa toda a fábrica.")
    if ate==agora.date():st.caption('OEE provisório: jornada transcorrida até a consulta e produção encerrada no período.')
    st.subheader('OEE por equipamento')
    st.dataframe(publico([r for r in rows if setor=='Todos' or r['Setor']==setor]),hide_index=True,use_container_width=True)
    with st.expander('Critérios e configuração do OEE'):
        st.write('OEE = Disponibilidade × Performance × Qualidade. Jornada cadastrada, sem intervalos, é o tempo planejado; todos os motivos de parada dentro dela reduzem disponibilidade. Paradas sobrepostas contam uma vez. Tempo sem parada registrada é considerado disponível para operação.')
        st.write('Performance usa tempo ideal por unidade e produção total. Qualidade considera boas sem retrabalho, ponderadas pelo tempo ideal. Encerramentos administrativos não contam. Ritmo ideal é a velocidade máxima sustentável, não a meta de produção.')
        st.caption('Os volumes pertencem à data do encerramento da sessão. OPs que atravessam dias podem exigir apontamentos parciais para uma avaliação diária coerente. Jornadas usam o cadastro atual; referências de ritmo têm vigência. Valores inconsistentes não são limitados artificialmente a 100%: ficam pendentes.')
        if not a.apontamento_autenticado():
            st.info('Entre com o acesso administrativo para cadastrar o ritmo ideal.');a.renderizar_login_apontamento();return
        mapa={r['_id']:r['Equipamento'] for r in rows}
        if not mapa:return
        eq=st.selectbox('Equipamento para configurar',list(mapa),format_func=lambda i:mapa[i],key='oee_eq')
        with a.conectar_banco_operacional() as c:
            ops=sorted({r[0] for r in c.execute('SELECT DISTINCT rota_operacao FROM ordens_operacionais WHERE equipamento_id=? AND rota_operacao IS NOT NULL',(eq,))})
            existentes=[dict(r) for r in c.execute('SELECT * FROM mes_oee_referencias WHERE equipamento_id=? ORDER BY vigencia DESC,id DESC',(eq,))] if c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_oee_referencias'").fetchone() else []
        st.caption('Use * somente se o mesmo tempo ideal por unidade servir para todas as peças e operações do equipamento. Para produtos com ritmos diferentes dentro da mesma operação, esta versão ainda não permite distinguir famílias; mantenha o OEE pendente até definir uma referência válida.')
        operacao=st.text_input('Operação exata ou *',value='*',key=f'oee_op_{eq}')
        if ops:st.caption('Operações existentes: '+', '.join(ops))
        unidade=st.selectbox('Unidade da referência',['peças','M²','m linear','uni'],key='oee_un')
        minutos=st.number_input('Minutos ideais por unidade',min_value=0.000001,value=1.,format='%.6f',key='oee_min')
        vigencia=st.date_input('Válido a partir de',agora.date(),key='oee_vig')
        confirma=st.checkbox('Confirmei o ritmo ideal e sua aplicação a todas as peças desta operação.',key='oee_conf')
        if st.button('Salvar referência OEE',disabled=not confirma):
            if not a.apontamento_autenticado():st.error('Sessão administrativa encerrada.');return
            with a.conectar_banco_operacional() as c:
                c.execute('BEGIN IMMEDIATE');salvar(c,eq,operacao,unidade,minutos,vigencia.isoformat(),str(a.LOGIN_APONTAMENTO),confirma)
            st.success('Referência salva. Atualize o resumo para recalcular.')
        if existentes:st.dataframe(existentes,hide_index=True,use_container_width=True)
