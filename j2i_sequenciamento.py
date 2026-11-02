"""Intertravamento de etapas. Validar dentro de BEGIN IMMEDIATE, antes do INSERT."""

def validar(a, conexao, equipamento_id, codigo):
    equipamento=conexao.execute('SELECT * FROM equipamentos WHERE id=?',(equipamento_id,)).fetchone()
    if equipamento is None:
        raise ValueError('Equipamento não encontrado no cadastro.')
    equipamento=dict(equipamento)
    with a.conectar_catalogo_fichas() as cat:
        linha=cat.execute('SELECT * FROM fichas_catalogo WHERE op=?',(codigo,)).fetchone()
        rotas=[dict(r) for r in cat.execute('SELECT * FROM rotas_catalogo WHERE op=? ORDER BY ordem_rota',(codigo,))]
    if linha is None or not rotas:
        raise ValueError('OP sem ficha ou roteiro importado. Solicite revisão ao PCP.')
    ficha=a.ficha_linha_para_dict(linha)
    lote=str(ficha.get('lote') or '').strip()
    if not lote:
        raise ValueError('OP sem lote definido no catálogo. Solicite revisão ao PCP.')
    registros=[dict(r) for r in conexao.execute('''SELECT *
        FROM ordens_operacionais WHERE ficha_op=? AND lote_identificado=?
        AND status IN ('ABERTA','FINALIZADA')''',(codigo,lote))]
    por_etapa={}
    for registro in registros:
        por_etapa.setdefault(registro['rota_ordem'],[]).append(registro)
    def cod(v): return str(v or '').strip().lstrip('0')
    candidatas=[r for r in rotas if cod(r['codigo_equipamento'])==cod(equipamento['codigo'])]
    if not candidatas:
        raise ValueError(f"OP {codigo}, lote {lote}: equipamento {equipamento['codigo']} não pertence ao roteiro.")
    from j2i_sessoes_producao import resumir
    estados = {etapa: resumir(rows) for etapa, rows in por_etapa.items()}
    for r in rotas:
        if any(cod(x['rota_codigo_equipamento']) != cod(r['codigo_equipamento'])
               for x in por_etapa.get(r['ordem_rota'], [])):
            raise ValueError('Equipamento do histórico diverge do roteiro. Solicite revisão ao PCP.')
    from j2i_encerramento_ppcp import fechadas
    manuais=fechadas(conexao)
    atual = next((r for r in candidatas if (codigo,lote,r['ordem_rota']) not in manuais and not estados.get(r['ordem_rota'], {}).get('concluida')), None)
    if atual is None:
        raise ValueError('Todas as passagens desta OP neste equipamento já foram finalizadas ou encerradas manualmente pelo PPCP.')
    referencia=rotas
    if conexao.execute("SELECT 1 FROM sqlite_master WHERE name='mes_importacao_contexto'").fetchone():
        import json
        ref=conexao.execute('SELECT ficha_json FROM mes_importacao_contexto WHERE op=?',(codigo,)).fetchone()
        if ref:
            referencia=[dict(r,ordem_rota=int(r['ordem'])) for r in json.loads(ref[0])['rotas']]
            por_ordem={r['ordem_rota']:r for r in referencia}
            por_ordem.update({r['ordem_rota']:r for r in rotas})
            referencia=[por_ordem[k] for k in sorted(por_ordem)]
    from j2i_industrial import opcao
    livre = bool(opcao(conexao, 'sequencia_livre_lote:'+lote))
    for anterior in ([] if livre else referencia):
        if anterior['ordem_rota'] >= atual['ordem_rota']: break
        if not estados.get(anterior['ordem_rota'], {}).get('concluida'):
            raise ValueError(f"OP {codigo}, lote {lote} bloqueada: finalize o saldo da etapa {anterior['ordem_rota']} — {anterior['equipamento']}.")
    estado = estados.get(atual['ordem_rota'])
    if estado and estado['aberta']:
        raise ValueError('Esta passagem da OP já está aberta. Atualize a tela.')
    anteriores = [r for r in referencia if r['ordem_rota'] < atual['ordem_rota']]
    precedente = estados.get(anteriores[-1]['ordem_rota']) if anteriores else None
    ficha['quantidade_liberada'] = (estado['saldo'] if estado else
        precedente['boas'] if precedente and precedente['concluida'] else ficha['quantidade_produzir'])
    if livre:
        from j2i_industrial import auditoria
        auditoria(conexao,'apontamento_sequencia_livre',equipamento['usuario'],
                  dict(op=codigo,lote=lote,etapa=atual['ordem_rota']))
    if ficha['quantidade_liberada'] <= 0:
        raise ValueError('Não há peças boas liberadas pela etapa anterior. PCP deve revisar a OP.')
    return equipamento,ficha,atual
