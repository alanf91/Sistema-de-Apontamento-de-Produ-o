"""Cadastro versionado de capacidade. Não altera a prioridade do sequenciador."""
import copy
import json
import math
from datetime import date, datetime, time
import pandas as pd
import streamlit as st
import j2i_industrial as m
import j2i_jornadas as j

VELOCIDADE = ['Operação','Família','Unidade','Base','Minutos','Quantidade por ciclo','Origem']
TROCAS = ['De','Para','Minutos']
BLOQUEIOS = ['Início','Fim','Motivo']


def iniciar(c):
    j.iniciar(c)
    c.execute('''CREATE TABLE IF NOT EXISTS mes_capacidade_config (
        equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
        versao INTEGER NOT NULL, dados_json TEXT NOT NULL,
        atualizado_em TEXT NOT NULL, usuario TEXT NOT NULL,
        PRIMARY KEY(equipamento_id,versao))''')


def padrao():
    return dict(vigencia=date.today().isoformat(),postos=1,velocidades=[],bloqueios=[],
                preparacao=0.,troca=0.,trocas=[],criterio='Nenhum',alternativos=[],
                lote_minimo=1.,transferencia=0.,espera=0.,observacoes='')


def obter(c,eq):
    r=c.execute('SELECT * FROM mes_capacidade_config WHERE equipamento_id=? ORDER BY versao DESC LIMIT 1',(eq,)).fetchone()
    return (json.loads(r['dados_json']),r['versao']) if r else (padrao(),0)


def numero(v,nome,minimo=0):
    try:n=float(v)
    except (TypeError,ValueError):raise ValueError(f'{nome}: informe um número.')
    if not math.isfinite(n) or n<minimo:raise ValueError(f'{nome}: valor mínimo {minimo}.')
    return n


def texto(valor):
    return '' if valor is None or pd.isna(valor) else str(valor).strip()


def validar(d,eq,ids):
    d=copy.deepcopy(d)
    date.fromisoformat(str(d['vigencia']))
    p=numero(d['postos'],'Postos',1)
    if not p.is_integer():raise ValueError('Postos deve ser um número inteiro.')
    d['postos']=int(p)
    for k in ['preparacao','troca','espera','transferencia']:d[k]=numero(d[k],k)
    d['lote_minimo']=numero(d['lote_minimo'],'Lote mínimo',0.000001)
    if d['transferencia'] and d['transferencia']<d['lote_minimo']:
        raise ValueError('Lote de transferência deve ser zero (OP completa) ou pelo menos o lote mínimo.')
    if eq in d['alternativos'] or not set(d['alternativos'])<=set(ids):
        raise ValueError('Equipamento alternativo inválido ou inativo. Revise a seleção.')
    vistos=set()
    for r in d['velocidades']:
        for k in ['Operação','Família','Unidade']:
            r[k]=texto(r.get(k))
            if not r[k]:raise ValueError(f'Preencha {k} em todas as velocidades. Use Geral para família padrão.')
        chave=(r['Operação'].casefold(),r['Família'].casefold())
        if chave in vistos:raise ValueError('Operação e família repetidas: mantenha uma regra por combinação.')
        vistos.add(chave)
        if r['Base'] not in ['Por unidade','Por ciclo'] or r['Origem'] not in ['Estimado','Cronometrado']:
            raise ValueError('Selecione a base e a origem do tempo.')
        r['Minutos']=numero(r['Minutos'],'Tempo padrão',0.000001)
        r['Quantidade por ciclo']=numero(r['Quantidade por ciclo'],'Quantidade por ciclo',0.000001) if r['Base']=='Por ciclo' else 1.
    vistos=set()
    for r in d['trocas']:
        r['De']=texto(r.get('De'));r['Para']=texto(r.get('Para'))
        if not r['De'] or not r['Para']:raise ValueError('Preencha origem e destino das trocas.')
        chave=(r['De'].casefold(),r['Para'].casefold())
        if chave in vistos:raise ValueError('Regra de troca repetida.')
        vistos.add(chave);r['Minutos']=numero(r['Minutos'],'Tempo de troca')
    for r in d['bloqueios']:
        ini=datetime.fromisoformat(str(r['Início']));fim=datetime.fromisoformat(str(r['Fim']))
        if fim<=ini:raise ValueError('A indisponibilidade deve terminar após seu início.')
        if not texto(r.get('Motivo')):raise ValueError('Informe o motivo da indisponibilidade.')
        r['Início']=ini.isoformat(timespec='minutes');r['Fim']=fim.isoformat(timespec='minutes')
    return d


