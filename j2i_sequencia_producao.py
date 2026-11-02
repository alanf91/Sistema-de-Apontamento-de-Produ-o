"""Sequência sugerida por complexidade do roteiro, sem alterar apontamentos."""
from collections import defaultdict
from datetime import datetime
import io
import re
import zipfile
import streamlit as st


def nome_pdf_equipamento(registro):
    """Nome legível e seguro no Windows, com identificação única do equipamento."""
    def limpar(valor):
        return re.sub(r'\s+', ' ', re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(valor))).strip(' .')
    nome = limpar(registro['Equipamento'])[:100].rstrip(' .') or 'Equipamento'
    codigo = limpar(registro.get('Código equipamento') or registro['equipamento_id'])[:30]
    return f"Sequenciamento - {nome} - {codigo} - ID {int(registro['equipamento_id'])}.pdf"


def validar_lotes(lotes):
    if not 1<=len(lotes)<=2 or len(set(lotes))!=len(lotes):
        raise ValueError('Selecione um ou dois lotes diferentes para gerar a sequência.')


def montar(fichas,rotas,equipamentos,planos,registros,livres,manuais=frozenset(),referencias=None):
    eqs={str(e['codigo']).lstrip('0'):e for e in equipamentos if e['ativo']}
    por_op=defaultdict(list)
    for r in rotas:por_op[r['op']].append(r)
    from j2i_sessoes_producao import agrupar
    estados=agrupar(registros)
    datas_op={}
    for p in planos:
        if p.get('data_programada'):datas_op[p['op']]=min(datas_op.get(p['op'],'9999'),p['data_programada'])
    planos={(p['op'],p['etapa']):p for p in planos}
    abertas={(r['ficha_op'],r['equipamento_id']) for r in registros if r['status']=='ABERTA'}
    saida=[];ocultas=0
    for f in fichas:
        roteiro=sorted(por_op[f['op']],key=lambda r:r['ordem_rota'])
        referencia=(referencias or {}).get(f['op'],roteiro)
        por_ordem={r['ordem_rota']:r for r in referencia}
        por_ordem.update({r['ordem_rota']:r for r in roteiro})
        referencia=[por_ordem[k] for k in sorted(por_ordem)]
        for i,r in enumerate(roteiro):
            if (f['op'],f['lote'],r['ordem_rota']) in manuais:continue
            reg=estados.get((f['op'],f['lote'],r['ordem_rota']))
            if reg and reg['concluida']:continue
            eq=eqs.get(str(r['codigo_equipamento']).lstrip('0'))
            if not eq:ocultas+=1;continue
            anteriores=[p for p in referencia if p['ordem_rota']<r['ordem_rota'] and estados.get((f['op'],f['lote'],p['ordem_rota']),{}).get('concluida')!=True]
            em_aberta=reg and reg['aberta']
            mesma_op_aberta=(f['op'],eq['id']) in abertas
            if em_aberta:situacao='Em andamento'
            elif mesma_op_aberta:situacao='Aguardar passagem aberta desta OP'
            elif anteriores and f['lote'] not in livres:
                situacao='Aguardar etapa '+str(anteriores[0]['ordem_rota'])
                if str(anteriores[0]['codigo_equipamento']).lstrip('0') not in eqs:situacao+=' (equipamento oculto/ausente)'
            elif anteriores:situacao='Sequência liberada pelo lote'
            else:situacao='Liberada por sequência'
            precedentes=[p for p in referencia if p['ordem_rota']<r['ordem_rota']]
            anterior=estados.get((f['op'],f['lote'],precedentes[-1]['ordem_rota'])) if precedentes else None
            qtd=reg['saldo'] if reg else (anterior['boas'] if anterior and anterior['concluida'] else f['quantidade_produzir'])
            plano=planos.get((f['op'],r['ordem_rota']),{})
            saida.append({'equipamento_id':eq['id'],'Equipamento':eq['maquina'],'Código equipamento':eq['codigo'],
                'OP':f['op'],'Lote':f['lote'],'Peça':f['descricao_peca'],'Etapa':r['ordem_rota'],
                'Operação':r.get('operacao') or 'Processo cadastrado','Quantidade de peças':qtd,
                'Processos totais da OP':len(roteiro),'Data programada':plano.get('data_programada') or '',
                'Situação':situacao})
    # Maior roteiro primeiro; desempate determinístico, independente da ordem de seleção.
    saida.sort(key=lambda r:(r['Equipamento'],r['equipamento_id'],r['Situação']!='Em andamento',-r['Processos totais da OP'],datas_op.get(r['OP'],'9999'),r['Lote'],r['OP'],r['Etapa']))
    cont=defaultdict(int)
    for r in saida:
        cont[r['equipamento_id']]+=1;r['Sequência']=cont[r['equipamento_id']]
    return saida,ocultas


