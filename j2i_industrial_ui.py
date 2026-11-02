"""Telas MES 6. Importações são validadas antes de qualquer gravação."""
import csv
import hashlib
import io
import json
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import j2i_industrial as m


def executar(a, fn, *args):
    try:
        with a.conectar_banco_operacional() as c:
            c.execute('BEGIN IMMEDIATE')
            fn(c, *args)
        st.success('Alteração salva.')
        return True
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
    except Exception:
        import logging
        logging.exception('MES industrial')
        st.error('Gravação não confirmada. Atualize a tela e confira os dados antes de tentar novamente.')
    return False


def equipamentos(a, incluir_inativos=False):
    with a.conectar_banco_operacional() as c:
        return [dict(r) for r in c.execute('SELECT id,codigo,maquina,setor,usuario,ativo FROM equipamentos '+('' if incluir_inativos else 'WHERE ativo=1 ')+'ORDER BY maquina')]


def escolher(a, key):
    eqs = [r for r in equipamentos(a) if r['ativo']]
    if not eqs:
        st.info('Cadastre um equipamento ativo.'); st.stop()
    return st.selectbox('Equipamento', eqs, format_func=lambda r: f"{r['codigo']} — {r['maquina']}", key=key)


def editor_regra(r, key):
    tipos = list(m.REGRAS)
    tipo = st.selectbox('Regra de cálculo', tipos, index=tipos.index(r.get('tipo', 'pecas')), format_func=m.REGRAS.get, key=key+'tipo')
    unidade = st.text_input('Unidade personalizada',r.get('unidade',''),key=key+'unidade') if tipo=='quantidade' else m.UNIDADES[tipo]
    escala = st.selectbox('Unidade das medidas na ficha', list(m.ESCALAS), index=list(m.ESCALAS).index(r.get('dimensao', 'm')), key=key+'dim')
    mult = st.number_input('Multiplicador: lados ou passagens dentro desta etapa', min_value=0.001, value=float(r.get('multiplicador', 1)), key=key+'mult')
    st.caption('Passagens que já aparecem como etapas separadas não devem ser multiplicadas novamente. Peças por ciclo não é multiplicador de produção.')
    bc = st.number_input('Bordas no comprimento', min_value=0.0, value=float(r.get('bordas_c', 0)), key=key+'bc') if tipo == 'bordas' else 0
    bl = st.number_input('Bordas na largura', min_value=0.0, value=float(r.get('bordas_l', 0)), key=key+'bl') if tipo == 'bordas' else 0
    return dict(tipo=tipo, dimensao=escala, multiplicador=mult, bordas_c=bc, bordas_l=bl, unidade=unidade)



