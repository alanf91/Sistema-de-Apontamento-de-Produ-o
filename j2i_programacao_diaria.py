"""Matriz diária de carga programada versus meta vigente."""
import json
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal
from html import escape
import streamlit as st
import j2i_industrial as m


def consultar(c,de,ate,turnos=1):
    planos=[dict(r) for r in c.execute('''SELECT p.*,e.maquina,e.setor FROM mes_programacao p
        JOIN equipamentos e ON e.id=p.equipamento_id WHERE e.ativo=1 AND data_programada BETWEEN ? AND ?
        ORDER BY e.setor,e.maquina,p.data_programada''',(de.isoformat(),ate.isoformat()))]
    metas=defaultdict(list)
    for r in c.execute('SELECT * FROM mes_metas WHERE vigencia<=? ORDER BY vigencia',(ate.isoformat(),)):metas[r['equipamento_id']].append(dict(r))
    jornadas={}
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_jornadas'").fetchone():
        jornadas={r['equipamento_id']:json.loads(r['dias_json']) for r in c.execute('SELECT * FROM mes_jornadas')}
    grupos={}
    for p in planos:
        regra=json.loads(p['regra_json']);unidade=m.validar_regra(regra)['unidade']
        chave=(p['equipamento_id'],p['data_programada'],unidade)
        g=grupos.setdefault(chave,dict(equipamento_id=p['equipamento_id'],Equipamento=p['maquina'],Setor=p['setor'] or 'Sem setor',Data=p['data_programada'],Unidade=unidade,Programado=Decimal(0),Meta=None,Estado='',invalida=False))
        try:
            fator=m.fator(regra,p['medida'])
            g['Programado']+=Decimal(str(m.calcular(p['quantidade'],fator)))
            if fator==0 and regra.get('permitir_dimensao_zero'):g['invalida']=True
        except ValueError:g['invalida']=True
    for (eq,dia,un),g in grupos.items():
        vigentes=[r for r in metas[eq] if r['vigencia']<=dia]
        meta=vigentes[-1] if vigentes else None
        if g['invalida']:g['Estado']='Dimensão pendente'
        elif not meta:g['Estado']='Sem meta'
        elif m.validar_regra(json.loads(meta['regra_json']))['unidade']!=un:g['Estado']='Unidade da meta diferente'
        else:
            multiplicador=Decimal(1)
            if meta['periodo']=='Hora':
                jornada=next((d for d in jornadas.get(eq,[]) if d['dia']==date.fromisoformat(dia).weekday()),None)
                if jornada is None:g['Estado']='Sem jornada';continue
                multiplicador=Decimal(str(jornada['minutos']))/60
            elif meta['periodo']=='Turno':multiplicador=Decimal(str(turnos))
            g['Meta']=Decimal(str(meta['valor']))*multiplicador
            g['Estado']='Dentro da meta' if g['Programado']<=g['Meta'] else 'Acima da meta'
    return list(grupos.values())


def diagnosticar_dimensoes(c,de,ate):
    problemas=[]
    for r in c.execute("""SELECT p.*,e.codigo,e.maquina,e.setor FROM mes_programacao p
        JOIN equipamentos e ON e.id=p.equipamento_id WHERE e.ativo=1
        AND p.data_programada BETWEEN ? AND ? ORDER BY e.maquina,p.data_programada,p.op,p.etapa""",
        (de.isoformat(),ate.isoformat())):
        try:
            regra=m.validar_regra(json.loads(r['regra_json']))
            f=m.fator(regra,r['medida'])
            if f<=0:raise ValueError('Medida zerada ou fator zero; não permite apurar o volume da etapa.')
        except (ValueError,TypeError,KeyError) as exc:
            problemas.append({'Equipamento':r['maquina'],'Código':r['codigo'],'Setor':r['setor'] or 'Sem setor',
                'Data':r['data_programada'],'Lote':r['lote'],'OP':r['op'],'Etapa':r['etapa'],
                'Peça':r['peca'],'Medida cadastrada':r['medida'],'Quantidade':r['quantidade'],
                'Motivo':str(exc)})
    return problemas


def numero(v):return f'{float(v):,.3f}'.replace(',','@').replace('.',',').replace('@','.')


