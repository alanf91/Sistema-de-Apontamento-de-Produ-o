"""Seleção central dos equipamentos ativos, sem excluir seus registros."""
import hashlib
import json
import streamlit as st
import j2i_industrial as m


def listar(c):
    return [dict(r) for r in c.execute('SELECT id,codigo,maquina,ativo FROM equipamentos ORDER BY maquina,id')]


def assinatura(rows):
    return hashlib.sha256(json.dumps([(r['id'],r['ativo']) for r in rows]).encode()).hexdigest()


def salvar(c,selecionados,versao,usuario):
    atuais=listar(c)
    if assinatura(atuais)!=versao:raise ValueError('O cadastro mudou em outro acesso. Atualize a tela antes de salvar.')
    ids={r['id'] for r in atuais};alvos=set(selecionados)
    if not alvos<=ids:raise ValueError('Equipamento não cadastrado.')
    for r in atuais:
        ativo=int(r['id'] in alvos)
        if ativo!=r['ativo']:c.execute('UPDATE equipamentos SET ativo=? WHERE id=?',(ativo,r['id']))
    m.auditoria(c,'selecao_equipamentos_ativos',usuario,dict(antes=[r['id'] for r in atuais if r['ativo']],depois=sorted(alvos)))


def renderizar(a):
    st.title('Equipamentos ativos no sistema')
    st.caption('Marque os equipamentos que devem aparecer nas telas e relatórios. Desmarcados ficam ocultos nos painéis e consultas, mas continuam aceitando login, importações, apontamentos e baixas de insumos. Cadastros e históricos são preservados.')
    st.warning('A seleção vale para todos os usuários. Etapas de lotes já importados não são removidas nem reordenadas; a sequência original continua valendo.')
    with a.conectar_banco_operacional() as c:rows=listar(c)
    if not rows:st.info('Cadastre os equipamentos em Equipamentos e Acessos.');return
    versao=assinatura(rows)
    dados=[{'Exibir':bool(r['ativo']),'ID':r['id'],'Código':r['codigo'],'Equipamento':r['maquina']} for r in rows]
    with st.form('equipamentos_ativos_form'):
        editado=st.data_editor(dados,hide_index=True,use_container_width=True,
            disabled=['ID','Código','Equipamento'],column_config={'ID':None},key='equipamentos_ativos_'+versao)
        confirmar=st.form_submit_button('Salvar equipamentos ativos',type='primary')
    if confirmar:
        try:
            with a.conectar_banco_operacional() as c:
                c.execute('BEGIN IMMEDIATE')
                salvar(c,[r['ID'] for r in editado if r['Exibir']],versao,a.LOGIN_APONTAMENTO)
            st.success('Seleção salva. As outras telas aplicam a seleção ao atualizar ou navegar.')
        except ValueError as exc:st.error(str(exc))
