"""Correção restrita das dimensões ausentes, por OP e lote, com auditoria."""
import hashlib
import json
import math
import re
import sqlite3
import logging
import streamlit as st

NOMES = ('Comprimento', 'Largura', 'Espessura')

def dimensoes(medida):
    partes = re.split(r'[/xX×;]', str(medida or '').strip())
    saida = []
    for i in range(3):
        texto = partes[i].strip() if i < len(partes) else ''
        try:
            v = float(texto.replace('.', '').replace(',', '.') if ',' in texto else texto)
            if not math.isfinite(v) or v < 0: v = None
        except ValueError: v = None
        saida.append((texto, v))
    return saida


def pendentes(a):
    with a.conectar_catalogo_fichas() as c:
        rows = [dict(r) for r in c.execute('SELECT op,lote,codigo_peca,descricao_peca,medida FROM fichas_catalogo ORDER BY lote,op')]
    return [r for r in rows if any(v is None or v == 0 for _, v in dimensoes(r['medida']))]


def contexto(c, op, lote):
    planos = [dict(r) for r in c.execute('SELECT * FROM mes_programacao WHERE op=? ORDER BY etapa', (op,))]
    if any(str(r['lote']) != str(lote) for r in planos):
        raise ValueError('A OP possui programação em outro lote. Confira o cadastro antes de corrigir.')
    unidades = set()
    for p in planos:
        regra = json.loads(p['regra_json'])
        if regra['tipo'] not in ('pecas', 'quantidade'):
            unidades.add(regra['dimensao'])
    if len(unidades) > 1:
        raise ValueError('As etapas desta OP usam unidades dimensionais diferentes (m/mm/cm). Uniformize a unidade em Métricas e Metas antes de corrigir a ficha compartilhada.')
    return planos, next(iter(unidades), None)


def revisao(a, op, lote):
    with a.conectar_banco_operacional() as c:
        planos, unidade = contexto(c, op, lote)
    return hashlib.sha256(json.dumps(planos, sort_keys=True).encode()).hexdigest(), unidade


def correcoes(a):
    with a.conectar_catalogo_fichas() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='auditoria_medidas_lote'").fetchone(): return []
        return [dict(r) for r in c.execute('''SELECT x.alterado_em AS Data,x.lote AS Lote,x.op AS OP,
            f.codigo_peca AS Código,f.descricao_peca AS Peça,x.anterior AS Anterior,x.nova AS Adicionada,
            f.medida AS Atual,x.unidade AS Unidade,x.usuario AS Responsável
            FROM auditoria_medidas_lote x LEFT JOIN fichas_catalogo f ON f.op=x.op AND f.lote=x.lote
            ORDER BY x.id DESC LIMIT 200''')]


def salvar(a, op, lote, medida_anterior, valores, versao, unidade):
    if not a.apontamento_autenticado():
        raise PermissionError('Entre com o acesso PPCP para corrigir medidas.')
    if unidade not in ('m', 'cm', 'mm'): raise ValueError('Informe a unidade dimensional da ficha.')
    if len(re.split(r'[/xX×;]', str(medida_anterior or '').strip())) > 3:
        raise ValueError('Formato da medida não reconhecido. Confira a ficha antes de corrigir.')
    antigos = dimensoes(medida_anterior)
    if len(valores) != 3: raise ValueError('Informe as três dimensões.')
    novos = []
    for (texto, velho), valor in zip(antigos, valores):
        try: v = float(valor)
        except (ValueError, TypeError): raise ValueError('Todas as medidas devem ser números positivos.')
        if not math.isfinite(v) or v <= 0: raise ValueError('Todas as medidas devem ser maiores que zero.')
        if velho is not None and velho > 0:
            if v != velho: raise ValueError('Medidas já preenchidas não podem ser alteradas nesta tela.')
            novos.append(texto)
        else: novos.append(format(v, '.12f').rstrip('0').rstrip('.').replace('.', ','))
    if all(v is not None and v > 0 for _, v in antigos): raise ValueError('Esta ficha não possui dimensões pendentes.')
    nova = '/'.join(novos)
    with a.conectar_banco_operacional() as c:
        c.execute('ATTACH DATABASE ? AS catalogo', (str(a.caminho_catalogo_fichas()),))
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT lote,medida FROM catalogo.fichas_catalogo WHERE op=?', (op,)).fetchone()
        if not row or str(row['lote']) != str(lote) or row['medida'] != medida_anterior:
            raise ValueError('A ficha foi alterada por outro usuário. Atualize a tela antes de salvar.')
        planos, escala = contexto(c, op, lote)
        atual = hashlib.sha256(json.dumps(planos, sort_keys=True).encode()).hexdigest()
        if atual != versao: raise ValueError('A programação foi alterada. Atualize a tela antes de salvar.')
        if escala and escala != unidade: raise ValueError('A unidade informada diverge das métricas desta OP.')
        if any(p['medida'] != medida_anterior for p in planos):
            raise ValueError('As medidas da programação divergem da ficha. Confira a importação antes de corrigir.')
        c.execute('''CREATE TABLE IF NOT EXISTS catalogo.auditoria_medidas_lote (
            id INTEGER PRIMARY KEY, op TEXT NOT NULL, lote TEXT NOT NULL, anterior TEXT,
            nova TEXT NOT NULL, unidade TEXT NOT NULL, usuario TEXT NOT NULL, alterado_em TEXT NOT NULL)''')
        c.execute('UPDATE catalogo.fichas_catalogo SET medida=? WHERE op=? AND lote=?', (nova, op, lote))
        # Somente a dimensão e o controle de revisão; não recalcular produção histórica.
        c.execute('UPDATE mes_programacao SET medida=?,versao=versao+1 WHERE op=? AND lote=?', (nova, op, lote))
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_importacao_contexto'").fetchone():
            ctx = c.execute('SELECT lote,ficha_json FROM mes_importacao_contexto WHERE op=?', (op,)).fetchone()
            if ctx:
                if str(ctx['lote']) != str(lote): raise ValueError('Lote divergente no contexto de importação.')
                ficha = json.loads(ctx['ficha_json']); ficha['medida'] = nova
                c.execute('UPDATE mes_importacao_contexto SET ficha_json=? WHERE op=?', (json.dumps(ficha, ensure_ascii=False), op))
        c.execute('INSERT INTO catalogo.auditoria_medidas_lote(op,lote,anterior,nova,unidade,usuario,alterado_em) VALUES(?,?,?,?,?,?,?)',
                  (op,lote,medida_anterior,nova,unidade,a.LOGIN_APONTAMENTO,a.agora_iso()))
    # Cache de medidas de relatórios antigos; não invalida dados de outras telas.
    cache = getattr(a, 'carregar_medidas_catalogo_cacheado', None)
    if cache is not None:
        try: cache.clear()
        except Exception: logging.exception('Medidas salvas; falha ao limpar cache legado')
    return nova


