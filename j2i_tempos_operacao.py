"""Disponibilidade diária: segundos reais, agrupamento visual por minuto."""
from collections import defaultdict
from datetime import datetime, timedelta
import streamlit as st


def calcular(jornada, ordens, paradas, agora):
    agora=agora.replace(microsecond=0)
    dia=agora.date()
    def hora(v):return datetime.combine(dia,datetime.strptime(v,'%H:%M').time())
    janelas=[]
    if jornada['ativo']:
        pares=[(jornada['inicio'],jornada['fim'])] if not jornada['intervalo'] else [(jornada['inicio'],jornada['pausa']),(jornada['retorno'],jornada['fim'])]
        janelas=[(hora(a),hora(b)) for a,b in pares]
    previsto=sum(int((b-a).total_seconds()) for a,b in janelas)
    janelas=[(a,min(b,agora)) for a,b in janelas if a<min(b,agora)]
    eventos=defaultdict(list); pontos=set(); buckets={}; por_op={}; sobrepostos=0
    def bucket(t):
        minuto=t.replace(second=0,microsecond=0)
        return buckets.setdefault(minuto,dict(disponivel=0,producao=0,parada=0,livre=0,ops=set(),motivos=set()))
    for a,b in janelas:
        pontos.update([a,b]);t=a
        while t<b:
            bucket(t);t=t.replace(second=0)+timedelta(minutes=1);pontos.add(min(t,b))
    for tipo,rows,ini,fim in [('op',ordens,'aberta_em','fechada_em'),('parada',paradas,'iniciada_em','encerrada_em')]:
        for r in rows:
            inicio=datetime.fromisoformat(r[ini]);final=datetime.fromisoformat(r[fim]) if r.get(fim) else agora
            if final<inicio:raise ValueError('Registro com término anterior ao início; revise os horários do servidor.')
            ident=(tipo,r['id'])
            if tipo=='op':por_op[r['id']]=dict(OP=r['ficha_op'],Etapa=r.get('rota_ordem'),Abertura=r[ini],Fechamento=r.get(fim) or 'Em andamento',**{'Processamento (s)':0,'Paradas na OP (s)':0})
            for a,b in janelas:
                x,y=max(a,inicio),min(b,final)
                if x<y:
                    eventos[x].append((1,ident,r));eventos[y].append((-1,ident,r));pontos.update([x,y])
                # Registros instantâneos ainda identificam a OP no minuto da abertura.
                if tipo=='op' and a<=inicio<b:bucket(inicio)['ops'].add(r['ficha_op'])
    ativos={};lista=sorted(pontos)
    for i,t in enumerate(lista[:-1]):
        for sinal,k,r in eventos[t]:
            if sinal==1:ativos[k]=r
            else:ativos.pop(k,None)
        fim=lista[i+1]
        if not any(a<=t<b for a,b in janelas):continue
        seg=int((fim-t).total_seconds())
        if seg<=0:continue
        ops=[r for (tipo,_),r in ativos.items() if tipo=='op']
        stops=[r for (tipo,_),r in ativos.items() if tipo=='parada']
        b=bucket(t);b['disponivel']+=seg
        b['ops'].update(r['ficha_op'] for r in ops);b['motivos'].update(r['motivo'] for r in stops)
        categoria='parada' if stops else 'producao' if ops else 'livre'
        b[categoria]+=seg
        if len(ops)>1:sobrepostos+=seg
        for r in ops:por_op[r['id']]['Paradas na OP (s)' if stops else 'Processamento (s)']+=seg
    totais={k:sum(b[k] for b in buckets.values()) for k in ['disponivel','producao','parada','livre']}
    minutos=[{'Minuto':t.strftime('%H:%M'),'OPs':', '.join(sorted(b['ops'])),
              'Disponível (s)':b['disponivel'],'Processamento (s)':b['producao'],
              'Parada (s)':b['parada'],'Sem registro (s)':b['livre'],
              'Motivos de parada':', '.join(sorted(b['motivos']))} for t,b in sorted(buckets.items())]
    return dict(previsto=previsto,totais=totais,minutos=minutos,ops=list(por_op.values()),sobrepostos=sobrepostos)


