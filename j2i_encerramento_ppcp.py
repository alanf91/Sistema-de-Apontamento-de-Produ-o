"""Encerramento administrativo de passagens vencidas, sem produzir ou baixar estoque."""
import hashlib
import json
from datetime import datetime, timedelta


def fechadas(c):
    return {(r['op'],r['lote'],r['etapa']) for r in c.execute('SELECT op,lote,etapa FROM mes_encerramentos_ppcp')}


def previa(c, equipamento_id, hoje):
    from j2i_atrasos_equipamento import consultar
    eq=c.execute('SELECT * FROM equipamentos WHERE id=? AND ativo=1',(equipamento_id,)).fetchone()
    if eq is None:raise ValueError('Selecione um equipamento ativo.')
    _,detalhes,_=consultar(c,hoje)
    itens=[r for r in detalhes if r['equipamento_id']==equipamento_id]
    chaves={(r['OP'],r['Lote'],r['Passagem']) for r in itens}
    planos=[dict(r) for r in c.execute('SELECT * FROM mes_programacao WHERE equipamento_id=? ORDER BY op,etapa',(equipamento_id,)) if (r['op'],r['lote'],r['etapa']) in chaves]
    sessoes=[dict(r) for r in c.execute('SELECT * FROM ordens_operacionais WHERE equipamento_id=? ORDER BY id',(equipamento_id,)) if (r['ficha_op'],r['lote_identificado'],r['rota_ordem']) in chaves]
    dados=dict(equipamento=dict(eq),corte=(hoje-timedelta(days=1)).isoformat(),itens=itens,planos=planos,sessoes=sessoes)
    assinatura=hashlib.sha256(json.dumps(dados,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return dados,assinatura


def encerrar(a, equipamento_id, assinatura, motivo, selecionadas=None):
    if not a.apontamento_autenticado():raise PermissionError('Acesso administrativo do PPCP necessário.')
    motivo=str(motivo or '').strip()
    if not motivo:raise ValueError('Informe o motivo do encerramento manual.')
    if len(motivo)>2000:raise ValueError('O motivo deve ter até 2.000 caracteres.')
    instante=a.agora_iso()
    hoje=datetime.fromisoformat(instante).date()
    usuario=a.LOGIN_APONTAMENTO
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        dados,atual=previa(c,equipamento_id,hoje)
        if atual!=assinatura:raise ValueError('Os dados mudaram desde a prévia. Gere uma nova prévia e confira antes de confirmar.')
        if not dados['itens']:raise ValueError('Não há passagens vencidas para encerrar.')
        itens=dados['itens']
        if selecionadas is not None:
            alvos={tuple(chave) for chave in selecionadas}
            permitidas={(r['OP'],r['Lote'],r['Passagem']) for r in itens}
            if not alvos:raise ValueError('Marque pelo menos uma passagem para encerrar.')
            if not alvos<=permitidas:raise ValueError('Seleção inválida ou fora da prévia deste equipamento.')
            itens=[r for r in itens if (r['OP'],r['Lote'],r['Passagem']) in alvos]
        for item in itens:
            op,lote,etapa=item['OP'],item['Lote'],item['Passagem']
            sessoes=[r for r in dados['sessoes'] if (r['ficha_op'],r['lote_identificado'],r['rota_ordem'])==(op,lote,etapa)]
            for r in sessoes:
                if r['status']=='ABERTA':
                    if datetime.fromisoformat(r['aberta_em'])>datetime.fromisoformat(instante):
                        raise ValueError('Abertura posterior ao horário atual. Confira o relógio do servidor.')
                    c.execute("""UPDATE ordens_operacionais SET status='ENCERRADA_PPCP',fechada_em=?,
                        duracao_segundos=0,observacao_fechamento=? WHERE id=? AND status='ABERTA'""",
                        (instante,'Encerramento manual PPCP: '+motivo,r['id']))
            c.execute('''INSERT INTO mes_encerramentos_ppcp
                (op,lote,etapa,equipamento_id,usuario,encerrado_em,motivo,corte,snapshot_json)
                VALUES(?,?,?,?,?,?,?,?,?)''',(op,lote,etapa,equipamento_id,usuario,instante,motivo,dados['corte'],
                json.dumps(dict(pendencia=item,sessoes_antes=sessoes),ensure_ascii=False)))
        from j2i_industrial import auditoria
        auditoria(c,'encerramento_manual_atrasos_ppcp',usuario,dict(equipamento_id=equipamento_id,
            encerrado_em=instante,motivo=motivo,corte=dados['corte'],assinatura=assinatura,
            modo='Todas' if selecionadas is None else 'Selecionadas',
            passagens=[dict(op=r['OP'],lote=r['Lote'],etapa=r['Passagem']) for r in itens]))
    return len(itens)


def renderizar(a, equipamento_id):
    import streamlit as st
    from j2i_industrial_ui import csv_bytes
    st.subheader('Encerramento manual de atrasos — PPCP')
    if equipamento_id is None:
        st.info('Selecione um único equipamento no filtro para encerrar suas passagens em atraso.')
        return
    st.caption('Encerra somente as passagens deste equipamento previstas até ontem e ainda pendentes, inclusive não iniciadas, parciais e abertas. Não encerra etapas de outros equipamentos nem as previstas para hoje ou depois.')
    st.warning('O saldo será encerrado administrativamente, sem gerar produção, refugo, retrabalho ou baixa de estoque. Produção real já apontada e programação histórica são preservadas. As passagens encerradas não poderão ser reabertas; o encerramento não libera produção para etapas seguintes. Paradas registradas permanecem inalteradas.')
    chave=f'ppcp_previa_{equipamento_id}'
    if st.button('Preparar encerramento dos atrasos',key=f'preparar_{equipamento_id}'):
        with a.conectar_banco_operacional() as c:
            c.execute('BEGIN')
            dados,assinatura=previa(c,equipamento_id,datetime.fromisoformat(a.agora_iso()).date())
        st.session_state[chave]=(dados,assinatura)
    preview=st.session_state.get(chave)
    if preview:
        dados,assinatura=preview
        st.write(f"Prévia: {len(dados['itens'])} passagens, de {len({(r['OP'],r['Lote']) for r in dados['itens']})} OPs. Corte: {dados['corte']}.")
        if dados['itens']:
            modo=st.radio('Quais passagens encerrar?', ['Todas as passagens em atraso','Somente as passagens marcadas'],key=f'modo_ppcp_{equipamento_id}_{assinatura}')
            st.caption('Cada linha representa uma passagem. Se a mesma OP aparece mais de uma vez, marque todas as passagens que deseja encerrar. As não marcadas permanecem pendentes.')
            linhas=[{'Encerrar':False,**{k:v for k,v in r.items() if k!='Ignorada por conversão zerada'}} for r in dados['itens']]
            editado=st.data_editor(linhas,hide_index=True,use_container_width=True,num_rows='fixed',
                disabled=[k for k in linhas[0] if k!='Encerrar']+(['Encerrar'] if modo=='Todas as passagens em atraso' else []),
                column_config={'Encerrar':st.column_config.CheckboxColumn('Encerrar',default=False),'equipamento_id':None},
                key=f'selecao_ppcp_{equipamento_id}_{assinatura}')
            selecionadas=None if modo=='Todas as passagens em atraso' else [(r['OP'],r['Lote'],r['Passagem']) for r in editado if r['Encerrar']]
            quantidade=len(dados['itens']) if selecionadas is None else len(selecionadas)
            st.write(f'Serão encerradas {quantidade} passagens ({modo.lower()}).')
            with st.form(f'confirmar_ppcp_{equipamento_id}_{assinatura}_{hashlib.sha256(repr(selecionadas).encode()).hexdigest()}'):
                motivo=st.text_area('Motivo obrigatório',max_chars=2000)
                confirmar=st.checkbox('Conferi a prévia e confirmo o encerramento manual dessas passagens pelo PPCP.')
                enviar=st.form_submit_button('Encerrar atrasos manualmente pelo PPCP' if selecionadas is None else 'Encerrar somente as passagens marcadas',type='primary',disabled=quantidade==0)
            if enviar:
                if not confirmar:st.error('Confirme a prévia antes de encerrar.')
                else:
                    try:
                        qtd=encerrar(a,equipamento_id,assinatura,motivo,selecionadas=selecionadas)
                        del st.session_state[chave]
                        st.session_state['ppcp_sucesso']=f'{qtd} passagens encerradas manualmente pelo PPCP, sem gerar produção.'
                        st.rerun()
                    except (ValueError,PermissionError) as exc:st.error(str(exc))
    with st.expander('Histórico de encerramentos manuais deste equipamento'):
        with a.conectar_banco_operacional() as c:
            rows=[dict(r) for r in c.execute('''SELECT op AS OP,lote AS Lote,etapa AS Passagem,
                usuario AS Responsável,encerrado_em AS Encerramento,motivo AS Motivo,corte AS Corte
                FROM mes_encerramentos_ppcp WHERE equipamento_id=? ORDER BY id DESC''',(equipamento_id,))]
        st.dataframe(rows,hide_index=True,use_container_width=True)
        if rows:st.download_button('Baixar encerramentos manuais',csv_bytes(rows),'encerramentos_ppcp.csv','text/csv')
