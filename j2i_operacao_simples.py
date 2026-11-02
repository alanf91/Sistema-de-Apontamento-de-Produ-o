"""Operação direta: entrada única, encerramento conjunto e parada na mesma tela."""
import hashlib
import json
import math
import streamlit as st


def estado(a, eq):
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        abertas=[dict(r) for r in c.execute("SELECT * FROM ordens_operacionais WHERE equipamento_id=? AND status='ABERTA' ORDER BY id",(eq,))]
        p=c.execute("SELECT * FROM paradas_operacionais WHERE equipamento_id=? AND status='ABERTA'",(eq,)).fetchone()
    return abertas, dict(p) if p else None


def recibo(eq, mensagem):
    st.session_state['op_recibo']=(eq,mensagem)
    for k in ('op_revisao','op_finalizar','op_pagina'):
        st.session_state.pop(k,None)
    st.session_state['op_form_versao']=st.session_state.get('op_form_versao',0)+1
    st.rerun()


def identificar(r):
    return f"OP {r['ficha_op']} · Lote {r['lote_identificado']} · Etapa {r['rota_ordem']}"


def abrir(a,eq):
    from j2i_telas_operacao import executar
    k=f"op_leitura_unica_{eq['id']}_{st.session_state.get('op_form_versao',0)}"
    with st.form(k,clear_on_submit=False):
        codigo=st.text_area('Leia ou digite uma ou várias OPs',placeholder='Uma OP por linha. Exemplo: 01325676',height=100,key=k+'codigo')
        st.caption('Leia uma OP e depois a próxima. Ao terminar, clique em Iniciar OPs.')
        enviar=st.form_submit_button('Iniciar OPs',type='primary',use_container_width=True)
    if enviar:
        from j2i_operacao_multipla import abrir_varias
        import re
        codigos=[v for v in re.split(r'[\s,;]+',codigo.strip()) if v]
        if not codigos or len(codigos)>100:
            st.error('Informe de 1 a 100 OPs.');return
        if any(not re.fullmatch(r'[0-9]{8}',v) for v in codigos):
            st.error('Cada OP deve ter 8 números. Separe as OPs por linha, espaço, vírgula ou ponto e vírgula.');return
        if len(set(codigos))!=len(codigos):
            st.error('Há uma OP repetida. Remova a repetição antes de iniciar.');return
        if executar(abrir_varias,a,eq,codigo):
            recibo(eq['id'],'OP iniciada: '+codigos[0] if len(codigos)==1 else f'{len(codigos)} OPs iniciadas.')


def encerrar_todas(a,eq,exibidas,ajustes):
    """Revalida a lista exibida e grava todas as ordens em uma transação."""
    esperadas={int(r['id']):float(r['quantidade_programada']) for r in exibidas}
    if not esperadas or len(esperadas)!=len(exibidas):raise ValueError('Atualize a lista de OPs abertas.')
    if not set(ajustes)<=set(esperadas):raise ValueError('Uma OP ajustada não está na lista. Atualize a tela.')
    resumo=[]
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        atuais=[dict(r) for r in c.execute("SELECT id,ficha_op,quantidade_programada FROM ordens_operacionais WHERE equipamento_id=? AND status='ABERTA' ORDER BY id",(eq,))]
        if {r['id']:float(r['quantidade_programada']) for r in atuais}!=esperadas:
            raise ValueError('A lista de OPs abertas mudou. Atualize a tela e confira antes de encerrar. Nenhuma OP foi encerrada nesta ação.')
        if c.execute("SELECT 1 FROM paradas_operacionais WHERE equipamento_id=? AND status='ABERTA'",(eq,)).fetchone():
            raise ValueError('Retome o equipamento antes de encerrar as OPs.')
        linhas=[]
        from j2i_sessoes_producao import validar_quantidades
        for r in atuais:
            ajuste=ajustes.get(r['id'],{})
            parcial=bool(ajuste.get('parcial',False))
            total=float(r['quantidade_programada'])
            try:
                processadas=float(ajuste.get('processadas',0)) if parcial else total
                sucata=float(ajuste.get('sucata',0));rt=float(ajuste.get('retrabalho',0))
                boas=processadas-sucata
                saldo=validar_quantidades(total,boas,sucata,rt,parcial)
            except (ValueError,TypeError) as e:
                raise ValueError(f"OP {r['ficha_op']}: {e} Nenhuma OP foi encerrada.") from e
            linhas.append((r,boas,sucata,rt,parcial,saldo))
        instante=a.agora_iso()
        for r,boas,sucata,rt,parcial,saldo in linhas:
            try:
                a.finalizar_ordem_operacional(eq,r['id'],boas,sucata,rt,'',parcial,_conexao=c,_momento=instante)
            except ValueError as e:
                raise ValueError(f"OP {r['ficha_op']}: {e} Nenhuma OP foi encerrada nesta ação.") from e
            resumo.append(dict(op=r['ficha_op'],boas=boas,sucata=sucata,parcial=parcial,saldo=saldo))
    return resumo


