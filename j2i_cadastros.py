"""Unidades e metas persistentes por equipamento, com controle de edição concorrente."""
import math
import sqlite3
import streamlit as st

UNIDADES=['uni','m linear','M²']
PERIODOS=['Hora','Turno','Dia']

def criar_tabelas(c):
    c.execute('''CREATE TABLE IF NOT EXISTS configuracao_equipamentos (
        equipamento_id INTEGER PRIMARY KEY REFERENCES equipamentos(id),
        unidade TEXT NOT NULL CHECK(unidade IN ('uni','m linear','M²')),
        meta REAL NOT NULL CHECK(meta>=0), periodo TEXT NOT NULL CHECK(periodo IN ('Hora','Turno','Dia')),
        versao INTEGER NOT NULL, atualizado_em TEXT NOT NULL, atualizado_por TEXT NOT NULL)''')

def listar(a):
    with a.conectar_banco_operacional() as c:
        return [dict(r) for r in c.execute('''SELECT e.id, e.codigo, e.maquina, e.setor, e.usuario,
            cfg.unidade, cfg.meta, cfg.periodo, COALESCE(cfg.versao,0) AS versao, cfg.atualizado_em
            FROM equipamentos e LEFT JOIN configuracao_equipamentos cfg ON cfg.equipamento_id=e.id
            WHERE e.ativo=1 ORDER BY CAST(e.codigo AS INTEGER),e.id''')]

def salvar(a, equipamento_id, unidade, meta, periodo, versao):
    if unidade not in UNIDADES or periodo not in PERIODOS or not math.isfinite(float(meta)) or float(meta)<0:
        raise ValueError('Unidade, período ou valor da meta inválidos.')
    with a.conectar_banco_operacional() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM equipamentos WHERE id=? AND ativo=1',(equipamento_id,)).fetchone():
            raise ValueError('Equipamento não está ativo.')
        atual=c.execute('SELECT versao FROM configuracao_equipamentos WHERE equipamento_id=?',(equipamento_id,)).fetchone()
        if (atual[0] if atual else 0)!=versao:
            raise ValueError('Outro usuário alterou este cadastro. Atualize a tela antes de salvar.')
        c.execute('''INSERT INTO configuracao_equipamentos
            (equipamento_id,unidade,meta,periodo,versao,atualizado_em,atualizado_por) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(equipamento_id) DO UPDATE SET unidade=excluded.unidade,meta=excluded.meta,
            periodo=excluded.periodo,versao=excluded.versao,atualizado_em=excluded.atualizado_em,atualizado_por=excluded.atualizado_por''',
            (equipamento_id,unidade,float(meta),periodo,versao+1,a.agora_iso(),a.LOGIN_APONTAMENTO))
    unidades_por_codigo.clear()

@st.cache_data(ttl=10,show_spinner=False)
def unidades_por_codigo(caminho):
    # Leitura por arquivo explícito; não inicializa banco durante relatórios antigos.
    from pathlib import Path
    p=Path(caminho)
    if not p.exists():return {}
    with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='configuracao_equipamentos'").fetchone():return {}
        linhas=c.execute('''SELECT e.codigo,cfg.unidade FROM equipamentos e JOIN configuracao_equipamentos cfg
            ON cfg.equipamento_id=e.id WHERE e.ativo=1''').fetchall()
    return {str(c).lstrip('0'):u for c,u in linhas}

def tela(a):
    st.title('Unidades e metas por equipamento')
    st.caption('Defina a unidade dos indicadores e a meta por hora, turno ou dia. Meta zero significa sem meta cadastrada.')
    registros=listar(a)
    if not registros:st.info('Não há equipamentos ativos.');return
    eqid=st.selectbox('Equipamento', [r['id'] for r in registros],format_func=lambda i:next(r['maquina'] for r in registros if r['id']==i))
    eq=next(r for r in registros if r['id']==eqid)
    padrao=eq['unidade'] or a.unidade_metrica_linha(eq['setor'],eq['maquina'])[0]
    st.caption(f"Setor: {eq['setor']} · Login: {eq['usuario']}")
    # Chave/versionamento vinculam os valores editados à revisão exibida.
    chave=f"config_{eqid}_{eq['versao']}"
    with st.form(chave):
        unidade=st.selectbox('Unidade de medida',UNIDADES,index=UNIDADES.index(padrao),format_func=lambda v:{'uni':'Unidades / peças','m linear':'Metros lineares','M²':'Metros quadrados (m²)'}[v])
        meta=st.number_input('Meta de produção',min_value=0.0,value=float(eq['meta'] or 0),step=1.0)
        periodo=st.selectbox('Período da meta',PERIODOS,index=PERIODOS.index(eq['periodo'] or 'Dia'))
        confirmar=st.form_submit_button('Salvar unidade e meta',type='primary')
    if confirmar:
        try:salvar(a,eqid,unidade,meta,periodo,eq['versao']);st.session_state['cfg_salvo']='Unidade e meta salvas.';st.rerun()
        except ValueError as exc:st.error(str(exc))
    if st.session_state.get('cfg_salvo'):st.success(st.session_state.pop('cfg_salvo'))
    st.caption('m² e metros lineares usam as dimensões da peça nos indicadores existentes. Quantidades de OP, sucata e retrabalho continuam em peças. As metas antigas por setor permanecem separadas deste cadastro por equipamento.')
    st.subheader('Cadastro completo')
    dados=[]
    for r in registros:
        u=r['unidade'] or a.unidade_metrica_linha(r['setor'],r['maquina'])[0]
        dados.append({'Código':r['codigo'],'Equipamento':r['maquina'],'Setor':r['setor'],'Unidade':u,
                      'Meta':r['meta'] or 0,'Período':r['periodo'] or 'Dia','Origem':'Cadastrada' if r['unidade'] else 'Padrão do sistema','Atualização':r['atualizado_em'] or ''})
    st.dataframe(dados,use_container_width=True,hide_index=True)


def lotes(a):
    with a.conectar_catalogo_fichas() as c:
        resumo=[dict(r) for r in c.execute('''SELECT COALESCE(NULLIF(lote,''),'Sem lote') AS Lote,
            COUNT(*) AS OPs, MIN(importado_em) AS "Primeira importação", MAX(importado_em) AS "Última importação",
            GROUP_CONCAT(DISTINCT fonte_arquivo) AS Arquivos
            FROM fichas_catalogo GROUP BY lote ORDER BY MAX(importado_em) DESC,lote''')]
        eventos=[dict(r) for r in c.execute('''SELECT arquivo AS Arquivo,importado_em AS Data,
            fichas_importadas AS "OPs inseridas",lote_principal AS "Lote principal"
            FROM importacoes_catalogo ORDER BY id DESC''')]
    st.subheader('Lotes já importados')
    st.caption(f"{len(resumo)} lote(s) · {sum(r['OPs'] for r in resumo)} OP(s) no catálogo")
    if resumo:st.dataframe(resumo,use_container_width=True,hide_index=True)
    else:st.info('Nenhum lote importado até o momento.')
    with st.expander('Histórico das importações'):
        if eventos:st.dataframe(eventos,use_container_width=True,hide_index=True)
        else:st.info('Sem eventos de importação registrados.')
