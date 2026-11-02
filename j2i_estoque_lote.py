"""Importação sequencial de até quatro posições, uma transação por arquivo."""
import hashlib
import streamlit as st
import j2i_industrial as m


def ler_arquivos(arquivos):
    if not 1<=len(arquivos)<=4:raise ValueError('Selecione de 1 a 4 arquivos.')
    from j2i_pdf_industrial import estoque
    from j2i_industrial_ui import ler_estoque
    from types import SimpleNamespace
    saida=[]
    for nome,dados in arquivos:
        item=dict(nome=nome,hash=hashlib.sha256(dados).hexdigest())
        try:
            item['linhas']=estoque(dados) if nome.lower().endswith('.pdf') else ler_estoque(SimpleNamespace(name=nome,getvalue=lambda:dados))
            if not item['linhas']:raise ValueError('Arquivo sem insumos.')
        except Exception as exc:item['erro']=str(exc)
        saida.append(item)
    return saida


def aplicar(a,itens,revisoes):
    if not 1<=len(itens)<=4:raise ValueError('Selecione de 1 a 4 arquivos.')
    esperado=dict(revisoes);resultado=[]
    for i,item in enumerate(itens):
        try:
            if item.get('erro'):raise ValueError(item['erro'])
            with a.conectar_banco_operacional() as c:
                c.execute('BEGIN IMMEDIATE')
                if c.execute('SELECT 1 FROM mes_importacoes_estoque WHERE hash=?',(item['hash'],)).fetchone():
                    resultado.append({'Arquivo':item['nome'],'Resultado':'Já importado; ignorado'});continue
                m.importar_saldos(c,item['linhas'],item['nome'],item['hash'],a.LOGIN_APONTAMENTO,esperado)
                for linha in item['linhas']:
                    codigo=str(linha['codigo']).strip()
                    esperado[codigo]=c.execute('SELECT versao FROM mes_insumos WHERE codigo=?',(codigo,)).fetchone()[0]
            resultado.append({'Arquivo':item['nome'],'Resultado':'Importado'})
        except Exception as exc:
            resultado.append({'Arquivo':item['nome'],'Resultado':'Não importado: '+str(exc)})
            resultado.extend({'Arquivo':r['nome'],'Resultado':'Não processado; valide novamente'} for r in itens[i+1:]);break
    return resultado


@st.fragment(run_every=2)
def acompanhar():
    job=st.session_state.get('estoque_lote_job')
    if not job:return
    chave,fut,revisoes=job
    if not fut.done():
        st.info('Lendo os arquivos, um por vez. Aguarde a conferência.');return
    try:st.session_state['estoque_lote_previa']=(chave,fut.result(),revisoes)
    except Exception as exc:st.session_state['estoque_lote_erro']=str(exc)
    del st.session_state['estoque_lote_job'];st.rerun()


def renderizar(a):
    arquivos=st.file_uploader('Selecione até 4 arquivos de estoque (PDF ou CSV)',type=['pdf','csv'],accept_multiple_files=True,key='estoque_arquivos')
    if st.session_state.get('estoque_lote_resultado'):
        st.dataframe(st.session_state['estoque_lote_resultado'],hide_index=True,use_container_width=True)
    if st.session_state.get('estoque_lote_job'):acompanhar()
    if st.session_state.get('estoque_lote_erro'):st.error(st.session_state.pop('estoque_lote_erro'))
    if not arquivos:return
    if len(arquivos)>4:
        st.error('O limite é quatro arquivos. Remova os excedentes.');return
    conteudos=[(f.name,f.getvalue()) for f in arquivos]
    chave=hashlib.sha256(repr([(n,hashlib.sha256(b).hexdigest()) for n,b in conteudos]).encode()).hexdigest()
    st.caption('A ordem abaixo é a ordem de leitura e gravação. Cada arquivo substitui o saldo dos seus insumos; não soma posições de estoque.')
    st.dataframe([{'Ordem':i+1,'Arquivo':f.name} for i,f in enumerate(arquivos)],hide_index=True)
    if st.button('Validar arquivos e visualizar',disabled=bool(st.session_state.get('estoque_lote_job'))):
        with a.conectar_banco_operacional() as c:
            revisoes={r['codigo']:r['versao'] for r in c.execute('SELECT codigo,versao FROM mes_insumos')}
        from j2i_importacao_v6 import pool
        st.session_state.pop('estoque_lote_previa',None)
        st.session_state['estoque_lote_job']=(chave,pool().submit(ler_arquivos,conteudos),revisoes)
        st.rerun()
    previa=st.session_state.get('estoque_lote_previa')
    if not previa or previa[0]!=chave:return
    itens=previa[1];vistos=set();repetidos=set();erros=False
    with a.conectar_banco_operacional() as c:
        importados={r[0] for r in c.execute('SELECT hash FROM mes_importacoes_estoque')}
    hashes=set()
    for i,item in enumerate(itens):
        with st.expander(f"{i+1}. {item['nome']}",expanded=bool(item.get('erro'))):
            if item.get('erro'):st.error(item['erro']);erros=True;continue
            st.dataframe(item['linhas'],use_container_width=True,hide_index=True)
            if item['hash'] in importados or item['hash'] in hashes:st.info('Conteúdo já importado ou repetido nesta seleção: será ignorado.');continue
            hashes.add(item['hash'])
            codigos={str(l['codigo']).strip() for l in item['linhas']}
            repetidos.update(codigos & vistos);vistos.update(codigos)
    if erros:
        st.error('Corrija ou remova os arquivos com erro e valide novamente.');return
    aceita_repetidos=True
    if repetidos:
        st.warning('Há insumos presentes em mais de um arquivo. Para esses códigos, valerá o saldo do último arquivo importado na ordem acima.')
        st.dataframe({'Código repetido':sorted(repetidos)},hide_index=True)
        aceita_repetidos=st.checkbox('Confirmo que o último arquivo deve substituir os saldos repetidos.',key='rep_'+chave)
    confirma=st.checkbox('Conferi e confirmo os saldos dos arquivos como posição atual.',key='pos_'+chave)
    if st.button('Aplicar posições em sequência',disabled=not(confirma and aceita_repetidos)):
        with st.spinner('Gravando um arquivo por vez...'):
            resultado=aplicar(a,itens,previa[2])
        st.session_state['estoque_lote_resultado']=resultado
        st.session_state.pop('estoque_lote_previa',None)
        st.rerun()
    st.caption('Cada arquivo é gravado por inteiro. Se ocorrer um erro, os anteriores permanecem salvos e os seguintes não são processados. Valide novamente para retomar; arquivos já importados serão ignorados.')