def reaplicar_metrica_lote(a, eq, lote, versao):
    """Reaplica a métrica salva, com bloqueio contra apontamento concorrente."""
    alteradas = []; preservadas = set(); fichas = {}; ops_iniciadas = set()
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        atual = c.execute('SELECT versao,regra_json FROM mes_metricas WHERE equipamento_id=?', (eq,)).fetchone()
        if not atual or atual['versao'] != versao:
            raise ValueError('Métrica alterada. Atualize a tela antes de recalcular.')
        regra = json.loads(atual['regra_json'])
        planos = c.execute('SELECT * FROM mes_programacao WHERE equipamento_id=? AND lote=?', (eq,lote)).fetchall()
        if not planos:
            raise ValueError('Nenhuma programação encontrada neste lote/equipamento.')
        eqs = {r['id']:dict(r) for r in c.execute('SELECT id,codigo FROM equipamentos WHERE ativo=1')}
        if eq not in eqs:raise ValueError('Equipamento inativo.')
        with a.conectar_catalogo_fichas() as catalogo:
            catalogo.execute('BEGIN IMMEDIATE')
            for plano in planos:
                op = plano['op']
                # Uma produção em outro equipamento não congela esta passagem ainda não iniciada.
                if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? AND lote_identificado=? AND rota_ordem=? LIMIT 1',
                             (op,lote,plano['etapa'])).fetchone():
                    preservadas.add(op); continue
                if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? LIMIT 1',(op,)).fetchone():
                    ops_iniciadas.add(op)
                if op not in fichas:
                    row = catalogo.execute('SELECT * FROM fichas_catalogo WHERE op=?',(op,)).fetchone()
                    if not row:raise ValueError(f'OP {op}: ficha ausente no catálogo.')
                    fichas[op] = a.ficha_linha_para_dict(row)
                f = fichas[op]
                rota = next((r for r in f['rotas'] if int(r['ordem'])==plano['etapa']),None)
                if (not rota or str(rota['codigo_equipamento']).lstrip('0')!=str(eqs[eq]['codigo']).lstrip('0')
                    or f['medida']!=plano['medida'] or f['quantidade_produzir']!=plano['quantidade'] or f['lote']!=lote):
                    raise ValueError(f'OP {op}: catálogo e programação divergem. Revise a importação antes de recalcular.')
                nova = m.regra_rota(regra,rota.get('operacao',''))
                m.fator(nova,plano['medida'])
                if nova == json.loads(plano['regra_json']):continue
                texto = json.dumps(nova,ensure_ascii=False,sort_keys=True)
                c.execute('UPDATE mes_programacao SET regra_json=?,versao=versao+1 WHERE op=? AND etapa=?',(texto,op,plano['etapa']))
                alteradas.append(dict(op=op,etapa=plano['etapa'],antes=json.loads(plano['regra_json']),depois=nova))
            # Atualiza o rateio previsto de MP das OPs afetadas; nunca movimenta estoque.
            for op in {x['op'] for x in alteradas}:
                # Consumos e política de estoque permanecem congelados após qualquer abertura da OP.
                if op in ops_iniciadas:continue
                consumos, pendencias = m.resolver_materiais(c,fichas[op],eqs)
                for etapa,itens in consumos.items():
                    m.salvar_consumos(c,op,etapa,itens,a.LOGIN_APONTAMENTO)
                    if pendencias:c.execute('DELETE FROM mes_revisao_mp WHERE op=? AND etapa=?',(op,etapa))
                c.execute('INSERT OR REPLACE INTO mes_pendencias_mp VALUES(?,?,?)',(op,json.dumps(pendencias,ensure_ascii=False),m.agora()))
            if alteradas:
                m.auditoria(c,'reaplicar_metrica_lote',a.LOGIN_APONTAMENTO,dict(equipamento=eq,lote=lote,alteradas=alteradas,consumos_preservados=sorted(ops_iniciadas)))
    return len(alteradas),sorted(preservadas)


