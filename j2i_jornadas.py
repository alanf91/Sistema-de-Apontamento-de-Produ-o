"""Jornada semanal por equipamento; minutos inteiros, sem movimentar produção."""
import json
from datetime import time
import j2i_industrial as m

DIAS = ['Segunda-feira','Terça-feira','Quarta-feira','Quinta-feira','Sexta-feira','Sábado','Domingo']


def iniciar(c):
    c.execute('''CREATE TABLE IF NOT EXISTS mes_jornadas (
        equipamento_id INTEGER PRIMARY KEY REFERENCES equipamentos(id),
        versao INTEGER NOT NULL, dias_json TEXT NOT NULL,
        atualizado_em TEXT NOT NULL, usuario TEXT NOT NULL)''')


def sugestao():
    return [dict(dia=i,ativo=i<5,inicio='07:00',intervalo=True,
                 pausa='11:20',retorno='12:36',fim='17:00') for i in range(7)]


def minuto(valor):
    if isinstance(valor,time):v=valor
    else:
        try:v=time.fromisoformat(str(valor))
        except (ValueError,TypeError):raise ValueError('Preencha os horários no formato HH:MM.')
    if v.second or v.microsecond:raise ValueError('Use horários com precisão de minutos.')
    return v.hour*60+v.minute


def validar(dias):
    if len(dias)!=7 or sorted(x['dia'] for x in dias)!=list(range(7)):
        raise ValueError('Informe os sete dias da semana, sem repetições.')
    saida=[]
    for d in sorted(dias,key=lambda x:x['dia']):
        if not d['ativo']:
            saida.append(dict(dia=d['dia'],ativo=False,intervalo=False,inicio=None,pausa=None,retorno=None,fim=None,minutos=0));continue
        try:
            ini,fim=minuto(d['inicio']),minuto(d['fim'])
            if fim<=ini:raise ValueError('O fim deve ser após o início, no mesmo dia.')
            pausa=retorno=None;total=fim-ini
            if d['intervalo']:
                pausa,retorno=minuto(d['pausa']),minuto(d['retorno'])
                if not ini<pausa<retorno<fim:
                    raise ValueError('Use a ordem: início < saída para intervalo < retorno < fim.')
                total-=retorno-pausa
            fmt=lambda x: None if x is None else f'{x//60:02d}:{x%60:02d}'
            saida.append(dict(dia=d['dia'],ativo=True,intervalo=bool(d['intervalo']),inicio=fmt(ini),
                              pausa=fmt(pausa),retorno=fmt(retorno),fim=fmt(fim),minutos=total))
        except ValueError as exc:raise ValueError(f"{DIAS[d['dia']]}: {exc}") from exc
    return saida


def obter(c,eq):
    r=c.execute('SELECT * FROM mes_jornadas WHERE equipamento_id=?',(eq,)).fetchone()
    return dict(versao=r['versao'],dias=json.loads(r['dias_json'])) if r else dict(versao=0,dias=sugestao())


def salvar(c,eq,dias,versao,usuario):
    dados=validar(dias)
    if not c.execute('SELECT 1 FROM equipamentos WHERE id=? AND ativo=1',(eq,)).fetchone():
        raise ValueError('Equipamento inativo ou inexistente.')
    atual=obter(c,eq)
    if atual['versao']!=versao:raise ValueError('Jornada alterada por outro usuário. Atualize a tela.')
    c.execute('''INSERT INTO mes_jornadas VALUES(?,?,?,?,?) ON CONFLICT(equipamento_id)
                 DO UPDATE SET versao=excluded.versao,dias_json=excluded.dias_json,
                 atualizado_em=excluded.atualizado_em,usuario=excluded.usuario''',
              (eq,versao+1,json.dumps(dados,ensure_ascii=False),m.agora(),usuario))
    m.auditoria(c,'jornada_equipamento',usuario,dict(equipamento=eq,antes=atual if versao else None,depois=dados))


def duracao(minutos):
    return f'{minutos//60}h{minutos%60:02d}'


def renderizar(a,eq):
    import streamlit as st
    import pandas as pd
    st.subheader('Horários disponíveis do equipamento')
    with a.conectar_banco_operacional() as c:
        iniciar(c);atual=obter(c,eq['id'])
    if not atual['versao']:
        st.info('Jornada ainda não cadastrada. Os horários abaixo são uma sugestão; ajuste e salve.')
    st.caption('Defina cada dia da semana. Desmarque Trabalha nos dias sem expediente ou Intervalo para jornada contínua. Os horários devem estar no mesmo dia.')
    rows=[]
    for d in atual['dias']:
        hora=lambda k: time.fromisoformat(d[k]) if d.get(k) else None
        rows.append({'Dia':DIAS[d['dia']],'Trabalha':d['ativo'],'Início':hora('inicio'),
                     'Intervalo':d['intervalo'],'Saída para intervalo':hora('pausa'),
                     'Retorno':hora('retorno'),'Fim':hora('fim')})
    with st.form(f"jornada_{eq['id']}_{atual['versao']}"):
        editado=st.data_editor(pd.DataFrame(rows),hide_index=True,use_container_width=True,disabled=['Dia'],
            column_config={k:st.column_config.TimeColumn(k,format='HH:mm',step=60) for k in ['Início','Saída para intervalo','Retorno','Fim']})
        salvar_btn=st.form_submit_button('Salvar horários do equipamento')
    if salvar_btn:
        dias=[dict(dia=i,ativo=r['Trabalha'],inicio=r['Início'],intervalo=r['Intervalo'],pausa=r['Saída para intervalo'],retorno=r['Retorno'],fim=r['Fim']) for i,r in enumerate(editado.to_dict('records'))]
        try:
            with a.conectar_banco_operacional() as c:
                c.execute('BEGIN IMMEDIATE');salvar(c,eq['id'],dias,atual['versao'],a.LOGIN_APONTAMENTO)
            st.success('Horários salvos.');atual=dict(versao=atual['versao']+1,dias=validar(dias))
        except ValueError as exc:st.error(str(exc))
    if atual['versao']:
        dias=atual['dias']
        st.metric('Disponibilidade semanal cadastrada',duracao(sum(d['minutos'] for d in dias)))
        st.dataframe([{'Dia':DIAS[d['dia']],'Disponível':duracao(d['minutos']) if d['ativo'] else 'Sem expediente'} for d in dias],hide_index=True,use_container_width=True)
    st.caption('Esta jornada registra a disponibilidade planejada. Não bloqueia apontamentos fora do horário, não desconta paradas reais e não altera automaticamente metas ou indicadores de desempenho.')
