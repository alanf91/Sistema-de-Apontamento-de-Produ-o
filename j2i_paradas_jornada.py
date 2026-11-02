"""Tempo útil por equipamento: interseção com a jornada semanal cadastrada."""
import json
from datetime import datetime, timedelta
from j2i_jornadas import validar


def carregar(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='mes_jornadas'").fetchone():
        return {}
    return {r[0]: validar(json.loads(r[1])) for r in c.execute('SELECT equipamento_id,dias_json FROM mes_jornadas')}


def segundos(dias, inicio, fim):
    if dias is None or inicio is None or fim is None:
        return None
    inicio = datetime.fromisoformat(inicio) if isinstance(inicio, str) else inicio
    fim = datetime.fromisoformat(fim) if isinstance(fim, str) else fim
    if fim < inicio:
        raise ValueError('Fim anterior ao início da parada.')
    total = 0
    dia = inicio.date()
    mapa = {d['dia']: d for d in dias}
    while dia <= fim.date():
        d = mapa[dia.weekday()]
        if d['ativo']:
            pares = [(d['inicio'], d['pausa']), (d['retorno'], d['fim'])] if d['intervalo'] else [(d['inicio'], d['fim'])]
            for a, b in pares:
                a = max(inicio, datetime.fromisoformat(f'{dia} {a}'))
                b = min(fim, datetime.fromisoformat(f'{dia} {b}'))
                total += max(0, int((b-a).total_seconds()))
        dia += timedelta(days=1)
    return total


def duracao_parada(c, equipamento_id, inicio, fim):
    return segundos(carregar(c).get(equipamento_id), inicio, fim)


def registrar_sql(c):
    jornadas = carregar(c)
    c.create_function('j2i_tempo_jornada', 3,
                      lambda eq, ini, fim: segundos(jornadas.get(eq), ini, fim))


def recalcular(c):
    """Transação pertence ao chamador; audita apenas durações alteradas."""
    jornadas = carregar(c)
    c.execute('''CREATE TABLE IF NOT EXISTS mes_auditoria_paradas_jornada (
        id INTEGER PRIMARY KEY, parada_id INTEGER NOT NULL, anterior INTEGER,
        novo INTEGER NOT NULL, jornada_json TEXT NOT NULL, corrigido_em TEXT NOT NULL)''')
    alteradas = pendentes = 0
    for r in c.execute("SELECT id,equipamento_id,iniciada_em,encerrada_em,duracao_segundos FROM paradas_operacionais WHERE status='FINALIZADA'").fetchall():
        novo = segundos(jornadas.get(r[1]), r[2], r[3])
        if novo is None:
            pendentes += 1
            continue
        if novo != r[4]:
            c.execute('INSERT INTO mes_auditoria_paradas_jornada(parada_id,anterior,novo,jornada_json,corrigido_em) VALUES(?,?,?,?,?)',
                      (r[0],r[4],novo,json.dumps(jornadas[r[1]],ensure_ascii=False),datetime.now().isoformat(timespec='seconds')))
            c.execute('UPDATE paradas_operacionais SET duracao_segundos=? WHERE id=?', (novo,r[0]))
            alteradas += 1
    return alteradas, pendentes