def metricas(a):
    st.title('Métricas e metas por equipamento')
    eq = escolher(a, 'metrica_eq')
    with a.conectar_banco_operacional() as c:
        row = c.execute('SELECT * FROM mes_metricas WHERE equipamento_id=?', (eq['id'],)).fetchone()
        metas = [dict(r) for r in c.execute('SELECT vigencia,valor,periodo,regra_json,usuario FROM mes_metas WHERE equipamento_id=? ORDER BY vigencia DESC', (eq['id'],))]
    versao = row['versao'] if row else 0
    regra = json.loads(row['regra_json']) if row else {}
    st.caption('A configuração vale para novas programações. Etapas programadas e apontamentos preservam sua própria regra.')
    with st.container(border=True):
        nova = editor_regra(regra, f'r{eq["id"]}_{versao}')
        exemplo = st.text_input('Medida para conferir o cálculo', '1,000/0,500/0,018')
        quantidade = st.number_input('Quantidade de exemplo', min_value=0.0, value=10.0)
        conferir = st.button('Conferir cálculo')
        salvar = st.button('Salvar métrica')
    if conferir or salvar:
        try:
            f = m.fator(nova, exemplo)
            st.info(f"Resultado do exemplo: {m.calcular(quantidade, f):g} {m.validar_regra(nova)['unidade']}")
            if salvar and executar(a, m.salvar_metrica, eq['id'], nova, versao, a.LOGIN_APONTAMENTO):
                st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    st.subheader('Recalcular programação existente')
    st.caption('Primeiro salve a métrica acima. O recálculo usa a configuração salva e a operação de cada etapa (incluindo pintura de um ou dois lados). Passagens já iniciadas são preservadas. Passagens ainda não iniciadas podem ser corrigidas mesmo se a OP já passou por outro equipamento. Datas e quantidades permanecem iguais. Em OPs já iniciadas, consumos e estoque permanecem intactos; o rateio previsto só é recalculado em OPs sem nenhum apontamento.')
    with a.conectar_banco_operacional() as c:
        lotes = [r[0] for r in c.execute('SELECT DISTINCT lote FROM mes_programacao WHERE equipamento_id=? ORDER BY lote',(eq['id'],))]
    if lotes:
        lote = st.selectbox('Lote para recalcular',lotes,key=f"recalcular_lote_{eq['id']}")
        st.caption('No PDF TEGA enviado, medidas como 0,905/0,905 estão em metros: selecione m em Unidade das medidas na ficha. Para peças, use Peças / passagens e multiplicador 1.')
        if st.button('Reaplicar métrica salva neste lote',key=f"reaplicar_{eq['id']}"):
            try:
                qtd, preservadas = reaplicar_metrica_lote(a,eq['id'],lote,versao)
                st.success(f'{qtd} etapas atualizadas. Consulte novamente o comparativo de desempenho.')
                if preservadas:
                    st.warning(f'{len(preservadas)} OPs possuem passagens já iniciadas neste equipamento; essas passagens foram preservadas.')
                    st.dataframe({'OP preservada':preservadas},hide_index=True)
            except ValueError as exc:st.error(str(exc))
            except Exception:
                import logging
                logging.exception('Reaplicar métrica')
                st.error('Não foi possível recalcular. A transação foi cancelada; confira o registro de erros.')
    else:st.info('Este equipamento ainda não possui programação.')
    st.subheader('Distribuição de MP entre os processos')
    with a.conectar_banco_operacional() as c:
        politica=m.obter_rateio(c,eq['id'])
    with st.form(f"rateio_{eq['id']}_{politica['versao']}"):
        modo=st.selectbox('Como distribuir o consumo previsto da OP',list(m.RATEIOS_MP),
                          index=list(m.RATEIOS_MP).index(politica['modo']),format_func=m.RATEIOS_MP.get)
        st.caption('Igual: divide pelo número de processos deste equipamento na OP. Por métrica: usa os metros, m² ou unidades previstos em cada etapa. O consumo total de MP não é multiplicado pelo número de processos.')
        salvar_rateio=st.form_submit_button('Salvar distribuição de MP')
    if salvar_rateio and executar(a,m.salvar_rateio,eq['id'],modo,politica['versao'],a.LOGIN_APONTAMENTO):st.rerun()
    st.caption('A mudança será aplicada em novas preparações. Para lotes ainda não iniciados, use Preparar lote já importado. OPs já iniciadas preservam seus consumos.')
    from j2i_jornadas import renderizar as renderizar_jornada
    renderizar_jornada(a, eq)
    st.subheader('Meta com vigência')
    with st.form(f'meta_{eq["id"]}'):
        vigencia = st.date_input('Válida a partir de', date.today())
        valor = st.number_input('Valor da meta', min_value=0.0)
        periodo = st.selectbox('Período', ['Hora', 'Turno', 'Dia'])
        salvar = st.form_submit_button('Cadastrar meta')
    if salvar and executar(a, m.salvar_meta, eq['id'], vigencia.isoformat(), valor, periodo, a.LOGIN_APONTAMENTO):
        st.rerun()
    if metas:
        for r in metas:
            r['unidade'] = json.loads(r.pop('regra_json'))['unidade']
        st.dataframe(metas, use_container_width=True, hide_index=True)