def consultar(a,lotes):
    validar_lotes(lotes)
    marks=','.join('?' for _ in lotes)
    # Mesma ordem de leitura usada no apontamento: operacional, depois catálogo.
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN')
        from j2i_encerramento_ppcp import fechadas
        manuais=fechadas(c)
        referencias={}
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_importacao_contexto'").fetchone():
            import json
            for ref in c.execute('SELECT op,ficha_json FROM mes_importacao_contexto'):
                referencias[ref['op']]=[dict(r,ordem_rota=int(r['ordem'])) for r in json.loads(ref['ficha_json'])['rotas']]
        eqs=[dict(r) for r in c.execute('SELECT id,codigo,maquina,ativo FROM equipamentos')]
        planos=[dict(r) for r in c.execute(f'SELECT * FROM mes_programacao WHERE lote IN ({marks})',lotes)]
        registros=[dict(r) for r in c.execute(f"SELECT * FROM ordens_operacionais WHERE lote_identificado IN ({marks}) AND status IN ('ABERTA','FINALIZADA')",lotes)]
        livres={l for l in lotes if c.execute("SELECT 1 FROM mes_opcoes WHERE chave=? AND valor='1'",('sequencia_livre_lote:'+l,)).fetchone()}
        with a.conectar_catalogo_fichas() as cat:
            cat.execute('BEGIN')
            fichas=[dict(r) for r in cat.execute(f'SELECT * FROM fichas_catalogo WHERE lote IN ({marks})',lotes)]
            rotas=[dict(r) for r in cat.execute(f'SELECT r.* FROM rotas_catalogo r JOIN fichas_catalogo f ON f.op=r.op WHERE f.lote IN ({marks}) ORDER BY r.op,r.ordem_rota',lotes)]
    rows,ocultas=montar(fichas,rotas,eqs,planos,registros,livres,manuais,referencias)
    return rows,dict(ops=len(fichas),ocultas=ocultas,gerado=a.agora_iso(),lotes=sorted(lotes))


