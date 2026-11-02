"""Importação do PDF único, com prévia e datas por equipamento."""
import hashlib
import io
import json
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from pathlib import Path
from datetime import date
import pandas as pd
import streamlit as st
import j2i_industrial as m
from j2i_pdf_industrial import fichas as extrair
from j2i_pdf_lotes import filtrar_equipamentos


@st.cache_resource
def pool():
    return ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))


@st.fragment(run_every=2)
def acompanhar():
    job=st.session_state.get('pdf_v6_job')
    if not job:return
    digest,fut=job
    if not fut.done():
        st.info('Lendo o PDF em segundo plano. Os apontamentos continuam disponíveis para os operadores.')
        return
    try:
        st.session_state['pdf_v6_lido']=(digest,fut.result())
    except Exception as exc:
        st.session_state['pdf_v6_erro']=str(exc)
    del st.session_state['pdf_v6_job']
    st.rerun()


def excel(fichas, datas, datas_salvas=None):
    rows=[];materiais=[]
    for f in fichas:
        for r in f['rotas']:
            eq=r['codigo_equipamento'].lstrip('0')
            data_etapa=(datas_salvas or {}).get((f['op'],int(r['ordem']))) if datas_salvas is not None else datas.get(eq)
            rows.append({'Data Programada':date.fromisoformat(data_etapa) if data_etapa else None,'OP/Lote':f['lote'],'Cliente/Pedido':f['obs_lote'],
                         'Produto/Equipamento':r['equipamento'],'Codigo Peca':f['codigo_peca'],
                         'Descricao Peca':f['descricao_peca'],'Operacao':r['operacao'],'Setor':r['setor'],
                         'Maquina/Posto':r['codigo_equipamento']+' - '+r['equipamento'],
                         'Qtde Programada':f['quantidade_produzir'],'OP':f['op'],'Etapa':r['ordem'],'Medida':f['medida']})
        for mp in f.get('materiais',[]):materiais.append({'OP':f['op'],'Lote':f['lote'],**mp,'Consumo total previsto':m.calcular(mp['consumo_por_peca'],f['quantidade_produzir'])})
    from j2i_industrial_ui import csv_bytes
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        for name,values in [('5_ACOMPANHAMENTO',rows),('Materiais_por_OP',materiais)]:
            df=pd.DataFrame(values)
            for col in df.select_dtypes(include=['object']).columns:
                df[col]=df[col].map(lambda v: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v)
            df.to_excel(writer,sheet_name=name,index=False)
            ws=writer.sheets[name];ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width=min(55,max(15,len(str(col[0].value))+3))
    return buf.getvalue()