def acessos(a):
    st.title('Equipamentos e acessos')
    st.caption('Exibindo apenas equipamentos ativos. Para reativar um equipamento, abra Métricas e Metas → Equipamentos ativos.')
    eqs = equipamentos(a)
    st.dataframe(eqs, use_container_width=True, hide_index=True)
    st.download_button('Baixar lista de logins', csv_bytes(eqs), 'logins_equipamentos.csv', 'text/csv')
    st.caption('Senha inicial dos equipamentos: 1234. Você pode trocar a senha no cadastro. As senhas ficam armazenadas como hash.')
    selecionado = st.selectbox('Cadastro', [None] + eqs, format_func=lambda r: 'Novo equipamento' if r is None else r['maquina'])
    atual = selecionado or {}
    with st.form('equipamento_'+str(atual.get('id', 'novo'))):
        codigo = st.text_input('Código no PDF', atual.get('codigo', ''))
        nome = st.text_input('Nome', atual.get('maquina', ''))
        setor = st.text_input('Setor (opcional; não interfere na importação)', atual.get('setor', ''))
        login = st.text_input('Login', atual.get('usuario', ''))
        st.caption('Ao alterar o login, informe também a senha para esse acesso. Pode repetir a senha anterior, inclusive 1234. O histórico mantém o usuário registrado na época.')
        senha = st.text_input('Nova senha (vazio mantém a atual; em novo cadastro usa 1234)', type='password')
        ativo = st.checkbox('Ativo', value=bool(atual.get('ativo', 1)))
        salvar = st.form_submit_button('Salvar equipamento')
    if salvar:
        def gravar(c):
            if not codigo.strip().isdigit() or not all(v.strip() for v in [nome, login]):
                raise ValueError('Informe código numérico, nome e login.')
            login_normalizado = login.strip().lower()
            mudou_login = bool(atual) and login_normalizado != atual['usuario']
            if mudou_login and not senha:
                raise ValueError('Ao alterar o login, informe a senha que será usada com o novo usuário.')
            senha_gravar = senha if atual else (senha or a.SENHA_PADRAO_EQUIPAMENTOS)
            if senha_gravar and len(senha_gravar) < 4:
                raise ValueError('A nova senha deve ter pelo menos 4 caracteres.')
            duplicado = c.execute("SELECT id FROM equipamentos WHERE (ltrim(codigo,'0')=ltrim(?,'0') OR lower(usuario)=lower(?)) AND id<>?", (codigo.strip(), login.strip(), atual.get('id', -1))).fetchone()
            if duplicado:
                raise ValueError('Código ou login já cadastrado.')
            if atual:
                canon = c.execute('SELECT codigo,maquina,setor,ativo,usuario FROM equipamentos WHERE id=?', (atual['id'],)).fetchone()
                if not canon or any(canon[k] != atual[k] for k in ('codigo', 'maquina', 'setor', 'ativo', 'usuario')):
                    raise ValueError('Cadastro alterado por outro usuário. Atualize a tela.')
                if codigo.strip() != atual['codigo']:
                    raise ValueError('Código existente é uma identidade do roteiro. Cadastre outro equipamento para usar outro código.')
                if not ativo and c.execute("SELECT 1 FROM ordens_operacionais WHERE equipamento_id=? AND status='ABERTA' UNION ALL SELECT 1 FROM paradas_operacionais WHERE equipamento_id=? AND status='ABERTA'", (atual['id'], atual['id'])).fetchone():
                    raise ValueError('Encerre OP/parada antes de desativar.')
                c.execute('UPDATE equipamentos SET maquina=?,setor=?,ativo=?,atualizado_em=?,usuario=? WHERE id=?', (nome.strip(), setor.strip(), int(ativo), m.agora(), login_normalizado, atual['id']))
                if senha:
                    c.execute('UPDATE equipamentos SET senha_hash=? WHERE id=?', (a.hash_senha_operador(login.strip().lower(), senha_gravar), atual['id']))
            else:
                c.execute('INSERT INTO equipamentos(usuario,senha_hash,codigo,setor,maquina,ativo,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?)',
                          (login.strip().lower(), a.hash_senha_operador(login.strip().lower(), senha_gravar), codigo.strip(), setor.strip(), nome.strip(), int(ativo), m.agora(), m.agora()))
            m.migrar_rateio(c)
            m.auditoria(c, 'equipamento', a.LOGIN_APONTAMENTO, {'equipamento_id': atual.get('id'), 'codigo': codigo, 'login_anterior': atual.get('usuario'), 'login': login_normalizado, 'ativo': ativo, 'senha_redefinida': bool(senha)})
        if executar(a, gravar):
            st.rerun()