def salvar(c,eq,d,versao,dias,versao_jornada,usuario):
    ids={r[0] for r in c.execute('SELECT id FROM equipamentos WHERE ativo=1')}
    if eq not in ids:raise ValueError('Equipamento inativo ou inexistente.')
    d=validar(d,eq,ids)
    if obter(c,eq)[1]!=versao:raise ValueError('Cadastro alterado por outro usuário. Recarregue antes de salvar.')
    # A jornada é compartilhada com a tela existente e usa o mesmo bloqueio otimista.
    j.salvar(c,eq,dias,versao_jornada,usuario)
    d['jornada_no_salvamento']=j.validar(dias)
    c.execute('INSERT INTO mes_capacidade_config VALUES(?,?,?,?,?)',
              (eq,versao+1,json.dumps(d,ensure_ascii=False),m.agora(),usuario))
    m.auditoria(c,'capacidade_sequenciamento',usuario,dict(equipamento=eq,versao=versao+1,dados=d))


def tempo_previsto(regra,quantidade,preparacao=0):
    q=numero(quantidade,'Quantidade')
    if q==0:return 0.
    return preparacao+regra['Minutos']*(math.ceil(q/regra['Quantidade por ciclo']) if regra['Base']=='Por ciclo' else q)


def tabela(dados,colunas,key,config=None):
    return st.data_editor(pd.DataFrame(dados,columns=colunas),num_rows='dynamic',hide_index=True,
                          use_container_width=True,key=key,column_config=config or {}).to_dict('records')


