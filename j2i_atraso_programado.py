"""Coluna de carteira atual vencida antes do início do filtro, sem alterar produção."""
from j2i_atrasos_equipamento import consultar as carteira


def incluir(c,resumo,de,ids):
    saldos,detalhes,avisos=carteira(c,de)
    ids=set(ids)
    saldos=[r for r in saldos if r['equipamento_id'] in ids]
    detalhes=[r for r in detalhes if r['equipamento_id'] in ids]
    lotes={}
    for d in detalhes:
        lote=str(d['Lote']).strip() if d.get('Lote') is not None else ''
        if lote:lotes.setdefault((d['equipamento_id'],d['Unidade']),set()).add(lote)
    mapa={(r['equipamento_id'],r['Unidade']):r for r in saldos}
    linhas=[dict(r) for r in resumo];existentes={(r['equipamento_id'],r['Unidade']) for r in linhas}
    for r in saldos:
        if r['Passagens pendentes'] and (r['equipamento_id'],r['Unidade']) not in existentes:
            linhas.append({'equipamento_id':r['equipamento_id'],'Código':r['Código'],'Equipamento':r['Equipamento'],'Setor':r['Setor'],'Lote':'—','Unidade':r['Unidade'],
               'Programado':0.,'Realizado total':0.,'Realizado bom':0.,'Sucata':0.,'Retrabalho':0.,'Apontamentos':0,'Atingimento bom/programado (%)':None})
    resultado=[]
    for r in linhas:
        saldo=mapa.get((r['equipamento_id'],r['Unidade']))
        valor=saldo['Total em atraso'] if saldo else 0.
        if saldo and (saldo['Pendências de cálculo'] or saldo['Passagens ignoradas (zero)']):
            avisos.append({'OP':'','Etapa':'','Pendência':f"{r['Equipamento']} ({r['Unidade']}): atraso com {saldo['Pendências de cálculo']+saldo['Passagens ignoradas (zero)']} passagem(ns) sem conversão válida. Confira o detalhamento."})
            # O subtotal conhecido permanece disponível no detalhamento, mas não é apresentado como total completo.
            valor=None
        linha={}
        for k,v in r.items():
            linha[k]=v
            if k=='Programado':
                linha['Atraso']=valor
                valores=lotes.get((r['equipamento_id'],r['Unidade']),set())
                linha['LOTES EM ATRASO']=', '.join(sorted(valores,key=lambda v:(0,int(v),v) if v.isdecimal() else (1,0,v))) or '—'
        resultado.append(linha)
    return sorted(resultado,key=lambda r:(r['Equipamento'],r['equipamento_id'],r['Unidade'])),detalhes,avisos