def pdf_equipamento(rows,info):
    import fitz
    if not rows:raise ValueError('Não há etapas para este equipamento.')
    doc=fitz.open();larguras=[28,95,175,145,48,60,231]
    margem=30;pagina=None;y=0
    def linhas(texto,largura,tamanho=8):
        # Helvetica/WinAnsi: normaliza glifos não disponíveis, sem quebrar layout.
        texto=str(texto or '').encode('cp1252',errors='replace').decode('cp1252')
        partes=[]
        for paragrafo in texto.splitlines() or ['']:
            linha=''
            for palavra in paragrafo.split():
                candidato=(linha+' '+palavra).strip()
                if fitz.get_text_length(candidato,fontname='helv',fontsize=tamanho)<=largura-10:
                    linha=candidato;continue
                if linha:partes.append(linha);linha=''
                for letra in palavra:
                    if fitz.get_text_length(linha+letra,fontname='helv',fontsize=tamanho)>largura-10:
                        partes.append(linha);linha=''
                    linha+=letra
            partes.append(linha)
        return partes
    def nova():
        nonlocal pagina,y
        pagina=doc.new_page(width=842,height=595)
        pagina.insert_text((30,30),'J2I MES | SEQUENCIAMENTO DE PRODUCAO',fontsize=14,color=(.08,.23,.32))
        titulo=str(rows[0]['Código equipamento'])+' - '+rows[0]['Equipamento']
        for i,l in enumerate(linhas(titulo,782,11)):pagina.insert_text((30,49+i*13),l,fontsize=11)
        pagina.insert_text((30,78),'Lotes: '+', '.join(info['lotes'])+' | Gerado: '+info['gerado'],fontsize=9)
        pagina.insert_text((30,94),'Prioridade: em andamento; mais processos na OP; data programada; lote/OP; etapa.',fontsize=8)
        pagina.insert_text((30,107),'Ordem sugerida, sem horarios previstos. Conferir liberacao, saldo e quantidade no sistema antes de iniciar.',fontsize=8)
        y=120;x=30
        for cab,w in zip(['Seq.','OP / Lote','Peca','Etapa / Operacao','Pecas','Processos OP','Situacao'],larguras):
            pagina.draw_rect(fitz.Rect(x,y,x+w,y+24),color=None,fill=(.08,.23,.32))
            pagina.insert_text((x+4,y+15),cab,fontsize=8,color=(1,1,1));x+=w
        y+=24
    nova()
    for idx,r in enumerate(rows):
        valores=[r['Sequência'],r['OP']+'\nLote '+r['Lote'],r['Peça'],str(r['Etapa'])+' - '+r['Operação'],f"{r['Quantidade de peças']:g}",r['Processos totais da OP'],r['Situação']]
        celulas=[linhas(v,w) for v,w in zip(valores,larguras)]
        # Divide linhas excepcionalmente longas em continuação na próxima página.
        while any(celulas):
            disponiveis=int((545-y-10)//10)
            if disponiveis<1:nova();continue
            n=min(max(map(len,celulas)),disponiveis);h=n*10+10;x=30
            for ls,w in zip(celulas,larguras):
                pagina.draw_rect(fitz.Rect(x,y,x+w,y+h),color=(.82,.86,.88),fill=(.95,.97,.98) if idx%2==0 else (1,1,1),width=.4)
                for j,l in enumerate(ls[:n]):pagina.insert_text((x+4,y+12+j*10),l,fontsize=8)
                del ls[:n];x+=w
            y+=h
            if any(celulas):nova()
    for i,p in enumerate(doc):p.insert_text((30,578),f'Pagina {i+1} de {len(doc)} | Quantidades previstas podem mudar por sucata nas etapas anteriores.',fontsize=8,color=(.35,.4,.45))
    dados=doc.tobytes(garbage=4,deflate=True);doc.close();return dados


def renderizar(a):
    st.title('Sequenciamento de produção')
    st.caption('Prioridade pelas OPs com mais processos cadastrados. Cronograma por ordem de execução, sem estimativa de horários.')
    with a.conectar_catalogo_fichas() as c:
        lotes=[r[0] for r in c.execute("SELECT DISTINCT lote FROM fichas_catalogo WHERE lote IS NOT NULL AND lote<>'' ORDER BY lote DESC")]
    selecionados=st.multiselect('Selecione um ou dois lotes',lotes,max_selections=2,key='seq_lotes')
    gerar=st.button('Analisar lotes e gerar sequência',type='primary',disabled=not selecionados)
    if gerar:
        with st.spinner('Analisando roteiros e apontamentos...'):
            st.session_state['seq_resultado']=consultar(a,selecionados)
    resultado=st.session_state.get('seq_resultado')
    if not resultado or resultado[1]['lotes']!=sorted(selecionados):
        st.info('Selecione os lotes e clique em Analisar lotes e gerar sequência.');return
    rows,info=resultado
    # Evita exibir resultados guardados de equipamentos recém-desativados.
    with a.conectar_banco_operacional() as c:ativos={r[0] for r in c.execute('SELECT id FROM equipamentos WHERE ativo=1')}
    rows=[r for r in rows if r['equipamento_id'] in ativos]
    st.caption('Consulta gerada em '+info['gerado']+'. Gere novamente após novos apontamentos ou alterações no roteiro.')
    cs=st.columns(3);cs[0].metric('OPs analisadas',info['ops']);cs[1].metric('Etapas não concluídas',len(rows));cs[2].metric('Equipamentos',len({r['equipamento_id'] for r in rows}))
    st.info('Em andamento vem primeiro. Entre as demais OPs, o roteiro mais longo tem prioridade. Uma etapa que aguarda processo anterior só deve iniciar após sua liberação; enquanto isso, avalie a próxima liberada. Estoque e outras validações continuam na tela de operação.')
    if info['ocultas']:st.warning(f"Há {info['ocultas']} etapa(s) não concluída(s) em equipamentos ocultos/ausentes, fora das listas. Equipamentos ocultos continuam operando; a liberação das etapas segue a política do lote.")
    if not rows:st.success('Não há etapas pendentes ou em andamento nos equipamentos ativos para os lotes selecionados.');return
    eqs={r['equipamento_id']:r['Equipamento'] for r in rows}
    eq=st.selectbox('Equipamento',list(eqs),format_func=eqs.get)
    lista=[r for r in rows if r['equipamento_id']==eq]
    colunas=['Sequência','OP','Lote','Peça','Etapa','Operação','Quantidade de peças','Processos totais da OP','Data programada','Situação']
    st.dataframe([{k:r[k] for k in colunas} for r in lista],hide_index=True,use_container_width=True)
    st.download_button('Baixar PDF deste equipamento',pdf_equipamento(lista,info),nome_pdf_equipamento(lista[0]),'application/pdf')
    if st.button('Preparar PDFs de todos os equipamentos'):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
            for eid in eqs:
                itens=[r for r in rows if r['equipamento_id']==eid]
                z.writestr(nome_pdf_equipamento(itens[0]),pdf_equipamento(itens,info))
        st.download_button('Baixar todos os PDFs (ZIP)',buf.getvalue(),'sequencias_equipamentos.zip','application/zip')
    st.caption('Conta todos os processos do roteiro importado, inclusive passagens repetidas. Etapas finalizadas não são reprogramadas. A consulta não altera datas, OPs, estoque ou a política de sequenciamento do lote. Não é uma otimização de capacidade, setup ou prazo.')