def csv_bytes(rows):
    # Evita fórmulas em textos exportados para Excel.
    df = pd.DataFrame(rows)
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].map(lambda v: "'"+v if isinstance(v,str) and v.startswith(('=', '+', '-', '@')) else v)
    return df.to_csv(index=False, sep=';').encode('utf-8-sig')


def ler_estoque(arquivo):
    if arquivo.name.lower().endswith('.csv'):
        df = pd.read_csv(io.BytesIO(arquivo.getvalue()), sep=';', dtype=str, keep_default_na=False)
    else:
        from j2i_pdf_industrial import estoque
        return estoque(arquivo.getvalue())
    if not {'codigo', 'descricao', 'unidade', 'saldo'}.issubset(df.columns):
        raise ValueError('Layout não reconhecido. Use tabela com cabeçalhos codigo, descricao, unidade, saldo. O PDF real ainda precisa ser validado para seu layout.')
    out = []
    for row in df.to_dict('records'):
        saldo = str(row['saldo']).strip()
        if ',' in saldo:
            saldo = saldo.replace('.', '').replace(',', '.')
        row['saldo'] = float(m.numero(saldo, minimo=-10**30))
        for k in ('codigo','descricao','unidade'):
            row[k] = str(row[k] or '').strip()
        out.append(row)
    return out


def estoque(a):
    st.title('Estoque de insumos')
    with a.conectar_banco_operacional() as c:
        controlar, negativo = m.opcao(c, 'controlar_estoque'), m.opcao(c, 'permitir_negativo')
        modo_atual=m.modo_baixa(c)
        linhas = [dict(r) for r in c.execute('SELECT * FROM mes_insumos ORDER BY codigo')]
    with st.form('politica'):
        controle = st.checkbox('Ativar baixa de estoque', controlar)
        permitir = st.checkbox('Permitir apontamento com saldo negativo e registrar ocorrência', negativo)
        modo=st.selectbox('Quando baixar os insumos',list(m.MODOS_BAIXA),index=list(m.MODOS_BAIXA).index(modo_atual),format_func=m.MODOS_BAIXA.get)
        st.caption('Baixa única: consome o total previsto no PDF uma vez por OP, sem vínculos por equipamento. Exige materiais identificados no estoque. A escolha vale para OPs ainda não iniciadas; OPs em andamento mantêm o modo anterior. Não há baixa retroativa nem devolução automática por sucata posterior.')
        salvar = st.form_submit_button('Salvar política')
    if salvar and executar(a, m.salvar_politica_estoque, controle, permitir, modo, modo_atual, a.LOGIN_APONTAMENTO):
        st.rerun()
    if not controlar:
        st.warning('Controle de estoque desativado: apontamentos não dão baixa de materiais.')
    from j2i_estoque_total import resumo
    with a.conectar_banco_operacional() as c:
        totais=resumo(c)
    st.subheader('Saldo total por MP e revestimento')
    st.dataframe(totais,use_container_width=True,hide_index=True)
    with st.expander('Saldos separados por local'):
        st.dataframe([r for r in linhas if not r['codigo'].startswith('TOTAL:')],use_container_width=True,hide_index=True)
    st.caption('A baixa usa o total dos locais para a mesma MP/revestimento. Unidades diferentes não são somadas. Registros internos TOTAL não representam estoque adicional.')
    st.subheader('Importar posição de estoque')
    st.caption('Substitui o saldo apenas dos códigos presentes no arquivo e registra o ajuste. Use posição atual e pause a produção durante a conferência; saldos históricos não são reconciliados automaticamente.')
    st.download_button('Modelo CSV', 'codigo;descricao;unidade;saldo\nMP001;Exemplo de insumo;kg;100,00\n'.encode('utf-8-sig'), 'modelo_estoque.csv', 'text/csv')
    from j2i_estoque_lote import renderizar as importar_estoque_lote
    importar_estoque_lote(a)
    vinculos(a)
    st.subheader('Ocorrências de falta de saldo')
    de = st.date_input('Ocorrências a partir de', date.today().replace(day=1))
    ate = st.date_input('Ocorrências até', date.today())
    with a.conectar_banco_operacional() as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM mes_excecoes WHERE equipamento_id IN (SELECT id FROM equipamentos WHERE ativo=1) AND instante>=? AND instante<? ORDER BY id', (de.isoformat(), ate.isoformat()+'T'))]
    st.dataframe(rows, use_container_width=True)
    st.download_button('Baixar ocorrências do período', csv_bytes(rows), 'ocorrencias_estoque.csv', 'text/csv')


