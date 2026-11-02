"""Telas adicionais. O caminho operacional não abre nem grava Excel."""
import hashlib
import time
import pandas as pd
import streamlit as st


def executar(funcao, *args):
    try:
        funcao(*args)
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc)); return False
    except Exception:
        import logging
        logging.exception('Falha na operação MES')
        st.error('Não foi possível confirmar a gravação. Atualize a tela e confira o estado antes de tentar novamente.')
        return False
    return True


def estados(a, eq):
    with a.conectar_banco_operacional() as c:
        abertas=c.execute("SELECT * FROM ordens_operacionais WHERE equipamento_id=? AND status='ABERTA' ORDER BY id",(eq['id'],)).fetchall()
        selecionada=st.session_state.get('op_ordem_selecionada')
        ordem=next((r for r in abertas if r['id']==selecionada),abertas[0] if abertas else None)
        parada=c.execute("SELECT * FROM paradas_operacionais WHERE equipamento_id=? AND status='ABERTA'",(eq['id'],)).fetchone()
    return dict(ordem) if ordem else None, dict(parada) if parada else None


def login(a):
    st.title('Operação por equipamento')
    with st.form('login_operador'):
        usuario=st.text_input('Usuário do equipamento')
        senha=st.text_input('Senha',type='password')
        entrar=st.form_submit_button('Entrar',type='primary')
    if entrar:
        if time.monotonic()<st.session_state.get('op_login_aguardar',0):
            st.error('Aguarde alguns segundos antes de tentar novamente.'); return
        eq=a.autenticar_operador(usuario,senha)
        if eq:
            from j2i_sessoes import adquirir
            try:
                with a.conectar_banco_operacional() as c:
                    c.execute('BEGIN IMMEDIATE')
                    token=adquirir(c,eq['id'])
            except ValueError as exc:
                st.error(str(exc));return
            st.session_state['operador_token']=token
            st.session_state['apontamento_autenticado']=False
            st.session_state['operador_equipamento_id']=eq['id']; st.rerun()
        else:
            st.session_state['op_login_aguardar']=time.monotonic()+3
            st.error('Usuário ou senha inválidos.')


def consultar_ops_pendentes(c, equipamento_id, lote, op=''):
    """Passagens programadas sem abertura; consulta isolada por equipamento/lote."""
    lote = str(lote).strip()
    op = str(op).strip()
    if not lote:
        return []
    return [dict(r) for r in c.execute("""
        SELECT p.op AS OP, p.lote AS Lote, p.etapa AS Passagem,
               p.peca AS Peça, COALESCE((SELECT MAX(0,o.quantidade_programada-o.quantidade_boa-o.refugo) FROM ordens_operacionais o WHERE o.equipamento_id=p.equipamento_id AND o.ficha_op=p.op AND o.lote_identificado=p.lote AND o.rota_ordem=p.etapa ORDER BY o.id DESC LIMIT 1),p.quantidade) AS 'Quantidade de peças',
               p.data_programada AS 'Data programada'
        FROM mes_programacao p
        WHERE p.equipamento_id=? AND p.lote=?
          AND (?='' OR instr(p.op,?)>0)
          AND NOT EXISTS (SELECT 1 FROM mes_encerramentos_ppcp m WHERE m.op=p.op AND m.lote=p.lote AND m.etapa=p.etapa)
          AND NOT EXISTS (
              SELECT 1 FROM ordens_operacionais o
              WHERE o.equipamento_id=p.equipamento_id
                AND o.ficha_op=p.op AND o.lote_identificado=p.lote
                AND o.rota_ordem=p.etapa AND (o.status='ABERTA' OR o.encerramento_parcial=0))
        ORDER BY p.data_programada,p.op,p.etapa LIMIT 501
    """, (equipamento_id,lote,op,op)).fetchall()]


