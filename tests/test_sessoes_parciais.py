"""Regressão com SQLite real; carrega funções do app sem iniciar a interface web."""
import ast
import concurrent.futures
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
# Apenas a integração com a sessão web é substituída; transações/regras/estoque são reais.
sys.modules.setdefault('streamlit', types.ModuleType('streamlit'))
sessao = types.ModuleType('j2i_sessoes')
sessao.validar_operacao = lambda c, eq: None
sys.modules['j2i_sessoes'] = sessao
import j2i_industrial as industrial
from j2i_operacao_multipla import abrir_varias, finalizar_varias
from j2i_sessoes_producao import resumir

TREE = ast.parse((APP/'J2I_MES.py').read_text(encoding='utf-8-sig'))
INIT = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name=='inicializar_banco_operacional')
SQL = [n.args[0].value for n in ast.walk(INIT) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
       and n.func.attr=='executescript' and n.args and isinstance(n.args[0],ast.Constant)]
COLS = ast.literal_eval(next(n.value for n in ast.walk(INIT) if isinstance(n,ast.Assign)
                           and any(isinstance(t,ast.Name) and t.id=='novas_colunas' for t in n.targets)))

class Conexao(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

class Fluxo(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'op.db';self.cat=Path(self.tmp.name)/'cat.db'
        def conectar(path):
            c=sqlite3.connect(path,timeout=10,factory=Conexao);c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON');return c
        self.connect=lambda:conectar(self.db)
        self.catalog=lambda:conectar(self.cat)
        with self.connect() as c:
            c.executescript(SQL[0])
            for k,v in COLS.items():c.execute(f'ALTER TABLE ordens_operacionais ADD COLUMN {k} {v}')
            industrial.iniciar(c)
            c.executescript(SQL[1])
            for i in (1,2):
                c.execute('INSERT INTO equipamentos VALUES(?,?,?,?,?,?,?,?,?)',(i,f'u{i}','hash',str(i),'Setor',f'Maquina {i}',1,'2026-01-01','2026-01-01'))
                c.execute('INSERT INTO mes_metricas VALUES(?,?,?,?)',(i,1,json.dumps(dict(tipo='pecas',dimensao='m',unidade='uni',multiplicador=1,bordas_c=0,bordas_l=0)),'2026-01-01'))
        with self.catalog() as c:
            c.executescript('''CREATE TABLE fichas_catalogo(op TEXT PRIMARY KEY,lote TEXT,codigo_peca TEXT,descricao_peca TEXT,quantidade_produzir REAL,medida TEXT);
            CREATE TABLE rotas_catalogo(op TEXT,ordem_rota INTEGER,codigo_equipamento TEXT,equipamento TEXT,operacao TEXT,setor TEXT);''')
            for op in ('00000001','00000002'):
                c.execute('INSERT INTO fichas_catalogo VALUES(?,?,?,?,?,?)',(op,'10','P','Peca',100,'1/1/0.018'))
                for etapa,eq in ((1,'1'),(2,'2'),(3,'1')):
                    c.execute('INSERT INTO rotas_catalogo VALUES(?,?,?,?,?,?)',(op,etapa,eq,'Maquina '+eq,'Processar','Setor'))
        ns=dict(sqlite3=sqlite3,json=json,datetime=datetime,Any=Any,
                conectar_banco_operacional=self.connect,conectar_catalogo_fichas=self.catalog,
                validar_formato_codigo_barras=lambda v:str(v),ficha_linha_para_dict=dict,
                texto_limpo=lambda v:str(v or ''),agora_iso=lambda:'2026-10-27 08:00:00')
        nodes=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in ('abrir_ordem_operacional','finalizar_ordem_operacional')]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),str(APP/'J2I_MES.py'),'exec'),ns)
        self.a=types.SimpleNamespace(**ns)
        with self.connect() as c:self.eq={i:dict(c.execute('SELECT * FROM equipamentos WHERE id=?',(i,)).fetchone()) for i in (1,2)}

    def tearDown(self):self.tmp.cleanup()
    def abrir(self,eq=1,op='00000001',dia='2026-10-27 08:00:00'):
        return self.a.abrir_ordem_operacional(self.eq[eq],op,{}, {},_momento=dia)
    def fechar(self,id,boas,sucata=0,parcial=False,eq=1,dia='2026-10-27 09:00:00',rt=0):
        return self.a.finalizar_ordem_operacional(eq,id,boas,sucata,rt,'teste',parcial,_momento=dia)
    def rows(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM ordens_operacionais ORDER BY id')]
    def estoque(self,modo='equipamento',saldo=1000):
        with self.connect() as c:
            c.execute("UPDATE mes_opcoes SET valor='1' WHERE chave='controlar_estoque'")
            c.execute("INSERT INTO mes_insumos VALUES('MP','Material','kg',?,1)",(saldo,))
            c.execute("INSERT INTO mes_politica_op VALUES('00000001',?,?,1)",(modo,json.dumps([dict(insumo='MP',quantidade=50)])))
            for etapa in (1,2,3):
                c.execute("INSERT INTO mes_revisao_mp VALUES('00000001',?,'pcp','hoje')",(etapa,))
                c.execute("INSERT INTO mes_consumos VALUES('00000001',?,'MP',50)",(etapa,))
    def saldo(self):
        with self.connect() as c:return c.execute("SELECT saldo FROM mes_insumos WHERE codigo='MP'").fetchone()[0]

    def test_parcial_reabre_outro_dia_e_soma_boas_na_proxima_etapa(self):
        i=self.abrir();self.fechar(i,38,2,True,rt=3)
        with self.assertRaises(ValueError):self.abrir(eq=2)
        j=self.abrir(dia='2026-10-28 10:00:00')
        self.assertEqual(self.rows()[-1]['quantidade_programada'],60)
        self.fechar(j,59,1,dia='2026-10-28 11:00:00')
        k=self.abrir(eq=2,dia='2026-10-28 12:00:00')
        self.assertEqual(self.rows()[-1]['quantidade_programada'],97)
        self.assertEqual([r['duracao_segundos'] for r in self.rows()[:2]],[3600,3600])
        self.assertEqual(resumir(self.rows()[:2])['boas'],97)
        with self.connect() as c:self.assertEqual(c.execute('SELECT SUM(programado) FROM mes_resultados WHERE ordem_id IN (?,?)',(i,j)).fetchone()[0],100)
        self.fechar(k,97,eq=2,dia='2026-10-28 13:00:00')
        self.abrir();self.assertEqual(self.rows()[-1]['rota_ordem'],3)

    def test_varios_parciais_e_sucata_total(self):
        for qtd in (20,30):self.fechar(self.abrir(),qtd,parcial=True)
        self.assertEqual(self.rows()[-1]['quantidade_programada'],80)
        self.fechar(self.abrir(),0,50)
        self.assertEqual(resumir(self.rows())['saldo'],0)
        self.abrir(eq=2);self.assertEqual(self.rows()[-1]['quantidade_programada'],50)

    def test_quantidades_invalidas_nao_gravam(self):
        i=self.abrir()
        for b,s,rt,partial in [(0,0,0,True),(100,0,0,True),(101,0,0,True),(-1,0,0,True),(float('nan'),0,0,True),(40,0,41,True),(40,0,0,False)]:
            with self.assertRaises(ValueError):self.fechar(i,b,s,partial,rt=rt)
            self.assertEqual(self.rows()[0]['status'],'ABERTA')
        self.fechar(i,100)

    def test_duplo_fechamento_e_dupla_abertura(self):
        i=self.abrir()
        with self.assertRaises(ValueError):self.abrir()
        self.fechar(i,40,parcial=True)
        with self.assertRaises(ValueError):self.fechar(i,40,parcial=True)
        self.assertEqual(len(self.rows()),1)

    def test_estoque_por_etapa_proporcional(self):
        self.estoque();self.fechar(self.abrir(),38,2,True)
        self.assertEqual(self.saldo(),980)
        self.fechar(self.abrir(),60)
        self.assertEqual(self.saldo(),950)

    def test_estoque_insuficiente_reverte_parcial(self):
        self.estoque(saldo=10);i=self.abrir()
        with self.assertRaises(ValueError):self.fechar(i,40,parcial=True)
        self.assertEqual(self.saldo(),10);self.assertEqual(self.rows()[0]['status'],'ABERTA')

    def test_baixa_unica_inicio_nao_repete(self):
        self.estoque('inicio_op');i=self.abrir();self.assertEqual(self.saldo(),950)
        self.fechar(i,40,parcial=True);self.fechar(self.abrir(),60)
        self.assertEqual(self.saldo(),950)

    def test_baixa_unica_fim_aguarda_conclusao(self):
        self.estoque('fim_op');self.fechar(self.abrir(),40,parcial=True)
        self.assertEqual(self.saldo(),1000)
        self.fechar(self.abrir(),60);self.assertEqual(self.saldo(),950)
        self.fechar(self.abrir(eq=2),100,eq=2);self.assertEqual(self.saldo(),950)

    def test_lote_misto_total_parcial_e_rollback(self):
        ids=abrir_varias(self.a,self.eq[1],'00000001\n00000002')
        linhas=[{'ID':ids[0],'Encerramento':'Parcial','Processadas':40},{'ID':ids[1],'Encerramento':'Selecione'}]
        with self.assertRaises(ValueError):finalizar_varias(self.a,1,linhas)
        self.assertTrue(all(r['status']=='ABERTA' for r in self.rows()))
        linhas[1]['Encerramento']='Total';finalizar_varias(self.a,1,linhas)
        self.assertEqual([r['encerramento_parcial'] for r in self.rows()],[1,0])
        self.abrir();self.assertEqual(self.rows()[-1]['quantidade_programada'],60)

    def test_concorrencia_reabertura_e_fechamento(self):
        self.fechar(self.abrir(),40,parcial=True)
        def tentativa(fn):
            try:return fn()
            except ValueError:return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            ids=list(pool.map(lambda _:tentativa(self.abrir),range(2)))
        self.assertEqual(sum(i is not None for i in ids),1)
        i=next(i for i in ids if i is not None)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            rs=list(pool.map(lambda _:tentativa(lambda:self.fechar(i,60)),range(2)))
        self.assertEqual(sum(r is not None for r in rs),1)
        self.assertEqual(len(self.rows()),2)

    def test_regra_congelada_na_reabertura(self):
        self.fechar(self.abrir(),40,parcial=True)
        with self.connect() as c:
            regra=json.loads(c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=1').fetchone()[0]);regra['multiplicador']=2
            c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(regra),))
        j=self.abrir()
        with self.connect() as c:self.assertEqual(c.execute('SELECT fator FROM mes_resultados WHERE ordem_id=?',(j,)).fetchone()[0],1)

    def test_indice_migracao_repetida_preserva_sessoes(self):
        self.fechar(self.abrir(),40,parcial=True);self.abrir()
        with self.connect() as c:c.executescript(SQL[1]);c.executescript(SQL[1])
        self.assertEqual(len(self.rows()),2)

    def test_pesquisa_pendentes_e_sequencia_incluem_saldo(self):
        with self.connect() as c:
            c.execute("INSERT INTO mes_programacao VALUES('00000001',1,1,'10','Peca',100,'1/1/0.018','2026-10-27','{}',1)")
            c.execute('UPDATE mes_programacao SET regra_json=(SELECT regra_json FROM mes_metricas WHERE equipamento_id=1)')
        self.fechar(self.abrir(),40,parcial=True)
        tela=ast.parse((APP/'j2i_telas_operacao.py').read_text())
        func=next(n for n in tela.body if isinstance(n,ast.FunctionDef) and n.name=='consultar_ops_pendentes')
        ns={};exec(compile(ast.Module(body=[func],type_ignores=[]),'consulta','exec'),ns)
        with self.connect() as c:
            pend=ns['consultar_ops_pendentes'](c,1,'10')
            self.assertEqual(pend[0]['Quantidade de peças'],60)
        from j2i_sequencia_producao import consultar
        linhas,_=consultar(self.a,['10'])
        primeiro=next(r for r in linhas if r['OP']=='00000001' and r['Etapa']==1)
        self.assertEqual(primeiro['Quantidade de peças'],60)
        segunda=next(r for r in linhas if r['OP']=='00000001' and r['Etapa']==2)
        self.assertIn('Aguardar',segunda['Situação'])
        self.abrir()
        with self.connect() as c:self.assertEqual(ns['consultar_ops_pendentes'](c,1,'10'),[])

    def test_sucata_integral_bloqueia_etapa_seguinte(self):
        self.fechar(self.abrir(),0,40,True)
        self.fechar(self.abrir(),0,60)
        with self.assertRaises(ValueError):self.abrir(eq=2)

    def test_sequencia_livre_preserva_saldo_congelado(self):
        with self.connect() as c:c.execute("INSERT INTO mes_opcoes VALUES('sequencia_livre_lote:10','1')")
        self.fechar(self.abrir(eq=2),40,parcial=True,eq=2)
        self.fechar(self.abrir(eq=1),90,10)
        self.abrir(eq=2)
        self.assertEqual(self.rows()[-1]['quantidade_programada'],60)

if __name__=='__main__':unittest.main()