def desempenho(a):
    from j2i_desempenho_periodo import renderizar
    renderizar(a)


def pendencias(a):
    st.title('Pendências de Importação')
    st.subheader('Insumos que não puderam ser preparados automaticamente')
    with a.conectar_banco_operacional() as c:
        materiais=[{'OP':r['op'],'Pendência':p} for r in c.execute('SELECT op,pendencias_json FROM mes_pendencias_mp ORDER BY op') for p in json.loads(r['pendencias_json'])]
    if materiais:
        st.dataframe(materiais,use_container_width=True,hide_index=True)
        st.download_button('Baixar pendências de insumos',csv_bytes(materiais),'pendencias_insumos.csv','text/csv')
        st.info('Ajuste os vínculos de materiais em Estoque de Insumos e use Preparar lote já importado em Importar Lotes PDF. OPs já iniciadas preservam seus consumos.')
    else:
        st.success('Nenhuma pendência de preparação de insumos registrada.')
    st.subheader('Equipamentos e páginas ignorados nas importações')
    with a.conectar_catalogo_fichas() as c:
        rows = c.execute('''SELECT i.arquivo,i.importado_em,a.avisos_json FROM auditoria_importacoes a JOIN importacoes_catalogo i
                            ON i.id=a.importacao_id ORDER BY i.id DESC LIMIT 200''').fetchall()
    itens = [{'Arquivo':r['arquivo'], 'Data':r['importado_em'], 'Aviso':aviso} for r in rows for aviso in json.loads(r['avisos_json'])]
    st.dataframe(itens, use_container_width=True, hide_index=True)
    st.download_button('Baixar resumo', csv_bytes(itens), 'pendencias_importacao.csv', 'text/csv')
    st.caption('Equipamentos ignorados não intertravam o roteiro ativo. Cadastrar depois não altera lotes já importados; revise e reimporte lotes sem apontamentos.')


def renderizar(a, pagina):
    a.inicializar_banco_operacional(); a.inicializar_catalogo_fichas()
    if not a.apontamento_autenticado():
        a.renderizar_login_apontamento(); return
    if 'Métricas' in pagina: metricas(a)
    elif 'Capacidade e Sequenciamento' in pagina:
        from j2i_capacidade_sequenciamento import renderizar as capacidade
        capacidade(a)
    elif 'Sequenciamento de produção' in pagina:
        from j2i_sequencia_producao import renderizar as sequencia
        sequencia(a)
    elif 'Equipamentos ativos' in pagina:
        from j2i_equipamentos_ativos import renderizar as ativos
        ativos(a)
    elif 'Acessos' in pagina: acessos(a)
    elif 'Estoque' in pagina: estoque(a)
    elif 'Pendências' in pagina: pendencias(a)
    elif 'Consumo de Insumos' in pagina:
        from j2i_consumo_insumos import renderizar as consumo
        consumo(a)
    elif 'Paradas registradas' in pagina:
        from j2i_paradas_consulta import renderizar as paradas
        paradas(a)
    elif 'Estatística por equipamento' in pagina:
        from j2i_estatistica import renderizar as estatistica
        estatistica(a)
    elif 'Saldo em atraso por equipamento' in pagina:
        from j2i_atrasos_equipamento import renderizar as atrasos
        atrasos(a)
    elif 'Programação diária' in pagina:
        from j2i_programacao_diaria import renderizar as diaria
        diaria(a)
    else: desempenho(a)