def matriz(rows,dias):
    mapa={(r['equipamento_id'],r['Unidade'],r['Data']):r for r in rows}
    eqs=sorted({(r['equipamento_id'],r['Equipamento'],r['Unidade']) for r in rows},key=lambda x:x[1])
    html=['<div style="overflow-x:auto"><table style="border-collapse:separate;border-spacing:5px;width:100%"><thead><tr><th>Equipamento / unidade</th>']
    html.extend('<th style="min-width:130px">'+d.strftime('%d/%m/%Y')+'</th>' for d in dias)
    html.append('</tr></thead><tbody>')
    for eq,nome,un in eqs:
        html.append('<tr><th style="min-width:230px;text-align:left">'+escape(nome)+'<br>'+escape(un)+'</th>')
        for d in dias:
            r=mapa.get((eq,un,d.isoformat()))
            if not r:html.append('<td style="text-align:center">—</td>');continue
            cor={'Dentro da meta':'#155e3b','Acima da meta':'#922b32'}.get(r['Estado'],'#454b54')
            valor='Revisar' if r['invalida'] else numero(r['Programado'])
            meta=numero(r['Meta']) if r['Meta'] is not None else '—'
            html.append(f'<td style="background:{cor};color:white;border-radius:7px;padding:12px;text-align:center"><strong>{valor}</strong><br><small>Meta: {meta}<br>{escape(r["Estado"])}</small></td>')
        html.append('</tr>')
    html.append('</tbody></table></div>');return ''.join(html)


def renderizar(a):
    st.title('Programação diária × meta')
    st.caption('Verde: programado menor ou igual à meta. Vermelho: acima da meta. Cinza: comparação indisponível. — indica ausência de programação.')
    cols=st.columns(2)
    de=cols[0].date_input('Data inicial',date.today(),key='matriz_de')
    ate=cols[1].date_input('Data final',date.today()+timedelta(days=6),key='matriz_ate')
    if de>ate:st.error('A data final deve ser igual ou posterior à inicial.');return
    turnos=st.number_input('Turnos por dia para metas cadastradas por turno',min_value=1,max_value=10,value=1)
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        rows=consultar(c,de,ate,turnos)
        problemas=diagnosticar_dimensoes(c,de,ate)
    if not rows:st.info('Não há equipamentos com programação no período selecionado.');return
    setores=sorted({r['Setor'] for r in rows})
    selecionados=st.multiselect('Setores',setores,default=setores)
    rows=[r for r in rows if r['Setor'] in selecionados]
    if not rows:st.info('Selecione pelo menos um setor.');return
    st.caption('A meta respeita sua vigência em cada data. Meta por hora × horas da jornada atualmente cadastrada; meta por turno × turnos informados acima; meta diária usada diretamente. Não há desconto automático de feriados nesta comparação. Alterar a jornada modifica a conversão de metas por hora.')
    blocos=[de+timedelta(days=i) for i in range(0,(ate-de).days+1,14)]
    inicio=st.selectbox('Dias exibidos no quadro (até 14 por vez)',blocos,format_func=lambda d:f'{d:%d/%m/%Y} a {min(d+timedelta(days=13),ate):%d/%m/%Y}')
    dias=[inicio+timedelta(days=i) for i in range(min(14,(ate-inicio).days+1))]
    for setor in selecionados:
        rs=[r for r in rows if r['Setor']==setor]
        if not rs:continue
        st.subheader(setor)
        st.markdown(matriz(rs,dias),unsafe_allow_html=True)
    from j2i_industrial_ui import csv_bytes
    problemas=[r for r in problemas if r['Setor'] in selecionados]
    if problemas:
        with st.expander('OPs com dimensão pendente — conferir origem do aviso',expanded=True):
            st.warning('Essas passagens impedem o cálculo completo dos dias indicados. Confirme as medidas no documento de origem; não são convertidas automaticamente a partir da descrição da peça.')
            st.dataframe(problemas,use_container_width=True,hide_index=True)
            st.download_button('Baixar OPs com dimensão pendente',csv_bytes(problemas),'ops_dimensao_pendente.csv','text/csv')
    export=[{k:(float(v) if isinstance(v,Decimal) else v) for k,v in r.items() if k not in ('invalida','equipamento_id')} for r in rows]
    st.download_button('Baixar programação e metas do período',csv_bytes(export),'programacao_diaria_metas.csv','text/csv')