def tela(a):
    st.title('Peças com medidas zeradas')
    if not a.apontamento_autenticado():
        a.renderizar_login_apontamento(); return
    st.caption('Corrija as dimensões ausentes ou zeradas de uma OP dentro do lote. Medidas positivas ficam bloqueadas.')
    if 'medidas_recibo' in st.session_state: st.success(st.session_state.pop('medidas_recibo'))
    with st.expander('Medidas adicionadas — últimas 200 correções'):
        historico = correcoes(a)
        if historico: st.dataframe(historico, hide_index=True, use_container_width=True)
        else: st.caption('Nenhuma correção registrada por esta tela.')
    if st.button('Atualizar lista'): st.rerun()
    rows = pendentes(a)
    if not rows: st.success('Nenhuma peça com medidas pendentes.'); return
    st.metric('OPs com dimensões pendentes', len(rows))
    lotes = sorted({str(r['lote'] or '') for r in rows})
    lote = st.selectbox('Lote', lotes, format_func=lambda x: x or '(Sem lote)')
    filtro = st.text_input('Buscar OP, código ou descrição da peça').strip().casefold()
    rows = [r for r in rows if str(r['lote'] or '') == lote and (not filtro or filtro in ' '.join(str(r[k] or '') for k in ('op','codigo_peca','descricao_peca')).casefold())]
    st.dataframe([{'OP':r['op'],'Lote':r['lote'],'Código da peça':r['codigo_peca'],'Peça':r['descricao_peca'],
                   'Medida atual':r['medida'],'Dimensões pendentes':', '.join(NOMES[i] for i,(_,v) in enumerate(dimensoes(r['medida'])) if v is None or v==0)} for r in rows], hide_index=True, use_container_width=True)
    if not rows: st.info('Nenhuma peça encontrada com esse filtro.'); return
    op = st.selectbox('OP para corrigir', [r['op'] for r in rows], format_func=lambda op: next(f"{r['op']} — {r['descricao_peca']}" for r in rows if r['op']==op))
    row = next(r for r in rows if r['op']==op)
    if not lote: st.warning('Cadastre o lote desta ficha antes de corrigir as medidas.'); return
    try: versao, unidade = revisao(a, op, lote)
    except (ValueError, KeyError, json.JSONDecodeError) as e: st.error(str(e)); return
    st.info('As medidas da ficha e da programação serão corrigidas. Produção já registrada e sessões já abertas mantêm os valores originais; novos apontamentos usarão a ficha corrigida. Não há alteração de quantidades, horários, roteiros ou estoque.')
    chave = hashlib.sha256(f"{op}|{lote}|{row['medida']}|{versao}".encode()).hexdigest()[:16]
    with st.form('medidas_'+chave):
        escala = st.selectbox('Unidade das medidas da ficha', ['m','cm','mm'], index=['m','cm','mm'].index(unidade or 'm'), disabled=unidade is not None,
                             help='Use a mesma unidade das métricas do equipamento. Exemplo: 1200 mm = 1,2 m.')
        valores = [st.number_input(nome, min_value=0.0, value=float(v or 0), step=0.001, format='%.6f', disabled=v is not None and v>0)
                   for nome,(_,v) in zip(NOMES,dimensoes(row['medida']))]
        confirma = st.checkbox(f'Conferi a peça, o lote {lote}, a OP {op} e a unidade das medidas.')
        enviado = st.form_submit_button('Salvar medidas e atualizar indicadores', type='primary')
    if enviado:
        if not confirma: st.error('Confira os dados e marque a confirmação antes de salvar.'); return
        try: nova = salvar(a, op, lote, row['medida'], valores, versao, escala)
        except (ValueError, PermissionError) as e: st.error(str(e)); return
        except Exception:
            logging.exception('Correção de medidas por lote')
            st.error('Não foi possível confirmar a gravação. Atualize a lista e confira a OP antes de tentar novamente.'); return
        st.session_state['medidas_recibo'] = f'✓ Medida adicionada — OP {op}, lote {lote}: {nova} {escala}. Ficha e programação atualizadas. A OP saiu das pendências; os indicadores programados considerarão a correção ao abrir ou atualizar o relatório. Produção já apontada preservada.'
        st.rerun()
