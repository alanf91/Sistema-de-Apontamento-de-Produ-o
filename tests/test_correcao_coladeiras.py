import ast
import json
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path
import test_sessoes_parciais as fixture
import j2i_industrial as m
from corrigir_coladeira_122 import preparar,aplicar,executar,ALVOS,MEDIDA

class Reparacao(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Fluxo();self.f.setUp()
        with self.f.connect() as c:
            c.execute("UPDATE equipamentos SET codigo='122' WHERE id=1")
            atual=m.validar_regra(dict(tipo='comprimento',dimensao='m',multiplicador=1))
            antiga=m.validar_regra(dict(tipo='pecas',dimensao='m',multiplicador=1))
            c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(atual),))
            for op,lote,qtd in ALVOS:
                for etapa in (5,6):
                    c.execute('INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?)',(op,etapa,1,lote,'Peca',qtd,MEDIDA,'2026-11-03',json.dumps(antiga),1))
    def tearDown(self):self.f.tearDown()
    def test_previa_e_aplicacao_idempotente(self):
        rows,b=executar(self.f.db);self.assertIsNone(b);self.assertTrue(all(r['estado']=='Corrigir' for r in rows))
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT SUM(versao) FROM mes_programacao').fetchone()[0],6)
        rows,b=executar(self.f.db,True);self.assertTrue(b.exists())
        rows,b=executar(self.f.db,True);self.assertIsNone(b);self.assertTrue(all(r['estado']=='Já corrigida' for r in rows))
    def test_metrica_alterada_recusa_sem_gravar(self):
        with self.f.connect() as c:
            r=json.loads(c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=1').fetchone()[0]);r['multiplicador']=2
            c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(r),))
        with self.assertRaises(ValueError):executar(self.f.db,True)
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT SUM(versao) FROM mes_programacao').fetchone()[0],6)
    def test_passagem_iniciada_recusa(self):
        with self.f.connect() as c:c.execute("UPDATE equipamentos SET codigo='1' WHERE id=1")
        i=self.f.abrir()
        with self.f.connect() as c:c.execute("UPDATE equipamentos SET codigo='122' WHERE id=1")
        with self.f.connect() as c:
            c.execute("UPDATE ordens_operacionais SET ficha_op='01323511',lote_identificado='10670',rota_ordem=5 WHERE id=?",(i,))
        with self.assertRaises(ValueError):executar(self.f.db,True)
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT SUM(versao) FROM mes_programacao').fetchone()[0],6)
    def test_falta_alvo_recusa(self):
        with self.f.connect() as c:c.execute("DELETE FROM mes_programacao WHERE op='01327857' AND etapa=6")
        with self.assertRaises(ValueError):executar(self.f.db,True)
        with self.f.connect() as c:self.assertEqual(c.execute('SELECT SUM(versao) FROM mes_programacao').fetchone()[0],5)
    def test_previa_obsoleta_recusa(self):
        with self.f.connect() as c:
            c.execute('BEGIN IMMEDIATE');rows=preparar(c)
            c.execute("UPDATE mes_programacao SET versao=2 WHERE op='01323511' AND etapa=5")
            with self.assertRaises(ValueError):aplicar(c,rows)
            self.assertEqual(c.execute("SELECT SUM(versao) FROM mes_programacao").fetchone()[0],7)