def vinculos(a):
    st.subheader('Material → equipamentos autorizados')
    with a.conectar_banco_operacional() as c:
        itens=[dict(r) for r in c.execute('SELECT codigo,descricao,unidade FROM mes_insumos ORDER BY codigo')]
        resumo=[dict(r) for r in c.execute('SELECT v.insumo,e.maquina,v.passagem FROM mes_vinculos_mp v JOIN equipamentos e ON e.id=v.equipamento_id WHERE e.ativo=1 ORDER BY v.insumo,e.maquina')]
    if not itens:
        st.info('Importe o estoque para vincular materiais.');return
    item=st.selectbox('Material / variante',itens,format_func=lambda r:r['codigo']+' — '+r['descricao'])
    with a.conectar_banco_operacional() as c:
        atuais=m.listar_vinculos(c,item['codigo'])
    token=m.versao_vinculos(atuais)
    chave='multi_mp_'+item['codigo']+'_'+hashlib.sha256(token.encode()).hexdigest()[:10]
    eqs={e['id']:e for e in equipamentos(a) if e['ativo'] or e['id'] in {v['equipamento_id'] for v in atuais}}
    chave+='_'+hashlib.sha256(str(sorted(eqs)).encode()).hexdigest()[:8]
    selecionados=st.multiselect('Equipamentos autorizados a consumir esta MP',list(eqs),
        default=[v['equipamento_id'] for v in atuais if v['equipamento_id'] in eqs],
        format_func=lambda i:eqs[i]['maquina']+(' (inativo)' if not eqs[i]['ativo'] else ''),key=chave)
    mapa={v['equipamento_id']:v['passagem'] for v in atuais}
    linhas=[{'equipamento_id':i,'Equipamento':eqs[i]['maquina'],'passagem':mapa.get(i,1)} for i in selecionados]
    editados=st.data_editor(pd.DataFrame(linhas,columns=['equipamento_id','Equipamento','passagem']),hide_index=True,
        disabled=['equipamento_id','Equipamento'],key=chave+'_passagens_'+str(selecionados),
        column_config={'equipamento_id':None,'passagem':st.column_config.NumberColumn('Passagem consumidora',min_value=1,step=1,required=True)})
    with a.conectar_banco_operacional() as c:
        politicas=[{'Equipamento':eqs[i]['maquina'],'Distribuição de MP':m.RATEIOS_MP[m.obter_rateio(c,i)['modo']]} for i in selecionados]
    if politicas:st.dataframe(politicas,use_container_width=True,hide_index=True)
    st.caption('A passagem acima é usada somente no modo Somente a passagem cadastrada. Nos modos de rateio, todos os processos daquele equipamento na OP participam. Configure em Métricas e Metas.')
    st.caption('O mesmo saldo atende todos os equipamentos. Se máquinas diferentes autorizadas estiverem na mesma OP, o PCP define a distribuição entre elas.')
    st.caption('Desmarcar um equipamento remove sua autorização para futuras preparações. OPs já iniciadas conservam seus consumos.')
    if st.button('Salvar equipamentos da MP'):
        novos=[{'equipamento_id':r['equipamento_id'],'passagem':r['passagem']} for r in editados.to_dict('records')]
        novos.extend(v for v in atuais if v['equipamento_id'] not in eqs)
        if executar(a,m.salvar_vinculos,item['codigo'],novos,a.LOGIN_APONTAMENTO,token):st.rerun()
    st.dataframe(resumo,use_container_width=True,hide_index=True)


@st.fragment(run_every=2)
def acompanhar_saldo():
    job=st.session_state.get('saldo_job')
    if not job:return
    digest,fut,revisoes=job
    if not fut.done():st.info('Lendo estoque em segundo plano...');return
    try:st.session_state['saldo_previa']=(digest,fut.result(),revisoes)
    except Exception as exc:st.session_state['saldo_erro']=str(exc)
    del st.session_state['saldo_job']
    st.rerun()
