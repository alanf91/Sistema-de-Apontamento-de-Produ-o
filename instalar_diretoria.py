import argparse,ast,hashlib,json,os,shutil
from datetime import datetime
from pathlib import Path


def integrar(s):
    if '# J2I_DIRETORIA_V1' in s:return s
    pares=[
      ('        "pecas-medidas-zeradas": 24,','        "pecas-medidas-zeradas": 24,\n        "resumo-executivo": 25,'),
      ('        "📏 Peças com medidas zeradas",\n    ]','        "📏 Peças com medidas zeradas",\n        "📈 Resumo Executivo",\n    ]'),
      ('(7,8,9,10,12,13,14,15,16,17,18,19,20,21,22,23,24)', '(7,8,9,10,12,13,14,15,16,17,18,19,20,21,22,23,24,25)'),
      ("with st.sidebar.expander('📈 Diretoria - Relatórios', expanded=False):\n                st.caption('Relatórios da diretoria em preparação.')", "with st.sidebar.expander('📈 Diretoria - Relatórios', expanded=atual.url_path==rotas[25].url_path):\n                st.page_link(rotas[25],label='Resumo Executivo',use_container_width=True)"),
      ('def renderizar_pagina_menu(pagina, paginas):','def renderizar_pagina_menu(pagina, paginas):\n    # J2I_DIRETORIA_V1\n    if pagina == "📈 Resumo Executivo":\n        from types import SimpleNamespace\n        from j2i_diretoria import renderizar\n        renderizar(SimpleNamespace(**globals()))\n        return')]
    for a,b in pares:
        if s.count(a)!=1:raise ValueError('Menu diferente do projeto enviado. Envie o J2I_MES.py atual para compatibilização; nenhum arquivo foi alterado.')
        s=s.replace(a,b)
    ast.parse(s);return s


def instalar(destino,parado):
    if not parado:raise ValueError('Pare o MES e use --servidor-parado.')
    destino=Path(destino);origem=Path(__file__).resolve().parent
    main=destino/'J2I_MES.py';novo=integrar(main.read_text(encoding='utf-8-sig'))
    payload=(origem/'j2i_diretoria.py').read_bytes();ast.parse(payload)
    manifesto=json.loads((origem/'manifesto.json').read_text())
    if hashlib.sha256(payload).hexdigest()!=manifesto['sha256']:raise ValueError('Pacote alterado.')
    for n in ('j2i_desempenho_periodo.py','j2i_atrasos_equipamento.py','j2i_jornadas.py','j2i_industrial_ui.py'):
        ast.parse((destino/n).read_bytes())
    alvo=destino/'j2i_diretoria.py'
    if alvo.exists() and alvo.read_bytes()!=payload:raise ValueError('Já existe outra versão de j2i_diretoria.py. Envie-a para compatibilização.')
    backup=destino/'backups'/('antes_diretoria_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));backup.mkdir(parents=True)
    antigos={p:p.read_bytes() if p.exists() else None for p in (main,alvo)}
    for p,b in antigos.items():
        if b is not None:(backup/p.name).write_bytes(b)
    try:
        for p,b in ((alvo,payload),(main,novo.encode('utf-8'))):
            tmp=p.with_suffix('.tmp');tmp.write_bytes(b);os.replace(tmp,p)
    except Exception:
        for p,b in antigos.items():
            if b is None:p.unlink(missing_ok=True)
            else:p.write_bytes(b)
        raise
    print(f'Instalado. Backup: {backup}\nBancos preservados. Reinicie o MES e abra Diretoria - Relatórios > Resumo Executivo.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--destino',required=True);p.add_argument('--servidor-parado',action='store_true');a=p.parse_args();instalar(a.destino,a.servidor_parado)