def _renderizar_importacao(a):
    from j2i_industrial_ui import csv_bytes
    st.title('Importar PDF único de produção')
    st.caption('OPs, passagens e consumo por peça são lidos juntos. Datas são informadas por equipamento. O cadastro preserva as OPs e o Excel é uma exportação da programação.')
    from j2i_calendario_producao import feriados, programacao, validar_datas
    permissao_lotes_existentes(a)
    feriados(a)
    arq=st.file_uploader('Fichas TEGA / Dobue',type=['pdf'])
    if st.session_state.get('pdf_v6_job'):acompanhar()
    if st.session_state.get('pdf_v6_erro'):st.error(st.session_state.pop('pdf_v6_erro'))
    if not arq:return
    digest=hashlib.sha256(arq.getvalue()).hexdigest()
    if st.button('Ler PDF e preparar prévia',disabled=bool(st.session_state.get('pdf_v6_job'))):
        st.session_state['pdf_v6_job']=(digest,pool().submit(extrair,arq.getvalue()))
        st.rerun()
    lido=st.session_state.get('pdf_v6_lido')
    if not lido or lido[0]!=digest:return
    with a.conectar_banco_operacional() as c:
        eqs=[dict(r) for r in c.execute('SELECT id,codigo,setor,maquina FROM equipamentos')]
        regras={r['equipamento_id']:json.loads(r['regra_json']) for r in c.execute('SELECT * FROM mes_metricas')}
    avisos=[]
    fichas=filtrar_equipamentos(lido[1],eqs,avisos)
    from j2i_reimportacao import selecionar
    apenas=st.checkbox('Importar somente equipamentos selecionados',key='pdf_filtrar_equipamentos')
    escolhidos=None
    if apenas:
        escolhidos=st.multiselect('Equipamentos a importar',[e['codigo'] for e in eqs],
            format_func=lambda cod:next(e['maquina'] for e in eqs if e['codigo']==cod),key='pdf_equipamentos')
        if not escolhidos:st.info('Selecione ao menos um equipamento.');return
    fichas=selecionar(fichas,escolhidos)
    digest=hashlib.sha256((digest+repr(sorted(escolhidos or []))).encode()).hexdigest()
    opcoes=['Importar novo','Preparar lote já importado','Substituir lote sem apontamentos','Corrigir quantidades por OP/palete','Reimportar / completar preservando apontamentos']
    modo=st.radio('Tratamento do lote',[opcoes[-1]] if apenas else opcoes,key='modo_importacao_'+str(apenas))
    mescla=apenas or modo==opcoes[-1]
    if mescla:
        st.info('Inclui OPs/processos novos e atualiza etapas não iniciadas. Preserva etapas abertas, parciais, concluídas e encerradas pelo PPCP, datas já programadas e processos ausentes neste PDF. O filtro não libera automaticamente a sequência.')
    with a.conectar_banco_operacional() as c:
        protegidas={(r[0],r[1]) for r in c.execute('SELECT ficha_op,rota_ordem FROM ordens_operacionais')}
        protegidas.update((r[0],r[1]) for r in c.execute('SELECT op,etapa FROM mes_encerramentos_ppcp'))

    st.info(f'{len(lido[1])} OPs lidas · {len(fichas)} OPs com equipamento cadastrado · {sum(len(f["rotas"]) for f in fichas)} etapas ativas')
    if avisos:
        with st.expander(f'{len(avisos)} avisos / etapas ignoradas',expanded=False):
            st.dataframe({'Aviso':avisos},use_container_width=True)
            st.download_button('Baixar avisos','\n'.join(avisos).encode('utf-8-sig'),'avisos_importacao.txt','text/plain')
    if not fichas:return
    usados={str(r['codigo_equipamento']).lstrip('0') for f in fichas for r in f['rotas']}
    eqs=[e for e in eqs if e['codigo'].lstrip('0') in usados]
    faltam=[e['maquina'] for e in eqs if e['id'] not in regras]
    if faltam:
        st.warning('Configure as métricas antes de programar: '+', '.join(faltam))
        st.caption('Abra Métricas e Metas no menu. A prévia do PDF fica preservada nesta sessão.');return
    datas=programacao(a,eqs,digest)
    if datas is None:return
    st.caption('Ao confirmar, as etapas, métricas e consumos serão preparados automaticamente. As OPs ficam disponíveis aos operadores, respeitando a sequência dos processos.')
    erros=[]; excecoes_dimensao=[]; avisos_dimensao=[]
    eqmap={e['codigo'].lstrip('0'):e['id'] for e in eqs}
    for f in fichas:
        for r in f['rotas']:
            if mescla and (f['op'],int(r['ordem'])) in protegidas:continue
            try:
                date.fromisoformat(datas[r['codigo_equipamento'].lstrip('0')])
                regra=m.regra_rota(regras[eqmap[r['codigo_equipamento'].lstrip('0')]],r['operacao'])
                try:
                    m.fator(regra,f['medida'])
                except ValueError:
                    # Somente medidas numéricas zeradas podem ser autorizadas.
                    especial=dict(regra,permitir_dimensao_zero=True)
                    if m.fator(especial,f['medida'])!=0:raise
                    excecoes_dimensao.append((f['op'],int(r['ordem'])))
                    avisos_dimensao.append(f"OP {f['op']}, etapa {r['ordem']}: medida {f['medida']} — produção dimensional será contabilizada como zero.")
            except ValueError as exc:erros.append(f"OP {f['op']}, etapa {r['ordem']}: {exc}")
    if erros:
        st.error('Corrija as métricas/datas antes de importar.');st.dataframe({'Erro':erros});return
    if excecoes_dimensao:
        st.warning('Existem etapas com dimensões zeradas. Sem medidas válidas, elas não acrescentarão m² ou metros ao programado e realizado.')
        st.dataframe({'Exceção de dimensão':avisos_dimensao},hide_index=True)
        if not st.checkbox('Permitir continuar com medidas zeradas nas etapas listadas (produção dimensional = 0)',key='autorizar_zero_'+digest):return
        avisos.extend(avisos_dimensao)
    st.dataframe([{'OP':f['op'],'Lote':f['lote'],'Peça':f['descricao_peca'],'Peças':f['quantidade_produzir'],'Etapas':len(f['rotas']),'Materiais':len(f.get('materiais',[]))} for f in fichas],use_container_width=True,hide_index=True)
    with a.conectar_catalogo_fichas() as c:
        existentes={r[0] for r in c.execute('SELECT DISTINCT lote FROM fichas_catalogo')}
    resultado=st.session_state.get('pdf_v6_resultado')
    if resultado and resultado[0]==digest:
        st.success('Importação anterior concluída nesta sessão.')
        st.download_button('Baixar Excel salvo',resultado[1],'programacao_importada.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='excel_salvo')
    lotes={f['lote'] for f in fichas};repetidos=lotes & existentes

    if modo=='Preparar lote já importado':
        st.info('Etapas já programadas mantêm suas datas. O calendário de cinco dias é aplicado somente às etapas ainda sem programação; este comando não reagenda o lote existente.')
    alvo=None
    if modo=='Importar novo' and repetidos:st.warning('Lote já cadastrado. Escolha preparar ou substituir.');return
    if modo=='Substituir lote sem apontamentos':
        if len(lotes)!=1 or not repetidos:st.warning('Substituição exige um único lote já cadastrado.');return
        alvo=next(iter(lotes))
        if st.text_input('Digite o lote para confirmar a substituição')!=alvo:return
    if modo=='Corrigir quantidades por OP/palete':
        st.info('Corrige a quantidade das OPs ainda não iniciadas usando a coluna Qtde do palete. Recalcula programação e consumo previsto; preserva métricas e datas existentes. OPs com apontamentos serão mantidas e listadas para conferência.')
    liberacoes={}
    with st.container(border=True):
        st.subheader('⚠️ Implantação — liberar processos sem etapas anteriores')
        st.warning('Marque somente os lotes que poderão iniciar processos adiantados. Sem conclusão anterior, será usada a quantidade original da OP. Estoque e controle de duplicidade continuam ativos.')
        with a.conectar_banco_operacional() as c:
            livres={lote:bool(m.opcao(c,'sequencia_livre_lote:'+lote)) for lote in lotes}
        for lote in sorted(lotes):
            liberacoes[lote]=st.checkbox(f'Lote {lote}: permitir apontar sem concluir os processos anteriores',value=livres[lote],key='sequencia_livre_'+digest+'_'+lote)
        st.caption('Ao confirmar esta importação/preparação, a escolha será salva para cada lote acima. Desmarcar reativa o intertravamento para novas aberturas; apontamentos existentes são preservados.')
    if mescla:
        st.subheader('Etapas incluídas nesta confirmação')
        st.dataframe([{'OP':f['op'],'Lote':f['lote'],'Peça':f['descricao_peca'],'Etapa':r['ordem'],'Equipamento':r['equipamento'],'Tratamento':'Preservar apontamentos/encerramento' if (f['op'],int(r['ordem'])) in protegidas else 'Importar ou atualizar processo pendente'} for f in fichas for r in f['rotas']],hide_index=True,use_container_width=True)
    aceite=st.checkbox('Conferi as datas, métricas e avisos. Etapas de equipamentos não cadastrados serão ignoradas.')
    if st.button('Importar e disponibilizar para produção',type='primary',disabled=not aceite):
        try:
            with a.conectar_banco_operacional() as c:
                validar_datas(c,datas)
            if mescla:
                from j2i_reimportacao import mesclar
                fichas,pend,resumo=mesclar(a,fichas,arq.name,datas,a.LOGIN_APONTAMENTO,excecoes_dimensao,liberacoes)
                st.dataframe(resumo,hide_index=True,use_container_width=True)
            elif modo=='Corrigir quantidades por OP/palete':
                fichas= corrigir_quantidades_paletes(a,fichas,arq.name,excecoes_dimensao)
            elif modo!='Preparar lote já importado':
                a.gravar_fichas_catalogo(fichas,arq.name,substituir_lote=alvo,avisos=avisos)
            else:
                # Não usar conteúdo diferente para preparar um catálogo existente.
                with a.conectar_catalogo_fichas() as c:
                    canon=[]
                    for f in fichas:
                        row=c.execute('SELECT * FROM fichas_catalogo WHERE op=? AND lote=?',(f['op'],f['lote'])).fetchone()
                        if not row:raise ValueError(f"OP {f['op']} / lote {f['lote']} não está no catálogo salvo. Para alterar somente a liberação da sequência, use Lotes já cadastrados — permissão de sequência, no início desta tela, sem reenviar o PDF.")
                        canon.append(a.ficha_linha_para_dict(row))
                fichas=canon
            if not mescla:
                with a.conectar_banco_operacional() as c:
                    c.execute('BEGIN IMMEDIATE')
                    validar_datas(c,datas)
                    pend=m.preparar_lote(c,fichas,datas,a.LOGIN_APONTAMENTO,excecoes_dimensao)
                    for lote,liberado in liberacoes.items():
                        c.execute('INSERT INTO mes_opcoes(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor',('sequencia_livre_lote:'+lote,'1' if liberado else '0'))
                        m.auditoria(c,'politica_sequencia_lote',a.LOGIN_APONTAMENTO,dict(lote=lote,liberado=liberado,arquivo=arq.name))
                    if excecoes_dimensao:m.auditoria(c,'importacao_dimensao_zero',a.LOGIN_APONTAMENTO,dict(arquivo=arq.name,etapas=excecoes_dimensao,avisos=avisos_dimensao))
            with a.conectar_banco_operacional() as c:
                datas_salvas={}
                for lote in sorted(lotes):
                    for row in c.execute('SELECT op,etapa,data_programada FROM mes_programacao WHERE lote=?',(lote,)):
                        datas_salvas[(row['op'],int(row['etapa']))]=row['data_programada']
            conteudo=excel(fichas,datas,datas_salvas)
            pasta=Path(a.caminho_banco_operacional()).parent/'exportacoes';pasta.mkdir(exist_ok=True)
            caminho=pasta/f'programacao_{digest[:16]}.xlsx'
            caminho.write_bytes(conteudo)
            st.session_state['pdf_v6_resultado']=(digest,conteudo,pend)
        except Exception as exc:
            st.error(f'Processo não concluído: {exc}')
            st.info('Se o catálogo já foi salvo, escolha Preparar lote já importado para retomar a programação. Nenhum apontamento é apagado.')
    resultado=st.session_state.get('pdf_v6_resultado')
    if resultado and resultado[0]==digest:
        if not resultado[2]:
            st.success('Importação concluída. OPs preparadas para os operadores, conforme a opção de sequenciamento de cada lote. Excel gerado.')
        else:
            st.info('Importação salva. Confira abaixo as OPs com pendências de preparação.')
        st.download_button('Baixar Excel da importação',resultado[1],'programacao_importada.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        if resultado[2]:
            st.warning(f'{len(resultado[2])} avisos de preparação. Ajuste os vínculos em Estoque e prepare novamente o lote. Com controle de estoque ativo, OPs com insumos pendentes não podem iniciar.')
            st.dataframe({'Pendência':resultado[2]})
            st.download_button('Baixar pendências de materiais','\n'.join(resultado[2]).encode('utf-8-sig'),'pendencias_mp.txt','text/plain')


def consultar_historico_importacoes(c, busca='', limite=100):
    """O histórico é do catálogo; não presume que a preparação operacional terminou."""
    if limite not in (50,100,200,500):raise ValueError('Limite de consulta inválido.')
    where='';args=[]
    if busca.strip():
        termo=busca.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        where=" WHERE (i.arquivo LIKE ? ESCAPE '\\' OR i.lote_principal LIKE ? ESCAPE '\\')"
        args=['%'+termo+'%']*2
    total=c.execute('SELECT COUNT(*) FROM importacoes_catalogo i'+where,args).fetchone()[0]
    rows=c.execute("""SELECT i.id,i.arquivo,i.importado_em,i.fichas_importadas,i.lote_principal,
      a.modo,a.lotes_json,a.avisos_json
      FROM importacoes_catalogo i LEFT JOIN auditoria_importacoes a
      ON a.id=(SELECT MAX(x.id) FROM auditoria_importacoes x WHERE x.importacao_id=i.id)
      """+where+' ORDER BY i.id DESC LIMIT ?',[*args,limite]).fetchall()
    tipos={'importacao':'Importação de lote','substituicao':'Substituição de lote','correcao_quantidades':'Correção de quantidades por OP'}
    historico=[]
    for row in rows:
        r=dict(row)
        lotes=json.loads(r['lotes_json']) if r['lotes_json'] else []
        avisos=json.loads(r['avisos_json']) if r['avisos_json'] else []
        historico.append({'ID':r['id'],'Data e hora':r['importado_em'],
          'Lotes':', '.join(str(l) for l in lotes) if lotes else r['lote_principal'],
          'Arquivo':r['arquivo'],'OPs registradas':r['fichas_importadas'],
          'Tipo':tipos.get(r['modo'],'Importação legada'),'Avisos':len(avisos),
          '_avisos':avisos})
    return total,historico


def historico_importacoes(a):
    from j2i_industrial_ui import csv_bytes
    a.inicializar_catalogo_fichas()
    st.divider()
    st.subheader('Histórico de importação dos lotes')
    st.caption('Importações e substituições gravadas no catálogo, da mais recente para a mais antiga. A preparação de um lote já importado não cria uma nova importação. Este histórico não confirma, por si só, a liberação para produção.')
    with st.form('filtros_historico_importacoes'):
        busca=st.text_input('Buscar lote ou nome do arquivo')
        limite=st.selectbox('Quantidade de registros para exibir',[50,100,200,500],index=1)
        st.form_submit_button('Consultar / atualizar histórico')
    with a.conectar_catalogo_fichas() as c:
        total,rows=consultar_historico_importacoes(c,busca,limite)
    if not rows:
        st.info('Nenhuma importação encontrada.' if busca.strip() else 'Ainda não há lotes importados neste banco.')
        return
    tabela=[{k:v for k,v in r.items() if k!='_avisos'} for r in rows]
    st.caption(f'Exibindo {len(rows)} de {total} registros encontrados. A quantidade de OPs representa cada evento; uma substituição pode incluir as mesmas OPs novamente.')
    st.dataframe(tabela,use_container_width=True,hide_index=True)
    st.download_button('Baixar histórico exibido (CSV)',csv_bytes(tabela),'historico_importacoes_lotes.csv','text/csv')
    with st.expander('Consultar avisos de uma importação'):
        por_id={r['ID']:r for r in rows}
        escolhido=st.selectbox('Importação',list(por_id),format_func=lambda i:f"{i} — {por_id[i]['Data e hora']} — lote(s) {por_id[i]['Lotes']} — {por_id[i]['Arquivo']}")
        avisos=por_id[escolhido]['_avisos']
        if avisos:
            st.dataframe({'Aviso':avisos},use_container_width=True,hide_index=True)
            st.download_button('Baixar avisos desta importação','\n'.join(avisos).encode('utf-8-sig'),f'avisos_importacao_{escolhido}.txt','text/plain')
        else:st.info('Nenhum aviso registrado nesta importação.')


def renderizar(a):
    _renderizar_importacao(a)
    historico_importacoes(a)


def corrigir_quantidades_paletes(a, fichas_pdf, arquivo, excecoes_dimensao=()):
    """Correção explícita, restrita a quantidades e OPs sem qualquer apontamento."""
    if len({f['op'] for f in fichas_pdf})!=len(fichas_pdf):raise ValueError('PDF contém OP repetida.')
    canon=[];alteradas=[];preservadas=[]
    with a.conectar_banco_operacional() as operacional:
        operacional.execute('BEGIN IMMEDIATE')
        with a.conectar_catalogo_fichas() as catalogo:
            catalogo.execute('BEGIN IMMEDIATE')
            # Valida o lote inteiro antes de qualquer alteração.
            for nova in fichas_pdf:
                row=catalogo.execute('SELECT * FROM fichas_catalogo WHERE op=?',(nova['op'],)).fetchone()
                if not row or a.normalizar_lote(row['lote'])!=a.normalizar_lote(nova['lote']):
                    raise ValueError(f"OP {nova['op']}: não encontrada neste lote. Importe primeiro o lote.")
                antiga=a.ficha_linha_para_dict(row)
                if str(antiga['medida']).strip()!=str(nova['medida']).strip() or str(antiga['descricao_peca']).strip()!=str(nova['descricao_peca']).strip():
                    raise ValueError(f"OP {nova['op']}: peça/medida divergente; correção de quantidade cancelada.")
                qtd=float(m.numero(nova['quantidade_produzir']))
                if qtd<=0:raise ValueError('Quantidade da OP deve ser positiva.')
                iniciada=operacional.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? LIMIT 1',(nova['op'],)).fetchone()
                if iniciada:
                    if antiga['quantidade_produzir']!=qtd:
                        preservadas.append(f"OP {nova['op']}: já possui apontamento; quantidade atual {antiga['quantidade_produzir']:g}, quantidade do palete no PDF {qtd:g}. Histórico e baixas não foram alterados.")
                else:
                    if antiga['quantidade_produzir']!=qtd:
                        alteradas.append({'op':nova['op'],'antes':antiga['quantidade_produzir'],'depois':qtd})
                    antiga['quantidade_produzir']=qtd
                    antiga['quantidade_material']=qtd
                canon.append((antiga,bool(iniciada)))
            for f,iniciada in canon:
                if iniciada:continue
                catalogo.execute('UPDATE fichas_catalogo SET quantidade_produzir=?,quantidade_material=? WHERE op=?',(f['quantidade_produzir'],f['quantidade_material'],f['op']))
                operacional.execute('UPDATE mes_programacao SET quantidade=?,versao=versao+1 WHERE op=? AND quantidade<>?',(f['quantidade_produzir'],f['op'],f['quantidade_produzir']))
                # Retira a liberação antiga até o recálculo automático terminar.
                operacional.execute('DELETE FROM mes_revisao_mp WHERE op=?',(f['op'],))
            if alteradas:
                lotes=sorted({f['lote'] for f,_ in canon})
                cur=catalogo.execute('INSERT INTO importacoes_catalogo(arquivo,importado_em,fichas_importadas,lote_principal) VALUES(?,?,?,?)',(arquivo,a.agora_iso(),len(alteradas),', '.join(lotes)))
                catalogo.execute('INSERT INTO auditoria_importacoes(importacao_id,modo,lotes_json,avisos_json,anterior_json) VALUES(?,?,?,?,?)',(cur.lastrowid,'correcao_quantidades',json.dumps(lotes),json.dumps(preservadas,ensure_ascii=False),json.dumps(alteradas)))
                m.auditoria(operacional,'correcao_quantidades_paletes',a.LOGIN_APONTAMENTO,{'alteradas':alteradas,'preservadas':preservadas})
        # Recalcula na mesma transação operacional; usa datas e métricas já congeladas.
        for f,iniciada in canon:
            if iniciada:continue
            planos=operacional.execute('SELECT p.data_programada,e.codigo FROM mes_programacao p JOIN equipamentos e ON e.id=p.equipamento_id WHERE p.op=?',(f['op'],)).fetchall()
            datas={str(r['codigo']).lstrip('0'):r['data_programada'] for r in planos}
            for rota in f['rotas']:datas.setdefault(str(rota['codigo_equipamento']).lstrip('0'),date.today().isoformat())
            m.preparar_lote(operacional,[f],datas,a.LOGIN_APONTAMENTO,excecoes_dimensao)
    if preservadas:st.warning('Algumas OPs já possuem apontamentos e foram preservadas.');st.dataframe({'Conferir':preservadas})
    st.info(f'{len(alteradas)} OPs tiveram a quantidade corrigida. As etapas das OPs não iniciadas foram recalculadas.')
    return [f for f,_ in canon]



def salvar_permissao_lote(a,lote,liberado,esperado):
    """Altera somente a política, sem preparar, importar ou recalcular a OP."""
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        with a.conectar_catalogo_fichas() as cat:
            if not cat.execute('SELECT 1 FROM fichas_catalogo WHERE lote=? LIMIT 1',(lote,)).fetchone():
                raise ValueError('Lote não encontrado no catálogo. Atualize a página.')
        chave='sequencia_livre_lote:'+str(lote)
        row=c.execute('SELECT valor FROM mes_opcoes WHERE chave=?',(chave,)).fetchone()
        atual=row['valor'] if row else '0'
        if atual!=esperado:
            raise ValueError('Outro usuário alterou a permissão deste lote. Atualize a página e confira antes de salvar.')
        novo='1' if liberado else '0'
        c.execute('INSERT INTO mes_opcoes(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor',(chave,novo))
        m.auditoria(c,'politica_sequencia_lote',a.LOGIN_APONTAMENTO,dict(lote=lote,liberado=liberado,antes=atual,origem='ajuste_lote_existente'))


def permissao_lotes_existentes(a):
    with st.expander('Lotes já cadastrados — permissão de sequência',expanded=True):
        st.caption('Altere a permissão sem reenviar PDF. Não modifica roteiros, datas, quantidades, apontamentos ou estoque.')
        with a.conectar_catalogo_fichas() as c:
            lotes=[r[0] for r in c.execute("SELECT DISTINCT lote FROM fichas_catalogo WHERE lote IS NOT NULL AND lote<>'' ORDER BY lote DESC")]
        if not lotes:
            st.info('Nenhum lote cadastrado.');return
        lote=st.selectbox('Lote cadastrado',lotes,index=None,placeholder='Selecione ou pesquise o lote',key='permissao_lote_existente')
        if lote is None:return
        with a.conectar_banco_operacional() as c:
            row=c.execute('SELECT valor FROM mes_opcoes WHERE chave=?',('sequencia_livre_lote:'+str(lote),)).fetchone()
        atual=row['valor'] if row else '0'
        st.info('Situação atual: '+('processos posteriores liberados sem conclusão dos anteriores.' if atual=='1' else 'exige a conclusão dos processos anteriores.'))
        with st.form('permissao_existente_'+str(lote)+'_'+atual):
            liberar=st.checkbox('Permitir apontar sem concluir os processos anteriores',value=atual=='1')
            st.caption('Sem conclusão anterior, usa a quantidade original da OP. Estoque e duplicidade continuam validados. Desmarcar volta a exigir a sequência nas novas aberturas.')
            gravar=st.form_submit_button('Salvar permissão deste lote',type='primary')
        if gravar:
            try:
                salvar_permissao_lote(a,lote,liberar,atual)
                st.session_state['permissao_lote_salva']=str(lote)
                st.rerun()
            except ValueError as exc:st.error(str(exc))
        if st.session_state.pop('permissao_lote_salva',None)==str(lote):st.success('Permissão do lote '+str(lote)+' salva. Os operadores já podem usar a nova regra.')
