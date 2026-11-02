"""Resumo diário somente leitura, sem gerar tabelas por minuto."""
from collections import defaultdict
from datetime import datetime, timedelta
import logging
import streamlit as st


def totais(jornada, ordens, paradas, agora):
    agora=agora.replace(microsecond=0)
    def hora(s):return datetime.combine(agora.date(),datetime.strptime(s,'%H:%M').time())
    pares=[] if not jornada['ativo'] else ([(jornada['inicio'],jornada['pausa']),(jornada['retorno'],jornada['fim'])] if jornada['intervalo'] else [(jornada['inicio'],jornada['fim'])])
    saida=dict(disponivel=0,producao=0,parada=0,livre=0)
    for ini,fim in pares:
        inicio,final=hora(ini),min(hora(fim),agora)
        if final<=inicio:continue
        eventos=defaultdict(lambda:[0,0]);eventos[inicio];eventos[final]
        for i,rows,ki,kf in [(0,ordens,'aberta_em','fechada_em'),(1,paradas,'iniciada_em','encerrada_em')]:
            for r in rows:
                a=datetime.fromisoformat(r[ki]);b=datetime.fromisoformat(r[kf]) if r.get(kf) else agora
                if b<a:raise ValueError('Horários inconsistentes.')
                a,b=max(inicio,a),min(final,b)
                if a<b:eventos[a][i]+=1;eventos[b][i]-=1
        pontos=sorted(eventos);ativos=[0,0]
        for a,b in zip(pontos,pontos[1:]):
            ativos=[ativos[i]+eventos[a][i] for i in (0,1)]
            segundos=int((b-a).total_seconds());saida['disponivel']+=segundos
            saida['parada' if ativos[1] else 'producao' if ativos[0] else 'livre']+=segundos
    return saida


def duracao(segundos):
    s=max(0,int(segundos));return f'{s//3600:02d}:{s//60%60:02d}:{s%60:02d}'


def painel(t, agora):
    cards=''.join(f'<div class="j2i-clock-card"><span>{nome}</span><strong>{duracao(t[k])}</strong></div>' for nome,k in [('Disponível','disponivel'),('Em produção','producao'),('Paradas','parada'),('Sem registro','livre')])
    return '''<style>
.j2i-clock{margin:0 0 .65rem 0;font-family:inherit;color:inherit}
.j2i-clock-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(125px,100%),1fr));gap:8px}
.j2i-clock-card{padding:9px 10px;border:1px solid rgba(128,128,128,.28);border-radius:8px;min-width:0}
.j2i-clock-card span{display:block;font-size:13px;line-height:1.25;margin-bottom:4px}
.j2i-clock-card strong{display:block;font-size:clamp(20px,2.5vw,26px);line-height:1.2;font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.j2i-clock-note{font-size:12px;line-height:1.4;margin:5px 0 0;opacity:.75}
</style><section class="j2i-clock" aria-label="Tempos do equipamento hoje"><div class="j2i-clock-grid">'''+cards+f'''</div><p class="j2i-clock-note">Hoje · horas:minutos:segundos · atualizado às {agora:%H:%M:%S}</p></section>'''


@st.fragment(run_every=10)
def renderizar(a,eq):
    try:
        from j2i_jornadas import obter
        agora=datetime.fromisoformat(a.agora_iso())
        dia=agora.date().isoformat();amanha=(agora.date()+timedelta(days=1)).isoformat()
        with a.conectar_banco_operacional() as c:
            c.execute('BEGIN')
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_jornadas'").fetchone():
                st.caption('Tempos: horário de trabalho ainda não cadastrado.');return
            cfg=obter(c,eq['id'])
            if not cfg['versao']:
                st.caption('Tempos: horário de trabalho ainda não cadastrado.');return
            jornada=next(d for d in cfg['dias'] if d['dia']==agora.weekday())
            ordens=[dict(r) for r in c.execute('''SELECT aberta_em,fechada_em FROM ordens_operacionais
                WHERE equipamento_id=? AND status IN ('ABERTA','FINALIZADA') AND aberta_em<?
                AND (fechada_em IS NULL OR fechada_em>=?)''',(eq['id'],amanha,dia))]
            paradas=[dict(r) for r in c.execute('''SELECT iniciada_em,encerrada_em FROM paradas_operacionais
                WHERE equipamento_id=? AND iniciada_em<? AND (encerrada_em IS NULL OR encerrada_em>=?)''',(eq['id'],amanha,dia))]
        st.markdown(painel(totais(jornada,ordens,paradas,agora),agora),unsafe_allow_html=True)
        if not jornada['ativo']:st.caption('Hoje está cadastrado como dia sem expediente.')
    except Exception:
        logging.exception('Resumo de tempos do operador')
        st.caption('Tempos indisponíveis no momento. Os apontamentos continuam disponíveis.')


@st.fragment(run_every=10)
def ultimos(a,eq):
    from html import escape
    st.markdown('**Últimos apontamentos**')
    try:
        with a.conectar_banco_operacional() as c:
            linhas=c.execute('''SELECT ficha_op,lote_identificado,descricao_peca,rota_ordem,
                fechada_em,quantidade_boa,refugo,encerramento_parcial
                FROM ordens_operacionais WHERE equipamento_id=? AND status='FINALIZADA'
                AND fechada_em IS NOT NULL ORDER BY fechada_em DESC,id DESC LIMIT 3''',(eq['id'],)).fetchall()
        if not linhas:st.caption('Nenhum apontamento concluído neste equipamento.');return
        for r in linhas:
            horario=datetime.fromisoformat(r['fechada_em']).strftime('%d/%m %H:%M')
            situacao='Parcial' if r['encerramento_parcial'] else 'Total'
            op=escape(str(r['ficha_op'] or ''));lote=escape(str(r['lote_identificado'] or ''))
            peca=escape(str(r['descricao_peca'] or ''));etapa=escape(str(r['rota_ordem'] or ''))
            boas=float(r['quantidade_boa'] or 0);sucata=float(r['refugo'] or 0)
            st.markdown(f'''<div style="border-bottom:1px solid rgba(128,128,128,.25);padding:8px 0;line-height:1.35">
<div style="font-size:14px;font-weight:600">OP {op} · Lote {lote}</div>
<div style="font-size:13px;overflow-wrap:anywhere">{peca}</div>
<div style="font-size:14px;margin-top:3px">{boas:g} boas · {sucata:g} sucata · {situacao}</div>
<div style="font-size:12px;opacity:.75">{horario} · Etapa {etapa}</div></div>''',unsafe_allow_html=True)
    except Exception:
        logging.exception('Últimos apontamentos do operador')
        st.caption('Histórico indisponível no momento.')
