"""Correção delimitada às seis passagens conferidas no banco e PDFs enviados.

Sem --aplicar, somente consulta. Não substitui banco nem altera produção/estoque.
"""
import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import j2i_industrial as m

ALVOS=(('01323511','10670',16.0),('01327856','10698',300.0),('01327857','10698',12.0))
MEDIDA='0,730/0,120/0,015'


def preparar(c):
    eqs=c.execute("SELECT id,codigo FROM equipamentos WHERE ltrim(codigo,'0')='122'").fetchall()
    if len(eqs)!=1:raise ValueError('Não foi encontrado um cadastro único do equipamento 122.')
    eq=eqs[0]['id']
    cfg=c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=?',(eq,)).fetchone()
    if not cfg:raise ValueError('Equipamento 122 sem métrica cadastrada.')
    nova=m.validar_regra(json.loads(cfg['regra_json']))
    if nova['tipo']!='comprimento' or nova['dimensao']!='m' or nova['multiplicador']!=1:
        raise ValueError('A métrica atual da coladeira 122 mudou. Esperado: primeira medida, metros, multiplicador 1. Solicite nova conferência.')
    alteracoes=[]
    for op,lote,qtd in ALVOS:
        for etapa in (5,6):
            r=c.execute('SELECT * FROM mes_programacao WHERE op=? AND etapa=?',(op,etapa)).fetchone()
            if not r or r['lote']!=lote or r['equipamento_id']!=eq or r['medida']!=MEDIDA or r['quantidade']!=qtd:
                raise ValueError(f'OP {op}, etapa {etapa}: programação diverge da cópia conferida. Nenhuma alteração será aplicada.')
            antiga=m.validar_regra(json.loads(r['regra_json']))
            if antiga==nova:
                alteracoes.append(dict(op=op,lote=lote,etapa=etapa,estado='Já corrigida',antes=m.calcular(qtd,m.fator(antiga,MEDIDA)),depois=m.calcular(qtd,m.fator(nova,MEDIDA))))
                continue
            if antiga['tipo']!='pecas' or antiga['multiplicador']!=1:
                raise ValueError(f'OP {op}, etapa {etapa}: regra anterior diferente da esperada. Solicite nova conferência.')
            if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? AND lote_identificado=? AND rota_ordem=? LIMIT 1',(op,lote,etapa)).fetchone():
                raise ValueError(f'OP {op}, etapa {etapa}: a passagem já foi iniciada após a cópia enviada. Histórico preservado; solicite nova conferência.')
            alteracoes.append(dict(op=op,lote=lote,etapa=etapa,estado='Corrigir',versao=r['versao'],
                regra_antes=r['regra_json'],regra_depois=json.dumps(nova,sort_keys=True,ensure_ascii=False),
                antes=m.calcular(qtd,m.fator(antiga,MEDIDA)),depois=m.calcular(qtd,m.fator(nova,MEDIDA))))
    return alteracoes


def aplicar(c,alteracoes):
    # Revalidação na mesma transação IMMEDIATE; não permite prévia obsoleta.
    if preparar(c)!=alteracoes:raise ValueError('Dados alterados após a prévia. Execute novamente.')
    mudancas=[r for r in alteracoes if r['estado']=='Corrigir']
    for r in mudancas:
        cur=c.execute('''UPDATE mes_programacao SET regra_json=?,versao=versao+1
            WHERE op=? AND etapa=? AND lote=? AND versao=? AND regra_json=?''',
            (r['regra_depois'],r['op'],r['etapa'],r['lote'],r['versao'],r['regra_antes']))
        if cur.rowcount!=1:raise ValueError('Programação alterada durante a correção. Transação cancelada.')
    if mudancas:
        m.auditoria(c,'correcao_coladeira_122_metricas','correcao_assistida',
                    {'origem':'Banco e PDFs 10670/10698 conferidos em 28/10/2026',
                     'alteracoes':mudancas,'consumos_e_apontamentos':'preservados integralmente'})
    return len(mudancas)


def executar(banco, gravar=False):
    caminho=Path(banco).expanduser().resolve()
    if not caminho.is_file():raise ValueError('Banco inexistente: '+str(caminho))
    c=sqlite3.connect(caminho.as_uri()+('?mode=rw' if gravar else '?mode=ro'),uri=True,timeout=15)
    c.row_factory=sqlite3.Row
    backup=None
    try:
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('BEGIN IMMEDIATE' if gravar else 'BEGIN')
        if c.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Integridade do banco não confirmada.')
        rows=preparar(c)
        if gravar and any(r['estado']=='Corrigir' for r in rows):
            pasta=caminho.parent/'backups'/('antes_correcao_coladeira122_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            pasta.mkdir(parents=True)
            backup=pasta/caminho.name
            # A conexão de escrita reserva o banco; outra conexão lê a versão confirmada para backup.
            with sqlite3.connect(caminho.as_uri()+'?mode=ro',uri=True,timeout=15) as src, sqlite3.connect(backup) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup não validado.')
            aplicar(c,rows)
        if gravar:c.commit()
        else:c.rollback()
        return rows,backup
    except Exception:
        c.rollback();raise
    finally:c.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--banco',required=True)
    p.add_argument('--aplicar',action='store_true')
    p.add_argument('--servidor-parado',action='store_true')
    args=p.parse_args()
    if args.aplicar and not args.servidor_parado:p.error('Pare o MES e alimentadores; depois use --aplicar --servidor-parado.')
    try:rows,backup=executar(args.banco,args.aplicar)
    except (ValueError,sqlite3.Error,OSError) as exc:p.exit(1,str(exc)+'\n')
    for r in rows:
        print(f"Lote {r['lote']} / OP {r['op']} / etapa {r['etapa']}: {r['estado']} -> {r['depois']:.3f} m linear")
    if backup:print('Backup:',backup)
    print('Correção concluída. Produção e estoque preservados.' if args.aplicar else 'Somente consulta. Nenhuma alteração gravada.')


if __name__=='__main__':main()
