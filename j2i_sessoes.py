"""Uma sessão de operação por equipamento, com lease validada no servidor."""
import secrets
import time
import streamlit as st

DURACAO=180


def esquema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS mes_sessoes_operador (
        equipamento_id INTEGER PRIMARY KEY REFERENCES equipamentos(id),
        token TEXT NOT NULL, expira REAL NOT NULL)''')


def adquirir(c, equipamento_id, agora=None):
    agora=time.time() if agora is None else agora
    esquema(c)
    token=secrets.token_urlsafe(32)
    cur=c.execute('''INSERT INTO mes_sessoes_operador VALUES(?,?,?)
        ON CONFLICT(equipamento_id) DO UPDATE SET token=excluded.token,expira=excluded.expira
        WHERE mes_sessoes_operador.expira<=?''',(equipamento_id,token,agora+DURACAO,agora))
    if cur.rowcount!=1:
        raise ValueError('Este usuário já está em uso em outra sessão. Saia pelo botão Sair do equipamento no outro acesso. Se ele foi fechado, aguarde até 3 minutos e tente novamente.')
    return token


def validar(c, equipamento_id, token, agora=None, renovar=False):
    agora=time.time() if agora is None else agora
    esquema(c)
    r=c.execute('SELECT token,expira FROM mes_sessoes_operador WHERE equipamento_id=?',(equipamento_id,)).fetchone()
    if not token or not r or not secrets.compare_digest(str(r[0]),str(token)):
        raise ValueError('Sua sessão de operação expirou ou não é mais válida. Entre novamente antes de apontar.')
    # Inatividade da aba não revoga o token. Ele só perde validade ao sair
    # ou quando outro login adquire a concessão vencida. CAS evita duas posses.
    if (renovar or r[1]<=agora) and r[1]<agora+DURACAO-25:
        cur=c.execute('UPDATE mes_sessoes_operador SET expira=? WHERE equipamento_id=? AND token=?',(agora+DURACAO,equipamento_id,token))
        if cur.rowcount!=1:raise ValueError('Este equipamento foi conectado em outra sessão. Entre novamente.')


def liberar(c, equipamento_id, token):
    esquema(c)
    c.execute('DELETE FROM mes_sessoes_operador WHERE equipamento_id=? AND token=?',(equipamento_id,token or ''))


def validar_operacao(c, equipamento_id):
    # Chamadas internas de scripts/testes não são sessões web. Toda gravação web
    # valida a posse da sessão dentro da transação que grava produção/estoque.
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx(suppress_warning=True) is None:return
    if st.session_state.get('operador_equipamento_id')!=equipamento_id:
        raise ValueError('Entre com o usuário deste equipamento para apontar.')
    validar(c,equipamento_id,st.session_state.get('operador_token'),renovar=True)


def limpar():
    for k in list(st.session_state):
        if k.startswith(('operador_','op_')):del st.session_state[k]


@st.fragment(run_every=30)
def manter(a, equipamento_id):
    try:
        with a.conectar_banco_operacional() as c:
            c.execute('BEGIN IMMEDIATE')
            validar(c,equipamento_id,st.session_state.get('operador_token'),renovar=True)
    except ValueError:
        limpar()
        st.rerun()