def encerramento(a,eq,abertas,parada):
    st.markdown('**OPs abertas**')
    st.dataframe([{'OP':r['ficha_op'],'Lote':r['lote_identificado'],'Peça':r['descricao_peca'],
                   'Operação':r.get('rota_operacao') or f"Etapa {r['rota_ordem']}",
                   'Quantidade':r['quantidade_programada']} for r in abertas],hide_index=True,use_container_width=True)
    if parada:return
    mapa={r['id']:r for r in abertas}
    assinatura=hashlib.sha256(json.dumps([(r['id'],r['quantidade_programada']) for r in abertas]).encode()).hexdigest()[:12]
    k=f"op_direto_{eq['id']}_{assinatura}_{st.session_state.get('op_form_versao',0)}"
    ajustes={}
    with st.expander('Informar sucata ou retrabalho',expanded=False):
        ids=st.multiselect('Quais OPs tiveram sucata ou retrabalho?',list(mapa),format_func=lambda i:identificar(mapa[i]),key=k+'perdas')
        for i in ids:
            st.write('**'+identificar(mapa[i])+'**')
            cols=st.columns(2)
            sc=cols[0].number_input('Sucata (peças perdidas)',min_value=0,step=1,key=k+f'sc{i}')
            rt=cols[1].number_input('Retrabalho (incluído nas boas)',min_value=0,step=1,key=k+f'rt{i}')
            ajustes[i]=dict(sucata=sc,retrabalho=rt)
    with st.expander('Encerramento parcial (se necessário)',expanded=False):
        parciais=st.multiselect('OPs que terão saldo para depois',list(mapa),format_func=lambda i:identificar(mapa[i]),key=k+'parciais')
        for i in parciais:
            qtd=st.number_input('Peças processadas — '+identificar(mapa[i]),min_value=0,step=1,key=k+f'qtd{i}')
            ajustes.setdefault(i,{}).update(parcial=True,processadas=qtd)
            st.caption(f"Saldo para depois: {max(0,float(mapa[i]['quantidade_programada'])-qtd):g} peças.")
    st.caption(f'{len(abertas)} OP(s) serão encerradas. Sem ajustes, todo o saldo será registrado como peças boas.')
    if st.button('Encerrar todas as OPs abertas',type='primary',use_container_width=True,key=k+'salvar'):
        try:res=encerrar_todas(a,eq['id'],abertas,ajustes)
        except ValueError as e:st.error(str(e));return
        except Exception:
            import logging
            logging.exception('Encerramento direto de OPs')
            st.error('Não foi possível confirmar a gravação. Atualize a tela e confira as OPs antes de tentar novamente.');return
        parciais=sum(r['parcial'] for r in res)
        recibo(eq['id'],f"Produção salva: {len(res)-parciais} OP(s) concluída(s) e {parciais} parcial(is). {sum(r['boas'] for r in res):g} boas e {sum(r['sucata'] for r in res):g} sucata.")


def parada_na_tela(a,eq,parada):
    from j2i_telas_operacao import executar
    if parada:
        st.caption('Ao retomar, as OPs abertas continuam em produção.')
        if st.button('Retomar equipamento',type='primary',use_container_width=True):
            if executar(a.encerrar_parada_operacional,eq['id'],parada['id']):recibo(eq['id'],'Parada encerrada. Equipamento retomado.')
    else:
        with st.expander('Registrar parada',expanded=False):
            categoria=st.selectbox('Tipo de parada',list(a.MOTIVOS_PARADA_PADRONIZADOS),key='op_parada_categoria')
            motivo=st.selectbox('Motivo',a.MOTIVOS_PARADA_PADRONIZADOS[categoria],key='op_parada_motivo')
            st.caption('A parada vale para todas as OPs abertas neste equipamento.')
            if st.button('Iniciar parada',use_container_width=True):
                if executar(a.iniciar_parada_operacional,eq,motivo):recibo(eq['id'],'Parada registrada: '+motivo)


def tela(a):
    eq=a.obter_equipamento_sessao()
    if not eq:
        from j2i_telas_operacao import login
        login(a);return
    from j2i_sessoes import manter
    manter(a,eq['id'])
    st.title(eq['maquina'])
    from j2i_relogio_operador import renderizar as relogio,ultimos
    relogio(a,eq)
    abertas,parada=estado(a,eq['id'])
    if parada:st.warning('EM PARADA — '+parada['motivo'])
    elif abertas:st.info(f'EM PRODUÇÃO — {len(abertas)} OP(s) aberta(s)')
    else:st.info('SEM OP ABERTA — leia uma OP para começar')
    r=st.session_state.pop('op_recibo',None)
    if r and r[0]==eq['id']:
        st.success(r[1])
    principal,recentes=st.columns([1.25,1],gap='medium')
    with recentes:ultimos(a,eq)
    with principal:
        if abertas:encerramento(a,eq,abertas,parada)
        elif not parada:abrir(a,eq)
        parada_na_tela(a,eq,parada)
    from j2i_telas_operacao import pesquisa_ops_pendentes,executar
    pesquisa_ops_pendentes(a,eq)
    if st.button('Sair do equipamento',use_container_width=True):
        from j2i_sessoes import liberar,limpar
        def sair():
            with a.conectar_banco_operacional() as c:
                liberar(c,eq['id'],st.session_state.get('operador_token'))
        if executar(sair):
            limpar();st.rerun()
