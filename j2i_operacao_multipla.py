"""Operações múltiplas atômicas: validação e estoque na mesma transação."""
import re
import streamlit as st


def abrir_varias(a, equipamento, texto):
    codigos=[a.validar_formato_codigo_barras(v) for v in re.split(r'[\s,;]+',texto.strip()) if v]
    if not codigos or len(codigos)>100:
        raise ValueError('Informe entre 1 e 100 OPs por confirmação.')
    if len(set(codigos))!=len(codigos):
        raise ValueError('Há OPs repetidas na lista. Informe cada OP apenas uma vez.')
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        instante=a.agora_iso()
        ids=[]
        for op in codigos:
            try:
                ids.append(a.abrir_ordem_operacional(equipamento,op,{}, {},_conexao=c,_momento=instante))
            except ValueError as exc:
                raise ValueError(f'OP {op}: {exc} Nenhuma OP desta confirmação foi aberta.') from exc
        return ids


def finalizar_varias(a, equipamento_id, linhas):
    if not linhas or len(linhas)>100:
        raise ValueError('Selecione entre 1 e 100 OPs para finalizar.')
    ids=[int(r['ID']) for r in linhas]
    if len(set(ids))!=len(ids):raise ValueError('Seleção duplicada.')
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        instante=a.agora_iso()
        for r in linhas:
            atual=c.execute("SELECT quantidade_programada FROM ordens_operacionais WHERE id=? AND equipamento_id=? AND status='ABERTA'",(int(r['ID']),equipamento_id)).fetchone()
            if atual is None:raise ValueError('Uma OP selecionada já foi encerrada ou não pertence ao equipamento. Atualize a tela. Nenhuma foi encerrada nesta confirmação.')
            try:
                sucata=float(r.get('Sucata',0));rt=float(r.get('Retrabalho',0))
                modo=r.get('Encerramento')
                if modo not in ('Total','Parcial'):raise ValueError('Escolha Total ou Parcial para cada OP selecionada.')
                processado=float(r.get('Processadas',0)) if modo=='Parcial' else float(atual[0])
                a.finalizar_ordem_operacional(equipamento_id,int(r['ID']),processado-sucata,sucata,rt,str(r.get('Observação','')),modo=='Parcial',_conexao=c,_momento=instante)
            except ValueError as exc:
                raise ValueError(f"Registro {r['ID']}: {exc} Nenhuma OP desta confirmação foi encerrada.") from exc
        return ids


def renderizar(a,eq,abertas,parada):
    from j2i_telas_operacao import executar
    with st.expander('Iniciar várias OPs ao mesmo tempo'):
        st.caption('Leia ou cole uma OP por linha, até 100. Todas terão o mesmo horário de abertura. Uma falha cancela toda a confirmação.')
        with st.form('op_multiplas_abrir'):
            texto=st.text_area('OPs para iniciar',height=140)
            confirmar=st.form_submit_button('Iniciar todas as OPs informadas',disabled=bool(parada))
        if confirmar and executar(abrir_varias,a,eq,texto):st.rerun()
    if abertas:
        st.write(f"**{len(abertas)} OP(s) em andamento neste equipamento**")
        with st.expander('Finalizar várias OPs ao mesmo tempo'):
            st.caption('Escolha Total ou Parcial para cada OP selecionada. No parcial, informe boas + sucata desta sessão. O saldo poderá ser reaberto depois. Se uma OP falhar, nenhuma será encerrada.')
            linhas=[]
            with st.form('op_multiplas_finalizar'):
                for r in abertas:
                    ident=f"multi_{eq['id']}_{r['id']}"
                    with st.expander(f"OP {r['ficha_op']} · Etapa {r['rota_ordem']} · Saldo {r['quantidade_programada']:g}"):
                        selecionar=st.checkbox('Encerrar esta OP', key=ident+'_selecionar')
                        modo=st.radio('Encerrar na quantidade total ou parcial?', ['Selecione','Total','Parcial'], key=ident+'_modo', horizontal=True)
                        qtd=st.number_input('Quantidade processada (boas + sucata), somente para Parcial',min_value=0,step=1,key=ident+'_qtd')
                        sucata=st.number_input('Sucata desta sessão',min_value=0,step=1,key=ident+'_sucata')
                        rt=st.number_input('Retrabalho incluído nas boas desta sessão',min_value=0,step=1,key=ident+'_rt')
                        obs=st.text_input('Observação',key=ident+'_obs')
                        if selecionar:
                            linhas.append({'ID':r['id'],'Encerramento':modo,'Processadas':qtd,'Sucata':sucata,'Retrabalho':rt,'Observação':obs})
                confirmar=st.form_submit_button('Confirmar encerramento das OPs selecionadas',disabled=bool(parada))
            if confirmar and executar(finalizar_varias,a,eq['id'],linhas):st.rerun()
