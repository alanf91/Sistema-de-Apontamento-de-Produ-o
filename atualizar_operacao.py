"""Instala a tela operacional simplificada, com backup; nunca substitui os bancos do servidor."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def atualizar(origem,destino):
    origem=Path(origem).resolve();destino=Path(destino).resolve()
    if origem==destino or not (destino/'J2I_MES.py').is_file():
        raise ValueError('Extraia em pasta separada e informe a instalação que contém J2I_MES.py.')
    manifesto=json.loads((origem/'manifesto.json').read_text())
    for nome,versoes in manifesto.items():
        if sha(origem/nome)!=versoes['novo']:raise ValueError('Pacote alterado ou incompleto: '+nome)
        alvo=destino/nome
        if alvo.exists() and sha(alvo) not in (versoes['anterior'],versoes['novo']):
            raise ValueError('Arquivo diferente do projeto enviado: '+nome+'. Preserve essa versão e envie para compatibilização.')
        if not alvo.exists() and versoes['anterior'] is not None:raise ValueError('Instalação incompleta: '+nome)
    backup=destino/'backups'/('antes_operacao_simples_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    for nome in manifesto:
        if (destino/nome).exists():shutil.copy2(destino/nome,backup/nome)
    for nome in ('apontamentos_operacionais.db','catalogo_fichas.db'):
        if (destino/nome).exists():
            with sqlite3.connect(destino/nome) as src,sqlite3.connect(backup/nome) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup inválido: '+nome)
    instalados=[]
    try:
        for nome in manifesto:
            temp=destino/(nome+'.novo')
            shutil.copy2(origem/nome,temp);temp.replace(destino/nome);instalados.append(nome)
    except Exception:
        for nome in instalados:
            if (backup/nome).exists():shutil.copy2(backup/nome,destino/nome)
            else:(destino/nome).unlink(missing_ok=True)
        raise
    return backup


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destino',required=True)
    p.add_argument('--servidor-parado',action='store_true')
    args=p.parse_args()
    if not args.servidor_parado:p.error('Pare o MES, a API e os alimentadores antes de atualizar e informe --servidor-parado.')
    b=atualizar(Path(__file__).resolve().parent,args.destino)
    print('Atualização concluída. Bancos, configurações e menus preservados.')
    print('Backup:',b)
    print('Reinicie o MES pelo comando habitual.')
