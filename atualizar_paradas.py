"""Instalador restrito, com backup e recálculo transacional das paradas antigas."""
import argparse,ast,hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
from datetime import datetime


def integrar(texto):
    arvore=ast.parse(texto)
    func=next(n for n in arvore.body if isinstance(n,ast.FunctionDef) and n.name=='encerrar_parada_operacional')
    linhas=texto.splitlines(keepends=True)
    trecho=''.join(linhas[func.lineno-1:func.end_lineno])
    if '# J2I_PARADAS_JORNADA_V1' in trecho:return texto
    antigo='        duracao = max(0, int((encerrada - iniciada).total_seconds()))'
    if trecho.count(antigo)!=1:raise ValueError('Função de parada diferente da versão enviada. Nenhum arquivo instalado.')
    novo='        # J2I_PARADAS_JORNADA_V1\n        from j2i_paradas_jornada import duracao_parada\n        duracao = duracao_parada(conexao, equipamento_id, iniciada, encerrada)'
    trecho=trecho.replace(antigo,novo)
    resultado=''.join(linhas[:func.lineno-1])+trecho+''.join(linhas[func.end_lineno:])
    ast.parse(resultado)
    return resultado


def instalar(destino,banco,parado):
    if not parado:raise ValueError('Pare o MES, API e alimentadores antes de instalar; use --servidor-parado.')
    origem=Path(__file__).resolve().parent;destino=Path(destino).resolve();banco=Path(banco).resolve()
    if not banco.is_file():raise ValueError('Banco operacional não encontrado. Confira --banco.')
    manifesto=json.loads((origem/'manifesto_paradas.json').read_text())
    principal=destino/'J2I_MES.py'
    texto=principal.read_text(encoding='utf-8-sig')
    novo=integrar(texto)
    for n,m in manifesto.items():
        payload=(origem/n).read_bytes();ast.parse(payload)
        if hashlib.sha256(payload).hexdigest()!=m['depois']:raise ValueError(f'Pacote alterado: {n}')
        alvo=destino/n
        if alvo.exists() and hashlib.sha256(alvo.read_bytes()).hexdigest() not in (m['antes'],m['depois']):
            raise ValueError(f'Outra versão de {n}. Envie esse arquivo para compatibilização.')
        if m['antes'] and not alvo.exists():raise ValueError(f'Arquivo necessário ausente: {n}')
    for n in ['j2i_jornadas.py','j2i_industrial.py']:
        ast.parse((destino/n).read_bytes())
    backup=destino/'backups'/('antes_paradas_jornada_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    nomes=['J2I_MES.py']+list(manifesto)
    anteriores={n:(destino/n).read_bytes() if (destino/n).exists() else None for n in nomes}
    for n,b in anteriores.items():
        if b is not None:(backup/n).write_bytes(b)
    c=sqlite3.connect(banco);c.row_factory=sqlite3.Row
    with sqlite3.connect(backup/'operacional_antes.db') as b:
        c.backup(b)
        if b.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Falha na integridade do backup.')
    sys.path.insert(0,str(destino));sys.path.insert(0,str(origem))
    from j2i_paradas_jornada import recalcular
    trocados=[]
    try:
        c.execute('BEGIN IMMEDIATE')
        alteradas,pendentes=recalcular(c)
        for n in nomes:
            conteudo=novo.encode('utf-8') if n=='J2I_MES.py' else (origem/n).read_bytes()
            tmp=destino/(n+'.paradas.tmp');tmp.write_bytes(conteudo);os.replace(tmp,destino/n);trocados.append(n)
        c.commit()
    except Exception:
        c.rollback()
        for n in reversed(trocados):
            if anteriores[n] is None:(destino/n).unlink(missing_ok=True)
            else:(destino/n).write_bytes(anteriores[n])
        raise
    finally:c.close()
    print(f'Backup: {backup}')
    print(f'Instalado. Paradas antigas recalculadas: {alteradas}. Sem jornada/horário: {pendentes}.')
    print('Início, fim, motivos e produção preservados. Reinicie o MES.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--destino',required=True);p.add_argument('--banco',required=True);p.add_argument('--servidor-parado',action='store_true');a=p.parse_args()
    instalar(a.destino,a.banco,a.servidor_parado)
