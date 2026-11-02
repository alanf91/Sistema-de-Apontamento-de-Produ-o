"""Saldo por passagem e validação de encerramentos de sessões de produção."""
import math

TOLERANCIA = 0.00001


def validar_quantidades(saldo, boas, sucata, retrabalho, parcial=False):
    valores = (saldo, boas, sucata, retrabalho)
    if not all(math.isfinite(float(v)) and float(v) >= 0 for v in valores):
        raise ValueError('Quantidades devem ser finitas e não negativas.')
    processado = boas + sucata
    if retrabalho > boas:
        raise ValueError('Retrabalho não pode exceder a quantidade boa.')
    if parcial:
        if processado <= 0 or processado >= saldo - TOLERANCIA:
            raise ValueError('No parcial, boas + sucata devem ser maiores que zero e menores que o saldo. Para concluir o saldo, escolha Total.')
    elif abs(processado - saldo) > TOLERANCIA:
        raise ValueError('No total, boas + sucata devem fechar todo o saldo da passagem.')
    return max(0.0, saldo - processado)


def resumir(registros):
    """Cada sessão conserva o saldo disponível na abertura e o produzido no fechamento."""
    rows = sorted((dict(r) for r in registros), key=lambda r: r['id'])
    if not rows:
        return dict(iniciada=False, concluida=False, aberta=False, saldo=0, boas=0, sucata=0, total=0)
    total = float(rows[0]['quantidade_programada'] or 0)
    saldo = total
    boas = sucata = 0.0
    aberta = concluida = False
    for r in rows:
        if aberta or concluida:
            raise ValueError('Passagem com sessões inconsistentes. Solicite revisão ao PCP.')
        if abs(float(r['quantidade_programada'] or 0) - saldo) > TOLERANCIA:
            raise ValueError('Saldo de abertura da passagem inconsistente. Solicite revisão ao PCP.')
        if r['status'] == 'ABERTA':
            aberta = True
        elif r['status'] == 'FINALIZADA' and r.get('fechada_em'):
            b, s = float(r['quantidade_boa'] or 0), float(r['refugo'] or 0)
            parcial = bool(r.get('encerramento_parcial', 0))
            saldo = validar_quantidades(saldo, b, s, float(r.get('retrabalho') or 0), parcial)
            boas += b
            sucata += s
            concluida = not parcial
        else:
            raise ValueError('Sessão sem encerramento válido. Solicite revisão ao PCP.')
    return dict(iniciada=True, concluida=concluida, aberta=aberta, saldo=saldo,
                boas=boas, sucata=sucata, total=total)


def agrupar(registros):
    grupos = {}
    for r in registros:
        grupos.setdefault((r['ficha_op'], r['lote_identificado'], r['rota_ordem']), []).append(r)
    return {chave: resumir(rows) for chave, rows in grupos.items()}