def renderizar(a):
    st.title('Capacidade e Sequenciamento')
    st.caption('Cadastre aos poucos. Cada salvamento mantém uma revisão para consulta futura.')
    with a.conectar_banco_operacional() as c:
        iniciar(c)
        eqs=[dict(r) for r in c.execute('SELECT id,codigo,maquina FROM equipamentos WHERE ativo=1 ORDER BY maquina')]
    if not eqs:st.info('Ative um equipamento em Métricas e Metas → Equipamentos ativos.');return
    mapa={e['id']:e for e in eqs}
    eq=st.selectbox('Equipamento',list(mapa),format_func=lambda i:mapa[i]['maquina'],key='cap_eq')
    with a.conectar_banco_operacional() as c:
        salvo,versao=obter(c,eq);jornada=j.obter(c,eq)
        historico=[dict(r) for r in c.execute('SELECT versao,atualizado_em,usuario FROM mes_capacidade_config WHERE equipamento_id=? ORDER BY versao DESC LIMIT 30',(eq,))]
    token=f"cap_{eq}_{versao}_{jornada['versao']}"
    d=copy.deepcopy(salvo)
    st.info('Este cadastro prepara os dados para o planejamento por capacidade. A sequência atual do PPCP continua priorizando a quantidade de processos. Apenas os horários semanais são compartilhados imediatamente com o sistema atual.')
    fontes=[i for i in mapa if i!=eq]
    with st.expander('Agilizar cadastro: copiar velocidades e preparações'):
        if fontes:
            fonte=st.selectbox('Copiar de',fontes,format_func=lambda i:mapa[i]['maquina'])
            if st.button('Carregar modelo do equipamento'):
                with a.conectar_banco_operacional() as c:modelo,_=obter(c,fonte)
                st.session_state[token+'_modelo']={k:modelo[k] for k in ['velocidades','preparacao','troca','trocas','criterio']}
                st.session_state[token+'_edicao']=st.session_state.get(token+'_edicao',0)+1
            st.caption('Copia somente velocidades e preparações. Confira os valores e salve; horários e demais regras permanecem próprios do equipamento.')
        else:st.caption('Cadastre outro equipamento para usar esta opção.')
    d.update(st.session_state.get(token+'_modelo',{}))
    chave=token+'_'+str(st.session_state.get(token+'_edicao',0))
    with st.form(chave):
        tabs=st.tabs(['Disponibilidade','Velocidade de produção','Preparação e trocas','Regras de sequenciamento'])
        with tabs[0]:
            d['vigencia']=st.date_input('Vigência dos parâmetros de capacidade',date.fromisoformat(d['vigencia'])).isoformat()
            st.caption('A vigência pertence a esta revisão dos parâmetros. Horários semanais salvos entram em vigor imediatamente; não possuem agendamento de vigência.')
            d['postos']=st.number_input('Postos independentes simultâneos',min_value=1,value=int(d['postos']),step=1)
            if not jornada['versao']:st.warning('Horários sugeridos: confira antes de salvar.')
            rows=[]
            for x in jornada['dias']:
                rows.append({'Dia':j.DIAS[x['dia']],'Trabalha':x['ativo'],'Intervalo':x['intervalo'],**{k:time.fromisoformat(x[k]) if x.get(k) else None for k in ['inicio','pausa','retorno','fim']}})
            horarios=st.data_editor(pd.DataFrame(rows),hide_index=True,disabled=['Dia'],key=chave+'_horas',
                 column_config={k:st.column_config.TimeColumn(label,format='HH:mm',step=60) for k,label in [('inicio','Início'),('pausa','Saída para intervalo'),('retorno','Retorno'),('fim','Fim')]})
            st.markdown('**Indisponibilidades programadas**')
            st.caption('Informe início e fim como AAAA-MM-DD HH:MM. Feriados gerais continuam no calendário do PPCP. Estes bloqueios serão usados na futura programação por capacidade.')
            d['bloqueios']=tabela(d['bloqueios'],BLOQUEIOS,chave+'_bloqueios')
        with tabs[1]:
            st.caption('Uma linha por operação e família. Use Geral para a família padrão. Minutos por unidade ou por ciclo; ciclos incompletos ocupam um ciclo inteiro. A unidade deve corresponder à medição da operação (peças, m², m etc.).')
            d['velocidades']=tabela(d['velocidades'],VELOCIDADE,chave+'_vel',{
                'Base':st.column_config.SelectboxColumn(options=['Por unidade','Por ciclo'],required=True),
                'Origem':st.column_config.SelectboxColumn(options=['Estimado','Cronometrado'],required=True),
                'Minutos':st.column_config.NumberColumn(min_value=0.000001,format='%.4f'),
                'Quantidade por ciclo':st.column_config.NumberColumn(min_value=0.000001,format='%.4f')})
            st.caption('É permitido salvar sem velocidades para continuar depois. Uma linha preenchida deve estar completa. Meta de produção não é substituída por este cadastro.')
        with tabs[2]:
            d['preparacao']=st.number_input('Preparação inicial (min)',min_value=0.,value=float(d['preparacao']))
            d['troca']=st.number_input('Troca padrão (min)',min_value=0.,value=float(d['troca']))
            opcoes=['Nenhum','Cor','Material','Espessura','Fita de borda','Ferramenta','Regulagem','Outro']
            d['criterio']=st.selectbox('Característica para agrupar e trocar',opcoes,index=opcoes.index(d['criterio']))
            st.caption('Regras específicas substituem o tempo padrão de troca. A → B e B → A são regras distintas. Use valores da característica escolhida.')
            d['trocas']=tabela(d['trocas'],TROCAS,chave+'_trocas',{'Minutos':st.column_config.NumberColumn(min_value=0.)})
        with tabs[3]:
            st.caption('Operações e famílias permitidas são as linhas da aba Velocidade. Sem linhas, a capacidade permanece pendente de cadastro.')
            invisiveis=set(d['alternativos'])-set(mapa)
            if invisiveis:st.warning('Há alternativas agora inativas. Ao salvar, elas serão retiradas desta configuração.')
            d['alternativos']=st.multiselect('Equipamentos alternativos candidatos',fontes,default=[i for i in d['alternativos'] if i in fontes],format_func=lambda i:mapa[i]['maquina'])
            st.caption('A alternativa precisa de cadastro próprio de operações e velocidades. Esta indicação não transfere OPs automaticamente.')
            d['lote_minimo']=st.number_input('Lote mínimo (peças)',min_value=0.000001,value=float(d['lote_minimo']))
            d['transferencia']=st.number_input('Lote de transferência (peças; 0 = OP completa)',min_value=0.,value=float(d['transferencia']))
            st.caption('Transferência parcial fica registrada para evolução futura; não libera apontamentos parciais nem altera o intertravamento atual.')
            d['espera']=st.number_input('Espera obrigatória após processo (min)',min_value=0.,value=float(d['espera']))
            d['observacoes']=st.text_area('Restrições e observações',d['observacoes'])
        gravar=st.form_submit_button('Salvar cadastro do equipamento',type='primary')
    if gravar:
        dias=[dict(dia=i,ativo=r['Trabalha'],intervalo=r['Intervalo'],**{k:r[k] for k in ['inicio','pausa','retorno','fim']}) for i,r in enumerate(horarios.to_dict('records'))]
        try:
            with a.conectar_banco_operacional() as c:
                c.execute('BEGIN IMMEDIATE');salvar(c,eq,d,versao,dias,jornada['versao'],a.LOGIN_APONTAMENTO)
            st.session_state['cap_sucesso']=eq;st.rerun()
        except (ValueError,TypeError) as exc:st.error(str(exc))
    if st.session_state.pop('cap_sucesso',None)==eq:st.success('Cadastro salvo com histórico de revisão.')
    st.subheader('Conferência do cadastro salvo')
    minutos=sum(x['minutos'] for x in j.validar(jornada['dias'])) if jornada['versao'] else 0
    c1,c2,c3=st.columns(3)
    c1.metric('Minutos semanais por posto',minutos);c2.metric('Operações / famílias',len(salvo['velocidades']));c3.metric('Revisão',versao)
    if not salvo['velocidades']:st.warning('Pendente: cadastrar velocidades para estimar duração e capacidade.')
    else:
        regras=salvo['velocidades']
        r=st.selectbox('Operação para simulação',range(len(regras)),format_func=lambda i:regras[i]['Operação']+' / '+regras[i]['Família'],key=token+'_sim')
        regra=regras[r];q=st.number_input('Quantidade para simular ('+regra['Unidade']+')',min_value=0.,value=100.,key=token+'_q')
        st.metric('Tempo estimado em um posto (min)',f"{tempo_previsto(regra,q,salvo['preparacao']):.2f}")
        capacidade=[]
        for x in j.validar(jornada['dias']):
            disponivel=max(0,x['minutos']-salvo['preparacao'])
            cap=(math.floor(disponivel/regra['Minutos'])*regra['Quantidade por ciclo'] if regra['Base']=='Por ciclo' else disponivel/regra['Minutos'])*salvo['postos']
            if x['ativo']:capacidade.append({'Dia':j.DIAS[x['dia']],'Capacidade teórica ('+regra['Unidade']+')':round(cap,2)})
        if jornada['versao']:st.dataframe(capacidade,hide_index=True,use_container_width=True)
        st.caption('Simulação teórica do cadastro salvo: uma preparação por posto/dia. Não desconta feriados, indisponibilidades, trocas, esperas ou perdas; não é um cronograma nem promessa de entrega.')
    with st.expander('Histórico de revisões'):
        st.dataframe(historico,hide_index=True)
        if historico:
            rev=st.selectbox('Revisão para consultar',[r['versao'] for r in historico],key=token+'_rev')
            with a.conectar_banco_operacional() as c:conteudo=c.execute('SELECT dados_json FROM mes_capacidade_config WHERE equipamento_id=? AND versao=?',(eq,rev)).fetchone()[0]
            st.json(json.loads(conteudo),expanded=False)
