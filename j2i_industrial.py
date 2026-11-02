"""MES 6: regras versionadas, programação e estoque transacional.

As funções de gravação exigem a mesma conexão/transação do apontamento.
Não há Excel, interface, rede ou processamento de PDF no caminho de fechamento.
"""
import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_FLOOR

REGRAS = {'quantidade': 'Quantidade × fator (unidade personalizada)', 'pecas': 'Peças / passagens', 'area': 'Área: comprimento × largura',
          'comprimento': 'Linear: primeira medida', 'largura': 'Linear: segunda medida',
          'bordas': 'Linear: bordas de comprimento e largura'}
UNIDADES = {'quantidade': 'personalizada', 'pecas': 'uni', 'area': 'M²', 'comprimento': 'm linear', 'largura': 'm linear', 'bordas': 'm linear'}
ESCALAS = {'mm': 1000, 'cm': 100, 'm': 1}
MODOS_BAIXA = {'equipamento':'Por equipamento / etapa', 'inicio_op':'Todos os insumos ao iniciar a primeira etapa da OP', 'fim_op':'Todos os insumos ao finalizar a primeira etapa da OP'}

RATEIOS_MP = {'passagem':'Somente a passagem cadastrada',
              'igual':'Dividir igualmente entre os processos da OP',
              'metrica':'Dividir proporcionalmente à métrica de cada processo'}


def agora():
    return datetime.now().isoformat(sep=' ', timespec='seconds')


def numero(v, minimo=0):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError('Valor numérico inválido.')
    if not d.is_finite() or d < minimo:
        raise ValueError(f'Valor deve ser finito e maior ou igual a {minimo}.')
    return d