def duracao(s):
    return f'{s//60} min {s%60:02d} s'


@st.fragment(run_every=10)
def renderizar(a,eq):
    from j2i_jornadas import obter
    agora=datetime.fromisoformat(a.agora_iso())
    dia=agora.date().isoformat();amanha=(agora.date()+timedelta(days=1)).isoformat()
    st.subheader('Tempos do equipamento hoje')
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mes_jornadas'").fetchone():
            st.info('Cadastre os horários deste equipamento em Métricas e metas para acompanhar os tempos.');return
        cfg=obter(c,eq['id'])
        if not cfg['versao']:
            st.info('Cadastre e salve os horários deste equipamento em Métricas e metas.');return
        jornada=next(d for d in cfg['dias'] if d['dia']==agora.weekday())
        ordens=[dict(r) for r in c.execute('''SELECT id,ficha_op,rota_ordem,aberta_em,fechada_em FROM ordens_operacionais
            WHERE status IN ('ABERTA','FINALIZADA') AND equipamento_id=? AND aberta_em<? AND (fechada_em IS NULL OR fechada_em>=?) ORDER BY aberta_em,id''',(eq['id'],amanha,dia))]
        paradas=[dict(r) for r in c.execute('''SELECT id,motivo,iniciada_em,encerrada_em FROM paradas_operacionais
            WHERE equipamento_id=? AND iniciada_em<? AND (encerrada_em IS NULL OR encerrada_em>=?) ORDER BY iniciada_em,id''',(eq['id'],amanha,dia))]
    try:res=calcular(jornada,ordens,paradas,agora)
    except ValueError as exc:st.error(str(exc));return
    if not jornada['ativo']:
        st.info('Hoje está cadastrado como dia sem expediente. Tempo disponível: 0 min.');return
    t=res['totais']
    st.caption(f"{agora:%d/%m/%Y} · atualizado às {agora:%H:%M:%S} (servidor) · jornada atual: {duracao(res['previsto'])}. Atualização a cada 10 segundos.")
    cols=st.columns(4)
    for col,label,k in zip(cols,['Disponível decorrido','Em processamento','Paradas registradas','Sem OP nem parada'],['disponivel','producao','parada','livre']):
        col.metric(label,duracao(t[k]))
    st.caption(f"Sem registro: {t['livre']} segundos dentro da jornada já decorrida. Almoço, horas futuras e períodos fora da jornada não entram. Uma OP aberta conta como processamento, exceto durante parada registrada; isso não mede automaticamente a atividade física da máquina.")
    if res['sobrepostos']:st.info('Há OPs processadas simultaneamente. O tempo total do equipamento conta cada segundo uma única vez; os tempos individuais das OPs podem se sobrepor.')
    with st.expander('Tempo utilizado por OP — dentro da jornada de hoje'):
        if res['ops']:
            linhas=[dict(r,**{'Processamento (min)':round(r['Processamento (s)']/60,3)}) for r in res['ops']]
            st.dataframe(linhas,use_container_width=True,hide_index=True)
        else:st.info('Nenhuma OP registrada hoje.')
    with st.expander('Detalhamento por minuto e OPs apontadas'):
        st.caption('Cada linha representa um minuto do relógio. Todas as OPs que passaram por ele aparecem juntas; os segundos são divididos entre processamento, parada e ausência de registro, sem arredondar cada OP para um minuto inteiro.')
        if res['minutos']:
            st.dataframe(res['minutos'],use_container_width=True,hide_index=True)
            from j2i_industrial_ui import csv_bytes
            st.download_button('Baixar tempos por minuto',csv_bytes(res['minutos']),f"tempos_{eq['codigo']}_{dia}.csv",'text/csv',key=f"tempos_csv_{eq['id']}")
        else:st.info('A jornada de hoje ainda não começou.')
    st.caption('Consulta calculada com a jornada atualmente cadastrada. Alterar os horários modifica esta apuração; os apontamentos originais permanecem intactos.')
