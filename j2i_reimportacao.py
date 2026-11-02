"""Mescla por OP/lote/etapa, sem substituir apontamentos ou movimentar estoque."""
import copy
import json
import math
import re
from datetime import date
import j2i_industrial as m


def codigo(v):return str(v or '').strip().lstrip('0')


def selecionar(fichas, codigos=None):
    """Conserva o roteiro de referência para rateio e intertravamento, sem renumerar."""
    saida=[]
    alvos=None if codigos is None else {codigo(x) for x in codigos}
    for original in fichas:
        f=copy.deepcopy(original)
        f['rotas_pdf']=copy.deepcopy(f.get('rotas_pdf',f['rotas']))
        f['rotas']=[r for r in f['rotas'] if alvos is None or codigo(r['codigo_equipamento']) in alvos]
        if f['rotas']:saida.append(f)
    return saida


def esquema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS mes_importacao_contexto (
        op TEXT PRIMARY KEY,lote TEXT NOT NULL,ficha_json TEXT NOT NULL)''')


class Catalogo:
    def __init__(self,c):self.c=c
    def execute(self,sql,args=()):
        for tabela in ('fichas_catalogo','rotas_catalogo','importacoes_catalogo','auditoria_importacoes'):
            sql=re.sub(r'\b'+tabela+r'\b','catalogo.'+tabela,sql)
        return self.c.execute(sql,args)


def mesclar(a, fichas, arquivo, datas, usuario, excecoes=(), liberacoes=None):
    if not a.apontamento_autenticado():raise PermissionError('Entre com o acesso PPCP para importar.')
    fichas=copy.deepcopy(fichas)
    if not fichas:raise ValueError('Nenhuma OP do equipamento selecionado no PDF.')
    if len({f['op'] for f in fichas})!=len(fichas):raise ValueError('OP duplicada no PDF.')
    for f in fichas:
        f['lote']=a.normalizar_lote(f['lote'])
        qtd=float(f.get('quantidade_produzir') or 0)
        if not f['lote'] or not f.get('descricao_peca') or not math.isfinite(qtd) or qtd<=0:
            raise ValueError('Ficha incompleta ou quantidade inválida.')
        etapas=[int(r['ordem']) for r in f['rotas']]
        if not etapas or min(etapas)<=0 or len(etapas)!=len(set(etapas)):raise ValueError('Etapas inválidas ou repetidas.')
    avisos=[];resumo=[];canon=[];anteriores=[]
    momento=a.agora_iso()
    with a.conectar_banco_operacional() as c:
        # Um commit para a mescla e a preparação. Mesmo lock usado pelos operadores.
        c.execute('ATTACH DATABASE ? AS catalogo',(str(a.caminho_catalogo_fichas()),))
        c.execute('BEGIN IMMEDIATE')
        esquema(c);cat=Catalogo(c)
        eqs={r['id']:dict(r) for r in c.execute('SELECT id,codigo FROM equipamentos')}
        por_codigo={codigo(e['codigo']):i for i,e in eqs.items()}
        manuais={(r['op'],r['lote'],r['etapa']) for r in c.execute('SELECT op,lote,etapa FROM mes_encerramentos_ppcp')}
        for nova in fichas:
            op=nova['op'];lote=nova['lote']
            linha=cat.execute('SELECT * FROM fichas_catalogo WHERE op=?',(op,)).fetchone()
            antiga=a.ficha_linha_para_dict(linha) if linha else None
            anteriores.append(dict(op=op,ficha=antiga,programacao=[dict(r) for r in c.execute('SELECT * FROM mes_programacao WHERE op=?',(op,))]))
            if antiga and a.normalizar_lote(antiga['lote'])!=lote:raise ValueError(f'OP {op} já pertence a outro lote.')
            registros=[dict(r) for r in c.execute('SELECT * FROM ordens_operacionais WHERE ficha_op=?',(op,))]
            if any(a.normalizar_lote(r['lote_identificado'])!=lote for r in registros):
                raise ValueError(f'OP {op}: lote do apontamento diverge do PDF.')
            protegidas={r['rota_ordem'] for r in registros}|{e for o,l,e in manuais if o==op and l==lote}
            if registros and not antiga:raise ValueError(f'OP {op}: histórico existente sem catálogo. Requer conferência do PPCP.')
            inicio=bool(protegidas)
            velhas={int(r['ordem']):r for r in (antiga or {}).get('rotas',[])}
            completas={int(r['ordem']):r for r in nova.get('rotas_pdf',nova['rotas'])}
            alvo={int(r['ordem']) for r in nova['rotas']}
            # Cabeçalho compartilhado não pode mudar os saldos das sessões ou etapas fora do filtro.
            preservar=antiga and (inicio or not set(velhas)<=alvo)
            ficha=copy.deepcopy(antiga if preservar else nova)
            if preservar and any(str(antiga.get(k))!=str(nova.get(k)) for k in ('quantidade_produzir','medida','descricao_peca','materiais')):
                avisos.append(f'OP {op}, lote {lote}: dados comuns preservados (quantidade, medidas, peça e materiais); há histórico ou etapas fora da seleção.')
            for r in nova['rotas']:
                etapa=int(r['ordem']);eq=por_codigo.get(codigo(r['codigo_equipamento']))
                if eq is None:raise ValueError(f'OP {op}, etapa {etapa}: equipamento não cadastrado.')
                if etapa in protegidas:
                    if etapa not in velhas:raise ValueError(f'OP {op}, etapa {etapa}: histórico sem roteiro correspondente.')
                    if codigo(velhas[etapa]['codigo_equipamento'])!=codigo(r['codigo_equipamento']) or velhas[etapa].get('operacao')!=r.get('operacao'):
                        raise ValueError(f'OP {op}, etapa {etapa}: roteiro alterado em etapa já apontada/encerrada. Confira a numeração do PDF.')
                    resumo.append(dict(OP=op,Lote=lote,Etapa=etapa,Ação='Preservada: já iniciada ou encerrada'))
                else:
                    velhas[etapa]=r
                    resumo.append(dict(OP=op,Lote=lote,Etapa=etapa,Ação='Preparada para apontamento'))
            ficha['rotas']=[velhas[k] for k in sorted(velhas)]
            if not antiga:
                a._inserir_ficha_catalogo(cat,ficha,arquivo,momento)
            else:
                # Atualiza apenas cabeçalho autorizado; nunca remove a OP ou suas etapas ausentes no PDF.
                cols=['codigo_peca','descricao_peca','codigo_revestimento','revestimento','medida','tipo_material',
                      'quantidade_material','quantidade_produzir','obs_lote','emissao_data','emissao_hora','pagina_pdf']
                if not preservar:
                    valores=[ficha.get(k,0 if k in ('quantidade_material','quantidade_produzir','pagina_pdf') else '') for k in cols]
                    cat.execute('UPDATE fichas_catalogo SET '+','.join(k+'=?' for k in cols)+',materiais_json=?,produtos_json=? WHERE op=?',
                        (*valores,json.dumps(ficha.get('materiais',[])),json.dumps(ficha.get('produtos',[])),op))
                cat.execute('UPDATE fichas_catalogo SET rotas_json=? WHERE op=?',(json.dumps(ficha['rotas'],ensure_ascii=False),op))
                for etapa in sorted(alvo-protegidas):
                    r=velhas[etapa]
                    cat.execute('''INSERT INTO rotas_catalogo(op,ordem_rota,codigo_setor,setor,codigo_equipamento,equipamento,operacao,pecas_por_vez)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(op,ordem_rota) DO UPDATE SET
                        codigo_setor=excluded.codigo_setor,setor=excluded.setor,codigo_equipamento=excluded.codigo_equipamento,
                        equipamento=excluded.equipamento,operacao=excluded.operacao,pecas_por_vez=excluded.pecas_por_vez''',
                        (op,etapa,r.get('codigo_setor',''),r.get('setor',''),r['codigo_equipamento'],r.get('equipamento',''),r.get('operacao',''),r.get('pecas_por_vez',0)))
            # Roteiro completo de referência: não disponibiliza processos fora do filtro.
            contexto=c.execute('SELECT ficha_json FROM mes_importacao_contexto WHERE op=?',(op,)).fetchone()
            anterior=json.loads(contexto[0]) if contexto else (antiga or {})
            fonte=copy.deepcopy(ficha)
            todas={int(r['ordem']):r for r in anterior.get('rotas',[])}
            todas.update(completas);todas.update(velhas)
            fonte['rotas']=[todas[k] for k in sorted(todas)]
            if contexto and inicio:
                # Rateio de material congelado no primeiro apontamento.
                fonte=json.loads(contexto[0])
            else:
                c.execute('INSERT OR REPLACE INTO mes_importacao_contexto VALUES(?,?,?)',(op,lote,json.dumps(fonte,ensure_ascii=False)))
            politica=c.execute('SELECT modo FROM mes_politica_op WHERE op=?',(op,)).fetchone()
            consumo,pend=m.resolver_materiais(c,fonte,eqs,modo=politica['modo'] if politica else None)
            if pend:avisos.extend(f'OP {op}: {x}' for x in pend)
            for etapa in sorted(alvo-protegidas):
                r=velhas[etapa];eq=por_codigo[codigo(r['codigo_equipamento'])]
                plano=c.execute('SELECT * FROM mes_programacao WHERE op=? AND etapa=?',(op,etapa)).fetchone()
                regra=json.loads(plano['regra_json']) if plano and plano['equipamento_id']==eq else m.regra_rota(m.regra_equipamento(c,eq),r.get('operacao',''))
                if (op,etapa) in excecoes:regra['permitir_dimensao_zero']=True
                dia=plano['data_programada'] if plano else datas[codigo(r['codigo_equipamento'])]
                date.fromisoformat(dia);m.fator(regra,ficha['medida'])
                c.execute('''INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(op,etapa) DO UPDATE SET
                    equipamento_id=excluded.equipamento_id,lote=excluded.lote,peca=excluded.peca,quantidade=excluded.quantidade,
                    medida=excluded.medida,regra_json=excluded.regra_json,versao=excluded.versao''',
                    (op,etapa,eq,lote,ficha['descricao_peca'],ficha['quantidade_produzir'],ficha['medida'],dia,json.dumps(regra),(plano['versao'] if plano else 0)+1))
                revisado=c.execute('SELECT 1 FROM mes_revisao_mp WHERE op=? AND etapa=?',(op,etapa)).fetchone()
                if inicio and revisado:continue
                itens=consumo.get(etapa,[])
                # Não permite que uma nova distribuição ultrapasse o orçamento já congelado.
                conflito=etapa not in consumo and bool(fonte.get('materiais'))
                if inicio:
                    totais={}
                    for lista in consumo.values():
                        for item in lista:totais[item['insumo']]=totais.get(item['insumo'],0)+item['quantidade']
                    for item in itens:
                        usado=c.execute('SELECT COALESCE(SUM(quantidade),0) FROM mes_consumos WHERE op=? AND etapa<>? AND insumo=?',(op,etapa,item['insumo'])).fetchone()[0]
                        if usado+item['quantidade']>totais.get(item['insumo'],0)+0.00001:conflito=True
                if conflito or pend:
                    c.execute('DELETE FROM mes_revisao_mp WHERE op=? AND etapa=?',(op,etapa))
                    avisos.append(f'OP {op}, etapa {etapa}: revisar consumo previsto em Consumo de Insumos antes de apontar com estoque ativo.')
                else:m.salvar_consumos(c,op,etapa,itens,usuario)
            if not inicio:
                c.execute('INSERT OR REPLACE INTO mes_preparacao_modo VALUES(?,?)',(op,m.modo_baixa(c)))
                c.execute('INSERT OR REPLACE INTO mes_pendencias_mp VALUES(?,?,?)',(op,json.dumps(pend),momento))
            # Exportação limitada às etapas selecionadas, com cabeçalho canônico.
            export=copy.deepcopy(ficha);export['rotas']=[r for r in ficha['rotas'] if int(r['ordem']) in alvo];canon.append(export)
        for lote,livre in (liberacoes or {}).items():
            c.execute('INSERT INTO mes_opcoes VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor',('sequencia_livre_lote:'+lote,'1' if livre else '0'))
        cur=cat.execute('INSERT INTO importacoes_catalogo(arquivo,importado_em,fichas_importadas,lote_principal) VALUES(?,?,?,?)',
            (arquivo,momento,len(canon),', '.join(sorted({f['lote'] for f in canon}))))
        cat.execute('INSERT INTO auditoria_importacoes(importacao_id,modo,lotes_json,avisos_json,anterior_json) VALUES(?,?,?,?,?)',
            (cur.lastrowid,'mescla_preservando_apontamentos',json.dumps(sorted({f['lote'] for f in canon})),json.dumps(avisos),json.dumps(anteriores,ensure_ascii=False)))
        m.auditoria(c,'reimportacao_preservando_etapas',usuario,dict(arquivo=arquivo,etapas=resumo,avisos=avisos,liberacoes=liberacoes or {}))
    return canon,avisos,resumo