def iniciar(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS mes_encerramentos_ppcp (
      id INTEGER PRIMARY KEY, op TEXT NOT NULL, lote TEXT NOT NULL, etapa INTEGER NOT NULL,
      equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),usuario TEXT NOT NULL,
      encerrado_em TEXT NOT NULL,motivo TEXT NOT NULL,corte TEXT NOT NULL,snapshot_json TEXT NOT NULL,
      UNIQUE(op,lote,etapa));
    CREATE TABLE IF NOT EXISTS mes_metricas (
      equipamento_id INTEGER PRIMARY KEY REFERENCES equipamentos(id),
      versao INTEGER NOT NULL, regra_json TEXT NOT NULL, atualizado_em TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_metas (
      id INTEGER PRIMARY KEY, equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
      vigencia TEXT NOT NULL, valor REAL NOT NULL CHECK(valor>=0), periodo TEXT NOT NULL,
      regra_json TEXT NOT NULL, criado_em TEXT NOT NULL, usuario TEXT NOT NULL,
      UNIQUE(equipamento_id,vigencia));
    CREATE TABLE IF NOT EXISTS mes_auditoria (
      id INTEGER PRIMARY KEY, evento TEXT NOT NULL, usuario TEXT NOT NULL,
      instante TEXT NOT NULL, dados_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_programacao (
      op TEXT NOT NULL, etapa INTEGER NOT NULL, equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
      lote TEXT NOT NULL, peca TEXT NOT NULL, quantidade REAL NOT NULL,
      medida TEXT NOT NULL, data_programada TEXT NOT NULL, regra_json TEXT NOT NULL,
      versao INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(op,etapa));
    CREATE INDEX IF NOT EXISTS ix_mes_programacao_data ON mes_programacao(data_programada,equipamento_id);
    CREATE TABLE IF NOT EXISTS mes_resultados (
      ordem_id INTEGER PRIMARY KEY REFERENCES ordens_operacionais(id), unidade TEXT NOT NULL,
      fator REAL NOT NULL, programado REAL NOT NULL, boas REAL, sucata REAL, retrabalho REAL,
      regra_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_insumos (
      codigo TEXT PRIMARY KEY, descricao TEXT NOT NULL, unidade TEXT NOT NULL,
      saldo REAL NOT NULL, versao INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS mes_consumos (
      op TEXT NOT NULL, etapa INTEGER NOT NULL, insumo TEXT NOT NULL REFERENCES mes_insumos(codigo),
      quantidade REAL NOT NULL CHECK(quantidade>0), PRIMARY KEY(op,etapa,insumo));
    CREATE TABLE IF NOT EXISTS mes_revisao_mp (
      op TEXT NOT NULL, etapa INTEGER NOT NULL, usuario TEXT NOT NULL, instante TEXT NOT NULL,
      PRIMARY KEY(op,etapa));
    CREATE TABLE IF NOT EXISTS mes_movimentos (
      id INTEGER PRIMARY KEY, insumo TEXT NOT NULL REFERENCES mes_insumos(codigo),
      ordem_id INTEGER REFERENCES ordens_operacionais(id), tipo TEXT NOT NULL,
      quantidade REAL NOT NULL, antes REAL NOT NULL, depois REAL NOT NULL,
      instante TEXT NOT NULL, usuario TEXT NOT NULL, origem TEXT NOT NULL,
      UNIQUE(ordem_id,insumo,tipo));
    CREATE TABLE IF NOT EXISTS mes_excecoes (
      id INTEGER PRIMARY KEY, movimento_id INTEGER NOT NULL UNIQUE REFERENCES mes_movimentos(id),
      ordem_id INTEGER NOT NULL REFERENCES ordens_operacionais(id), op TEXT NOT NULL,
      equipamento_id INTEGER NOT NULL, insumo TEXT NOT NULL, saldo_antes REAL NOT NULL,
      consumo REAL NOT NULL, saldo_depois REAL NOT NULL, instante TEXT NOT NULL, usuario TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_preparacao_modo (op TEXT PRIMARY KEY, modo TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_politica_op (
      op TEXT PRIMARY KEY, modo TEXT NOT NULL, itens_json TEXT NOT NULL, primeira_ordem INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_baixa_unica_op (
      op TEXT PRIMARY KEY, ordem_id INTEGER NOT NULL REFERENCES ordens_operacionais(id), instante TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_opcoes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
    INSERT OR IGNORE INTO mes_opcoes VALUES ('permitir_negativo','0');
    INSERT OR IGNORE INTO mes_opcoes VALUES ('controlar_estoque','0');
    INSERT OR IGNORE INTO mes_opcoes VALUES ('modo_baixa','equipamento');
    CREATE TABLE IF NOT EXISTS mes_importacoes_estoque (
      hash TEXT PRIMARY KEY, arquivo TEXT NOT NULL, instante TEXT NOT NULL, usuario TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_mes_movimentos_data ON mes_movimentos(instante);
    CREATE INDEX IF NOT EXISTS ix_mes_excecoes_data ON mes_excecoes(instante);
    ''')

    iniciar_extensoes(c)


def auditoria(c, evento, usuario, dados):
    c.execute('INSERT INTO mes_auditoria(evento,usuario,instante,dados_json) VALUES(?,?,?,?)',
              (evento, usuario, agora(), json.dumps(dados, ensure_ascii=False)))


def validar_regra(regra):
    r = dict(regra)
    if r.get('tipo') not in REGRAS or r.get('dimensao') not in ESCALAS:
        raise ValueError('Regra ou unidade das dimensões inválida.')
    for k in ('multiplicador', 'bordas_c', 'bordas_l'):
        r[k] = float(numero(r.get(k, 1 if k == 'multiplicador' else 0)))
    if r['multiplicador'] <= 0:
        raise ValueError('O multiplicador deve ser maior que zero.')
    if r['tipo'] == 'bordas' and r['bordas_c'] + r['bordas_l'] <= 0:
        raise ValueError('Informe pelo menos uma borda.')
    if r['tipo']=='quantidade':
        r['unidade']=str(r.get('unidade','')).strip()
        if not r['unidade'] or len(r['unidade'])>24:
            raise ValueError('Informe uma unidade personalizada com até 24 caracteres.')
    else:
        r['unidade'] = UNIDADES[r['tipo']]
    return r


def fator(regra, medida):
    r = validar_regra(regra)
    mult = numero(r['multiplicador'])
    if r['tipo'] in ('pecas','quantidade'):
        return float(mult)
    # A unidade é explícita no cadastro. Não inferir mm/m pela magnitude.
    partes = re.split(r'[/xX×;]', str(medida).strip())
    def dim(i):
        try:
            texto = partes[i].strip()
            if ',' in texto:
                texto = texto.replace('.', '').replace(',', '.')
            valor = numero(texto)
            if valor < 0 or (valor == 0 and not r.get('permitir_dimensao_zero',False)):
                raise ValueError()
            return valor / Decimal(ESCALAS[r['dimensao']])
        except (IndexError, ValueError, InvalidOperation):
            raise ValueError(f'Medida "{medida}" inválida para {REGRAS[r["tipo"]]}. Revise a ficha e a unidade dimensional.')
    if r['tipo'] == 'area':
        base = dim(0) * dim(1)
    elif r['tipo'] == 'comprimento':
        base = dim(0)
    elif r['tipo'] == 'largura':
        base = dim(1)
    else:
        base = (dim(0) * numero(r['bordas_c']) if r['bordas_c'] else Decimal(0)) + (dim(1) * numero(r['bordas_l']) if r['bordas_l'] else Decimal(0))
    return float(base * mult)


def calcular(qtd, f):
    return float((numero(qtd) * numero(f)).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP))


def salvar_metrica(c, eq, regra, versao, usuario):
    r = validar_regra(regra)
    atual = c.execute('SELECT versao,regra_json FROM mes_metricas WHERE equipamento_id=?', (eq,)).fetchone()
    if (atual['versao'] if atual else 0) != versao:
        raise ValueError('Cadastro alterado por outro usuário. Atualize a tela.')
    if not c.execute('SELECT 1 FROM equipamentos WHERE id=?', (eq,)).fetchone():
        raise ValueError('Equipamento inexistente.')
    texto = json.dumps(r, ensure_ascii=False, sort_keys=True)
    c.execute('''INSERT INTO mes_metricas VALUES(?,?,?,?) ON CONFLICT(equipamento_id)
                 DO UPDATE SET versao=excluded.versao,regra_json=excluded.regra_json,atualizado_em=excluded.atualizado_em''',
              (eq, versao + 1, texto, agora()))
    auditoria(c, 'metrica', usuario, {'equipamento': eq, 'antes': dict(atual) if atual else None, 'depois': r})


def regra_equipamento(c, eq):
    row = c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=?', (eq,)).fetchone()
    if not row:
        raise ValueError('Cadastre a regra de cálculo deste equipamento em Métricas e Metas antes de iniciar.')
    return json.loads(row[0])


def salvar_meta(c, eq, vigencia, valor, periodo, usuario):
    date.fromisoformat(vigencia)
    if periodo not in ('Hora', 'Turno', 'Dia'):
        raise ValueError('Período de meta inválido.')
    r = regra_equipamento(c, eq)
    if c.execute('SELECT 1 FROM mes_metas WHERE equipamento_id=? AND vigencia=?', (eq, vigencia)).fetchone():
        raise ValueError('Já existe meta nesta vigência. Preserve o histórico e use uma nova data.')
    c.execute('INSERT INTO mes_metas(equipamento_id,vigencia,valor,periodo,regra_json,criado_em,usuario) VALUES(?,?,?,?,?,?,?)',
              (eq, vigencia, float(numero(valor)), periodo, json.dumps(r, sort_keys=True), agora(), usuario))
    auditoria(c, 'meta', usuario, {'equipamento': eq, 'vigencia': vigencia, 'valor': valor, 'periodo': periodo})


def programar(c, ficha, rota, eq, dia, regra, usuario, versao=0):
    date.fromisoformat(dia)
    op, etapa = ficha['op'], int(rota.get('ordem_rota', rota.get('ordem', 0)))
    if etapa <= 0:
        raise ValueError('Etapa inválida.')
    if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? AND rota_ordem=?', (op, etapa)).fetchone():
        raise ValueError('Esta etapa já possui apontamento; programação e regra estão congeladas.')
    antigo = c.execute('SELECT versao FROM mes_programacao WHERE op=? AND etapa=?', (op, etapa)).fetchone()
    if (antigo[0] if antigo else 0) != versao:
        raise ValueError('Programação alterada por outro usuário. Atualize a tela.')
    r = validar_regra(regra)
    fator(r, ficha.get('medida', ''))
    c.execute('''INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(op,etapa)
      DO UPDATE SET data_programada=excluded.data_programada, regra_json=excluded.regra_json,versao=excluded.versao''',
      (op, etapa, eq, ficha.get('lote', ''), ficha.get('descricao_peca', ''), float(numero(ficha['quantidade_produzir'])),
       ficha.get('medida', ''), dia, json.dumps(r, sort_keys=True), versao + 1))
    auditoria(c, 'programacao', usuario, {'op': op, 'etapa': etapa, 'data': dia, 'regra': r})


def abrir(c, ordem_id, eq, ficha, rota, legado=False):
    o=dict(c.execute('SELECT * FROM ordens_operacionais WHERE id=?',(ordem_id,)).fetchone())
    politica=c.execute('SELECT * FROM mes_politica_op WHERE op=?',(ficha['op'],)).fetchone()
    if not politica:
        anterior=c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? AND id<>? LIMIT 1',(ficha['op'],ordem_id)).fetchone()
        modo=modo_baixa(c) if not anterior and not legado and opcao(c,'controlar_estoque') else 'equipamento'
        preparado=c.execute('SELECT modo FROM mes_preparacao_modo WHERE op=?',(ficha['op'],)).fetchone()
        if modo=='equipamento' and not anterior and not legado and preparado and preparado[0]!='equipamento':
            eqs={r['id']:dict(r) for r in c.execute('SELECT id,codigo FROM equipamentos')}
            consumos,pend=resolver_materiais(c,ficha,eqs,'equipamento')
            if pend:raise ValueError('Insumos da OP pendentes: '+'; '.join(pend))
            for etapa,itens_etapa in consumos.items():
                # A primeira ordem acabou de ser inserida, mas ainda não foi iniciada/confirmada.
                c.execute('DELETE FROM mes_consumos WHERE op=? AND etapa=?',(ficha['op'],etapa))
                for item in itens_etapa:c.execute('INSERT INTO mes_consumos VALUES(?,?,?,?)',(ficha['op'],etapa,item['insumo'],item['quantidade']))
                c.execute('INSERT OR REPLACE INTO mes_revisao_mp VALUES(?,?,?,?)',(ficha['op'],etapa,o['usuario'],agora()))
            c.execute('UPDATE mes_preparacao_modo SET modo=? WHERE op=?',('equipamento',ficha['op']))
        itens=[]
        if modo!='equipamento':
            if 'materiais' not in ficha:raise ValueError('OP sem dados de materiais. Reimporte o PDF antes de iniciar.')
            consumos,pend=resolver_materiais(c,ficha,{},modo)
            if pend:raise ValueError('Insumos da OP pendentes: '+'; '.join(pend))
            itens=[item for lista in consumos.values() for item in lista]
            for etapa in consumos:
                c.execute('INSERT OR REPLACE INTO mes_revisao_mp VALUES(?,?,?,?)',(ficha['op'],etapa,o['usuario'],agora()))
            c.execute('INSERT OR REPLACE INTO mes_pendencias_mp VALUES(?,?,?)',(ficha['op'],'[]',agora()))
        c.execute('INSERT INTO mes_politica_op VALUES(?,?,?,?)',(ficha['op'],modo,json.dumps(itens),ordem_id))
        politica=c.execute('SELECT * FROM mes_politica_op WHERE op=?',(ficha['op'],)).fetchone()
    if opcao(c,'controlar_estoque'):
        if politica['modo']=='equipamento' and not c.execute('SELECT 1 FROM mes_revisao_mp WHERE op=? AND etapa=?',(ficha['op'],rota['ordem_rota'])).fetchone():
            raise ValueError('Consumo de insumos não preparado. Confira Pendências de Importação e prepare novamente o lote.')
        if politica['modo']=='inicio_op':baixar_op_unica(c,o,politica)
    etapa = int(rota['ordem_rota'])
    plano = c.execute('SELECT regra_json FROM mes_programacao WHERE op=? AND etapa=?', (ficha['op'], etapa)).fetchone()
    anterior = c.execute('''SELECT r.regra_json FROM mes_resultados r JOIN ordens_operacionais o ON o.id=r.ordem_id
        WHERE o.ficha_op=? AND o.lote_identificado=? AND o.rota_ordem=? AND o.id<>? ORDER BY o.id LIMIT 1''',
        (ficha['op'], o['lote_identificado'], etapa, ordem_id)).fetchone()
    r = json.loads(anterior[0]) if anterior else json.loads(plano[0]) if plano else regra_rota(regra_equipamento(c, eq), rota.get('operacao',''))
    f = fator(r, ficha.get('medida', ''))
    qtd = c.execute('SELECT quantidade_programada FROM ordens_operacionais WHERE id=?', (ordem_id,)).fetchone()[0]
    c.execute('INSERT INTO mes_resultados(ordem_id,unidade,fator,programado,regra_json) VALUES(?,?,?,?,?)',
              (ordem_id, r['unidade'], f, calcular(qtd, f), json.dumps(r, sort_keys=True)))


def opcao(c, chave):
    r = c.execute('SELECT valor FROM mes_opcoes WHERE chave=?', (chave,)).fetchone()
    return r and r[0] == '1'


def salvar_opcoes(c, controlar, negativo, usuario):
    if controlar and not opcao(c,'controlar_estoque'):
        abertas=c.execute("""SELECT COUNT(*) FROM ordens_operacionais o WHERE status='ABERTA' AND NOT EXISTS
          (SELECT 1 FROM mes_revisao_mp r WHERE r.op=o.ficha_op AND r.etapa=o.rota_ordem)""").fetchone()[0]
        if abertas:
            raise ValueError('Existem OPs abertas sem consumo revisado. Encerre-as antes de ativar o estoque.')
    for chave, valor in [('controlar_estoque', controlar), ('permitir_negativo', negativo)]:
        c.execute('UPDATE mes_opcoes SET valor=? WHERE chave=?', ('1' if valor else '0', chave))
    auditoria(c, 'politica_estoque', usuario, {'controlar': controlar, 'permitir_negativo': negativo})


def salvar_consumos(c, op, etapa, itens, usuario):
    if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? AND rota_ordem=?', (op, etapa)).fetchone():
        raise ValueError('Consumo não pode ser alterado após o início da etapa.')
    codigos = [str(i['insumo']).strip() for i in itens]
    if len(codigos) != len(set(codigos)):
        raise ValueError('Insumo duplicado. Consolide a quantidade.')
    c.execute('DELETE FROM mes_consumos WHERE op=? AND etapa=?', (op, etapa))
    for i in itens:
        qtd = numero(i['quantidade'])
        if qtd <= 0:
            raise ValueError('Consumo deve ser maior que zero.')
        c.execute('INSERT INTO mes_consumos VALUES(?,?,?,?)', (op, etapa, str(i['insumo']).strip(), float(qtd)))
    c.execute('INSERT OR REPLACE INTO mes_revisao_mp VALUES(?,?,?,?)', (op, etapa, usuario, agora()))
    auditoria(c, 'consumos', usuario, {'op': op, 'etapa': etapa, 'itens': itens})


def finalizar(c, ordem, boas, sucata, retrabalho, parcial=False):
    o = dict(ordem)
    snap = c.execute('SELECT * FROM mes_resultados WHERE ordem_id=?', (o['id'],)).fetchone()
    if not snap:
        # Ordens abertas antes da atualização: cadastro validado explicitamente no fechamento.
        ficha = json.loads(o.get('ficha_snapshot_json') or '{}').get('ficha', {})
        ficha.setdefault('op', o['ficha_op']); ficha.setdefault('medida', o.get('medida_ficha', ''))
        abrir(c, o['id'], o['equipamento_id'], ficha, {'ordem_rota': o['rota_ordem']}, legado=True)
        snap = c.execute('SELECT * FROM mes_resultados WHERE ordem_id=?', (o['id'],)).fetchone()
    politica=c.execute('SELECT * FROM mes_politica_op WHERE op=?',(o['ficha_op'],)).fetchone()
    unico=politica is not None and politica['modo']!='equipamento'
    if opcao(c,'controlar_estoque') and unico and politica['modo']=='fim_op' and not parcial:
        baixar_op_unica(c,o,politica)
    if opcao(c, 'controlar_estoque') and not unico:
        if not c.execute('SELECT 1 FROM mes_revisao_mp WHERE op=? AND etapa=?', (o['ficha_op'], o['rota_ordem'])).fetchone():
            raise ValueError('Consumo de MP não preparado para esta etapa. Ajuste os vínculos em Estoque e prepare novamente o lote em Importar Lotes PDF.')
        itens = c.execute('''SELECT x.*,i.saldo FROM mes_consumos x JOIN mes_insumos i ON i.codigo=x.insumo
                             WHERE op=? AND etapa=?''', (o['ficha_op'], o['rota_ordem'])).fetchall()
        ficha = json.loads(o.get('ficha_snapshot_json') or '{}').get('ficha', {})
        original = numero(ficha.get('quantidade_produzir', o['quantidade_programada']))
        if original <= 0:
            raise ValueError('Quantidade original da OP inválida para rateio de consumo.')
        for i in itens:
            # Consumo previsto do lote, proporcional à quantidade processada, inclui sucata.
            consumo = float((numero(i['quantidade']) * numero(boas + sucata) / original).quantize(Decimal('0.000001')))
            registrar_consumo(c,o,i['insumo'],consumo)
    c.execute('UPDATE mes_resultados SET boas=?,sucata=?,retrabalho=?,programado=? WHERE ordem_id=?',
              (calcular(boas, snap['fator']), calcular(sucata, snap['fator']), calcular(retrabalho, snap['fator']), calcular(boas+sucata, snap['fator']), o['id']))


def importar_saldos(c, linhas, arquivo, digest, usuario, revisoes):
    if not linhas:
        raise ValueError('Nenhum saldo para importar.')
    if c.execute('SELECT 1 FROM mes_importacoes_estoque WHERE hash=?', (digest,)).fetchone():
        raise ValueError('Este arquivo de saldo já foi importado.')
    vistos = set()
    for item in linhas:
        cod = str(item['codigo']).strip()
        unidade = str(item['unidade']).strip()
        if not cod or not unidade or cod in vistos:
            raise ValueError('Código/unidade vazio ou código duplicado no arquivo.')
        vistos.add(cod)
        saldo = float(numero(item['saldo'], minimo=Decimal('-1E30')))
        atual = c.execute('SELECT * FROM mes_insumos WHERE codigo=?', (cod,)).fetchone()
        if (atual['versao'] if atual else 0) != revisoes.get(cod, 0):
            raise ValueError(f'Estoque de {cod} mudou após a prévia. Valide novamente o arquivo.')
        if atual and atual['unidade'] != unidade:
            raise ValueError(f'Unidade de {cod} diverge do cadastro; não há conversão implícita.')
        antes = float(atual['saldo']) if atual else 0
        c.execute('''INSERT INTO mes_insumos VALUES(?,?,?,?,1) ON CONFLICT(codigo)
                     DO UPDATE SET descricao=excluded.descricao,saldo=excluded.saldo,versao=mes_insumos.versao+1''',
                  (cod, str(item['descricao']), unidade, saldo))
        if 'produto' in item:
            c.execute('INSERT OR REPLACE INTO mes_identidade_insumos VALUES(?,?,?,?,?)',
                      (cod,item['produto'],item['local'],item['revestimento_codigo'],item['revestimento']))
        c.execute('''INSERT INTO mes_movimentos(insumo,tipo,quantidade,antes,depois,instante,usuario,origem)
                     VALUES(?,?,?,?,?,?,?,?)''', (cod, 'POSICAO', saldo - antes, antes, saldo, agora(), usuario, arquivo))
    c.execute('INSERT INTO mes_importacoes_estoque VALUES(?,?,?,?)', (digest, arquivo, agora(), usuario))
    from j2i_estoque_total import atualizar
    atualizar(c)
    auditoria(c, 'posicao_estoque', usuario, {'arquivo': arquivo, 'hash': digest, 'itens': len(linhas)})


def iniciar_extensoes(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS mes_identidade_insumos (
      insumo TEXT PRIMARY KEY REFERENCES mes_insumos(codigo), produto TEXT NOT NULL,
      local TEXT NOT NULL, revestimento_codigo TEXT NOT NULL, revestimento TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_vinculos_mp (
      insumo TEXT NOT NULL REFERENCES mes_insumos(codigo), equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
      passagem INTEGER NOT NULL DEFAULT 1 CHECK(passagem>=1), atualizado_em TEXT NOT NULL,
      PRIMARY KEY(insumo,equipamento_id));
    CREATE TABLE IF NOT EXISTS mes_rateio_mp (
      equipamento_id INTEGER PRIMARY KEY REFERENCES equipamentos(id),
      modo TEXT NOT NULL CHECK(modo IN ('passagem','igual','metrica')),
      versao INTEGER NOT NULL DEFAULT 1, atualizado_em TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS mes_pendencias_mp (
      op TEXT PRIMARY KEY, pendencias_json TEXT NOT NULL, atualizado_em TEXT NOT NULL);
    ''')

    # Migração transacional e idempotente dos vínculos únicos da versão 6.0.
    colunas=c.execute('PRAGMA table_info(mes_vinculos_mp)').fetchall()
    if sum(bool(r['pk']) for r in colunas)==1:
        c.execute('SAVEPOINT migrar_vinculos')
        try:
            c.execute('ALTER TABLE mes_vinculos_mp RENAME TO mes_vinculos_mp_v60')
            c.execute("""CREATE TABLE mes_vinculos_mp (
              insumo TEXT NOT NULL REFERENCES mes_insumos(codigo),
              equipamento_id INTEGER NOT NULL REFERENCES equipamentos(id),
              passagem INTEGER NOT NULL CHECK(passagem>=1), atualizado_em TEXT NOT NULL,
              PRIMARY KEY(insumo,equipamento_id))""")
            c.execute('INSERT INTO mes_vinculos_mp SELECT * FROM mes_vinculos_mp_v60')
            c.execute('DROP TABLE mes_vinculos_mp_v60')
            c.execute('RELEASE migrar_vinculos')
        except Exception:
            c.execute('ROLLBACK TO migrar_vinculos');c.execute('RELEASE migrar_vinculos');raise


def listar_vinculos(c, insumo):
    return [dict(r) for r in c.execute('SELECT equipamento_id,passagem FROM mes_vinculos_mp WHERE insumo=? ORDER BY equipamento_id',(insumo,))]


def versao_vinculos(itens):
    return json.dumps(sorted((int(i['equipamento_id']),int(i['passagem'])) for i in itens))


def salvar_vinculos(c, insumo, itens, usuario, esperado=None):
    antes=listar_vinculos(c,insumo)
    if esperado is not None and versao_vinculos(antes)!=esperado:
        raise ValueError('Vínculos alterados por outro usuário. Atualize a tela antes de salvar.')
    if not c.execute('SELECT 1 FROM mes_insumos WHERE codigo=?',(insumo,)).fetchone():
        raise ValueError('Material não cadastrado.')
    vistos=set();validados=[]
    for item in itens:
        eq=int(numero(item['equipamento_id'],1));valor=numero(item['passagem'],1)
        if valor!=int(valor) or numero(item['equipamento_id'],1)!=eq:
            raise ValueError('Equipamento e passagem devem ser números inteiros.')
        if eq in vistos:raise ValueError('Equipamento repetido no cadastro do material.')
        # Visibilidade não restringe vínculos operacionais.
        ativo=c.execute('SELECT ativo FROM equipamentos WHERE id=?',(eq,)).fetchone()
        if not ativo:
            raise ValueError('Equipamento inexistente.')
        vistos.add(eq);validados.append((eq,int(valor)))
    c.execute('DELETE FROM mes_vinculos_mp WHERE insumo=?',(insumo,))
    c.executemany('INSERT INTO mes_vinculos_mp VALUES(?,?,?,?)',[(insumo,eq,p,agora()) for eq,p in validados])
    auditoria(c,'vinculos_mp',usuario,{'insumo':insumo,'antes':antes,'depois':validados})


def salvar_vinculo(c, insumo, eq, passagem, usuario):
    # Compatibilidade: adicionar um equipamento nunca apaga os demais.
    itens=[i for i in listar_vinculos(c,insumo) if i['equipamento_id']!=eq]
    itens.append({'equipamento_id':eq,'passagem':passagem})
    salvar_vinculos(c,insumo,itens,usuario)


def resolver_materiais(c, ficha, equipamentos, modo=None):
    modo = modo or modo_baixa(c)
    modo_consumo = modo
    from j2i_pdf_industrial import normal
    estoque = [dict(r) for r in c.execute('SELECT * FROM mes_identidade_insumos')]
    vinculos={}
    for r in c.execute('SELECT insumo,equipamento_id,passagem FROM mes_vinculos_mp'):
        vinculos.setdefault(r['insumo'],[]).append(dict(r))
    por_etapa={int(r['ordem']):[] for r in ficha['rotas']}
    pendencias=[]
    for mp in ficha.get('materiais',[]):
        candidatos=[i for i in estoque if i['produto']==mp['produto'] and normal(i['revestimento'])==normal(mp['revestimento'])]
        if not candidatos:
            pendencias.append(f"MP {mp['produto']} / {mp['revestimento']}: material/revestimento não encontrado no estoque importado.");continue
        if len(candidatos)>1:
            from j2i_estoque_total import consolidar
            try:
                grupo=consolidar(c,candidatos)
            except ValueError as exc:
                pendencias.append(str(exc));continue
            # Mantém autorizações existentes; duplicadas no mesmo equipamento são uma só.
            autorizacoes={}
            for item in candidatos:
                for v in vinculos.get(item['insumo'],[]):autorizacoes[(v['equipamento_id'],v['passagem'])]=v
            for v in vinculos.get(grupo['insumo'],[]):autorizacoes[(v['equipamento_id'],v['passagem'])]=v
            vinculos[grupo['insumo']]=list(autorizacoes.values())
            candidatos=[grupo]
        i=candidatos[0]
        if modo_consumo != 'equipamento':
            if not por_etapa:
                pendencias.append('OP sem etapas cadastradas.');continue
            quantidade=calcular(mp['consumo_por_peca'],ficha['quantidade_produzir'])
            if quantidade>0:por_etapa[min(por_etapa)].append({'insumo':i['insumo'],'quantidade':quantidade})
            continue
        autorizados=vinculos.get(i['insumo'],[])
        if not autorizados:
            pendencias.append(f"MP {i['insumo']}: vincule aos equipamentos consumidores.");continue
        destinos=[]
        for vinculo in autorizados:
            eqid=vinculo['equipamento_id'];eq=equipamentos.get(eqid)
            rotas=[r for r in ficha['rotas'] if eq and str(r['codigo_equipamento']).lstrip('0')==str(eq['codigo']).lstrip('0')]
            modo=obter_rateio(c,eqid)['modo']
            if modo=='passagem':
                rotas=rotas[vinculo['passagem']-1:vinculo['passagem']]
            for rota in rotas:destinos.append((eqid,modo,rota))
        if not destinos:
            pendencias.append(f"MP {i['insumo']}: nenhum equipamento/passagem autorizado está no roteiro ativo.");continue
        # Vários processos da mesma máquina são repartidos. Máquinas diferentes
        # na mesma OP continuam exigindo decisão explícita, sem escolher por acaso.
        if len({d[0] for d in destinos})>1:
            etapas=', '.join(str(d[2]['ordem']) for d in destinos)
            pendencias.append(f"MP {i['insumo']}: mais de uma etapa autorizada em equipamentos diferentes no roteiro ({etapas}). Revise os equipamentos autorizados desta MP em Estoque; o destino está ambíguo e o total não será duplicado.");continue
        destinos.sort(key=lambda d:int(d[2]['ordem']))
        try:
            pesos=[];unidades=set()
            for eqid,modo,rota in destinos:
                peso=1
                if modo=='metrica':
                    plano=c.execute('SELECT regra_json FROM mes_programacao WHERE op=? AND etapa=?',(ficha['op'],int(rota['ordem']))).fetchone()
                    regra=json.loads(plano[0]) if plano else regra_rota(regra_equipamento(c,eqid),rota.get('operacao',''))
                    regra=validar_regra(regra)
                    peso=fator(regra,ficha.get('medida',''));unidades.add(regra['unidade'])
                pesos.append(peso)
            if len(unidades)>1:raise ValueError('As etapas têm unidades diferentes; revise suas métricas antes do rateio.')
            qtd=calcular(mp['consumo_por_peca'],ficha['quantidade_produzir'])
            parcelas=dividir_consumo(qtd,pesos)
        except ValueError as exc:
            pendencias.append(f"MP {i['insumo']}: rateio não realizado: {exc}");continue
        for destino,parcela in zip(destinos,parcelas):
            if parcela>0:
                por_etapa[int(destino[2]['ordem'])].append({'insumo':i['insumo'],'quantidade':parcela})
    # O PDF pode ter mais de uma linha do mesmo insumo (continuações/repetições legítimas).
    for etapa,itens in por_etapa.items():
        totais={}
        for i in itens:totais[i['insumo']]=round(totais.get(i['insumo'],0)+i['quantidade'],6)
        por_etapa[etapa]=[{'insumo':k,'quantidade':v} for k,v in totais.items()]
    return por_etapa,pendencias


def regra_rota(regra, operacao):
    """Variações explícitas do roteiro prevalecem sobre o padrão do equipamento."""
    from j2i_pdf_industrial import normal
    r=dict(regra);texto=normal(operacao)
    if r['tipo']=='area' and 'PINTURA' in texto:
        lado=re.search(r'\b([12])\s*LADO',texto)
        if lado:r['multiplicador']=int(lado[1])
    if r['tipo'] in ('comprimento','largura','bordas') and 'COLAR' in texto:
        if 'COMP' in texto:r.update(tipo='comprimento',multiplicador=1,bordas_c=0,bordas_l=0)
        elif 'LARG' in texto:r.update(tipo='largura',multiplicador=1,bordas_c=0,bordas_l=0)
    return validar_regra(r)


def preparar_lote(c, fichas, datas, usuario, excecoes_dimensao=()):
    """Plano, métricas e consumos em uma única transação; permite retomar após importar catálogo."""
    eqs={r['id']:dict(r) for r in c.execute('SELECT id,codigo FROM equipamentos')}
    por_codigo={str(e['codigo']).lstrip('0'):i for i,e in eqs.items()}
    pendencias=[]
    for f in fichas:
        if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? LIMIT 1',(f['op'],)).fetchone():
            pendencias.append(f"OP {f['op']}: já iniciada; consumos preservados, sem reaplicar vínculos para evitar nova baixa do mesmo material.")
            continue
        consumos,pend=resolver_materiais(c,f,eqs)
        c.execute('INSERT OR REPLACE INTO mes_preparacao_modo VALUES(?,?)',(f['op'],modo_baixa(c)))
        pendencias.extend([f"OP {f['op']}: {x}" for x in pend])
        c.execute('INSERT OR REPLACE INTO mes_pendencias_mp VALUES(?,?,?)',(f['op'],json.dumps(pend,ensure_ascii=False),agora()))
        for r in f['rotas']:
            eq=por_codigo[str(r['codigo_equipamento']).lstrip('0')]
            etapa=int(r['ordem'])
            if c.execute('SELECT 1 FROM ordens_operacionais WHERE ficha_op=? AND rota_ordem=?',(f['op'],etapa)).fetchone():
                continue
            plano=c.execute('SELECT 1 FROM mes_programacao WHERE op=? AND etapa=?',(f['op'],etapa)).fetchone()
            if not plano:
                regra=regra_rota(regra_equipamento(c,eq),r['operacao'])
                if (f['op'],etapa) in excecoes_dimensao:
                    regra['permitir_dimensao_zero']=True
                programar(c,f,r,eq,datas[str(r['codigo_equipamento']).lstrip('0')],regra,usuario)
            # Não marca o consumo revisado se algum material da OP ficou sem destino.
            salvar_consumos(c,f['op'],etapa,consumos[etapa],usuario)
            if pend:
                c.execute('DELETE FROM mes_revisao_mp WHERE op=? AND etapa=?',(f['op'],etapa))
    return pendencias


def migrar_configuracoes(c):
    """Conserva unidades e metas já cadastradas, sem regravar configurações novas."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='configuracao_equipamentos'").fetchone():
        return
    for cfg in c.execute('SELECT * FROM configuracao_equipamentos').fetchall():
        if c.execute('SELECT 1 FROM mes_metricas WHERE equipamento_id=?',(cfg['equipamento_id'],)).fetchone():continue
        tipo={'uni':'pecas','m linear':'comprimento','M²':'area'}[cfg['unidade']]
        r=validar_regra(dict(tipo=tipo,dimensao='m',multiplicador=1,bordas_c=0,bordas_l=0))
        c.execute('INSERT INTO mes_metricas VALUES(?,?,?,?)',(cfg['equipamento_id'],1,json.dumps(r,sort_keys=True),agora()))
        if cfg['meta']:
            salvar_meta(c,cfg['equipamento_id'],cfg['atualizado_em'][:10],cfg['meta'],cfg['periodo'],'migracao_v6')


def obter_rateio(c, equipamento_id):
    linha=c.execute('SELECT modo,versao FROM mes_rateio_mp WHERE equipamento_id=?',(equipamento_id,)).fetchone()
    return dict(linha) if linha else {'modo':'passagem','versao':0}


def migrar_rateio(c):
    # Migração aditiva: somente equipamentos ainda sem política recebem padrão.
    for e in c.execute('SELECT id,maquina FROM equipamentos').fetchall():
        if c.execute('SELECT 1 FROM mes_rateio_mp WHERE equipamento_id=?',(e['id'],)).fetchone():continue
        nome=re.sub('[^A-Z]','',e['maquina'].upper())
        modo='igual' if ('COLADEIRA' in nome or 'PINTURAUV' in nome) else 'passagem'
        c.execute('INSERT INTO mes_rateio_mp VALUES(?,?,1,?)',(e['id'],modo,agora()))
        auditoria(c,'politica_rateio_inicial','migracao_v62',{'equipamento':e['id'],'modo':modo})


def salvar_rateio(c, equipamento_id, modo, versao, usuario):
    if modo not in RATEIOS_MP:raise ValueError('Modo de rateio inválido.')
    if not c.execute('SELECT 1 FROM equipamentos WHERE id=?',(equipamento_id,)).fetchone():
        raise ValueError('Equipamento inexistente.')
    antes=obter_rateio(c,equipamento_id)
    if antes['versao']!=versao:raise ValueError('Outro usuário alterou o rateio. Atualize a tela.')
    c.execute("""INSERT INTO mes_rateio_mp VALUES(?,?,?,?) ON CONFLICT(equipamento_id)
      DO UPDATE SET modo=excluded.modo,versao=excluded.versao,atualizado_em=excluded.atualizado_em""",
      (equipamento_id,modo,versao+1,agora()))
    auditoria(c,'politica_rateio',usuario,{'equipamento':equipamento_id,'antes':antes,'modo':modo})


def dividir_consumo(total, pesos):
    """Maior resto em milionésimos: soma exata, sem parcela negativa."""
    if not pesos:raise ValueError('Nenhum processo disponível para rateio.')
    ps=[numero(p) for p in pesos]
    if any(p<=0 for p in ps):raise ValueError('Cada processo deve ter uma métrica positiva.')
    micros=int((numero(total)*1000000).quantize(Decimal(1),rounding=ROUND_HALF_UP))
    soma=sum(ps)
    exatos=[Decimal(micros)*p/soma for p in ps]
    partes=[int(v.to_integral_value(rounding=ROUND_FLOOR)) for v in exatos]
    resto=micros-sum(partes)
    ordem=sorted(range(len(ps)),key=lambda i:(-(exatos[i]-partes[i]),i))
    for i in ordem[:resto]:partes[i]+=1
    return [float(Decimal(v)/1000000) for v in partes]


def modo_baixa(c):
    row=c.execute("SELECT valor FROM mes_opcoes WHERE chave='modo_baixa'").fetchone()
    return row[0] if row else 'equipamento'


def salvar_politica_estoque(c,controlar,negativo,modo,esperado,usuario):
    if modo not in MODOS_BAIXA:raise ValueError('Modo de baixa inválido.')
    if modo_baixa(c)!=esperado:raise ValueError('Outro usuário alterou o modo de baixa. Atualize a tela.')
    salvar_opcoes(c,controlar,negativo,usuario)
    c.execute("INSERT INTO mes_opcoes VALUES('modo_baixa',?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",(modo,))
    auditoria(c,'modo_baixa',usuario,{'antes':esperado,'depois':modo})


def registrar_consumo(c,o,insumo,consumo):
    if insumo.startswith('TOTAL:'):
        from j2i_estoque_total import baixar
        return baixar(c,o,insumo,consumo)
    row=c.execute('SELECT saldo FROM mes_insumos WHERE codigo=?',(insumo,)).fetchone()
    if not row:raise ValueError('Insumo não cadastrado: '+insumo)
    antes=float(row[0]);depois=round(antes-consumo,6)
    if depois < -0.0000005 and not opcao(c,'permitir_negativo'):
        raise ValueError(f'Saldo insuficiente do insumo {insumo}: saldo {antes:g}, consumo {consumo:g}. Nada foi gravado.')
    c.execute('UPDATE mes_insumos SET saldo=?,versao=versao+1 WHERE codigo=?',(depois,insumo))
    cur=c.execute("INSERT INTO mes_movimentos(insumo,ordem_id,tipo,quantidade,antes,depois,instante,usuario,origem) VALUES(?,?,'CONSUMO',?,?,?,?,?,?)",
                  (insumo,o['id'],-consumo,antes,depois,agora(),o['usuario'],o['ficha_op']))
    if antes<=0 or depois<=0:
        c.execute('INSERT INTO mes_excecoes(movimento_id,ordem_id,op,equipamento_id,insumo,saldo_antes,consumo,saldo_depois,instante,usuario) VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (cur.lastrowid,o['id'],o['ficha_op'],o['equipamento_id'],insumo,antes,consumo,depois,agora(),o['usuario']))

    from j2i_estoque_total import atualizar
    atualizar(c)


def baixar_op_unica(c,o,politica):
    # A transação IMMEDIATE do apontamento serializa o saldo e a marca única por OP.
    if politica['primeira_ordem']!=o['id']:
        primeira=c.execute('SELECT equipamento_id,rota_ordem,lote_identificado FROM ordens_operacionais WHERE id=?',(politica['primeira_ordem'],)).fetchone()
        if politica['modo']!='fim_op' or not primeira or tuple(primeira)!=(o['equipamento_id'],o['rota_ordem'],o['lote_identificado']):return
    if c.execute('SELECT 1 FROM mes_baixa_unica_op WHERE op=?',(o['ficha_op'],)).fetchone():return
    for item in json.loads(politica['itens_json']):
        registrar_consumo(c,o,item['insumo'],item['quantidade'])
    c.execute('INSERT INTO mes_baixa_unica_op VALUES(?,?,?)',(o['ficha_op'],o['id'],agora()))
    auditoria(c,'baixa_unica_op',o['usuario'],{'op':o['ficha_op'],'ordem':o['id'],'modo':politica['modo']})