class ReaplicacaoPorPassagem(unittest.TestCase):
    def setUp(self):
        self.f=fixture.Fluxo();self.f.setUp();self.a=self.f.a
        self.a.LOGIN_APONTAMENTO='teste'
        self.a.ficha_linha_para_dict=lambda row:dict(dict(row),rotas=[{'ordem':1,'codigo_equipamento':'1','operacao':'COLAR 1º COMP.'},{'ordem':2,'codigo_equipamento':'2','operacao':'Processar'},{'ordem':3,'codigo_equipamento':'1','operacao':'COLAR 2º COMP'}])
        # Wrapper usa o mesmo namespace das funções reais de abertura.
        self.a.abrir_ordem_operacional.__globals__['ficha_linha_para_dict']=self.a.ficha_linha_para_dict
        node=next(n for n in ast.parse((fixture.APP/'j2i_industrial_ui.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='reaplicar_metrica_lote')
        ns={'m':m,'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),'reaplicar','exec'),ns)
        self.reaplicar=ns['reaplicar_metrica_lote']
        with self.f.connect() as c:
            c.execute("INSERT INTO mes_opcoes VALUES('sequencia_livre_lote:10','1')")
            antiga=c.execute('SELECT regra_json FROM mes_metricas WHERE equipamento_id=1').fetchone()[0]
            for etapa in (1,3):c.execute('INSERT INTO mes_programacao VALUES(?,?,?,?,?,?,?,?,?,?)',('00000001',etapa,1,'10','Peca',100,'1/1/0.018','2026-10-27',antiga,1))
    def tearDown(self):self.f.tearDown()
    def metrica_nova(self):
        with self.f.connect() as c:c.execute('UPDATE mes_metricas SET regra_json=? WHERE equipamento_id=1',(json.dumps(m.validar_regra(dict(tipo='comprimento',dimensao='m',multiplicador=1))),))
    def test_outro_equipamento_nao_bloqueia_e_consumo_fica_intacto(self):
        self.f.fechar(self.f.abrir(eq=2),100,eq=2);self.metrica_nova()
        with self.f.connect() as c:
            c.execute("INSERT INTO mes_insumos VALUES('M','Material','kg',99,1)")
            c.execute("INSERT INTO mes_consumos VALUES('00000001',1,'M',5)")
        with patch.object(m,'resolver_materiais',side_effect=AssertionError('Não recalcular consumo de OP iniciada')):
            qtd,preservadas=self.reaplicar(self.a,1,'10',1)
        self.assertEqual(qtd,2);self.assertEqual(preservadas,[])
        with self.f.connect() as c:
            self.assertEqual(c.execute('SELECT quantidade FROM mes_consumos').fetchone()[0],5)
            self.assertEqual(c.execute('SELECT saldo FROM mes_insumos').fetchone()[0],99)
    def test_passagem_iniciada_preservada_futura_permitida(self):
        self.f.fechar(self.f.abrir(),40,parcial=True);self.metrica_nova()
        qtd,p=self.reaplicar(self.a,1,'10',1)
        self.assertEqual(qtd,1);self.assertEqual(p,['00000001'])
        with self.f.connect() as c:
            r=list(c.execute('SELECT regra_json FROM mes_programacao ORDER BY etapa'))
            self.assertEqual(json.loads(r[0][0])['tipo'],'pecas')
            self.assertEqual(json.loads(r[1][0])['tipo'],'comprimento')
    def test_diagnostico_identifica_dimensao_zero(self):
        from j2i_programacao_diaria import diagnosticar_dimensoes
        from datetime import date
        with self.f.connect() as c:
            regra=m.validar_regra(dict(tipo='comprimento',dimensao='m',multiplicador=1))
            regra['permitir_dimensao_zero']=True
            c.execute("UPDATE mes_programacao SET medida='0,000/0,000/0,000',regra_json=? WHERE etapa=1",(json.dumps(regra),))
            problemas=diagnosticar_dimensoes(c,date(2026,10,27),date(2026,10,27))
            self.assertEqual(len(problemas),1)
            self.assertEqual(problemas[0]['OP'],'00000001')
            self.assertEqual(problemas[0]['Etapa'],1)
            self.assertEqual(c.execute('SELECT versao FROM mes_programacao WHERE etapa=1').fetchone()[0],1)

    def test_op_nao_iniciada_mantem_recalculo_consumo(self):
        self.metrica_nova()
        with patch.object(m,'resolver_materiais',return_value=({1:[],3:[]},[])) as resolver:
            qtd,p=self.reaplicar(self.a,1,'10',1)
        self.assertEqual(qtd,2);resolver.assert_called_once()

if __name__=='__main__':unittest.main()
