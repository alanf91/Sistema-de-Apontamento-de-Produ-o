"""Saldo consolidado para consumo, preservando os estoques de cada local."""
import json
import hashlib
from decimal import Decimal
from collections import defaultdict


def iniciar(c):
    c.execute('CREATE TABLE IF NOT EXISTS mes_grupos_insumos (codigo TEXT PRIMARY KEY, membros_json TEXT NOT NULL)')


def consolidar(c,candidatos):
    iniciar(c)
    membros=sorted({x['insumo'] for x in candidatos})
    rows=[dict(c.execute('SELECT * FROM mes_insumos WHERE codigo=?',(k,)).fetchone()) for k in membros]
    if len({r['unidade'].strip().upper() for r in rows})!=1:
        raise ValueError('MP encontrada com unidades diferentes entre locais; revise o cadastro antes de baixar.')
    codigo='TOTAL:'+hashlib.sha256(json.dumps(membros).encode()).hexdigest()[:24]
    saldo=float(sum(Decimal(str(r['saldo'])) for r in rows))
    c.execute('INSERT OR IGNORE INTO mes_insumos VALUES(?,?,?,?,1)',(codigo,rows[0]['descricao']+' [total dos locais]',rows[0]['unidade'],saldo))
    c.execute('INSERT OR IGNORE INTO mes_grupos_insumos VALUES(?,?)',(codigo,json.dumps(membros)))
    c.execute('UPDATE mes_insumos SET saldo=?,versao=versao+1 WHERE codigo=? AND saldo<>?',(saldo,codigo,saldo))
    return dict(candidatos[0],insumo=codigo)


def atualizar(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_grupos_insumos'").fetchone():return
    for codigo,txt in c.execute('SELECT codigo,membros_json FROM mes_grupos_insumos').fetchall():
        saldo=sum(Decimal(str(c.execute('SELECT saldo FROM mes_insumos WHERE codigo=?',(k,)).fetchone()[0])) for k in json.loads(txt))
        c.execute('UPDATE mes_insumos SET saldo=?,versao=versao+1 WHERE codigo=? AND saldo<>?',(float(saldo),codigo,float(saldo)))


def baixar(c,o,codigo,consumo):
    import j2i_industrial as m
    grupo=c.execute('SELECT membros_json FROM mes_grupos_insumos WHERE codigo=?',(codigo,)).fetchone()
    if not grupo:raise ValueError('Grupo de estoque não encontrado.')
    membros=json.loads(grupo[0])
    saldos={k:Decimal(str(c.execute('SELECT saldo FROM mes_insumos WHERE codigo=?',(k,)).fetchone()[0])) for k in membros}
    qtd=Decimal(str(consumo));total=sum(saldos.values())
    if total-qtd<Decimal('-0.0000005') and not m.opcao(c,'permitir_negativo'):
        raise ValueError(f'Saldo total insuficiente: saldo {total}, consumo {qtd}. Nada foi gravado.')
    # Primeiro consome saldos positivos em ordem estável dos locais.
    parcelas={};resto=qtd
    for k in membros:
        v=min(max(saldos[k],Decimal(0)),resto)
        if v>0:parcelas[k]=v;resto-=v
    if resto>0:parcelas[membros[0]]=parcelas.get(membros[0],Decimal(0))+resto
    for k,v in parcelas.items():m.registrar_consumo(c,o,k,float(v))
    atualizar(c)


def resumo(c):
    from j2i_pdf_industrial import normal
    grupos=defaultdict(list)
    for r in c.execute('''SELECT x.produto,x.revestimento,x.local,i.unidade,i.saldo FROM mes_identidade_insumos x
                           JOIN mes_insumos i ON i.codigo=x.insumo'''):
        grupos[(r['produto'],normal(r['revestimento']),r['unidade'].strip().upper())].append(dict(r))
    return [{'MP':k[0],'Revestimento':rs[0]['revestimento'],'Unidade':k[2],
             'Locais':', '.join(sorted({r['local'] for r in rs})),
             'Saldo total':float(sum(Decimal(str(r['saldo'])) for r in rs))} for k,rs in sorted(grupos.items())]