def pesquisa_ops_pendentes(a, eq):
    with st.expander('Pesquisar OPs pendentes por lote', expanded=False):
        st.caption('Exibe passagens não iniciadas e saldos de sessões parciais neste equipamento. '
                   'OPs em andamento não entram na lista. O sequenciamento continua obrigatório.')
        with st.form('op_pesquisa_pendentes'):
            lote=st.text_input('Número do lote',key='op_pesquisa_lote')
            op=st.text_input('Pesquisar OP (opcional)',placeholder='Número completo ou parte da OP',key='op_pesquisa_numero')
            pesquisar=st.form_submit_button('Pesquisar OPs')
        chave=f"op_filtro_pendentes_{eq['id']}"
        if pesquisar:
            if not lote.strip():
                st.session_state.pop(chave,None)
                st.warning('Informe o número do lote.')
            else:
                st.session_state[chave]=(a.normalizar_lote(lote),op.strip())
        filtro=st.session_state.get(chave)
        if filtro:
            with a.conectar_banco_operacional() as c:
                linhas=consultar_ops_pendentes(c,eq['id'],*filtro)
            if not linhas:
                st.info('Nenhuma passagem pendente encontrada para este lote e filtro no equipamento. Confira o lote e sua importação.')
            else:
                if len(linhas)>500:
                    st.warning('Exibindo as primeiras 500 passagens. Refine a pesquisa por OP.')
                linhas=linhas[:500]
                st.caption(f"Lote {filtro[0]} • {len({r['OP'] for r in linhas})} OP(s) • {len(linhas)} passagem(ns) exibidas")
                st.dataframe(linhas,use_container_width=True,hide_index=True)


def operacao(a):
    from j2i_operacao_simples import tela
    tela(a)


def importar(a):
    st.title('Importar lotes de produção')
    st.caption('Páginas inválidas e etapas de equipamentos não cadastrados são ignoradas com aviso. Lotes já importados são bloqueados.')
    from j2i_cadastros import lotes
    lotes(a)
    if st.session_state.get('importacao_ok'):
        st.success(st.session_state.pop('importacao_ok'))
    arquivo = st.file_uploader('PDF de fichas de produção TEGA/Dobue', type=['pdf'])
    if not arquivo:
        return
    dados = arquivo.getvalue()
    chave = hashlib.sha256(dados).hexdigest()
    if st.button('Validar e visualizar PDF', type='primary'):
        st.session_state.pop('pdf_validado', None)
        try:
            with st.spinner('Lendo as fichas...'):
                fichas, avisos = a.preparar_importacao_pdf(dados)
            st.session_state['pdf_validado'] = (chave, fichas, avisos)
        except Exception as exc:
            st.error(str(exc))
    validado = st.session_state.get('pdf_validado')
    if not validado or validado[0] != chave or len(validado) != 3:
        return
    fichas, avisos = validado[1:]
    nomes = sorted({a.normalizar_lote(f['lote']) for f in fichas})
    st.success(f"{len(fichas)} OPs válidas. Lotes: {', '.join(nomes)}")
    if avisos:
        st.warning(f'{len(avisos)} avisos encontrados. Confira as páginas e etapas ignoradas antes de confirmar.')
        with st.expander('Ver todos os avisos', expanded=True):
            st.dataframe({'Aviso': avisos}, use_container_width=True)
            st.download_button('Baixar avisos', '\n'.join(avisos).encode('utf-8-sig'), 'avisos_importacao.txt', 'text/plain')
    st.dataframe([{'OP': f['op'], 'Lote': f['lote'], 'Peça': f['descricao_peca'], 'Quantidade': f['quantidade_produzir'],
                   'Equipamentos': ', '.join(r['codigo_equipamento'] for r in f['rotas'])} for f in fichas], use_container_width=True)
    with a.conectar_catalogo_fichas() as c:
        anteriores = {a.normalizar_lote(r['lote']): r['qtd'] for r in c.execute('SELECT lote, COUNT(*) qtd FROM fichas_catalogo GROUP BY lote')}
    repetidos = sorted(set(nomes) & set(anteriores))
    modo = st.radio('Modo de importação', ['Importar novos lotes', 'Substituir lote existente'])
    alvo = None
    habilitado = True
    if modo == 'Importar novos lotes':
        if repetidos:
            st.error('Lote já importado: ' + ', '.join(repetidos) + '. Para recarregar, selecione Substituir lote existente.')
            habilitado = False
    else:
        if len(nomes) != 1 or not repetidos:
            st.error('A substituição exige um PDF com somente um lote já cadastrado.')
            habilitado = False
        else:
            alvo = nomes[0]
            st.warning(f'Lote {alvo}: serão excluídas todas as {anteriores[alvo]} OPs cadastradas e importadas as {len(fichas)} OPs válidas exibidas acima. Páginas ignoradas não serão recuperadas do cadastro anterior. Lotes com apontamentos não podem ser substituídos.')
            digitado = st.text_input('Digite o número do lote para confirmar', key='confirmar_lote_' + chave)
            aceite = st.checkbox('Confirmo a exclusão das OPs anteriores e a substituição pelas OPs válidas deste PDF.', key='aceitar_lote_' + chave)
            habilitado = aceite and a.normalizar_lote(digitado) == alvo
    ciente = st.checkbox('Li os avisos e confirmo a importação somente das páginas e etapas válidas.', key='avisos_' + chave) if avisos else True
    if st.button('Confirmar substituição' if alvo else 'Importar e liberar OPs para apontamento', disabled=not (habilitado and ciente)):
        try:
            qtd = a.gravar_fichas_catalogo(fichas, arquivo.name, substituir_lote=alvo, avisos=avisos)
            st.session_state['importacao_ok'] = f"{qtd} OPs importadas. " + ('Lote substituído com cópia do cadastro anterior no histórico interno.' if alvo else 'Lotes liberados para apontamento.')
            st.session_state.pop('pdf_validado', None)
            st.rerun()
        except Exception as exc:
            st.error(f'Importação não confirmada: {exc}')


