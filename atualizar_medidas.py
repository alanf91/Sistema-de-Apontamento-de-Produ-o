"""Instala a tela PPCP sem substituir bancos ou personalizações dos menus."""
import argparse
import ast
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime


def integrar(texto):
    marcador = '# J2I_MEDIDAS_LOTE_V1'
    if marcador in texto: return texto
    pares = [
        ('        "saldo-atraso-equipamento": 23,', '        "saldo-atraso-equipamento": 23,\n        "pecas-medidas-zeradas": 24,'),
        ('        "⏳ Saldo em atraso por equipamento",\n    ]', '        "⏳ Saldo em atraso por equipamento",\n        "📏 Peças com medidas zeradas",\n    ]'),
        ('(7,8,9,10,12,13,14,15,16,17,18,19,20,21,22,23)', '(7,8,9,10,12,13,14,15,16,17,18,19,20,21,22,23,24)'),
        ("with st.sidebar.expander('📋 PPCP', expanded=atual.url_path in (rotas[8].url_path,rotas[15].url_path,rotas[21].url_path)):",
         "with st.sidebar.expander('📋 PPCP', expanded=atual.url_path in (rotas[8].url_path,rotas[15].url_path,rotas[21].url_path,rotas[24].url_path)):\n                st.page_link(rotas[24],label='Peças com medidas zeradas',use_container_width=True)"),
        ('def renderizar_pagina_menu(pagina, paginas):',
         'def renderizar_pagina_menu(pagina, paginas):\n    # J2I_MEDIDAS_LOTE_V1\n    if pagina == "📏 Peças com medidas zeradas":\n        from types import SimpleNamespace\n        from j2i_medidas_lote import tela\n        tela(SimpleNamespace(**globals()))\n        return')]
    for antigo, novo in pares:
        if texto.count(antigo) != 1: raise ValueError('Menu diferente da versão enviada. Nenhum arquivo alterado; envie o J2I_MES.py atual para compatibilização.')
        texto = texto.replace(antigo, novo, 1)
    ast.parse(texto)
    return texto


def instalar(origem, destino):
    origem=Path(origem).resolve();destino=Path(destino).resolve()
    if origem == destino: raise ValueError('Extraia o pacote em uma pasta separada.')
    principal=destino/'J2I_MES.py'; modulo='j2i_medidas_lote.py'
    conteudo=(origem/modulo).read_bytes()
    if hashlib.sha256(conteudo).hexdigest()!=json.loads((origem/'manifesto.json').read_text())[modulo]:
        raise ValueError('Pacote alterado ou incompleto.')
    antigo=principal.read_bytes();novo=integrar(antigo.decode('utf-8-sig')).encode('utf-8')
    if (destino/modulo).exists() and (destino/modulo).read_bytes()!=conteudo:
        raise ValueError('Já existe outra versão do módulo de medidas. Preserve-a e envie para compatibilização.')
    ast.parse(conteudo)
    backup=destino/'backups'/('antes_medidas_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));backup.mkdir(parents=True)
    shutil.copy2(principal,backup/principal.name)
    if (destino/modulo).exists():shutil.copy2(destino/modulo,backup/modulo)
    arquivos=set()
    for nome in ('apontamentos_operacionais.db','catalogo_fichas.db'):
        arquivos.update(destino.glob('**/'+nome))
    for var in ('PPCP_BANCO_OPERACIONAL','PPCP_CATALOGO_FICHAS'):
        if os.environ.get(var): arquivos.add(Path(os.environ[var]).resolve())
    for i,p in enumerate(sorted(arquivos)):
        if 'backups' in p.parts or not p.exists():continue
        with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(backup/(str(i)+'_'+p.name)) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup inválido: '+str(p))
    try:
        (destino/(modulo+'.novo')).write_bytes(conteudo);(destino/(modulo+'.novo')).replace(destino/modulo)
        principal.with_suffix('.py.novo').write_bytes(novo);principal.with_suffix('.py.novo').replace(principal)
    except Exception:
        shutil.copy2(backup/principal.name,principal)
        if (backup/modulo).exists():shutil.copy2(backup/modulo,destino/modulo)
        else:(destino/modulo).unlink(missing_ok=True)
        raise
    return backup


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--destino',required=True);p.add_argument('--servidor-parado',action='store_true')
    args=p.parse_args()
    if not args.servidor_parado:p.error('Pare MES, API e alimentadores antes de instalar; informe --servidor-parado.')
    print('Backup:',instalar(Path(__file__).resolve().parent,args.destino))
    print('Tela instalada. Bancos preservados. Reinicie o MES normalmente.')