def historico(a):
    st.title('Histórico de OPs e paradas')
    with a.conectar_banco_operacional() as c:
        from j2i_paradas_jornada import registrar_sql
        registrar_sql(c)
        linhas=c.execute('''SELECT o.id, o.usuario, o.maquina, o.ficha_op AS op, o.lote_identificado AS lote,
            o.descricao_peca, o.rota_ordem AS etapa, o.rota_operacao AS operacao, o.aberta_em, o.fechada_em, o.status, o.quantidade_boa, o.refugo AS sucata,
            o.retrabalho, j2i_tempo_jornada(o.equipamento_id,o.aberta_em,o.fechada_em) AS tempo_total_segundos,
            COALESCE((SELECT SUM(j2i_tempo_jornada(p.equipamento_id,MAX(p.iniciada_em,o.aberta_em),MIN(p.encerrada_em,o.fechada_em)))
                FROM paradas_operacionais p WHERE p.equipamento_id=o.equipamento_id
                AND p.status='FINALIZADA' AND o.fechada_em IS NOT NULL
                AND p.iniciada_em<o.fechada_em AND p.encerrada_em>o.aberta_em),0) AS parada_segundos
            FROM ordens_operacionais o WHERE o.equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) ORDER BY o.id DESC LIMIT 5000''').fetchall()
        paradas=c.execute('SELECT * FROM paradas_operacionais WHERE equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) ORDER BY id DESC LIMIT 5000').fetchall()
        from j2i_paradas_jornada import carregar, segundos
        jornadas=carregar(c)
        paradas=[dict(r) for r in paradas]
        for r in paradas:
            r['duracao_segundos']=segundos(jornadas.get(r['equipamento_id']),r['iniciada_em'],r['encerrada_em'] or a.agora_iso())
    df=pd.DataFrame([dict(r) for r in linhas])
    st.caption('Até 5.000 registros mais recentes. Tempos das OPs encerradas consideram a jornada semanal atual, excluindo intervalos e horas sem expediente. Sem jornada cadastrada, o tempo fica pendente.')
    if not df.empty:
        df['tempo_produtivo_segundos']=(df['tempo_total_segundos']-df['parada_segundos']).clip(lower=0)
        st.dataframe(df,use_container_width=True)
        st.download_button('Exportar OPs CSV',df.to_csv(index=False,sep=';').encode('utf-8-sig'),'historico_ops.csv','text/csv')
    st.subheader('Paradas')
    st.dataframe([dict(r) for r in paradas],use_container_width=True)


def renderizar(a,pagina):
    a.inicializar_banco_operacional();a.inicializar_catalogo_fichas()
    if 'Operação por' in pagina:operacao(a);return
    if not a.apontamento_autenticado():
        a.renderizar_login_apontamento();return
    if 'Unidades e Metas' in pagina:
        from j2i_cadastros import tela
        tela(a)
    elif 'Importar' in pagina:
        from j2i_importacao_v6 import renderizar as importar_v6
        importar_v6(a)
    else:historico(a)
